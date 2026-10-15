"""Paroles via Musixmatch (API de l'app de bureau, non officielle) : le
plus gros catalogue de paroles synchronisées **au mot près** (« richsync »).

Musixmatch ne répond correctement qu'avec un jeton d'utilisateur
(`MUSIXMATCH_TOKEN` dans le .env, à recopier depuis l'app Musixmatch de
bureau). Sans lui, on tente un jeton anonyme ; depuis 2025, Musixmatch en
donne un factice (que des zéros) qui renvoie des titres au hasard : on le
détecte et la source se met en veille, sans jamais servir de paroles
fausses (le service de paroles vérifie de toute façon titre, artiste et
durée de ce qui revient).
"""

from __future__ import annotations

import json
import logging
import re
import time

import httpx

from app.providers.lrclib import Lyrics, LyricsError, LyricsLine, LyricsWord

logger = logging.getLogger(__name__)

API_BASE = "https://apic-desktop.musixmatch.com/ws/1.1"
APP_ID = "web-desktop-app-v1.0"
HEADERS = {
    "Cookie": "AWSELB=0; AWSELBCORS=0",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Musixmatch/3.14.0 Chrome/120.0 Electron/28.0 Safari/537.36",
}
# Jeton refusé ou factice : on ne réessaie pas avant ce délai.
COOLDOWN_SECONDS = 30 * 60
# Mention ajoutée par Musixmatch au bas des paroles brutes gratuites.
_TRAILER_RE = re.compile(r"\n*\*{3,}.*$", re.DOTALL)


def _valid_token(token: str | None) -> bool:
    return bool(token) and set(token) != {"0"}


def parse_richsync(body: str) -> list[LyricsLine]:
    """richsync : `[{"ts": 12.3, "te": 15.0, "l": [{"c": "Hello", "o": 0}, …], "x": "Hello world"}]`
    → lignes, chaque mot à `ts + o` ; un mot finit où commence le suivant."""
    lines: list[LyricsLine] = []
    for raw in json.loads(body):
        start, end = float(raw["ts"]), float(raw.get("te") or raw["ts"])
        chunks = [c for c in raw.get("l") or [] if c.get("c")]
        words: list[LyricsWord] = []
        for chunk in chunks:
            text = str(chunk["c"])
            begin = start + float(chunk.get("o") or 0)
            if not text.strip():
                # Espace entre deux mots : on le recolle au mot d'avant.
                if words:
                    words[-1].text += text
                continue
            words.append(LyricsWord(begin, text))
        for i, word in enumerate(words):
            word.end = words[i + 1].time if i + 1 < len(words) else end
        text = str(raw.get("x") or "".join(w.text for w in words)).strip()
        if text:
            lines.append(LyricsLine(time=start, text=text, words=words or None, end=end))
    return lines


def parse_subtitles(body: str) -> list[LyricsLine]:
    """Sous-titres (une ligne horodatée par vers) : `[{"text": "…", "time": {"total": 12.3}}]`."""
    lines = [
        LyricsLine(time=float(raw["time"]["total"]), text=str(raw.get("text") or "").strip())
        for raw in json.loads(body)
    ]
    return [line for line in lines if line.text]


class MusixmatchClient:
    def __init__(self, token: str | None = None, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(base_url=API_BASE, timeout=8.0, headers=HEADERS)
        self._configured = token
        self._token: str | None = token if _valid_token(token) else None
        self._sleep_until = 0.0

    async def aclose(self) -> None:
        await self._client.aclose()

    @property
    def available(self) -> bool:
        return time.monotonic() >= self._sleep_until

    def _pause(self, why: str) -> None:
        logger.info("Musixmatch en veille %d min : %s", COOLDOWN_SECONDS // 60, why)
        self._sleep_until = time.monotonic() + COOLDOWN_SECONDS
        if not _valid_token(self._configured):
            self._token = None

    async def _call(self, method: str, params: dict) -> dict:
        try:
            response = await self._client.get(f"/{method}", params={"app_id": APP_ID, "format": "json", **params})
        except httpx.HTTPError as exc:
            raise LyricsError(f"Musixmatch injoignable : {exc}") from exc
        if response.status_code != 200:
            raise LyricsError(f"Musixmatch a répondu {response.status_code}")
        try:
            message = response.json()["message"]
        except (ValueError, KeyError, TypeError) as exc:
            raise LyricsError("Réponse Musixmatch illisible") from exc
        status = (message.get("header") or {}).get("status_code")
        if status in (401, 402):
            self._pause(f"jeton refusé ({status})")
            raise LyricsError("Jeton Musixmatch refusé")
        return message

    async def _ensure_token(self) -> str:
        if self._token:
            return self._token
        message = await self._call("token.get", {"user_language": "fr", "t": str(int(time.time() * 1000))})
        token = ((message.get("body") or {}).get("user_token")) or None
        if not _valid_token(token):
            self._pause("jeton anonyme factice")
            raise LyricsError("Musixmatch ne donne pas de jeton (MUSIXMATCH_TOKEN absent)")
        self._token = token
        return token

    async def find(
        self, title: str, artist: str, album: str | None, duration: int | None
    ) -> tuple[dict, Lyrics] | None:
        """Morceau reconnu par Musixmatch (ses métadonnées, pour vérifier la
        correspondance) et ses meilleures paroles. None : rien de connu."""
        if not self.available:
            return None
        token = await self._ensure_token()
        params = {
            "namespace": "lyrics_richsynched", "subtitle_format": "mxm", "q_track": title,
            "q_artist": artist, "q_artists": artist, "usertoken": token,
        }
        if album:
            params["q_album"] = album
        if duration:
            params["q_duration"] = duration
            params["f_subtitle_length"] = duration
        body = (await self._call("macro.subtitles.get", params)).get("body") or {}
        calls = body.get("macro_calls") or {}

        def call_body(name: str) -> dict:
            message = (calls.get(name) or {}).get("message") or {}
            return message.get("body") if isinstance(message.get("body"), dict) else {}

        track = call_body("matcher.track.get").get("track")
        if not isinstance(track, dict) or not track.get("track_id"):
            return None
        meta = {
            "title": track.get("track_name") or "",
            "artist": track.get("artist_name") or "",
            "album": track.get("album_name") or None,
            "duration": float(track["track_length"]) if track.get("track_length") else None,
        }
        if track.get("instrumental"):
            return meta, Lyrics(synced=False, instrumental=True)

        lyrics_body = call_body("track.lyrics.get").get("lyrics") or {}
        language = lyrics_body.get("lyrics_language") or None

        lines: list[LyricsLine] = []
        if track.get("has_richsync"):
            try:
                rich = await self._call("track.richsync.get", {"track_id": track["track_id"], "usertoken": token})
                rich_body = ((rich.get("body") or {}).get("richsync") or {}).get("richsync_body")
                if rich_body:
                    lines = parse_richsync(rich_body)
            except (LyricsError, ValueError, KeyError, TypeError) as exc:
                logger.debug("Richsync Musixmatch illisible : %s", exc)
        if not lines:
            subtitles = call_body("track.subtitles.get").get("subtitle_list") or []
            try:
                sub_body = subtitles[0]["subtitle"]["subtitle_body"] if subtitles else None
                lines = parse_subtitles(sub_body) if sub_body else []
            except (ValueError, KeyError, TypeError, IndexError):
                lines = []
        if lines:
            meta["language"] = language
            return meta, Lyrics(synced=True, lines=lines)

        plain = _TRAILER_RE.sub("", str(lyrics_body.get("lyrics_body") or "")).strip()
        if plain:
            meta["language"] = language
            return meta, Lyrics(synced=False, lines=[LyricsLine(time=None, text=t.strip()) for t in plain.splitlines()])
        return None
