from __future__ import annotations

import asyncio
import logging
import re
from difflib import SequenceMatcher
from functools import lru_cache

from ytmusicapi import YTMusic

from app.providers.base import TrackInfo

logger = logging.getLogger(__name__)

_FEAT_RE = re.compile(r"\(feat\.?[^)]*\)|\[feat\.?[^\]]*\]|feat\.?.*$", re.IGNORECASE)
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)


class ResolutionError(Exception):
    pass


@lru_cache(maxsize=1)
def _ytmusic() -> YTMusic:
    return YTMusic()


def _normalize(text: str) -> str:
    text = _FEAT_RE.sub("", text)
    text = _PUNCT_RE.sub(" ", text.lower())
    return " ".join(text.split())


def _score(track: TrackInfo, candidate: dict) -> float:
    cand_title = candidate.get("title") or ""
    cand_artists = ", ".join(a.get("name", "") for a in candidate.get("artists") or [])

    title_sim = SequenceMatcher(None, _normalize(track.title), _normalize(cand_title)).ratio()
    artist_sim = SequenceMatcher(None, _normalize(track.artist), _normalize(cand_artists)).ratio()

    score = title_sim * 0.6 + artist_sim * 0.4

    cand_duration = candidate.get("duration_seconds")
    if track.duration_seconds and cand_duration:
        diff = abs(track.duration_seconds - cand_duration)
        if diff <= 3:
            score += 0.15
        elif diff <= 8:
            score += 0.05
        elif diff > 20:
            score -= 0.2

    if candidate.get("resultType") == "song":
        score += 0.05

    return score


def _search_sync(query: str) -> list[dict]:
    yt = _ytmusic()
    results = yt.search(query, filter="songs", limit=10)
    if not results:
        results = yt.search(query, filter="videos", limit=10)
    return results


async def find_youtube_match(track: TrackInfo) -> tuple[str, TrackInfo] | None:
    """Cherche le meilleur équivalent YouTube Music pour un morceau.

    Retourne (video_id, TrackInfo YouTube du résultat choisi) ou None.
    """
    if track.source == "youtube":
        return track.source_id, track

    query = f"{track.artist} {track.title}"
    try:
        results = await asyncio.to_thread(_search_sync, query)
    except Exception as exc:  # ytmusicapi peut lever divers types selon la panne réseau
        logger.warning("Recherche YouTube Music échouée pour %r: %s", query, exc)
        raise ResolutionError("Recherche de la source impossible.") from exc

    if not results:
        return None

    best = max(results, key=lambda c: _score(track, c))
    if _score(track, best) < 0.35:
        return None

    video_id = best.get("videoId")
    if not video_id:
        return None

    thumbnails = best.get("thumbnails") or []
    matched = TrackInfo(
        source="youtube",
        source_id=video_id,
        title=best.get("title") or track.title,
        artist=", ".join(a.get("name", "") for a in best.get("artists") or []) or track.artist,
        album=(best.get("album") or {}).get("name") if isinstance(best.get("album"), dict) else None,
        year=None,
        duration_seconds=best.get("duration_seconds") or track.duration_seconds,
        cover_url=thumbnails[-1]["url"] if thumbnails else track.cover_url,
    )
    return video_id, matched
