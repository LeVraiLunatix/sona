"""« Écoute ensemble » (voir services/party.py)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.auth import require_token
from app.api.schemas import Track
from app.api.state import ApiDeps
from app.services import party as party_service

router = APIRouter(prefix="/party", tags=["écoute ensemble"])


class PartyStateIn(BaseModel):
    track: Track | None = None
    position: float = Field(0, ge=0)
    paused: bool = False


class ProposeIn(BaseModel):
    track: Track


class ConsumeIn(BaseModel):
    ids: list[int]


class ReactIn(BaseModel):
    emoji: str = Field(min_length=1, max_length=8)


def _identity(deps: ApiDeps) -> tuple[str, str | None]:
    account = deps.account
    if account is None:
        return "Admin", None
    return account.display_name or account.lastfm_username, account.avatar_url


def _party(code: str):
    try:
        return party_service.get(code)
    except party_service.PartyError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


def _guard(call):
    try:
        return call()
    except party_service.PartyError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.post("")
async def create_party(deps: ApiDeps = Depends(require_token)) -> dict:
    name, avatar = _identity(deps)
    party = party_service.create(deps.user_id, name, avatar)
    return party_service.snapshot(party, deps.user_id)


@router.get("/active")
async def active_parties(deps: ApiDeps = Depends(require_token)) -> list[dict]:
    """Sessions en cours : celles des amis (à rejoindre) et la sienne."""
    visible = {a.user_id for a in await deps.repo.list_accounts() if a.status == "approved" and a.share_listening}
    visible.add(deps.user_id)
    out = []
    for party in party_service.all_parties():
        if party.host_user_id not in visible and deps.user_id not in party.members:
            continue
        host = party.host
        out.append({
            "code": party.code,
            "host_name": host.name if host else None,
            "host_avatar_url": host.avatar_url if host else None,
            "members": len(party.members),
            "track": party.track,
            "joined": deps.user_id in party.members,
        })
    return out


@router.get("/{code}")
async def party_state(code: str, deps: ApiDeps = Depends(require_token)) -> dict:
    party = _party(code)
    _guard(lambda: party_service.touch(party, deps.user_id))
    return party_service.snapshot(party, deps.user_id)


@router.post("/{code}/join")
async def join_party(code: str, deps: ApiDeps = Depends(require_token)) -> dict:
    name, avatar = _identity(deps)
    party = _guard(lambda: party_service.join(code, deps.user_id, name, avatar))
    return party_service.snapshot(party, deps.user_id)


@router.post("/{code}/leave")
async def leave_party(code: str, deps: ApiDeps = Depends(require_token)) -> dict:
    party = _party(code)
    party_service.leave(party, deps.user_id)
    return {"left": True}


@router.post("/{code}/state")
async def set_party_state(code: str, payload: PartyStateIn, deps: ApiDeps = Depends(require_token)) -> dict:
    party = _party(code)
    track = payload.track.model_dump() if payload.track else None
    _guard(lambda: party_service.set_state(party, deps.user_id, track, payload.position, payload.paused))
    return party_service.snapshot(party, deps.user_id)


@router.post("/{code}/queue")
async def propose_track(code: str, payload: ProposeIn, deps: ApiDeps = Depends(require_token)) -> dict:
    party = _party(code)
    _guard(lambda: party_service.propose(party, deps.user_id, payload.track.model_dump()))
    return party_service.snapshot(party, deps.user_id)


@router.post("/{code}/queue/consume")
async def consume_queue(code: str, payload: ConsumeIn, deps: ApiDeps = Depends(require_token)) -> dict:
    party = _party(code)
    _guard(lambda: party_service.consume(party, deps.user_id, payload.ids))
    return party_service.snapshot(party, deps.user_id)


@router.post("/{code}/queue/{item_id}/vote")
async def vote_track(code: str, item_id: int, deps: ApiDeps = Depends(require_token)) -> dict:
    party = _party(code)
    _guard(lambda: party_service.vote(party, deps.user_id, item_id))
    return party_service.snapshot(party, deps.user_id)


@router.post("/{code}/react")
async def react(code: str, payload: ReactIn, deps: ApiDeps = Depends(require_token)) -> dict:
    party = _party(code)
    _guard(lambda: party_service.react(party, deps.user_id, payload.emoji))
    return party_service.snapshot(party, deps.user_id)
