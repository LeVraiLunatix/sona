from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.auth import require_token
from app.api.schemas import LibraryAddRequest, LibraryItemOut
from app.api.state import ApiDeps
from app.bot import lookup
from app.db.repository import VALID_KINDS

router = APIRouter(prefix="/library", tags=["library"])

_GETTERS = {
    "track": lookup.get_track,
    "album": lookup.get_album,
    "artist": lookup.get_artist,
}


def _check_kind(kind: str) -> None:
    if kind not in VALID_KINDS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Type inconnu : {kind} (attendu : {VALID_KINDS})")


@router.get("/{kind}")
async def list_library(
    kind: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    deps: ApiDeps = Depends(require_token),
) -> dict:
    _check_kind(kind)
    items, total = await deps.repo.library_list(deps.user_id, kind, offset, limit)
    return {"total": total, "items": [LibraryItemOut.from_item(i) for i in items]}


@router.post("/{kind}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def add_to_library(kind: str, payload: LibraryAddRequest, deps: ApiDeps = Depends(require_token)) -> None:
    _check_kind(kind)
    try:
        obj = await _GETTERS[kind](deps, payload.source, payload.source_id)
    except lookup.ProviderErrors as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    await deps.repo.library_add(deps.user_id, kind, obj)


@router.delete("/{kind}/{source}/{source_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def remove_from_library(
    kind: str, source: str, source_id: str, deps: ApiDeps = Depends(require_token)
) -> None:
    _check_kind(kind)
    await deps.repo.library_remove(deps.user_id, kind, source, source_id)
