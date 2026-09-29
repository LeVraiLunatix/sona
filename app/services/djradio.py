"""Radio DJ : une station sans fin à partir d'un titre, dont l'ordre est
pensé pour l'AutoMix — des tempos qui s'enchaînent (même BPM, ou moitié /
double), jamais deux fois le même artiste d'affilée, le tout en restant dans
l'univers du titre de départ.

Les candidats viennent de Deezer (mix de l'artiste, titres des artistes
proches). Leur tempo n'est donné que par la fiche complète d'un titre : on
en complète une vingtaine par tirage, en parallèle, puis on construit la
chaîne pas à pas en partant du tempo du dernier titre joué. L'app rappelle
la radio avec son dernier titre en file : la chaîne continue sans couture.
"""

from __future__ import annotations

import asyncio
import logging
import random

from app.providers.base import TrackInfo
from app.providers.deezer import DeezerError, _artist_key

logger = logging.getLogger(__name__)

BATCH = 15
DETAILED = 24
# Au-delà de cet écart relatif, le tempo ne se cale plus (voir l'AutoMix).
TEMPO_TOLERANCE = 0.08


def tempo_distance(a: float | None, b: float | None) -> float:
    """Écart relatif de tempo, en tenant compte des moitiés / doubles (un
    titre à 70 BPM se mixe très bien avec un titre à 140)."""
    if not a or not b:
        return 0.12  # inconnu : ni favorisé ni exclu
    return min(abs(a / b - 1), abs(a / (b * 2) - 1), abs((a * 2) / b - 1))


def chain(seed_bpm: float | None, seed_artist: str, candidates: list[TrackInfo], count: int, rng: random.Random) -> list[TrackInfo]:
    """Chaîne gloutonne : à chaque pas, le candidat le plus facile à mixer
    avec le précédent, un artiste différent des deux derniers."""
    remaining = list(candidates)
    out: list[TrackInfo] = []
    bpm = seed_bpm
    recent = [_artist_key(seed_artist)]
    while remaining and len(out) < count:
        def cost(t: TrackInfo) -> float:
            c = tempo_distance(bpm, t.bpm)
            if c > TEMPO_TOLERANCE:
                c += 0.2  # hors calage : seulement faute de mieux
            if _artist_key(t.artist) in recent[-2:]:
                c += 1.0
            return c + rng.random() * 0.03
        best = min(remaining, key=cost)
        remaining.remove(best)
        out.append(best)
        bpm = best.bpm or bpm
        recent.append(_artist_key(best.artist))
    return out


async def _deezer_seed(deps, track: TrackInfo) -> TrackInfo | None:
    if track.source == "deezer":
        try:
            return await deps.deezer.get_track(track.source_id)
        except DeezerError:
            return track
    try:
        found, _ = await deps.deezer.search_tracks(f"{track.artist} {track.title}", limit=1)
    except DeezerError:
        return None
    if not found:
        return None
    try:
        return await deps.deezer.get_track(found[0].source_id)
    except DeezerError:
        return found[0]


async def build(deps, seed: TrackInfo, exclude: set[str], count: int = BATCH, rng: random.Random | None = None) -> list[TrackInfo]:
    rng = rng or random.Random()
    full = await _deezer_seed(deps, seed)
    if full is None or not full.artist_source_id:
        return []
    exclude = exclude | {full.source_id, seed.source_id}

    pool: list[TrackInfo] = []
    try:
        pool += await deps.deezer.get_artist_radio(full.artist_source_id, limit=40)
        related = await deps.deezer.get_related_artists(full.artist_source_id, limit=10)
        picks = rng.sample(related, min(4, len(related)))
        tops = await asyncio.gather(
            *(deps.deezer.get_artist_top_tracks(a.source_id, limit=6) for a in picks), return_exceptions=True
        )
        for result in tops:
            if isinstance(result, list):
                pool += result
    except DeezerError as exc:
        logger.info("Radio DJ : Deezer indisponible (%s)", exc)
    seen: set[str] = set()
    candidates = []
    for t in pool:
        key = f"{t.title.casefold()}|{_artist_key(t.artist)}"
        if t.source_id in exclude or key in seen:
            continue
        seen.add(key)
        candidates.append(t)
    rng.shuffle(candidates)
    candidates = candidates[:DETAILED]

    # Tempo : fiche complète de chaque candidat (en parallèle, Deezer limite
    # lui-même le débit côté client).
    async def detailed(t: TrackInfo) -> TrackInfo:
        if t.bpm:
            return t
        try:
            return await deps.deezer.get_track(t.source_id)
        except DeezerError:
            return t
    candidates = list(await asyncio.gather(*(detailed(t) for t in candidates)))
    return chain(full.bpm, full.artist, candidates, count, rng)
