"""Crédits d'un titre : artistes (principal, en featuring), label, date de
sortie, genres, puis compositeurs / producteurs / ingénieurs quand
MusicBrainz les connaît (retrouvés par le code ISRC).

Chaque source est facultative : un titre YouTube n'aura que son artiste,
un titre Deezer aura presque tout."""

from __future__ import annotations

import asyncio
import logging

from app.api.state import ApiDeps
from app.bot import lookup
from app.providers.deezer import DeezerError
from app.providers.musicbrainz import MusicBrainzError

logger = logging.getLogger(__name__)


async def _album_meta(deps: ApiDeps, source: str, album_id: str | None) -> dict:
    if source != "deezer" or not album_id:
        return {}
    try:
        return await deps.deezer.get_album_meta(album_id)
    except DeezerError as exc:
        logger.debug("Méta d'album Deezer indisponible : %s", exc)
        return {}


async def _musicbrainz(deps: ApiDeps, isrc: str | None) -> list[dict]:
    if deps.musicbrainz is None or not isrc:
        return []
    try:
        return await deps.musicbrainz.credits_by_isrc(isrc)
    except MusicBrainzError as exc:
        logger.debug("MusicBrainz indisponible : %s", exc)
        return []


async def build(deps: ApiDeps, source: str, source_id: str, details: bool = True) -> dict:
    """`details=False` : artistes seulement (rapide, appelé à chaque titre
    joué) ; sinon label, genres, et crédits MusicBrainz — plus lents, MusicBrainz
    n'acceptant qu'une requête par seconde."""
    track = await lookup.get_track(deps, source, source_id)
    meta: dict = {}
    written: list[dict] = []
    if details:
        meta, written = await asyncio.gather(
            _album_meta(deps, source, track.album_source_id),
            _musicbrainz(deps, track.isrc),
        )
    artists = track.artists or [{"name": track.artist, "source_id": track.artist_source_id, "role": "main"}]
    return {
        "artists": artists,
        "credits": written,
        "album": track.album,
        "label": meta.get("label"),
        "release_date": meta.get("release_date") or track.year,
        "genres": meta.get("genres") or [],
        "isrc": track.isrc,
        "disc_number": track.disc_number,
        "track_number": track.track_number,
        "duration_seconds": track.duration_seconds,
    }
