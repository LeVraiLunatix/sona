from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.auth import require_token
from app.api.schemas import Album, Artist, Track
from app.api.state import ApiDeps
from app.bot import lookup

router = APIRouter(tags=["catalog"])


async def _handle(coro):
    try:
        return await coro
    except lookup.UnknownSourceError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Source inconnue : {exc}") from exc
    except lookup.ProviderErrors as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@router.get("/tracks/{source}/{source_id}", response_model=Track)
async def get_track(source: str, source_id: str, deps: ApiDeps = Depends(require_token)) -> Track:
    track = await _handle(lookup.get_track(deps, source, source_id))
    await deps.repo.history_add(deps.user_id, track)
    # Titre de la bibliothèque ajouté avant qu'on garde les fiches : complété
    # une fois pour toutes, la bibliothèque n'aura plus à le redemander.
    await deps.repo.library_fill_track(deps.user_id, track)
    return Track.from_info(track)


@router.get("/albums/{source}/{source_id}", response_model=Album)
async def get_album(source: str, source_id: str, deps: ApiDeps = Depends(require_token)) -> Album:
    album = await _handle(lookup.get_album(deps, source, source_id))
    await deps.repo.history_add(deps.user_id, album)
    return Album.from_info(album)


@router.get("/playlists/{source}/{source_id}", response_model=Album)
async def get_playlist(source: str, source_id: str, deps: ApiDeps = Depends(require_token)) -> Album:
    playlist = await _handle(lookup.get_playlist(deps, source, source_id))
    return Album.from_info(playlist)


@router.get("/artists/{source}/{source_id}", response_model=Artist)
async def get_artist(source: str, source_id: str, deps: ApiDeps = Depends(require_token)) -> Artist:
    artist = await _handle(lookup.get_artist(deps, source, source_id))
    return Artist.from_info(artist)


@router.get("/artists/{source}/{source_id}/top-tracks", response_model=list[Track])
async def get_artist_top_tracks(
    source: str, source_id: str, deps: ApiDeps = Depends(require_token)
) -> list[Track]:
    tracks = await _handle(lookup.get_artist_top_tracks(deps, source, source_id))
    return [Track.from_info(t) for t in tracks]


@router.get("/artists/{source}/{source_id}/related", response_model=list[Artist])
async def get_related_artists(
    source: str, source_id: str, deps: ApiDeps = Depends(require_token)
) -> list[Artist]:
    artists = await _handle(lookup.get_related_artists(deps, source, source_id))
    return [Artist.from_info(a) for a in artists]


@router.get("/artists/{source}/{source_id}/radio", response_model=list[Track])
async def get_artist_radio(
    source: str, source_id: str, deps: ApiDeps = Depends(require_token)
) -> list[Track]:
    tracks = await _handle(lookup.get_artist_radio(deps, source, source_id))
    return [Track.from_info(t) for t in tracks]


@router.get("/artists/{source}/{source_id}/albums")
async def get_artist_albums(
    source: str, source_id: str, deps: ApiDeps = Depends(require_token)
) -> dict[str, list[Album]]:
    albums, singles = await _handle(lookup.get_artist_albums(deps, source, source_id))
    return {
        "albums": [Album.from_info(a) for a in albums],
        "singles": [Album.from_info(a) for a in singles],
    }
