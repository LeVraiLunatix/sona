"""Mode sport : des titres au tempo de ta foulée. L'app mesure ta cadence
(pas par minute, podomètre de l'iPhone) ; on cherche dans l'univers de tes
artistes préférés des titres à ce tempo (ou à sa moitié / son double :
un titre à 85 BPM se court très bien à 170 pas par minute)."""

from __future__ import annotations

import asyncio
import random

from app.providers.base import TrackInfo
from app.providers.deezer import DeezerError
from app.services.djradio import tempo_distance
from app.services.releases import favourite_artists

DETAILED = 40
CLOSE = 0.06


async def tracks_for_tempo(
    deps, user_id: int, bpm: float, exclude: set[str], count: int = 15, rng: random.Random | None = None
) -> list[TrackInfo]:
    rng = rng or random.Random()
    artists = await favourite_artists(deps, user_id, count=8)
    pool: list[TrackInfo] = []
    try:
        for _, artist_id in rng.sample(artists, min(3, len(artists))):
            pool += await deps.deezer.get_artist_radio(artist_id, limit=40)
        if len(pool) < 40:
            pool += await deps.deezer.get_chart_tracks(limit=100)
    except DeezerError:
        pass
    seen: set[str] = set()
    candidates = []
    for t in pool:
        if t.source_id in exclude or t.source_id in seen:
            continue
        seen.add(t.source_id)
        candidates.append(t)
    rng.shuffle(candidates)
    candidates = candidates[:DETAILED]
    semaphore = asyncio.Semaphore(6)

    async def detailed(t: TrackInfo) -> TrackInfo:
        if t.bpm:
            return t
        async with semaphore:
            try:
                return await deps.deezer.get_track(t.source_id)
            except DeezerError:
                return t

    candidates = list(await asyncio.gather(*(detailed(t) for t in candidates)))
    with_tempo = [t for t in candidates if t.bpm]
    with_tempo.sort(key=lambda t: tempo_distance(bpm, t.bpm))
    close = [t for t in with_tempo if tempo_distance(bpm, t.bpm) <= CLOSE]
    rest = [t for t in with_tempo if t not in close]
    return (close + rest)[:count]
