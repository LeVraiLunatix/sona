"""Concerts à venir des artistes les plus écoutés (voir services/concerts.py)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.auth import require_token
from app.api.state import ApiDeps
from app.services import concerts

router = APIRouter(tags=["concerts"])


@router.get("/concerts")
async def upcoming_concerts(deps: ApiDeps = Depends(require_token)) -> list[dict]:
    return await concerts.upcoming_for_user(deps, deps.user_id)
