"""Mixes personnalisés de l'accueil, tirés des écoutes du compte :

- « Mix du jour » : les radios Deezer de tes artistes du moment, mêlées ;
- « Découvertes » : des artistes proches de tes favoris que tu n'as jamais
  écoutés ;
- « En boucle » : tes titres les plus écoutés ces 30 derniers jours.

Recalculés une fois par jour et par compte (le « du jour » ne change pas à
chaque ouverture de l'app), ou à la demande.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from app.db.repository import Play
from app.providers.base import TrackInfo
from app.providers.deezer import DeezerError, _artist_key
from app.services import stats as stats_service

logger = logging.getLogger(__name__)

WINDOW_DAYS = 30
MIX_SIZE = 50
SEED_ARTISTS = 4
DISCOVERY_ARTISTS = 12
DISCOVERY_TRACKS_PER_ARTIST = 2


@dataclass(slots=True)
class Mix:
    id: str
    title: str
    subtitle: str
    tracks: list[TrackInfo] = field(default_factory=list)

    @property
    def covers(self) -> list[str]:
        seen: list[str] = []
        for t in self.tracks:
            if t.cover_url and t.cover_url not in seen:
                seen.append(t.cover_url)
            if len(seen) == 4:
                break
        return seen


_cache: dict[tuple[int, date], list[Mix]] = {}
_locks: dict[int, asyncio.Lock] = {}


def _track_key(t: TrackInfo) -> tuple[str, str]:
    return (t.title.casefold(), _artist_key(t.artist))


def dedupe(tracks: list[TrackInfo], limit: int = MIX_SIZE) -> list[TrackInfo]:
    seen_ids: set[str] = set()
    seen_keys: set[tuple[str, str]] = set()
    kept = []
    for t in tracks:
        if t.uid in seen_ids or _track_key(t) in seen_keys:
            continue
        seen_ids.add(t.uid)
        seen_keys.add(_track_key(t))
        kept.append(t)
        if len(kept) >= limit:
            break
    return kept


def interleave(groups: list[list[TrackInfo]]) -> list[TrackInfo]:
    """A1 B1 C1 A2 B2 C2… : aucun artiste ne monopolise le début du mix."""
    out = []
    for i in range(max((len(g) for g in groups), default=0)):
        out += [g[i] for g in groups if i < len(g)]
    return out


def on_repeat(plays: list[Play], limit: int = MIX_SIZE) -> list[TrackInfo]:
    """Titres les plus écoutés (ceux qu'on sait relire : source connue)."""
    counts: Counter = Counter()
    latest: dict[tuple[str, str], Play] = {}
    for p in plays:
        if not p.source or not p.source_id:
            continue
        key = (p.source, p.source_id)
        counts[key] += 1
        latest[key] = p
    ranked = [k for k, n in counts.most_common() if n >= 2][:limit]
    return [
        TrackInfo(
            source=p.source, source_id=p.source_id, title=p.title, artist=p.artist, album=p.album, year=None,
            duration_seconds=p.duration_seconds, cover_url=p.cover_url,
            artist_source_id=p.artist_source_id, album_source_id=p.album_source_id,
        )
        for p in (latest[k] for k in ranked)
    ]


async def _deezer_artist_id(deezer, name: str, source: str | None, source_id: str | None) -> str | None:
    if source == "deezer" and source_id:
        return source_id
    try:
        found = await deezer.search_artists(name, limit=3)
    except DeezerError:
        return None
    wanted = _artist_key(name)
    match = next((a for a in found if _artist_key(a.name) == wanted), None)
    return match.source_id if match else None


async def build_mixes(deps, user_id: int, today: date | None = None) -> list[Mix]:
    now = datetime.now(timezone.utc)
    plays = await deps.repo.plays_between(user_id, stats_service.to_utc_iso(now - timedelta(days=WINDOW_DAYS)), None)
    if len(plays) < 5:
        # Peu d'écoutes récentes : on part de tout l'historique.
        plays = await deps.repo.plays_between(user_id, None, None)
    if not plays:
        return []

    rng = random.Random(f"{user_id}-{today or date.today()}")
    top = stats_service.top_artists(plays, limit=SEED_ARTISTS * 2)
    seeds: list[tuple[str, str]] = []
    for artist in top:
        artist_id = await _deezer_artist_id(deps.deezer, artist.name, artist.source, artist.source_id)
        if artist_id:
            seeds.append((artist.name, artist_id))
        if len(seeds) >= SEED_ARTISTS:
            break

    mixes: list[Mix] = []

    # Mix du jour
    radios = []
    for _, artist_id in seeds:
        try:
            radios.append(await deps.deezer.get_artist_radio(artist_id, limit=25))
        except DeezerError as exc:
            logger.info("Radio Deezer de l'artiste %s indisponible : %s", artist_id, exc)
    daily = dedupe(interleave(radios))
    if daily:
        names = [name for name, _ in seeds[:3]]
        mixes.append(Mix("daily", "Mix du jour", ", ".join(names) + (" et plus" if len(seeds) > 3 else ""), daily))

    # Découvertes : artistes proches, jamais écoutés
    known = set((await deps.repo.plays_first_by_artist(user_id)).keys())
    new_artists = []
    for _, artist_id in seeds:
        try:
            related = await deps.deezer.get_related_artists(artist_id, limit=15)
        except DeezerError:
            continue
        for artist in related:
            if artist.name.casefold() in known or any(a.source_id == artist.source_id for a in new_artists):
                continue
            new_artists.append(artist)
    rng.shuffle(new_artists)
    groups = []
    for artist in new_artists[:DISCOVERY_ARTISTS]:
        try:
            top_tracks = await deps.deezer.get_artist_top_tracks(artist.source_id, limit=5)
        except DeezerError:
            continue
        groups.append(top_tracks[:DISCOVERY_TRACKS_PER_ARTIST])
    discoveries = dedupe(interleave(groups))
    if discoveries:
        mixes.append(Mix("discoveries", "Découvertes", "Des artistes proches de tes favoris, jamais écoutés", discoveries))

    # En boucle
    repeat = on_repeat(plays)
    if len(repeat) >= 5:
        mixes.append(Mix("repeat", "En boucle", "Tes titres les plus écoutés ces derniers temps", repeat))
    return mixes


async def get_mixes(deps, user_id: int, refresh: bool = False) -> list[Mix]:
    today = date.today()
    key = (user_id, today)
    lock = _locks.setdefault(user_id, asyncio.Lock())
    async with lock:
        if refresh or key not in _cache:
            # Un seul jour gardé par compte.
            for old in [k for k in _cache if k[0] == user_id]:
                del _cache[old]
            _cache[key] = await build_mixes(deps, user_id, today)
        return _cache[key]
