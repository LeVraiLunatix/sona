"""Musique locale (lossless) : état, analyse du dossier, liste, pochettes.
Le fichier lui-même est servi par `/stream/local/{id}` (voir stream.py)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from app.api.auth import get_deps, require_token
from app.api.schemas import Track
from app.api.state import ApiDeps
from app.services import local_library

router = APIRouter(tags=["local"])


def _root(deps: ApiDeps):
    root = deps.settings.local_music_dir
    if root is None or not root.is_dir():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "Musique locale non configurée : renseigne LOCAL_MUSIC_DIR (dossier existant sur le serveur).",
        )
    return root


def _track(request: Request, row: dict) -> dict:
    track = Track(
        source="local", source_id=row["id"], title=row["title"], artist=row["artist"], album=row["album"],
        year=row["year"], duration_seconds=row["duration_seconds"],
        cover_url=str(request.url_for("local_cover", track_id=row["id"])),
        disc_number=row["disc_number"], track_number=row["track_number"],
    ).model_dump()
    track["quality"] = local_library.quality_label(row)
    track["lossless"] = bool(row["lossless"])
    return track


@router.get("/local/status")
async def local_status(deps: ApiDeps = Depends(require_token)) -> dict:
    root = deps.settings.local_music_dir
    if root is None:
        return {"enabled": False, "tracks": 0}
    rows, total = await deps.repo.local_list(limit=1)
    return {"enabled": True, "available": root.is_dir(), "tracks": total}


@router.post("/local/scan")
async def local_scan(deps: ApiDeps = Depends(require_token)) -> dict:
    """Relit le dossier : nouveaux fichiers ajoutés, modifiés relus, disparus oubliés."""
    return await local_library.scan(deps.repo, _root(deps))


@router.get("/local/tracks")
async def local_tracks(
    request: Request,
    q: str = Query("", description="Artiste, titre ou album"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    deps: ApiDeps = Depends(require_token),
) -> dict:
    _root(deps)
    rows, total = await deps.repo.local_list(q, offset, limit)
    return {"total": total, "tracks": [_track(request, r) for r in rows]}


@router.get("/local/tracks/{track_id}")
async def local_track(request: Request, track_id: str, deps: ApiDeps = Depends(require_token)) -> dict:
    row = await deps.repo.local_get(track_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Titre inconnu.")
    return _track(request, row)


@router.get("/local/cover/{track_id}", name="local_cover")
async def local_cover(track_id: str, deps: ApiDeps = Depends(get_deps)) -> Response:
    """Pochette d'un titre. Sans jeton : une image <img> ne peut pas en envoyer,
    et l'identifiant (empreinte du chemin) ne se devine pas."""
    row = await deps.repo.local_get(track_id)
    root = deps.settings.local_music_dir
    path = local_library.resolve_path(root, row) if row and root else None
    found = local_library.cover(path) if path else None
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pas de pochette.")
    data, mime = found
    return Response(data, media_type=mime, headers={"Cache-Control": "public, max-age=86400"})
