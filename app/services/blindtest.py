"""Blind test : des extraits de quelques secondes, quatre propositions, le
plus vite possible.

Les titres viennent des écoutes (les siennes et celles des amis pour une
partie libre ; de tout le monde pour le défi du jour, identique pour chacun),
complétées au besoin par le classement Deezer. Les extraits sont les
extraits officiels de 30 s de Deezer, redemandés à chaque partie : leurs
adresses expirent.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.providers.base import TrackInfo
from app.providers.deezer import DeezerError
from app.services import stats as stats_service

logger = logging.getLogger(__name__)

QUESTIONS = 10
CHOICES = 4
POOL_DAYS = 180


@dataclass(slots=True)
class Candidate:
    source_id: str
    title: str
    artist: str


def _key(title: str, artist: str) -> tuple[str, str]:
    return (title.casefold().strip(), artist.casefold().strip())


async def _pool(deps, user_ids: list[int]) -> list[Candidate]:
    since = stats_service.to_utc_iso(datetime.now(timezone.utc) - timedelta(days=POOL_DAYS))
    seen: dict[tuple[str, str], Candidate] = {}
    for user_id in user_ids:
        for play in await deps.repo.plays_between(user_id, since, None):
            if play.source != "deezer" or not play.source_id:
                continue
            key = _key(play.title, play.artist)
            if key not in seen:
                seen[key] = Candidate(play.source_id, play.title, play.artist)
    return list(seen.values())


async def _chart(deps) -> list[Candidate]:
    try:
        tracks = await deps.deezer.get_chart_tracks(limit=60)
    except DeezerError as exc:
        logger.info("Classement Deezer indisponible pour le blind test : %s", exc)
        return []
    return [Candidate(t.source_id, t.title, t.artist) for t in tracks]


async def build_round(deps, user_ids: list[int], seed: str | int | None) -> list[dict]:
    rng = random.Random(seed)
    pool = await _pool(deps, user_ids)
    if len(pool) < QUESTIONS + CHOICES:
        known = {_key(c.title, c.artist) for c in pool}
        pool += [c for c in await _chart(deps) if _key(c.title, c.artist) not in known]
    # Ordre stable avant le tirage : le défi du jour doit être le même pour tous.
    pool.sort(key=lambda c: (c.artist.casefold(), c.title.casefold()))
    rng.shuffle(pool)

    questions: list[dict] = []
    used_artists: set[str] = set()
    for candidate in pool:
        if len(questions) >= QUESTIONS:
            break
        if candidate.artist.casefold() in used_artists:
            continue  # un artiste par question : plus varié
        try:
            track: TrackInfo = await deps.deezer.get_track(candidate.source_id)
        except DeezerError:
            continue
        if not track.preview_url:
            continue
        others = [c for c in pool if _key(c.title, c.artist) != _key(candidate.title, candidate.artist)]
        # Leurres d'autres artistes d'abord (sinon trop facile... ou trop dur).
        rng.shuffle(others)
        decoys: list[Candidate] = []
        for other in others:
            if len(decoys) == CHOICES - 1:
                break
            if other.artist.casefold() != candidate.artist.casefold() and all(
                _key(other.title, other.artist) != _key(d.title, d.artist) for d in decoys
            ):
                decoys.append(other)
        if len(decoys) < CHOICES - 1:
            continue
        choices = [candidate, *decoys]
        rng.shuffle(choices)
        used_artists.add(candidate.artist.casefold())
        questions.append({
            "preview_url": track.preview_url,
            "cover_url": track.cover_url,
            "answer": choices.index(candidate),
            "choices": [{"title": c.title, "artist": c.artist} for c in choices],
            "track": {
                "source": track.source, "source_id": track.source_id, "title": track.title,
                "artist": track.artist, "album": track.album, "year": track.year,
                "duration_seconds": track.duration_seconds, "cover_url": track.cover_url,
                "artist_source_id": track.artist_source_id, "album_source_id": track.album_source_id,
            },
        })
    return questions
