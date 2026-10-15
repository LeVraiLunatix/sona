"""Paroles via NetEase Cloud Music (music.163.com) : API publique non
officielle, sans clé, qui a des paroles synchronisées **au mot près**
(format « yrc ») pour une grande partie du catalogue international — y
compris beaucoup de titres que LRCLIB n'a qu'à la ligne.

Format yrc, une ligne par vers (temps en millisecondes) :
`[31420,2670](31420,390,0)Like (31810,150,0)the (31960,630,0)legend`
→ début et durée du vers, puis chaque mot avec son début et sa durée.

Rien ici n'est garanti (API non documentée) : la moindre surprise lève
`LyricsError`, et le service de paroles passe à la source suivante.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

import httpx

from app.providers.lrclib import Lyrics, LyricsError, LyricsLine, LyricsWord, parse_lrc

logger = logging.getLogger(__name__)

API_BASE = "https://music.163.com/api"
# Sans Referer ni User-Agent de navigateur, l'API répond souvent vide.
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Referer": "https://music.163.com/",
}
SEARCH_LIMIT = 8

_YRC_LINE_RE = re.compile(r"^\[(\d+),(\d+)\](.*)$")
_YRC_WORD_RE = re.compile(r"\((\d+),(\d+),\d+\)")
# Crédits glissés dans les paroles par NetEase : « 作词 : X », « 吉他：Y »,
# « Written by：Z »… (un intitulé court suivi de deux-points).
_CREDIT_RE = re.compile(
    r"^(?:[㐀-鿿\s/&]{1,12}"
    r"|(?:written|composed|produced|lyrics|lyricist|music|composer|producer|arranged|arranger"
    r"|mixed|mastered|recorded|vocals?|guitar|bass|drums|keyboards?)(?:\s+by)?"
    r")\s*[:：]",
    re.IGNORECASE,
)
# Ce que NetEase met à la place de paroles absentes (« pas encore de
# paroles ») ou d'un instrumental (« musique pure, profitez »).
_NO_LYRICS = "暂无歌词"
_INSTRUMENTAL = ("纯音乐，请欣赏", "纯音乐, 请欣赏")


@dataclass(slots=True)
class NeteaseSong:
    id: int
    title: str
    artist: str
    album: str | None
    duration: float | None  # secondes


def _is_credit(text: str) -> bool:
    return bool(_CREDIT_RE.match(text))


def parse_yrc(text: str) -> list[LyricsLine]:
    """yrc → lignes avec leurs mots horodatés (début et fin de chaque mot).
    Les lignes de crédits (JSON `{"t":…}` ou « 作词 : … ») sont ignorées."""
    lines: list[LyricsLine] = []
    for raw in text.splitlines():
        m = _YRC_LINE_RE.match(raw.strip())
        if not m:
            continue
        start, length, body = int(m.group(1)) / 1000, int(m.group(2)) / 1000, m.group(3)
        stamps = list(_YRC_WORD_RE.finditer(body))
        words: list[LyricsWord] = []
        for i, w in enumerate(stamps):
            chunk = body[w.end(): stamps[i + 1].start() if i + 1 < len(stamps) else len(body)]
            if not chunk:
                continue
            begin = int(w.group(1)) / 1000
            words.append(LyricsWord(begin, chunk, end=begin + int(w.group(2)) / 1000))
        line_text = re.sub(r"\s+", " ", "".join(w.text for w in words)).strip()
        if not line_text or _is_credit(line_text):
            continue
        lines.append(LyricsLine(time=start, text=line_text, words=words or None, end=start + length))
    lines.sort(key=lambda line: line.time or 0.0)
    return lines


def lyrics_from_payload(payload: dict) -> Lyrics | None:
    """Réponse de `/song/lyric/v1` → paroles : au mot près si le yrc est là,
    sinon à la ligne (LRC). None quand NetEase n'a rien de lisible."""
    if payload.get("nolyric") or payload.get("uncollected"):
        return None
    yrc = ((payload.get("yrc") or {}).get("lyric") or "").strip()
    if yrc:
        lines = parse_yrc(yrc)
        if lines:
            return Lyrics(synced=True, lines=lines)
    lrc = ((payload.get("lrc") or {}).get("lyric") or "").strip()
    if any(marker in lrc for marker in _INSTRUMENTAL):
        return Lyrics(synced=False, instrumental=True)
    if not lrc or _NO_LYRICS in lrc:
        return None
    lines = [line for line in parse_lrc(lrc) if line.text and not _is_credit(line.text)]
    if lines:
        return Lyrics(synced=True, lines=lines)
    return None


class NeteaseClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(base_url=API_BASE, timeout=8.0, headers=HEADERS)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict) -> dict:
        try:
            response = await self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise LyricsError(f"NetEase injoignable : {exc}") from exc
        if response.status_code != 200:
            raise LyricsError(f"NetEase a répondu {response.status_code}")
        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise LyricsError("Réponse NetEase illisible") from exc
        if not isinstance(data, dict):
            raise LyricsError("Réponse NetEase inattendue")
        return data

    async def search(self, title: str, artist: str) -> list[NeteaseSong]:
        data = await self._get("/search/get", {"s": f"{artist} {title}", "type": 1, "limit": SEARCH_LIMIT})
        songs: list[NeteaseSong] = []
        for raw in ((data.get("result") or {}).get("songs") or []):
            try:
                songs.append(NeteaseSong(
                    id=int(raw["id"]),
                    title=str(raw.get("name") or ""),
                    artist=", ".join(str(a.get("name") or "") for a in raw.get("artists") or [] if a.get("name")),
                    album=(raw.get("album") or {}).get("name") or None,
                    duration=(raw["duration"] / 1000) if raw.get("duration") else None,
                ))
            except (KeyError, TypeError, ValueError):
                continue
        return songs

    async def lyrics(self, song_id: int) -> Lyrics | None:
        data = await self._get("/song/lyric/v1", {
            "id": song_id, "cp": "false", "tv": 0, "lv": 0, "rv": 0, "kv": 0, "yv": 0, "ytv": 0, "yrv": 0,
        })
        return lyrics_from_payload(data)
