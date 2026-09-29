"""Blind test : des extraits de quelques secondes, quatre propositions, le
plus vite possible.

D'où viennent les titres (le « mode ») :
- `daily` : écoutes de tout le monde, tirage du jour identique pour chacun ;
- `solo` : tes écoutes et celles de tes amis ;
- `chart` : le top du moment (Deezer) ;
- `artist` : un artiste et ses proches (titres populaires) ;
- `radio` : une radio thématique Deezer (rap FR, années 2000…) ;
- `playlist` : une de tes playlists.
On devine le titre (`guess=title`) ou l'artiste (`guess=artist`). Les
extraits sont les extraits officiels de 30 s de Deezer, redemandés à chaque
partie : leurs adresses expirent.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone

from app.providers.base import TrackInfo
from app.providers.deezer import DeezerError, _artist_key
from app.services import stats as stats_service

logger = logging.getLogger(__name__)

DEFAULT_QUESTIONS = 10
CHOICES = 4
POOL_DAYS = 180
MODES = ("daily", "solo", "chart", "artist", "radio", "playlist")
GUESSES = ("title", "artist")


def _key(track: TrackInfo) -> tuple[str, str]:
    return (track.title.casefold().strip(), _artist_key(track.artist))


def _main_artist(track: TrackInfo) -> str:
    return track.artist.split(",")[0].strip()


def _dedupe(tracks: list[TrackInfo]) -> list[TrackInfo]:
    seen: set[tuple[str, str]] = set()
    out = []
    for t in tracks:
        if _key(t) not in seen:
            seen.add(_key(t))
            out.append(t)
    return out


async def pool_from_plays(deps, user_ids: list[int]) -> list[TrackInfo]:
    """Titres Deezer écoutés (sans extrait : il sera demandé au tirage)."""
    since = stats_service.to_utc_iso(datetime.now(timezone.utc) - timedelta(days=POOL_DAYS))
    pool = []
    for user_id in user_ids:
        for play in await deps.repo.plays_between(user_id, since, None):
            if play.source == "deezer" and play.source_id:
                pool.append(TrackInfo(
                    "deezer", play.source_id, play.title, play.artist, play.album, None,
                    play.duration_seconds, play.cover_url,
                ))
    return _dedupe(pool)


async def pool_for_mode(deps, mode: str, user_ids: list[int], ref: str | None) -> list[TrackInfo]:
    try:
        if mode in ("daily", "solo"):
            pool = await pool_from_plays(deps, user_ids)
            if len(pool) < 14:
                pool = _dedupe(pool + await deps.deezer.get_chart_tracks(limit=100))
            return pool
        if mode == "chart":
            return _dedupe(await deps.deezer.get_chart_tracks(limit=100))
        if mode == "artist" and ref:
            tracks = list(await deps.deezer.get_artist_top_tracks(ref, limit=50))
            for related in (await deps.deezer.get_related_artists(ref, limit=8))[:8]:
                tracks += (await deps.deezer.get_artist_top_tracks(related.source_id, limit=8))
            return _dedupe(tracks)
        if mode == "radio" and ref:
            first = await deps.deezer.get_radio_tracks(ref, limit=50)
            second = await deps.deezer.get_radio_tracks(ref, limit=50)  # nouveau tirage : plus de choix
            return _dedupe(list(first) + list(second))
        if mode == "playlist" and ref and ref.isdigit():
            entries = await deps.repo.playlist_tracks(int(ref))
            return _dedupe([e.track for e in entries if e.track.source == "deezer"])
    except DeezerError as exc:
        logger.info("Blind test (%s) : Deezer indisponible (%s)", mode, exc)
    return []


async def _with_preview(deps, track: TrackInfo) -> TrackInfo | None:
    if track.preview_url:
        return track
    try:
        full = await deps.deezer.get_track(track.source_id)
    except DeezerError:
        return None
    return full if full.preview_url else None


async def build_round(
    deps, pool: list[TrackInfo], seed, count: int = DEFAULT_QUESTIONS, guess: str = "title"
) -> list[dict]:
    rng = random.Random(seed)
    # Ordre stable avant le tirage : le défi du jour doit être le même pour tous.
    pool = sorted(pool, key=lambda t: (_artist_key(t.artist), t.title.casefold()))
    rng.shuffle(pool)
    artists = {_artist_key(_main_artist(t)) for t in pool}
    # Assez d'artistes différents : un artiste par question, leurres d'autres
    # artistes. Sinon (mode « un artiste »), ses propres titres servent de leurres.
    varied = len(artists) >= CHOICES + 2

    questions: list[dict] = []
    used_answers: set[str] = set()
    for candidate in pool:
        if len(questions) >= count:
            break
        main = _artist_key(_main_artist(candidate))
        if guess == "artist" or varied:
            if main in used_answers:
                continue
        track = await _with_preview(deps, candidate)
        if track is None:
            continue

        if guess == "artist":
            names: dict[str, str] = {}
            for other in pool:
                name = _main_artist(other)
                if _artist_key(name) != main:
                    names.setdefault(_artist_key(name), name)
            decoy_names = list(names.values())
            rng.shuffle(decoy_names)
            if len(decoy_names) < CHOICES - 1:
                continue
            choices = [{"title": "", "artist": _main_artist(candidate)}] + [
                {"title": "", "artist": n} for n in decoy_names[: CHOICES - 1]
            ]
        else:
            others = [o for o in pool if o.title.casefold() != candidate.title.casefold()]
            rng.shuffle(others)
            decoys: list[TrackInfo] = []
            for other in others:
                if len(decoys) == CHOICES - 1:
                    break
                if varied and _artist_key(_main_artist(other)) == main:
                    continue
                if any(d.title.casefold() == other.title.casefold() for d in decoys):
                    continue
                decoys.append(other)
            if len(decoys) < CHOICES - 1:
                continue
            choices = [{"title": candidate.title, "artist": candidate.artist}] + [
                {"title": d.title, "artist": d.artist} for d in decoys
            ]

        answer_choice = choices[0]
        rng.shuffle(choices)
        used_answers.add(main)
        questions.append({
            "preview_url": track.preview_url,
            "cover_url": track.cover_url,
            "answer": choices.index(answer_choice),
            "choices": choices,
            "track": {
                "source": track.source, "source_id": track.source_id, "title": track.title,
                "artist": track.artist, "album": track.album, "year": track.year,
                "duration_seconds": track.duration_seconds, "cover_url": track.cover_url,
                "artist_source_id": track.artist_source_id, "album_source_id": track.album_source_id,
            },
        })
    return questions
