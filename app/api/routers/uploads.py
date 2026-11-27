"""« Mes fichiers » : envoyer ses propres audios, les retrouver dans sa bibliothèque et ses playlists.

Chacun ne voit et n'écoute QUE les siens (la lecture passe par `/stream/upload/{id}`). Le corps de la
requête est le fichier lui-même, écrit au fil de l'eau et coupé au-delà de la taille permise.
"""

from __future__ import annotations

import secrets
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.api import limits
from app.api.auth import require_token
from app.api.schemas import Track
from app.api.state import ApiDeps
from app.providers.base import TrackInfo
from app.services import uploads

router = APIRouter(tags=["mes fichiers"])

SOURCE = "upload"


def to_info(request: Request, row: dict) -> TrackInfo:
    return TrackInfo(
        source=SOURCE, source_id=row["id"], title=row["title"], artist=row["artist"], album=row["album"],
        year=None, duration_seconds=row["duration_seconds"],
        cover_url=f"{str(request.base_url).rstrip('/')}/web/icons/icon-512.png",
    )


def _quota(deps: ApiDeps) -> int:
    return deps.settings.upload_quota_mb * 1024 * 1024


@router.get("/uploads")
async def list_uploads(request: Request, deps: ApiDeps = Depends(require_token)) -> dict:
    rows = await deps.repo.upload_list(deps.user_id)
    return {
        "tracks": [Track.from_info(to_info(request, r)) for r in rows],
        "used_bytes": sum(r["size"] for r in rows),
        "quota_bytes": _quota(deps),
        "max_file_bytes": uploads.MAX_FILE_BYTES,
    }


@router.post("/uploads", response_model=Track, status_code=status.HTTP_201_CREATED)
async def add_upload(
    request: Request,
    filename: str = Query("", max_length=300),
    deps: ApiDeps = Depends(limits.heavy("upload", 100)),
) -> Track:
    too_big = HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Fichier trop lourd (100 Mo maximum).")
    full = HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Ton espace est plein : supprime des fichiers.")
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > uploads.MAX_FILE_BYTES:
        raise too_big
    count, used = await deps.repo.upload_usage(deps.user_id)
    if count >= uploads.MAX_FILES or used >= _quota(deps):
        raise full

    with tempfile.TemporaryDirectory(prefix="sona-envoi-") as work:
        received = Path(work) / "envoi"
        size = 0
        with received.open("wb") as handle:
            async for chunk in request.stream():
                size += len(chunk)
                if size > uploads.MAX_FILE_BYTES:
                    raise too_big
                handle.write(chunk)
        title, artist, album = uploads.describe(received, filename)
        try:
            cleaned = await uploads.clean(received, deps.settings.uploads_dir, deps.settings.ffmpeg_path)
        except uploads.UploadError as exc:
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc

    row = {
        "id": secrets.token_hex(12), "user_id": deps.user_id, "title": title, "artist": artist, "album": album,
        "duration_seconds": cleaned.duration, "mime": cleaned.mime, "size": cleaned.size, "path": cleaned.path.name,
    }
    # Quota revérifié au moment d'enregistrer : plusieurs envois peuvent arriver en même temps.
    if not await deps.repo.upload_add(row, uploads.MAX_FILES, _quota(deps)):
        cleaned.path.unlink(missing_ok=True)
        raise full
    info = to_info(request, row)
    await deps.repo.library_add(deps.user_id, "track", info)
    return Track.from_info(info)


@router.delete("/uploads/{upload_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_upload(upload_id: str, deps: ApiDeps = Depends(require_token)) -> None:
    row = await deps.repo.upload_delete(deps.user_id, upload_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fichier introuvable.")
    (deps.settings.uploads_dir / row["path"]).unlink(missing_ok=True)


async def own_file(deps: ApiDeps, upload_id: str) -> tuple[Path, str]:
    """Chemin et type du fichier, seulement pour la personne qui l'a envoyé."""
    row = await deps.repo.upload_get(deps.user_id, upload_id)
    path = deps.settings.uploads_dir / row["path"] if row else None
    if path is None or not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fichier introuvable.")
    return path, row["mime"]
