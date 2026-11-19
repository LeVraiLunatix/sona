"""Albums et titres pas encore sortis.

Une sortie est effective à minuit (heure de Paris) le jour de sa date : avant,
l'album est « à venir » — l'app affiche un compte à rebours et grise ses
titres. Un album annoncé n'a souvent ni pochette ni liste de titres chez Deezer :
Apple Music, qui les montre dès l'annonce, sert de secours."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time, timezone

from app.providers.base import AlbumInfo, TrackInfo
from app.services import apple_motion
from app.services.stats import resolve_tz

logger = logging.getLogger(__name__)

# Albums complétés en parallèle pour une page d'artiste.
ENRICH_CONCURRENCY = 4
# Pochettes cherchées à la fois sur une page d'artiste, hors albums annoncés.
MAX_COVER_LOOKUPS = 8


def release_moment(value: str | None) -> datetime | None:
    """Instant de sortie d'une date `AAAA-MM-JJ` (ou ISO avec heure), ou `None`
    quand la date manque ou n'a pas de sens (« 0000-00-00 »)."""
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        day = date.fromisoformat(value[:10])
    except ValueError:
        return None
    if day.year < 1900:
        return None
    return datetime.combine(day, time.min, tzinfo=resolve_tz("Europe/Paris"))


def is_upcoming(value: str | None, now: datetime | None = None) -> bool:
    moment = release_moment(value)
    return moment is not None and moment > (now or datetime.now(timezone.utc))


def track_released(track: TrackInfo, album_date: str | None, now: datetime | None = None) -> bool:
    """Un titre est sorti quand sa date (à défaut celle de l'album) est passée ;
    sans aucune date connue, on le suppose sorti."""
    moment = release_moment(track.release_date or album_date)
    return moment is None or moment <= (now or datetime.now(timezone.utc))


async def enrich_album(album: AlbumInfo) -> None:
    """Pochette et, pour un album annoncé, liste des titres manquantes, lues sur
    Apple Music. Au mieux : sans réponse, l'album reste tel quel."""
    need_cover = not album.cover_url
    need_tracks = not album.tracks and is_upcoming(album.release_date)
    if not need_cover and not need_tracks:
        return
    found = await apple_motion.album_preview(album.title, album.artist, with_tracks=need_tracks)
    if not found:
        return
    if need_cover and found.get("cover_url"):
        album.cover_url = found["cover_url"]
        for track in album.tracks:
            track.cover_url = track.cover_url or album.cover_url
    if not album.release_date and found.get("release_date"):
        album.release_date = found["release_date"]
        album.year = album.year or album.release_date[:4]
    if need_tracks and found.get("tracks"):
        album.tracks = [
            TrackInfo(
                source="apple", source_id=t["id"], title=t["title"], artist=t["artist"], album=album.title,
                year=album.year, duration_seconds=t["duration"], cover_url=album.cover_url,
                artist_source_id=album.artist_source_id, isrc=t.get("isrc"),
                disc_number=t.get("disc"), track_number=t.get("track"),
                release_date=t.get("release_date") or album.release_date,
            )
            for t in found["tracks"]
        ]
        album.track_count = album.track_count or len(album.tracks)


async def enrich_albums(albums: list[AlbumInfo]) -> None:
    gate = asyncio.Semaphore(ENRICH_CONCURRENCY)

    async def one(album: AlbumInfo) -> None:
        async with gate:
            try:
                await enrich_album(album)
            except Exception as exc:  # noqa: BLE001 - cosmétique : jamais bloquant
                logger.info("Album %s : complément Apple Music impossible (%s)", album.title, exc)

    await asyncio.gather(*(one(a) for a in albums))


def split_upcoming(albums: list[AlbumInfo], now: datetime | None = None) -> tuple[list[AlbumInfo], list[AlbumInfo]]:
    """(à venir, du plus proche au plus lointain ; déjà sortis)."""
    ahead = [a for a in albums if is_upcoming(a.release_date, now)]
    ahead.sort(key=lambda a: (release_moment(a.release_date), a.title))
    ids = {id(a) for a in ahead}
    return ahead, [a for a in albums if id(a) not in ids]
