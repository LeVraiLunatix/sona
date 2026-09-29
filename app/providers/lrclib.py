"""Paroles via LRCLIB (https://lrclib.net) : base publique et gratuite, sans
clé d'API, qui fournit des paroles synchronisées au format LRC
(`[mm:ss.xx] texte`) pour une grande partie du catalogue, et au moins les
paroles brutes pour beaucoup d'autres."""

from __future__ import annotations

import logging
import re
from collections import OrderedDict
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

API_BASE = "https://lrclib.net/api"
# LRCLIB demande explicitement un User-Agent qui identifie l'application
# (ASCII seulement : un en-tête HTTP accentué fait échouer httpx).
USER_AGENT = "Sona/1.0 (bot musical prive; https://github.com/LeVraiLunatix/sona)"
# Écart de durée toléré entre notre morceau et une entrée LRCLIB : au-delà,
# c'est probablement une autre version (live, remix, radio edit) dont les
# paroles synchronisées seraient décalées.
DURATION_TOLERANCE = 3
CACHE_SIZE = 256

_LRC_LINE_RE = re.compile(r"\[(\d+):(\d+(?:[.:]\d+)?)\]")
# LRC « enrichi » : un horodatage par mot, `<00:12.34>mot`.
_WORD_STAMP_RE = re.compile(r"<(\d+):(\d+(?:[.:]\d+)?)>")
# « (feat. X) », « [Remastered 2011] », « - Radio Edit »... : absents des
# titres LRCLIB la plupart du temps, ils font échouer la correspondance exacte.
_TITLE_NOISE_RE = re.compile(
    r"\s*[\(\[][^)\]]*\b(feat|ft|with|remaster\w*|version|edit|live|mono|stereo|deluxe|bonus)\b[^)\]]*[\)\]]"
    r"|\s+-\s+.*\b(remaster\w*|version|edit|live|mono|stereo)\b.*$",
    re.IGNORECASE,
)

# « x » seulement entouré d'espaces : « Ziak x Gazo », pas « Malcolm X ».
_ARTIST_SEP_RE = re.compile(r"\s*(?:,|&|\bfeat\.?\s|\bft\.?\s)\s*|\s+x\s+", re.IGNORECASE)


class LyricsError(Exception):
    pass


@dataclass(slots=True)
class LyricsWord:
    time: float
    text: str


@dataclass(slots=True)
class LyricsLine:
    time: float | None  # secondes depuis le début ; None pour des paroles non synchronisées
    text: str
    # Mot par mot, quand la source le donne (LRC enrichi) ; sinon l'app
    # répartit elle-même la ligne.
    words: list[LyricsWord] | None = None


@dataclass(slots=True)
class Lyrics:
    synced: bool
    instrumental: bool = False
    lines: list[LyricsLine] = field(default_factory=list)


def clean_title(title: str) -> str:
    return _TITLE_NOISE_RE.sub("", title).strip() or title


def main_artist(artist: str) -> str:
    """« Aya Nakamura, Ninho » / « Ziak feat. Gazo » → « Aya Nakamura » /
    « Ziak » : LRCLIB indexe rarement tous les artistes crédités."""
    return _ARTIST_SEP_RE.split(artist, maxsplit=1)[0].strip() or artist


def _stamp(minutes: str, seconds: str) -> float:
    return int(minutes) * 60 + float(seconds.replace(":", "."))


def parse_words(lyric: str) -> tuple[str, list[LyricsWord] | None]:
    """`<00:01.00>Je <00:01.40>suis` → texte propre et mots horodatés."""
    stamps = list(_WORD_STAMP_RE.finditer(lyric))
    if not stamps:
        return lyric, None
    words: list[LyricsWord] = []
    for i, m in enumerate(stamps):
        end = stamps[i + 1].start() if i + 1 < len(stamps) else len(lyric)
        chunk = lyric[m.end():end]
        if chunk.strip():
            words.append(LyricsWord(_stamp(m.group(1), m.group(2)), chunk))
    clean = _WORD_STAMP_RE.sub("", lyric)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean, (words or None)


def parse_lrc(text: str) -> list[LyricsLine]:
    """Une ligne LRC peut porter plusieurs horodatages (refrain répété) :
    une entrée par horodatage, le tout trié par temps. Les balises de
    métadonnées (`[ar:...]`, `[offset:...]`) ne correspondent pas au motif
    et sont ignorées."""
    lines: list[LyricsLine] = []
    for raw in text.splitlines():
        stamps = list(_LRC_LINE_RE.finditer(raw))
        if not stamps:
            continue
        lyric, words = parse_words(raw[stamps[-1].end():].strip())
        for m in stamps:
            start = _stamp(m.group(1), m.group(2))
            # Refrain répété : mêmes mots décalés à la nouvelle position.
            shifted = None
            if words:
                delta = start - _stamp(stamps[0].group(1), stamps[0].group(2))
                shifted = [LyricsWord(w.time + delta, w.text) for w in words]
            lines.append(LyricsLine(time=start, text=lyric, words=shifted))
    lines.sort(key=lambda line: line.time or 0.0)
    return lines


def _lyrics_from_json(d: dict) -> Lyrics | None:
    if d.get("instrumental"):
        return Lyrics(synced=False, instrumental=True)
    synced = d.get("syncedLyrics")
    if synced:
        lines = parse_lrc(synced)
        if lines:
            return Lyrics(synced=True, lines=lines)
    plain = d.get("plainLyrics")
    if plain:
        return Lyrics(synced=False, lines=[LyricsLine(time=None, text=t.strip()) for t in plain.splitlines()])
    return None


def _duration_ok(d: dict, duration: int | None) -> bool:
    if duration is None or not d.get("duration"):
        return True
    return abs(float(d["duration"]) - duration) <= DURATION_TOLERANCE


class LrclibClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(
            base_url=API_BASE, timeout=10.0, headers={"User-Agent": USER_AGENT}
        )
        # Le lecteur redemande les paroles à chaque ouverture du panneau :
        # on garde les réponses (y compris « rien trouvé ») en mémoire.
        self._cache: OrderedDict[tuple, Lyrics | None] = OrderedDict()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, path: str, params: dict) -> httpx.Response:
        try:
            response = await self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise LyricsError(f"LRCLIB injoignable : {exc}") from exc
        if response.status_code >= 500:
            raise LyricsError(f"LRCLIB a répondu {response.status_code}")
        return response

    async def get_lyrics(
        self, title: str, artist: str, album: str | None = None, duration: int | None = None
    ) -> Lyrics | None:
        key = (title.casefold(), artist.casefold(), (album or "").casefold(), duration)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]

        lyrics = await self._lookup(title, artist, album, duration)

        self._cache[key] = lyrics
        if len(self._cache) > CACHE_SIZE:
            self._cache.popitem(last=False)
        return lyrics

    async def _lookup(self, title: str, artist: str, album: str | None, duration: int | None) -> Lyrics | None:
        # 1) Correspondance exacte (titre, artiste, album, durée à ±2 s côté
        #    LRCLIB) : la plus fiable quand elle répond.
        if duration:
            params = {"track_name": title, "artist_name": artist, "duration": duration}
            if album:
                params["album_name"] = album
            response = await self._request("/get", params)
            if response.status_code == 200:
                found = _lyrics_from_json(response.json())
                if found:
                    return found

        # 2) Recherche avec le titre nettoyé et l'artiste principal : rattrape
        #    les « (feat. X) », « - Remastered », artistes multiples... En
        #    préférant une entrée synchronisée de durée compatible.
        response = await self._request(
            "/search", {"track_name": clean_title(title), "artist_name": main_artist(artist)}
        )
        if response.status_code != 200:
            return None
        results = [d for d in response.json() if isinstance(d, dict)]
        candidates = [d for d in results if _duration_ok(d, duration)]
        candidates.sort(key=lambda d: (not d.get("syncedLyrics"), not d.get("plainLyrics")))
        for d in candidates:
            found = _lyrics_from_json(d)
            if found:
                return found
        # 3) Aucune version de même durée : les paroles brutes d'une autre
        #    version restent justes, seul l'horodatage serait décalé.
        for d in results:
            if d.get("plainLyrics") and not d.get("instrumental"):
                return _lyrics_from_json({"plainLyrics": d["plainLyrics"]})
        return None
