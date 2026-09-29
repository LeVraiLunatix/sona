"""Karaoké : la version instrumentale d'un titre sur YouTube, quand elle
existe. Bien meilleure que d'effacer la voix par traitement du son — mais
il faut qu'elle ait la même durée, sinon les paroles se décaleraient."""

from __future__ import annotations

import asyncio
import re
import unicodedata

from app.providers.base import TrackInfo
from app.services.resolver import _search_ytmusic_sync, _search_ytdlp_sync

# Écart de durée toléré avec le titre original (secondes).
MAX_DURATION_GAP = 4
_INSTRUMENTAL = re.compile(r"\b(instru|instrumental|instrumentale|karaoke|karaoké|backing track)\b", re.IGNORECASE)
_UNWANTED = re.compile(r"\b(remix|cover|reprise|type beat|slowed|sped up|speed up|nightcore|8d|piano|acoustic)\b", re.IGNORECASE)

_cache: dict[tuple[str, str], str | None] = {}


def reset() -> None:
    _cache.clear()


def _key(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if ch.isalnum() and not unicodedata.combining(ch))


def pick(track: TrackInfo, candidates) -> str | None:
    """La meilleure instrumentale : le titre du morceau dans son nom, marquée
    « instrumental », pas un remix, et à la bonne durée."""
    title = _key(re.sub(r"\(.*?\)|\[.*?\]", "", track.title)) or _key(track.title)
    best, best_gap = None, None
    for c in candidates:
        name = f"{c.title} {c.album or ''}"
        if not _INSTRUMENTAL.search(name) or _UNWANTED.search(name) or title not in _key(c.title):
            continue
        if track.duration_seconds and c.duration_seconds:
            gap = abs(track.duration_seconds - c.duration_seconds)
            if gap > MAX_DURATION_GAP:
                continue
        elif track.duration_seconds:
            continue  # durée inconnue : impossible de garantir le calage des paroles
        else:
            gap = 0
        if best_gap is None or gap < best_gap:
            best, best_gap = c.video_id, gap
    return best


async def find(track: TrackInfo, cookies_file=None) -> str | None:
    key = (track.source, track.source_id)
    if key in _cache:
        return _cache[key]
    artist = track.artist.split(",")[0].strip()
    queries = [f"{artist} {track.title} instrumental", f"{track.title} instrumental"]
    found = pick(track, await asyncio.to_thread(_search_ytmusic_sync, queries))
    if found is None:
        found = pick(track, await asyncio.to_thread(_search_ytdlp_sync, queries[0], cookies_file))
    _cache[key] = found
    return found
