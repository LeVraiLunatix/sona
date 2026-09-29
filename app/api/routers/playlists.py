"""Playlists de l'utilisateur : création, ajout / retrait / réordonnancement
de morceaux, et import depuis Deezer, Spotify ou Apple Music.

Préfixe `/me/playlists` : `/playlists/{source}/{id}` (catalogue) désigne
déjà les playlists publiques des plateformes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.auth import require_token
from app.api.schemas import (
    PlaylistAddTracks,
    PlaylistCreate,
    PlaylistDetailOut,
    PlaylistEntryOut,
    PlaylistImportRequest,
    PlaylistOut,
    PlaylistReorder,
    PlaylistUpdate,
    Track,
)
from app.api.state import ApiDeps
from app.db.repository import PLAYLIST_VISIBILITIES, Playlist
from app.services import playlist_import

router = APIRouter(prefix="/me/playlists", tags=["playlists"])

KNOWN_SOURCES = {"deezer", "apple", "spotify", "youtube"}


async def _owned(deps: ApiDeps, playlist_id: int) -> Playlist:
    """Playlist du compte appelant (renommer, supprimer, partager...)."""
    playlist = await deps.repo.playlist_get(deps.user_id, playlist_id)
    if playlist is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Playlist introuvable.")
    return playlist


async def _accessible(deps: ApiDeps, playlist_id: int, *, edit: bool = False) -> Playlist:
    """Playlist lisible (à soi, ou partagée par un ami), ou modifiable (à
    soi, ou « à plusieurs ») quand `edit`."""
    playlist = await deps.repo.playlist_by_id(playlist_id)
    if playlist is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Playlist introuvable.")
    if playlist.user_id == deps.user_id:
        return playlist
    allowed = ("collaborative",) if edit else ("friends", "collaborative")
    if playlist.visibility not in allowed:
        # Même réponse qu'une playlist inexistante : rien ne fuit.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Playlist introuvable.")
    return playlist


async def _owner_name(deps: ApiDeps, playlist: Playlist) -> str | None:
    if playlist.user_id == deps.user_id:
        return None
    owner = await deps.repo.account_by_user_id(playlist.user_id)
    return (owner.display_name or owner.lastfm_username) if owner else None


async def _out(deps: ApiDeps, playlist: Playlist) -> PlaylistOut:
    return PlaylistOut.from_playlist(playlist, deps.user_id, await _owner_name(deps, playlist))


def _check_tracks(tracks: list[Track]) -> None:
    unknown = {t.source for t in tracks} - KNOWN_SOURCES
    if unknown:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Source inconnue : {', '.join(sorted(unknown))}")


async def _detail(deps: ApiDeps, playlist_id: int) -> PlaylistDetailOut:
    playlist = await _accessible(deps, playlist_id)
    entries = await deps.repo.playlist_tracks(playlist_id)
    return PlaylistDetailOut(
        **(await _out(deps, playlist)).model_dump(),
        entries=[PlaylistEntryOut.from_entry(e) for e in entries],
    )


@router.get("", response_model=list[PlaylistOut])
async def list_playlists(deps: ApiDeps = Depends(require_token)) -> list[PlaylistOut]:
    playlists = await deps.repo.playlist_list(deps.user_id, include_collaborative=True)
    return [await _out(deps, p) for p in playlists]


@router.post("", response_model=PlaylistDetailOut, status_code=status.HTTP_201_CREATED)
async def create_playlist(payload: PlaylistCreate, deps: ApiDeps = Depends(require_token)) -> PlaylistDetailOut:
    _check_tracks(payload.tracks)
    playlist_id = await deps.repo.playlist_create(
        deps.user_id, payload.name.strip() or "Nouvelle playlist", payload.description
    )
    await deps.repo.playlist_add_tracks(playlist_id, [t.to_info() for t in payload.tracks])
    return await _detail(deps, playlist_id)


@router.post("/import", response_model=PlaylistOut, status_code=status.HTTP_202_ACCEPTED)
async def import_playlist(payload: PlaylistImportRequest, deps: ApiDeps = Depends(require_token)) -> PlaylistOut:
    """Lance l'import en tâche de fond ; l'app suit ensuite la playlist
    (`import_status`, `import_done` / `import_total`) jusqu'à « done »."""
    try:
        playlist_id = await playlist_import.start_import(deps, deps.user_id, payload.url)
    except playlist_import.PlaylistImportError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return await _out(deps, await _owned(deps, playlist_id))


@router.post("/{playlist_id}/reimport", response_model=PlaylistOut, status_code=status.HTTP_202_ACCEPTED)
async def reimport_playlist(playlist_id: int, deps: ApiDeps = Depends(require_token)) -> PlaylistOut:
    """Relit la playlist d'origine (Deezer, Spotify, Apple Music) et remplace
    ses titres — pour récupérer les ajouts, ou un import incomplet."""
    playlist = await _owned(deps, playlist_id)
    try:
        await playlist_import.start_reimport(deps, playlist)
    except playlist_import.PlaylistImportError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return await _out(deps, await _owned(deps, playlist_id))


@router.get("/{playlist_id}", response_model=PlaylistDetailOut)
async def get_playlist(playlist_id: int, deps: ApiDeps = Depends(require_token)) -> PlaylistDetailOut:
    return await _detail(deps, playlist_id)


@router.patch("/{playlist_id}", response_model=PlaylistOut)
async def update_playlist(
    playlist_id: int, payload: PlaylistUpdate, deps: ApiDeps = Depends(require_token)
) -> PlaylistOut:
    await _owned(deps, playlist_id)
    fields = payload.model_dump(exclude_unset=True)
    if "name" in fields:
        fields["name"] = (fields["name"] or "").strip() or "Nouvelle playlist"
    if "visibility" in fields and fields["visibility"] not in PLAYLIST_VISIBILITIES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Visibilité inconnue (attendu : {', '.join(PLAYLIST_VISIBILITIES)})"
        )
    fields = {k: v for k, v in fields.items() if v is not None or k == "description"}
    if fields:
        await deps.repo.playlist_update(playlist_id, **fields)
    return await _out(deps, await _owned(deps, playlist_id))


@router.delete("/{playlist_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_playlist(playlist_id: int, deps: ApiDeps = Depends(require_token)) -> None:
    await _owned(deps, playlist_id)
    await deps.repo.playlist_delete(deps.user_id, playlist_id)


@router.post("/{playlist_id}/tracks", response_model=PlaylistDetailOut)
async def add_tracks(
    playlist_id: int, payload: PlaylistAddTracks, deps: ApiDeps = Depends(require_token)
) -> PlaylistDetailOut:
    await _accessible(deps, playlist_id, edit=True)
    _check_tracks(payload.tracks)
    await deps.repo.playlist_add_tracks(playlist_id, [t.to_info() for t in payload.tracks])
    return await _detail(deps, playlist_id)


@router.delete("/{playlist_id}/tracks/{entry_id}", response_model=PlaylistDetailOut)
async def remove_track(playlist_id: int, entry_id: int, deps: ApiDeps = Depends(require_token)) -> PlaylistDetailOut:
    await _accessible(deps, playlist_id, edit=True)
    await deps.repo.playlist_remove_entry(playlist_id, entry_id)
    return await _detail(deps, playlist_id)


@router.put("/{playlist_id}/order", response_model=PlaylistDetailOut)
async def reorder_tracks(
    playlist_id: int, payload: PlaylistReorder, deps: ApiDeps = Depends(require_token)
) -> PlaylistDetailOut:
    await _accessible(deps, playlist_id, edit=True)
    await deps.repo.playlist_reorder(playlist_id, payload.entry_ids)
    return await _detail(deps, playlist_id)
