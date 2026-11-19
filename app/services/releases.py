"""Nouvelles sorties des artistes que tu écoutes : albums, EP et singles
parus ces derniers jours chez tes artistes les plus écoutés (90 jours)."""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from datetime import date, datetime, timedelta, timezone

from app.providers.base import AlbumInfo
from app.providers.deezer import DeezerError
from app.services import artist_photos, upcoming
from app.services import stats as stats_service

logger = logging.getLogger(__name__)

WINDOW_DAYS = 21
ARTISTS = 15
LISTEN_DAYS = 90


async def favourite_artists(deps, user_id: int, count: int = ARTISTS) -> list[tuple[str, str]]:
    """(nom, identifiant Deezer vérifié) des artistes les plus écoutés."""
    since = stats_service.to_utc_iso(datetime.now(timezone.utc) - timedelta(days=LISTEN_DAYS))
    plays = await deps.repo.plays_between(user_id, since, None)
    ranked = stats_service.top_artists(plays, limit=count)
    await artist_photos.fix(deps, ranked, limit=count)
    return [(a.name, a.source_id) for a in ranked if a.source == "deezer" and a.source_id]


async def recent_releases(deps, user_id: int, today: date | None = None) -> list[dict]:
    today = today or date.today()
    oldest = today - timedelta(days=WINDOW_DAYS)
    artists = await favourite_artists(deps, user_id)
    semaphore = asyncio.Semaphore(4)

    async def of(name: str, artist_id: str) -> list[dict]:
        async with semaphore:
            try:
                albums, singles = await deps.deezer.get_artist_albums(artist_id, name)
            except DeezerError as exc:
                logger.info("Sorties de %s indisponibles : %s", name, exc)
                return []
        out = []
        for album in albums + singles:
            try:
                released = date.fromisoformat(album.release_date or "")
            except ValueError:
                continue
            if oldest <= released <= today:
                out.append({
                    "source": album.source, "source_id": album.source_id, "title": album.title,
                    "artist": album.artist or name, "artist_source_id": album.artist_source_id or artist_id,
                    "cover_url": album.cover_url, "release_date": album.release_date,
                    "kind": {"album": "Album", "ep": "EP", "single": "Single"}.get((album.record_type or "").lower(), "Sortie"),
                    "track_count": album.track_count,
                })
        return out

    found = [r for group in await asyncio.gather(*(of(n, i) for n, i in artists)) for r in group]
    unique = {r["source_id"]: r for r in found}
    return sorted(unique.values(), key=lambda r: r["release_date"], reverse=True)


UPCOMING_LIMIT = 12


async def upcoming_releases(deps, user_id: int, limit: int = UPCOMING_LIMIT) -> list[AlbumInfo]:
    """Sorties annoncées (pas encore parues) chez tes artistes les plus écoutés,
    de la plus proche à la plus lointaine. Pochette manquante : Apple Music."""
    artists = await favourite_artists(deps, user_id)
    semaphore = asyncio.Semaphore(4)

    async def of(name: str, artist_id: str) -> list[AlbumInfo]:
        async with semaphore:
            try:
                albums, singles = await deps.deezer.get_artist_albums(artist_id, name)
            except DeezerError as exc:
                logger.info("Sorties annoncées de %s indisponibles : %s", name, exc)
                return []
        return [a for a in albums + singles if upcoming.is_upcoming(a.release_date)]

    found = [a for group in await asyncio.gather(*(of(n, i) for n, i in artists)) for a in group]
    unique = list({a.uid: a for a in found}.values())
    ahead, _ = upcoming.split_upcoming(unique)
    ahead = ahead[:limit]
    await upcoming.enrich_albums(ahead)
    return ahead
