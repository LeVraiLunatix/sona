"""Blind test en direct entre amis (voir services/blindlive.py)."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.auth import require_token
from app.api.state import ApiDeps
from app.services import blindlive
from app.services import blindtest

router = APIRouter(prefix="/blindlive", tags=["blind test en direct"])


class ConfigIn(BaseModel):
    mode: str = "solo"
    ref: str | None = None
    label: str | None = Field(None, max_length=120)
    count: int = Field(blindtest.DEFAULT_QUESTIONS, ge=3, le=30)
    guess: str = "title"


class AnswerIn(BaseModel):
    index: int = Field(ge=0)
    choice: int = Field(ge=0)


def _identity(deps: ApiDeps) -> tuple[str, str | None]:
    account = deps.account
    if account is None:
        return "Admin", None
    return account.display_name or account.lastfm_username, account.avatar_url


def _guard(call):
    try:
        return call()
    except blindlive.LiveError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


def _room(code: str):
    return _guard(lambda: blindlive.get(code))


def _check_config(payload: ConfigIn) -> None:
    # Le défi du jour reste un défi solo, avec son classement.
    if payload.mode not in blindtest.MODES or payload.mode == "daily":
        raise HTTPException(400, f"Thème inconnu : {payload.mode}")
    if payload.guess not in blindtest.GUESSES:
        raise HTTPException(400, f"Question inconnue : {payload.guess}")


@router.post("")
async def create_room(deps: ApiDeps = Depends(require_token)) -> dict:
    name, avatar = _identity(deps)
    room = blindlive.create(deps.user_id, name, avatar)
    return blindlive.snapshot(room, deps.user_id)


@router.get("/active")
async def active_rooms(deps: ApiDeps = Depends(require_token)) -> list[dict]:
    """Parties des amis (à rejoindre) et la sienne."""
    visible = {a.user_id for a in await deps.repo.list_accounts() if a.status == "approved" and a.share_listening}
    visible.add(deps.user_id)
    out = []
    for room in blindlive.all_rooms():
        if room.host_user_id not in visible and deps.user_id not in room.players:
            continue
        host = room.host
        out.append({
            "code": room.code,
            "host_name": host.name if host else None,
            "host_avatar_url": host.avatar_url if host else None,
            "players": len(room.players),
            "phase": room.phase,
            "label": room.label,
            "joined": deps.user_id in room.players,
        })
    return out


@router.get("/{code}")
async def room_state(code: str, deps: ApiDeps = Depends(require_token)) -> dict:
    room = _room(code)
    _guard(lambda: blindlive.touch(room, deps.user_id))
    return blindlive.snapshot(room, deps.user_id)


@router.post("/{code}/join")
async def join_room(code: str, deps: ApiDeps = Depends(require_token)) -> dict:
    name, avatar = _identity(deps)
    room = _guard(lambda: blindlive.join(code, deps.user_id, name, avatar))
    return blindlive.snapshot(room, deps.user_id)


@router.post("/{code}/leave")
async def leave_room(code: str, deps: ApiDeps = Depends(require_token)) -> dict:
    room = _room(code)
    blindlive.leave(room, deps.user_id)
    return {"left": True}


@router.post("/{code}/config")
async def configure_room(code: str, payload: ConfigIn, deps: ApiDeps = Depends(require_token)) -> dict:
    _check_config(payload)
    room = _room(code)
    _guard(lambda: blindlive.configure(
        room, deps.user_id, payload.mode, payload.ref, payload.label, payload.count, payload.guess
    ))
    return blindlive.snapshot(room, deps.user_id)


@router.post("/{code}/start")
async def start_room(code: str, deps: ApiDeps = Depends(require_token)) -> dict:
    room = _room(code)
    if room.host_user_id != deps.user_id:
        raise HTTPException(403, "Seul l'hôte lance la partie.")
    if room.mode == "playlist" and room.ref:
        playlist = await deps.repo.playlist_by_id(int(room.ref)) if room.ref.isdigit() else None
        if playlist is None or (playlist.user_id != deps.user_id and playlist.visibility == "private"):
            raise HTTPException(404, "Playlist introuvable.")
    # « Vos titres » : les écoutes de tous les joueurs de la partie.
    pool = await blindtest.pool_for_mode(deps, room.mode, list(room.players), room.ref)
    questions = await blindtest.build_round(deps, pool, secrets.randbits(32), room.count, room.guess)
    room = _room(code)  # la partie a pu se fermer pendant la préparation
    _guard(lambda: blindlive.start(room, deps.user_id, questions))
    return blindlive.snapshot(room, deps.user_id)


@router.post("/{code}/answer")
async def answer(code: str, payload: AnswerIn, deps: ApiDeps = Depends(require_token)) -> dict:
    room = _room(code)
    _guard(lambda: blindlive.answer(room, deps.user_id, payload.index, payload.choice))
    return blindlive.snapshot(room, deps.user_id)
