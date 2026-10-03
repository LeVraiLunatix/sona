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


class SaveIn(BaseModel):
    device_id: str = Field(min_length=6, max_length=64)


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


MAX_SAVED = 20


def _saved_item(user_id: int, row: dict) -> dict:
    """Un appareil enregistré, avec sa lecture s'il est allumé."""
    live = connect.device_info(user_id, row["device_id"]) or {}
    return {
        "id": row["device_id"], "name": live.get("name") or row["name"], "kind": live.get("kind") or row["kind"],
        "saved_at": row["saved_at"], "online": bool(live.get("online")), "playing": bool(live.get("playing")),
        "track": live.get("track"), "volume": live.get("volume"), "position": live.get("position", 0),
        "seen_seconds": live.get("seen_seconds"),
    }


@router.get("/saved")
async def saved_devices(deps: ApiDeps = Depends(require_token)) -> list[dict]:
    """« Appareils » : les appareils enregistrés (PC…), allumés ou non."""
    return [_saved_item(deps.user_id, row) for row in await deps.repo.connect_saved(deps.user_id)]


@router.post("/saved")
async def save_device(payload: SaveIn, deps: ApiDeps = Depends(require_token)) -> dict:
    """Enregistre un appareil du compte (vu récemment) : il reste dans la
    liste même éteint, et un appui le pilote dès qu'il est allumé."""
    live = connect.device_info(deps.user_id, payload.device_id)
    if live is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Appareil introuvable : ouvre Sona dessus, avec ce compte.")
    rows = await deps.repo.connect_saved(deps.user_id)
    if len(rows) >= MAX_SAVED and all(r["device_id"] != payload.device_id for r in rows):
        raise HTTPException(status.HTTP_409_CONFLICT, f"{MAX_SAVED} appareils au plus : oublies-en un d'abord.")
    await deps.repo.connect_save(deps.user_id, payload.device_id, live["name"], live["kind"])
    row = next(r for r in await deps.repo.connect_saved(deps.user_id) if r["device_id"] == payload.device_id)
    return _saved_item(deps.user_id, row)


@router.delete("/saved/{device_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def forget_device(device_id: str, deps: ApiDeps = Depends(require_token)) -> None:
    await deps.repo.connect_forget(deps.user_id, device_id)
