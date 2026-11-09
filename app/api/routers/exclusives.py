"""Exclus : titres inédits ajoutés à la main par l'admin, stockés sur Discord.

Lecture pour tout compte accepté ; ajout, modification et suppression
réservés aux administrateurs. Le fichier est servi par `/stream/exclusive/{id}`
(voir stream.py), la pochette par `/exclusives/cover/{id}`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel

from app.api.auth import get_deps, require_admin, require_token
from app.api.state import ApiDeps
from app.services import exclusives
from app.services.discord_storage import StorageError

router = APIRouter(tags=["exclusives"])


def _storage(deps: ApiDeps):
    storage = deps.exclusive_storage
    if storage is None or not storage.enabled:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Exclus non configurés : renseigne DISCORD_STORAGE_WEBHOOK (webhook du salon de stockage).",
        )
    return storage


def track_for(request: Request, row: dict, extras: list[dict] | None = None) -> dict:
    return exclusives.track_dict(row, str(request.url_for("exclusive_cover", exclusive_id=row["id"])), extras)


async def _tracks(request: Request, deps: ApiDeps, rows: list[dict]) -> list[dict]:
    extras = await deps.repo.exclusive_versions()
    return [track_for(request, r, extras.get(r["id"])) for r in rows]


async def _track(request: Request, deps: ApiDeps, exclusive_id: str) -> dict:
    row = await _row(deps, exclusive_id)
    return track_for(request, row, (await deps.repo.exclusive_versions(exclusive_id)).get(exclusive_id))


async def _row(deps: ApiDeps, exclusive_id: str) -> dict:
    row = await deps.repo.exclusive_get(exclusive_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Exclu inconnu.")
    return row


@router.get("/exclusives/status")
async def exclusives_status(deps: ApiDeps = Depends(require_token)) -> dict:
    enabled = bool(deps.exclusive_storage and deps.exclusive_storage.enabled)
    return {"enabled": enabled, "can_add": deps.is_admin and enabled}


@router.get("/exclusives")
async def list_exclusives(request: Request, deps: ApiDeps = Depends(require_token)) -> dict:
    return {"tracks": await _tracks(request, deps, await deps.repo.exclusive_list())}


@router.get("/artists/{source}/{source_id}/exclusives")
async def artist_exclusives(
    request: Request,
    source: str,
    source_id: str,
    name: str = Query("", description="Nom de l'artiste : rattache aussi les exclus saisis sans fiche"),
    deps: ApiDeps = Depends(require_token),
) -> dict:
    return {"tracks": await _tracks(request, deps, await deps.repo.exclusive_list(source, source_id, name))}


@router.get("/exclusives/cover/{exclusive_id}", name="exclusive_cover")
async def exclusive_cover(exclusive_id: str, deps: ApiDeps = Depends(get_deps)) -> Response:
    """Pochette. Sans jeton (une balise <img> n'en envoie pas) ; l'identifiant
    est aléatoire. Sans pochette, une vignette neutre."""
    row = await deps.repo.exclusive_get(exclusive_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Exclu inconnu.")
    cover = None
    if deps.exclusive_storage and deps.exclusive_storage.enabled:
        try:
            cover = await exclusives.read_cover(deps.exclusive_storage, row)
        except StorageError:
            cover = None
    if cover is not None:
        return Response(cover[0], media_type=cover[1], headers={"Cache-Control": "public, max-age=86400"})
    initial = (row["title"][:1] or "?").upper().replace("&", "").replace("<", "")
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 300"><rect width="300" height="300" fill="#16141c"/>'
        f'<text x="150" y="190" font-family="sans-serif" font-size="140" font-weight="700" text-anchor="middle" fill="#7c6cf0">{initial}</text></svg>'
    )
    return Response(svg, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=3600"})


@router.post("/exclusives", status_code=status.HTTP_201_CREATED)
async def add_exclusive(
    request: Request,
    title: str = Query(..., min_length=1, max_length=200),
    artist: str = Query(..., min_length=1, max_length=200),
    artist_source: str | None = Query(None, max_length=40),
    artist_source_id: str | None = Query(None, max_length=120),
    year: str | None = Query(None, max_length=4),
    kind: str = Query("exclu"),
    filename: str = Query("", max_length=300),
    deps: ApiDeps = Depends(require_admin),
) -> dict:
    """Ajoute un exclu : le corps de la requête EST le fichier audio (envoyé
    tel quel, jamais lu en entier en mémoire)."""
    storage = _storage(deps)
    suffix = exclusives.audio_suffix(filename, request.headers.get("content-type"))
    if not suffix:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Format audio non reconnu (MP3, FLAC, M4A, WAV…).")
    try:
        path, size = await exclusives.spool(request.stream(), suffix, exclusives.MAX_AUDIO_BYTES)
    except ValueError as exc:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, str(exc)) from exc
    try:
        if size == 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Fichier vide.")
        row = await exclusives.add(
            storage, deps.repo, path, size, filename, request.headers.get("content-type"),
            title=title.strip(), artist=artist.strip(), artist_source=artist_source, artist_source_id=artist_source_id,
            year=year, kind=kind,
        )
    except StorageError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Stockage Discord : {exc}") from exc
    finally:
        path.unlink(missing_ok=True)
    return track_for(request, row)


@router.get("/exclusives/{exclusive_id}/versions")
async def list_versions(exclusive_id: str, deps: ApiDeps = Depends(require_token)) -> dict:
    """Les fichiers d'un exclu et leur qualité (le menu « Qualité » du lecteur)."""
    row = await _row(deps, exclusive_id)
    found = exclusives.versions_of(row, (await deps.repo.exclusive_versions(exclusive_id)).get(exclusive_id))
    return {"versions": [
        {"id": v["version_id"], "label": v["label"], "lossless": bool(v.get("lossless")), "size": v["size"],
         "main": v["version_id"] == exclusives.MAIN} for v in found
    ]}


@router.post("/exclusives/{exclusive_id}/versions", status_code=status.HTTP_201_CREATED)
async def add_version(
    request: Request, exclusive_id: str, filename: str = Query("", max_length=300), deps: ApiDeps = Depends(require_admin)
) -> dict:
    """Ajoute une autre version du titre (ex. le FLAC d'un exclu en MP3) : le corps est le fichier."""
    storage = _storage(deps)
    await _row(deps, exclusive_id)
    suffix = exclusives.audio_suffix(filename, request.headers.get("content-type"))
    if not suffix:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Format audio non reconnu (MP3, FLAC, M4A, WAV…).")
    try:
        path, size = await exclusives.spool(request.stream(), suffix, exclusives.MAX_AUDIO_BYTES)
    except ValueError as exc:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, str(exc)) from exc
    try:
        if size == 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Fichier vide.")
        await exclusives.add_version(storage, deps.repo, exclusive_id, path, size, filename, request.headers.get("content-type"))
    except StorageError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Stockage Discord : {exc}") from exc
    finally:
        path.unlink(missing_ok=True)
    return await _track(request, deps, exclusive_id)


@router.delete("/exclusives/{exclusive_id}/versions/{version_id}")
async def delete_version(request: Request, exclusive_id: str, version_id: str, deps: ApiDeps = Depends(require_admin)) -> dict:
    """Retire une version ajoutée (le fichier d'origine ne se supprime qu'avec l'exclu)."""
    await _row(deps, exclusive_id)
    extras = (await deps.repo.exclusive_versions(exclusive_id)).get(exclusive_id, [])
    target = next((e for e in extras if e["id"] == version_id), None)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Version inconnue (le fichier d'origine ne se retire pas).")
    await deps.repo.exclusive_version_delete(exclusive_id, version_id)
    if deps.exclusive_storage is not None:
        await deps.exclusive_storage.delete(exclusives.chunks_of(target["chunks"]))
    for leftover in deps.settings.exclusives_cache_dir.glob(f"{exclusive_id}_{version_id}*"):
        leftover.unlink(missing_ok=True)
    return await _track(request, deps, exclusive_id)


@router.post("/exclusives/{exclusive_id}/cover")
async def set_cover(request: Request, exclusive_id: str, deps: ApiDeps = Depends(require_admin)) -> dict:
    """Remplace la pochette (le corps est l'image)."""
    storage = _storage(deps)
    row = await _row(deps, exclusive_id)
    mime = (request.headers.get("content-type") or "").split(";")[0].strip()
    if mime not in ("image/jpeg", "image/png", "image/webp"):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Pochette : JPEG, PNG ou WebP.")
    data = await request.body()
    if not data or len(data) > exclusives.MAX_COVER_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Pochette vide ou supérieure à 8 Mo.")
    try:
        chunks, cover_mime = await exclusives.store_cover(storage, data, mime)
    except StorageError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Stockage Discord : {exc}") from exc
    await deps.repo.exclusive_update(exclusive_id, {"cover_chunks": chunks, "cover_mime": cover_mime})
    await storage.delete(exclusives.chunks_of(row.get("cover_chunks")))
    return await _track(request, deps, exclusive_id)


class ExclusivePatch(BaseModel):
    title: str | None = None
    artist: str | None = None
    artist_source: str | None = None
    artist_source_id: str | None = None
    year: str | None = None
    kind: str | None = None


@router.patch("/exclusives/{exclusive_id}")
async def edit_exclusive(
    request: Request, exclusive_id: str, body: ExclusivePatch, deps: ApiDeps = Depends(require_admin)
) -> dict:
    await _row(deps, exclusive_id)
    fields = body.model_dump(exclude_unset=True)
    if "year" in fields:
        fields["year"] = exclusives.clean_year(fields["year"])
    if fields.get("kind") not in (None, *exclusives.KINDS):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Type inconnu (exclu ou inedit).")
    for key in ("title", "artist"):
        if key in fields and not (fields[key] or "").strip():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Titre et artiste ne peuvent pas être vides.")
    # Titre, artiste et type ne s'effacent pas ; la fiche artiste et l'année, si.
    keep = {k: v for k, v in fields.items() if v is not None or k in ("artist_source", "artist_source_id", "year")}
    await deps.repo.exclusive_update(exclusive_id, keep)
    return await _track(request, deps, exclusive_id)


@router.delete("/exclusives/{exclusive_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_exclusive(exclusive_id: str, deps: ApiDeps = Depends(require_admin)) -> Response:
    row = await _row(deps, exclusive_id)
    storage = deps.exclusive_storage
    if storage is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Stockage indisponible.")
    await exclusives.remove(storage, deps.repo, deps.settings.exclusives_cache_dir, row)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
