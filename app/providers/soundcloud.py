"""SoundCloud : playlists (« sets »), likes publics et titres, pour l'import
dans Sona et la lecture des titres qui n'existent que là.

L'API publique (api-v2.soundcloud.com) demande un `client_id`, celui que le
site lui-même utilise : on le lit dans les scripts de soundcloud.com (comme
yt-dlp), on le garde, et on le relit si SoundCloud le refuse (il change de
temps en temps).
"""

from __future__ import annotations

import logging
import re

import httpx

from app.providers.base import ExternalPlaylist, TrackInfo

logger = logging.getLogger(__name__)

API_BASE = "https://api-v2.soundcloud.com"
SITE = "https://soundcloud.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
}
# Au-delà, l'import est partiel (et le dit) : des likes accumulés sur dix
# ans dépassent vite ce qu'on veut rapprocher du catalogue en une fois.
MAX_TRACKS = 1000
# Titres complétés par requête (`/tracks?ids=`), limite de l'API.
BATCH = 50

_SCRIPT_RE = re.compile(r'<script[^>]+src="(https://a-v2\.sndcdn\.com/assets/[^"]+\.js)"')
_CLIENT_ID_RE = re.compile(r'client_id\s*:\s*"([0-9a-zA-Z]{32})"')
# Mentions de téléchargement gratuit, très courantes dans les titres
# SoundCloud : « (FREE DL) », « [BUY = FREE DOWNLOAD] »…
_TITLE_NOISE_RE = re.compile(
    r"\s*[\(\[][^\)\]]*\b(?:free\s*(?:dl|download)|buy\s*(?:=|for)?\s*free|out\s+now)\b[^\)\]]*[\)\]]",
    re.IGNORECASE,
)


class SoundcloudError(Exception):
    pass


def track_from_api(data: dict) -> TrackInfo:
    """Titre de l'API → TrackInfo. L'artiste vient des métadonnées de
    l'éditeur quand il y en a, sinon d'un « Artiste - Titre » dans le
    titre, sinon du compte qui l'a publié."""
    title = _TITLE_NOISE_RE.sub("", str(data.get("title") or "")).strip() or "Titre inconnu"
    meta = data.get("publisher_metadata") or {}
    user = data.get("user") or {}
    artist = (meta.get("artist") or "").strip()
    if not artist and " - " in title:
        artist, title = (part.strip() for part in title.split(" - ", 1))
    artist = artist or str(user.get("username") or "Artiste inconnu")
    artwork = data.get("artwork_url") or user.get("avatar_url")
    if artwork:
        artwork = artwork.replace("-large.", "-t500x500.")
    created = str(data.get("release_date") or data.get("created_at") or "")
    return TrackInfo(
        source="soundcloud",
        source_id=str(data.get("id") or ""),
        title=title,
        artist=artist,
        album=(meta.get("album_title") or None),
        year=created[:4] if created[:4].isdigit() else None,
        duration_seconds=round(data["duration"] / 1000) if data.get("duration") else None,
        cover_url=artwork,
        isrc=(meta.get("isrc") or None),
    )


class SoundcloudClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(timeout=20.0, headers=HEADERS, follow_redirects=True)
        self._client_id: str | None = None

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _find_client_id(self) -> str:
        try:
            home = await self._client.get(f"{SITE}/")
            for script in reversed(_SCRIPT_RE.findall(home.text)):
                match = _CLIENT_ID_RE.search((await self._client.get(script)).text)
                if match:
                    return match.group(1)
        except httpx.HTTPError as exc:
            raise SoundcloudError(f"SoundCloud injoignable : {exc}") from exc
        raise SoundcloudError("SoundCloud a changé : identifiant d'application introuvable.")

    async def _api(self, path: str, params: dict | None = None) -> dict:
        for attempt in (1, 2):
            if self._client_id is None:
                self._client_id = await self._find_client_id()
            try:
                response = await self._client.get(
                    path if path.startswith("http") else f"{API_BASE}{path}",
                    params={**(params or {}), "client_id": self._client_id},
                )
            except httpx.HTTPError as exc:
                raise SoundcloudError(f"SoundCloud injoignable : {exc}") from exc
            if response.status_code in (401, 403) and attempt == 1:
                self._client_id = None  # identifiant périmé : on le relit
                continue
            if response.status_code == 404:
                raise SoundcloudError("Introuvable sur SoundCloud (privé ou supprimé ?).")
            if response.status_code != 200:
                raise SoundcloudError(f"SoundCloud a répondu {response.status_code}")
            return response.json()
        raise SoundcloudError("SoundCloud refuse l'accès.")

    async def resolve(self, url: str) -> dict:
        return await self._api("/resolve", {"url": url})

    async def _complete(self, partial: list[dict]) -> list[dict]:
        """Les playlists ne donnent le détail que des premiers titres : les
        autres (id seulement) sont complétés par lots, dans l'ordre."""
        missing = [str(t["id"]) for t in partial if t.get("id") and not t.get("title")]
        full: dict[str, dict] = {}
        for start in range(0, len(missing), BATCH):
            batch = await self._api("/tracks", {"ids": ",".join(missing[start:start + BATCH])})
            for item in batch if isinstance(batch, list) else []:
                full[str(item.get("id"))] = item
        return [full.get(str(t.get("id")), t) for t in partial if t.get("title") or str(t.get("id")) in full]

    async def get_playlist(self, url: str) -> ExternalPlaylist:
        data = await self.resolve(url)
        if data.get("kind") not in ("playlist", "system-playlist"):
            raise SoundcloudError("Ce lien SoundCloud n'est pas une playlist.")
        raw = (data.get("tracks") or [])[:MAX_TRACKS]
        tracks = [track_from_api(t) for t in await self._complete(raw)]
        count = data.get("track_count") or len(tracks)
        return ExternalPlaylist(
            name=str(data.get("title") or "Playlist SoundCloud"),
            description=(data.get("description") or None),
            cover_url=(data.get("artwork_url") or "").replace("-large.", "-t500x500.") or (tracks[0].cover_url if tracks else None),
            tracks=tracks,
            note=f"Import partiel : les {MAX_TRACKS} premiers titres sur {count}." if count > MAX_TRACKS else None,
        )

    async def get_likes(self, url: str) -> ExternalPlaylist:
        """Titres aimés (publics) d'un compte, du plus récent au plus ancien."""
        profile = re.sub(r"/likes/?$", "", url.split("?")[0].rstrip("/"))
        user = await self.resolve(profile)
        if user.get("kind") != "user":
            raise SoundcloudError("Compte SoundCloud introuvable.")
        tracks: list[TrackInfo] = []
        page: dict | None = await self._api(f"/users/{user['id']}/likes", {"limit": 200})
        truncated = False
        while page:
            for like in page.get("collection") or []:
                if like.get("track"):
                    tracks.append(track_from_api(like["track"]))
            if len(tracks) >= MAX_TRACKS:
                truncated = bool(page.get("next_href")) or len(tracks) > MAX_TRACKS
                tracks = tracks[:MAX_TRACKS]
                break
            next_href = page.get("next_href")
            page = await self._api(next_href) if next_href else None
        name = user.get("username") or "SoundCloud"
        return ExternalPlaylist(
            name=f"Likes de {name}",
            description=None,
            cover_url=(user.get("avatar_url") or "").replace("-large.", "-t500x500.") or None,
            tracks=tracks,
            note=f"Import partiel : les {MAX_TRACKS} likes les plus récents." if truncated else None,
        )

    async def get_track(self, track_id: str) -> TrackInfo:
        data = await self._api(f"/tracks/{track_id}")
        return track_from_api(data)

    async def get_track_by_url(self, url: str) -> TrackInfo:
        data = await self.resolve(url)
        if data.get("kind") != "track":
            raise SoundcloudError("Ce lien SoundCloud n'est pas un titre.")
        return track_from_api(data)


_shared: SoundcloudClient | None = None


def shared_client() -> SoundcloudClient:
    """Client commun (identifiant d'application gardé d'un appel à l'autre)."""
    global _shared
    if _shared is None:
        _shared = SoundcloudClient()
    return _shared
