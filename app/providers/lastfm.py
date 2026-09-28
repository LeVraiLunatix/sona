"""Lecture de l'historique Last.fm (`user.getRecentTracks`), pour importer les
écoutes passées dans les stats de Sona. Lecture seule : une clé API suffit,
aucune connexion au compte."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from app.db.repository import Play

logger = logging.getLogger(__name__)

API_URL = "https://ws.audioscrobbler.com/2.0/"
PAGE_SIZE = 200
# Last.fm tolère ~5 requêtes/s par clé ; on reste nettement en dessous.
PAGE_DELAY = 0.3
# Image « étoile » grise que Last.fm renvoie à la place des vraies pochettes
# depuis 2019 : autant ne rien stocker.
_PLACEHOLDER_IMAGE = "2a96cbd8b46e442fc41c2b86b821562f"


class LastfmError(Exception):
    pass


@dataclass(slots=True)
class RecentPage:
    plays: list[Play]
    page: int
    total_pages: int


def _text(value) -> str | None:
    if isinstance(value, dict):
        value = value.get("#text") or value.get("name")
    value = (value or "").strip() if isinstance(value, str) else None
    return value or None


def _play_from_json(d: dict) -> Play | None:
    if (d.get("@attr") or {}).get("nowplaying") == "true":
        return None  # en cours d'écoute : pas encore une écoute terminée
    uts = (d.get("date") or {}).get("uts")
    title, artist = _text(d.get("name")), _text(d.get("artist"))
    if not uts or not title or not artist:
        return None
    image = None
    for img in d.get("image") or []:
        url = img.get("#text") if isinstance(img, dict) else None
        if url and _PLACEHOLDER_IMAGE not in url:
            image = url
    played_at = datetime.fromtimestamp(int(uts), tz=timezone.utc).isoformat()
    return Play(
        played_at=played_at, title=title, artist=artist, album=_text(d.get("album")),
        cover_url=image, origin="lastfm",
    )


class LastfmClient:
    def __init__(self, api_key: str, client: httpx.AsyncClient | None = None) -> None:
        self._api_key = api_key
        self._client = client or httpx.AsyncClient(timeout=20.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def recent_tracks(self, user: str, page: int = 1, since: int | None = None) -> RecentPage:
        params = {
            "method": "user.getrecenttracks", "user": user, "api_key": self._api_key,
            "format": "json", "limit": PAGE_SIZE, "page": page,
        }
        if since:
            params["from"] = since
        try:
            response = await self._client.get(API_URL, params=params)
        except httpx.HTTPError as exc:
            raise LastfmError(f"Last.fm injoignable : {exc}") from exc
        try:
            data = response.json()
        except ValueError as exc:
            raise LastfmError(f"Réponse Last.fm illisible ({response.status_code})") from exc
        if "error" in data:
            raise LastfmError(f"Last.fm : {data.get('message') or data['error']}")
        recent = data.get("recenttracks") or {}
        tracks = recent.get("track") or []
        if isinstance(tracks, dict):
            tracks = [tracks]
        attr = recent.get("@attr") or {}
        plays = [p for p in (_play_from_json(t) for t in tracks) if p]
        return RecentPage(plays=plays, page=int(attr.get("page") or page), total_pages=int(attr.get("totalPages") or 0))


@dataclass(slots=True)
class ImportStatus:
    running: bool = False
    page: int = 0
    total_pages: int = 0
    imported: int = 0
    error: str | None = None
    finished_at: str | None = None


async def import_history(client: LastfmClient, repo, user_id: int, username: str, status: ImportStatus) -> None:
    """Rapatrie tout l'historique (ou seulement ce qui manque, après un
    premier import) page par page. Relançable sans risque : les écoutes
    déjà présentes sont ignorées."""
    status.running, status.error, status.imported, status.page = True, None, 0, 0
    try:
        latest = await repo.plays_latest(user_id, "lastfm")
        # Écoutes faites dans l'app puis envoyées à Last.fm (scrobbling) :
        # elles reviennent avec le même horodatage — déjà comptées.
        own = await repo.plays_timestamps(user_id, "sona")
        since = int(datetime.fromisoformat(latest).timestamp()) + 1 if latest else None
        page = 1
        while True:
            result = await client.recent_tracks(username, page=page, since=since)
            status.page, status.total_pages = page, result.total_pages
            fresh = [p for p in result.plays if p.played_at not in own]
            status.imported += len(await repo.plays_add(user_id, fresh))
            if page >= result.total_pages or not result.plays:
                break
            page += 1
            await asyncio.sleep(PAGE_DELAY)
    except LastfmError as exc:
        status.error = str(exc)
        logger.warning("Import Last.fm interrompu : %s", exc)
    finally:
        status.running = False
        status.finished_at = datetime.now(timezone.utc).isoformat()
