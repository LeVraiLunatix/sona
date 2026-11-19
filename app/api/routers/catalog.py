from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse

from app.api.auth import require_token
from app.api.schemas import Album, Artist, Track
from app.api.routers.exclusives import track_for as exclusive_track
from app.api.state import ApiDeps
from app.bot import lookup
from app.providers.base import TrackInfo
from app.services import album_versions, apple_motion, artist_bio, credits, djradio, upcoming

router = APIRouter(tags=["catalog"])


async def _handle(coro):
    try:
        return await coro
    except lookup.UnknownSourceError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Source inconnue : {exc}") from exc
    except lookup.ProviderErrors as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@router.get("/tracks/{source}/{source_id}", response_model=Track)
async def get_track(request: Request, source: str, source_id: str, deps: ApiDeps = Depends(require_token)) -> Track:
    if source == "exclusive":
        row = await deps.repo.exclusive_get(source_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Exclu inconnu.")
        return exclusive_track(request, row)
    track = await _handle(lookup.get_track(deps, source, source_id))
    await deps.repo.history_add(deps.user_id, track)
    # Titre de la bibliothèque ajouté avant qu'on garde les fiches : complété
    # une fois pour toutes, la bibliothèque n'aura plus à le redemander.
    await deps.repo.library_fill_track(deps.user_id, track)
    return Track.from_info(track)


@router.get("/tracks/{source}/{source_id}/credits")
async def get_track_credits(
    source: str,
    source_id: str,
    details: bool = Query(True, description="Label, genres, compositeurs, producteurs… (plus lent)"),
    deps: ApiDeps = Depends(require_token),
) -> dict:
    """Crédits d'un titre (artistes, label, compositeurs…). Contrairement à
    `/tracks/...`, ne touche pas à l'historique : l'app l'appelle à chaque
    changement de titre."""
    if source == "exclusive":
        row = await deps.repo.exclusive_get(source_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Exclu inconnu.")
        return {
            "artists": [{"name": row["artist"], "source_id": row["artist_source_id"], "role": "main"}],
            "credits": [], "album": None, "label": None, "release_date": row["year"], "genres": [],
            "isrc": None, "disc_number": None, "track_number": None, "duration_seconds": row["duration_seconds"],
        }
    return await _handle(credits.build(deps, source, source_id, details))


@router.get("/albums/{source}/{source_id}", response_model=Album)
async def get_album(source: str, source_id: str, deps: ApiDeps = Depends(require_token)) -> Album:
    album = await _handle(lookup.get_album(deps, source, source_id))
    # Pochette (et titres, pour un album annoncé) qui manquent : Apple Music.
    await upcoming.enrich_albums([album])
    await deps.repo.history_add(deps.user_id, album)
    return Album.from_info(album)


@router.get("/albums/{source}/{source_id}/motion")
async def get_album_motion(source: str, source_id: str, deps: ApiDeps = Depends(require_token)) -> dict:
    """Pochette animée d'Apple Music (flux HLS muet) ; 404 s'il n'y en a pas."""
    album = await _handle(lookup.get_album(deps, source, source_id))
    motion = await apple_motion.album_motion(album.title, album.artist)
    if motion is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pas de pochette animée pour cet album.")
    return motion


@router.get("/albums/{source}/{source_id}/motion/{kind}.mp4")
async def get_album_motion_file(
    source: str, source_id: str, kind: Literal["tall", "square"], deps: ApiDeps = Depends(require_token)
) -> FileResponse:
    """La pochette animée en MP4 (3:4 ou 1:1), pour l'écran verrouillé d'iOS 26."""
    album = await _handle(lookup.get_album(deps, source, source_id))
    motion = await apple_motion.album_motion(album.title, album.artist)
    video = (motion or {}).get(kind)
    if not video:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pas de pochette animée pour cet album.")
    path = await apple_motion.mp4_for(video, deps.settings.downloads_dir.parent / "motion", deps.settings.ffmpeg_path)
    if path is None:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Conversion de la pochette animée impossible.")
    return FileResponse(path, media_type="video/mp4")


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


@router.get("/artists/{source}/{source_id}/bio")
async def get_artist_bio(source: str, source_id: str, deps: ApiDeps = Depends(require_token)) -> dict:
    """Biographie (Wikipédia) ; 404 quand aucune page de musicien n'est trouvée."""
    artist = await _handle(lookup.get_artist(deps, source, source_id))
    bio = await artist_bio.get_bio(artist.name)
    if bio is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pas de biographie pour cet artiste.")
    return bio


@router.get("/artists/{source}/{source_id}/motion")
async def get_artist_motion(source: str, source_id: str, deps: ApiDeps = Depends(require_token)) -> dict:
    """Portrait animé d'Apple Music (flux HLS muet) ; 404 s'il n'y en a pas."""
    artist = await _handle(lookup.get_artist(deps, source, source_id))
    motion = await apple_motion.artist_motion(artist.name)
    if motion is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ni vidéo ni logo pour cet artiste.")
    return motion


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
    """Albums et singles, du plus récent au plus ancien, une seule édition de
    chaque ; les éditions écartées (deluxe, remasterisé…) vont dans
    `other_versions`. Les sorties annoncées (pas encore parues) sont à part,
    dans `upcoming`, de la plus proche à la plus lointaine."""
    albums, singles = await _handle(lookup.get_artist_albums(deps, source, source_id))
    ahead, released = upcoming.split_upcoming(albums + singles)
    keep = {id(a) for a in released}
    albums = [a for a in albums if id(a) in keep]
    singles = [a for a in singles if id(a) in keep]
    # Pochettes manquantes (annoncé, ou jamais fournie) : Apple Music en secours.
    bare = [a for a in albums + singles if not a.cover_url]
    await upcoming.enrich_albums(ahead + bare[:upcoming.MAX_COVER_LOOKUPS])
    main_albums, other_albums = album_versions.split_versions(albums)
    main_singles, other_singles = album_versions.split_versions(singles)
    return {
        "upcoming": [Album.from_info(a) for a in ahead],
        "albums": [Album.from_info(a) for a in main_albums],
        "singles": [Album.from_info(a) for a in main_singles],
        "other_versions": [Album.from_info(a) for a in album_versions.newest_first(other_albums + other_singles)],
    }


@router.get("/albums/{source}/{source_id}/versions", response_model=list[Album])
async def get_album_versions(source: str, source_id: str, deps: ApiDeps = Depends(require_token)) -> list[Album]:
    """Autres éditions d'un album (« Autres versions » en bas de sa page)."""
    album = await _handle(lookup.get_album(deps, source, source_id))
    if not album.artist_source_id:
        return []
    albums, singles = await _handle(lookup.get_artist_albums(deps, source, album.artist_source_id))
    return [Album.from_info(a) for a in album_versions.siblings(album, albums + singles)]


@router.get("/djradio/{source}/{source_id}", response_model=list[Track])
async def dj_radio(
    source: str,
    source_id: str,
    title: str = Query(..., min_length=1),
    artist: str = Query(..., min_length=1),
    exclude: str = Query("", description="Identifiants déjà joués, séparés par des virgules"),
    deps: ApiDeps = Depends(require_token),
) -> list[Track]:
    """Radio DJ (voir services/djradio.py) : la suite de la station à partir
    du dernier titre en file."""
    seed = TrackInfo(source, source_id, title, artist, None, None, None, None)
    excluded = {x for x in exclude.split(",") if x}
    tracks = await djradio.build(deps, seed, excluded)
    return [Track.from_info(t) for t in tracks]

