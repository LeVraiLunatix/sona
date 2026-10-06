from __future__ import annotations

import random
from datetime import date

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


@router.get("/daily")
async def daily_track(deps: ApiDeps = Depends(require_token)) -> dict:
    """Titre du jour : une découverte choisie d'après tes goûts (un artiste
    proche de tes favoris, sinon ton mix du jour), la même toute la journée."""
    mixes = await mixes_service.get_mixes(deps, deps.user_id)
    by_id = {m.id: m for m in mixes}
    for mix_id, reason in (("discoveries", "Un artiste proche de tes favoris, que tu n'as jamais écouté"),
                           ("daily", "D'après tes artistes du moment")):
        mix = by_id.get(mix_id)
        if mix and mix.tracks:
            pick = random.Random(f"{deps.user_id}-{date.today()}-titre").choice(mix.tracks)
            return {"track": Track.from_info(pick).model_dump(), "reason": reason}
    return {"track": None, "reason": "Écoute un peu de musique : ton titre du jour arrivera vite."}


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
