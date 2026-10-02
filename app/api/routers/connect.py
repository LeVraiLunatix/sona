"""Sona Connect : reprendre la lecture d'un appareil à l'autre, piloter un
appareil depuis un autre (voir services/connect.py)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.auth import require_token
from app.api.schemas import Track
from app.api.state import ApiDeps
from app.services import connect

router = APIRouter(prefix="/connect", tags=["sona connect"])


class PlaybackIn(BaseModel):
    queue: list[Track] = Field(min_length=1, max_length=500)
    index: int = Field(0, ge=0)
    position: float = Field(0, ge=0)
    paused: bool = False
    volume: float | None = Field(None, ge=0, le=1)
    name: str | None = Field(None, max_length=200)


class SyncIn(BaseModel):
    device_id: str = Field(min_length=6, max_length=64)
    name: str = Field(min_length=1, max_length=60)
    # `desktop` : Sona pour Windows (l'app d'ordinateur, voir desktop/).
    kind: str = Field("web", pattern="^(iphone|web|desktop)$")
    state: PlaybackIn | None = None
    # Lecture lancée à la main sur cet appareil : les autres se mettent en pause.
    claim: bool = False
    # Secondes d'attente d'une nouveauté (commande, lecture qui change
    # ailleurs) avant de répondre : réactions quasi instantanées.
    wait: float = Field(0, ge=0, le=30)


class CommandIn(BaseModel):
    device_id: str = Field(min_length=6, max_length=64)
    target: str = Field(min_length=6, max_length=64)
    action: str
    position: float | None = Field(None, ge=0)
    volume: float | None = Field(None, ge=0, le=1)


@router.post("/sync")
async def sync(payload: SyncIn, deps: ApiDeps = Depends(require_token)) -> dict:
    state = None
    if payload.state is not None:
        state = payload.state.model_dump()
        state["queue"] = [t.model_dump() for t in payload.state.queue]
    return await connect.sync_wait(
        deps.user_id, payload.device_id, payload.name, payload.kind, state, payload.claim, payload.wait
    )


@router.post("/command", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def send_command(payload: CommandIn, deps: ApiDeps = Depends(require_token)) -> None:
    extra = {k: v for k, v in (("position", payload.position), ("volume", payload.volume)) if v is not None}
    try:
        sent = connect.command(deps.user_id, payload.device_id, payload.target, payload.action, extra)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Commande inconnue.")
    if not sent:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cet appareil n'est plus connecté.")
