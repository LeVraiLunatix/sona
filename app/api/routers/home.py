from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.api.auth import require_token
from app.api.schemas import Track
from app.api.state import ApiDeps
from app.services import mixes as mixes_service

router = APIRouter(prefix="/home", tags=["accueil"])


class MixOut(BaseModel):
    id: str
    title: str
    subtitle: str
    covers: list[str]
    tracks: list[Track]


@router.get("/mixes", response_model=list[MixOut])
async def get_mixes(
    refresh: bool = Query(False, description="Recalculer au lieu de reprendre les mixes du jour"),
    deps: ApiDeps = Depends(require_token),
) -> list[MixOut]:
    """Mixes « Faits pour toi » de l'accueil (voir services/mixes.py)."""
    mixes = await mixes_service.get_mixes(deps, deps.user_id, refresh)
    return [
        MixOut(id=m.id, title=m.title, subtitle=m.subtitle, covers=m.covers, tracks=[Track.from_info(t) for t in m.tracks])
        for m in mixes
    ]
