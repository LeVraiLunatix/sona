"""Méthodes Last.fm qui demandent le secret de l'application : connexion
d'un utilisateur (« Se connecter avec Last.fm ») et scrobbling.

Flux de connexion (web auth) : l'app ouvre
`https://www.last.fm/api/auth/?api_key=…&cb=encre://lastfm`, l'utilisateur
accepte, Last.fm renvoie vers `encre://lastfm?token=…`, et le serveur
échange ce jeton contre une clé de session (`auth.getSession`, signée).

Variante « appli de bureau » (Sona web installé sur l'écran d'accueil) : le
serveur demande d'abord un jeton (`auth.getToken`), le site ouvre la page
d'autorisation avec ce jeton, puis l'échange quand on revient dans l'appli —
aucun retour de Last.fm vers le site n'est nécessaire.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from app.db.repository import Play

logger = logging.getLogger(__name__)

API_URL = "https://ws.audioscrobbler.com/2.0/"
AUTH_URL = "https://www.last.fm/api/auth/"
APP_CALLBACK = "encre://lastfm"
SCROBBLE_BATCH = 50
_PLACEHOLDER_IMAGE = "2a96cbd8b46e442fc41c2b86b821562f"


class LastfmAuthError(Exception):
    pass


@dataclass(slots=True)
class LastfmSession:
    username: str
    key: str


@dataclass(slots=True)
class LovedTrack:
    title: str
    artist: str
    loved_at: datetime | None


@dataclass(slots=True)
class LastfmProfile:
    display_name: str | None
    avatar_url: str | None


def sign(params: dict[str, str], secret: str) -> str:
    """Signature Last.fm : paramètres triés, clé+valeur concaténées, secret
    en suffixe, MD5 — `format` et `callback` exclus."""
    payload = "".join(f"{k}{params[k]}" for k in sorted(params) if k not in ("format", "callback"))
    return hashlib.md5((payload + secret).encode("utf-8")).hexdigest()


class LastfmAuthClient:
    def __init__(self, api_key: str, secret: str, client: httpx.AsyncClient | None = None) -> None:
        self._api_key = api_key
        self._secret = secret
        self._client = client or httpx.AsyncClient(timeout=20.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _call(self, method: str, params: dict[str, str], *, signed: bool, post: bool = False) -> dict:
        data = {"method": method, "api_key": self._api_key, **params}
        if signed:
            data["api_sig"] = sign(data, self._secret)
        data["format"] = "json"
        try:
            if post:
                response = await self._client.post(API_URL, data=data)
            else:
                response = await self._client.get(API_URL, params=data)
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise LastfmAuthError(f"Last.fm injoignable : {exc}") from exc
        if "error" in body:
            raise LastfmAuthError(f"Last.fm : {body.get('message') or body['error']}")
        return body

    async def get_token(self) -> str:
        body = await self._call("auth.getToken", {}, signed=True)
        token = body.get("token")
        if not isinstance(token, str) or not token:
            raise LastfmAuthError("Last.fm : jeton de connexion invalide.")
        return token

    async def get_session(self, token: str) -> LastfmSession:
        body = await self._call("auth.getSession", {"token": token}, signed=True)
        session = body.get("session") or {}
        if not session.get("name") or not session.get("key"):
            raise LastfmAuthError("Last.fm : session invalide.")
        return LastfmSession(username=session["name"], key=session["key"])

    async def profile(self, username: str) -> LastfmProfile:
        try:
            body = await self._call("user.getInfo", {"user": username}, signed=False)
        except LastfmAuthError:
            return LastfmProfile(display_name=None, avatar_url=None)
        user = body.get("user") or {}
        avatar = None
        for image in user.get("image") or []:
            url = image.get("#text") if isinstance(image, dict) else None
            if url and _PLACEHOLDER_IMAGE not in url:
                avatar = url
        return LastfmProfile(display_name=(user.get("realname") or "").strip() or None, avatar_url=avatar)

    async def update_now_playing(
        self, session_key: str, title: str, artist: str, album: str | None, duration: int | None
    ) -> None:
        """« En train d'écouter » sur le profil Last.fm (s'efface tout seul à
        la fin du titre, ou quand un scrobble arrive)."""
        params = {"sk": session_key, "track": title, "artist": artist}
        if album:
            params["album"] = album
        if duration:
            params["duration"] = str(duration)
        await self._call("track.updateNowPlaying", params, signed=True, post=True)

    async def scrobble(self, session_key: str, plays: list[Play]) -> None:
        """Envoie des écoutes terminées sur le profil Last.fm de l'utilisateur
        (par lots de 50, le maximum accepté)."""
        for start in range(0, len(plays), SCROBBLE_BATCH):
            params: dict[str, str] = {"sk": session_key}
            for i, play in enumerate(plays[start:start + SCROBBLE_BATCH]):
                params[f"artist[{i}]"] = play.artist
                params[f"track[{i}]"] = play.title
                params[f"timestamp[{i}]"] = str(int(datetime.fromisoformat(play.played_at).timestamp()))
                if play.album:
                    params[f"album[{i}]"] = play.album
                if play.duration_seconds:
                    params[f"duration[{i}]"] = str(play.duration_seconds)
            await self._call("track.scrobble", params, signed=True, post=True)

    async def love(self, session_key: str, title: str, artist: str) -> None:
        """♥ sur Last.fm (titre aimé)."""
        await self._call("track.love", {"sk": session_key, "track": title, "artist": artist}, signed=True, post=True)

    async def unlove(self, session_key: str, title: str, artist: str) -> None:
        await self._call("track.unlove", {"sk": session_key, "track": title, "artist": artist}, signed=True, post=True)

    async def loved_tracks(self, username: str, max_tracks: int = 2000) -> list[LovedTrack]:
        """Titres aimés du profil, du plus récent au plus ancien."""
        loved: list[LovedTrack] = []
        page, total_pages = 1, 1
        while page <= total_pages and len(loved) < max_tracks:
            body = await self._call(
                "user.getLovedTracks", {"user": username, "limit": "200", "page": str(page)}, signed=False
            )
            block = body.get("lovedtracks") or {}
            total_pages = int((block.get("@attr") or {}).get("totalPages") or 1)
            for item in block.get("track") or []:
                artist = item.get("artist") or {}
                artist_name = (artist.get("name") or artist.get("#text") or "") if isinstance(artist, dict) else str(artist)
                title = (item.get("name") or "").strip()
                if not title or not artist_name.strip():
                    continue
                uts = (item.get("date") or {}).get("uts")
                loved.append(LovedTrack(
                    title=title, artist=artist_name.strip(),
                    loved_at=datetime.fromtimestamp(int(uts), tz=timezone.utc) if uts else None,
                ))
            page += 1
        return loved[:max_tracks]
