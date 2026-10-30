"""Paroles via Genius (genius.com) : texte brut, **sans synchronisation**.

Genius n'a pas d'API de paroles : on lit sa recherche publique puis la page
du titre. Source de dernier recours — elle ne passe devant les autres que
lorsqu'elles n'ont rien (texte brut = palier 1) — et rien ici n'est garanti :
la moindre surprise lève `LyricsError` et le service passe son tour.
"""

from __future__ import annotations

import html
import json
import logging
import re
from dataclasses import dataclass

import httpx

from app.providers.lrclib import Lyrics, LyricsError, LyricsLine

logger = logging.getLogger(__name__)

BASE_URL = "https://genius.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "en,fr;q=0.8",
}
SEARCH_LIMIT = 5

_CONTAINER_RE = re.compile(r'<div[^>]*data-lyrics-container="true"[^>]*>', re.IGNORECASE)
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
# Mentions de structure ([Couplet 1], [Refrain: X]…) : pas des paroles.
_SECTION_RE = re.compile(r"^\[[^\]]*\]$")
_EMBED_RE = re.compile(r"\d*\s*Embed$")


@dataclass(slots=True)
class GeniusSong:
    title: str
    artist: str
    url: str


def _container_text(page: str, start: int) -> str:
    """Contenu du `<div>` qui s'ouvre à `start`, en comptant les `<div>` imbriqués."""
    depth = 1
    for tag in re.finditer(r"<(/?)div\b", page[start:], re.IGNORECASE):
        depth += -1 if tag.group(1) else 1
        if depth == 0:
            return page[start:start + tag.start()]
    return page[start:]


def parse_lyrics_page(page: str) -> Lyrics | None:
    chunks = []
    for opening in _CONTAINER_RE.finditer(page):
        chunks.append(_container_text(page, opening.end()))
    if not chunks:
        return None
    text = html.unescape(_TAG_RE.sub("", _BR_RE.sub("\n", "\n".join(chunks))))
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            lines.append(None)
        elif not _SECTION_RE.match(line) and not _EMBED_RE.match(line):
            lines.append(line)
    # Lignes vides en tête, en queue ou doublées : on les écarte ; un couplet
    # sépare deux blocs par une ligne vide.
    out: list[LyricsLine] = []
    for line in lines:
        if line is None:
            if out and out[-1].text:
                out.append(LyricsLine(None, ""))
        else:
            out.append(LyricsLine(None, line))
    while out and not out[-1].text:
        out.pop()
    if not any(line.text for line in out):
        return None
    return Lyrics(synced=False, lines=out)


class GeniusClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(base_url=BASE_URL, timeout=8.0, headers=HEADERS, follow_redirects=True)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict | None = None) -> httpx.Response:
        try:
            response = await self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise LyricsError(f"Genius injoignable : {exc}") from exc
        if response.status_code != 200:
            raise LyricsError(f"Genius a répondu {response.status_code}")
        return response

    async def search(self, title: str, artist: str) -> list[GeniusSong]:
        response = await self._get("/api/search/song", {"q": f"{artist} {title}", "per_page": SEARCH_LIMIT})
        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise LyricsError("Réponse Genius illisible") from exc
        songs: list[GeniusSong] = []
        for section in ((data.get("response") or {}).get("sections") or []):
            for hit in section.get("hits") or []:
                result = hit.get("result") or {}
                url = result.get("url")
                if not url or not result.get("title"):
                    continue
                songs.append(GeniusSong(
                    title=str(result["title"]),
                    artist=str((result.get("primary_artist") or {}).get("name") or result.get("artist_names") or ""),
                    url=str(url),
                ))
        return songs

    async def lyrics(self, song: GeniusSong) -> Lyrics | None:
        if not song.url.startswith(BASE_URL + "/"):
            return None
        response = await self._get(song.url[len(BASE_URL):])
        return parse_lyrics_page(response.text)
