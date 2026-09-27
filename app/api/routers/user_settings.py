from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.auth import require_token
from app.api.schemas import UserSettingsOut, UserSettingsUpdate
from app.api.state import ApiDeps
from app.db.repository import FORMAT_CHOICES, QUALITY_CHOICES

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=UserSettingsOut)
async def get_settings(deps: ApiDeps = Depends(require_token)) -> UserSettingsOut:
    return UserSettingsOut.from_settings(await deps.repo.get_settings(deps.user_id))


@router.put("", response_model=UserSettingsOut)
async def update_settings(payload: UserSettingsUpdate, deps: ApiDeps = Depends(require_token)) -> UserSettingsOut:
    if payload.quality is not None:
        if payload.quality not in QUALITY_CHOICES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Qualité inconnue : {payload.quality}")
        await deps.repo.set_quality(deps.user_id, payload.quality)
    if payload.format is not None:
        if payload.format not in FORMAT_CHOICES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Format inconnu : {payload.format}")
        await deps.repo.set_format(deps.user_id, payload.format)
    if payload.autoplay is not None:
        current = await deps.repo.get_settings(deps.user_id)
        if current.autoplay != payload.autoplay:
            await deps.repo.toggle_autoplay(deps.user_id)
    return UserSettingsOut.from_settings(await deps.repo.get_settings(deps.user_id))
