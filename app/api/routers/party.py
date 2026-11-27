"""« Écoute ensemble » (voir services/party.py)."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.services import social
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


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=party_service.MAX_MESSAGE_LENGTH)


class CommandIn(BaseModel):
    action: str


class SettingsIn(BaseModel):
    open_controls: bool | None = None
    access: str | None = None
    locked: bool | None = None
    chat_enabled: bool | None = None
    max_participants: int | None = Field(None, ge=2, le=party_service.MAX_PARTICIPANTS_LIMIT)
    permissions: dict[str, str] | None = None


class MemberIn(BaseModel):
    member_id: int


class MuteIn(MemberIn):
    muted: bool = True


class ModeratorIn(MemberIn):
    moderator: bool = True


class JoinIn(BaseModel):
    invite: str | None = Field(None, max_length=200)


class InviteIn(BaseModel):
    ttl_seconds: int = Field(party_service.INVITE_DEFAULT_TTL, ge=60, le=party_service.INVITE_MAX_TTL)


def _identity(deps: ApiDeps) -> tuple[str, str | None]:
    account = deps.account
    if account is None:
        return "Admin", None
    return account.display_name or account.lastfm_username, account.avatar_url


def _uid(deps: ApiDeps) -> str | None:
    return deps.account.supabase_uid if deps.account else None


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
    party = party_service.create(deps.user_id, name, avatar, _uid(deps))
    return party_service.snapshot(party, deps.user_id)


@router.get("/active")
async def active_parties(deps: ApiDeps = Depends(require_token)) -> list[dict]:
    """Sessions en cours : celles des amis (à rejoindre) et la sienne."""
    visible = {a.user_id for a in await social.friend_accounts(deps, "presence")}
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
async def party_state(
    code: str,
    since: int | None = Query(None, description="Dernière version connue : attend qu'elle change"),
    wait: float = Query(0, ge=0, le=25, description="Attente maximale (s) avec `since`"),
    deps: ApiDeps = Depends(require_token),
) -> dict:
    party = _party(code)
    _guard(lambda: party_service.touch(party, deps.user_id))
    if since is not None and wait > 0:
        await party_service.wait_change(party, since, wait)
        party = _party(code)  # la session a pu se fermer pendant l'attente
        if deps.user_id not in party.members:
            raise HTTPException(403, "Tu ne fais plus partie de cette session.")
    return party_service.snapshot(party, deps.user_id)


@router.post("/{code}/join")
async def join_party(code: str, payload: JoinIn | None = None, deps: ApiDeps = Depends(require_token)) -> dict:
    name, avatar = _identity(deps)
    party = _party(code)
    is_friend, blocked = await _relations_with(deps, party)
    party = _guard(lambda: party_service.join(
        code, deps.user_id, name, avatar, _uid(deps), is_friend=is_friend, blocked=blocked,
        invite=payload.invite if payload else None,
    ))
    return party_service.snapshot(party, deps.user_id)


async def _relations_with(deps: ApiDeps, party) -> tuple[bool, bool]:
    """(ami accepté de l'hôte ?, un blocage existe avec un membre ?) — calculés par le service de comptes. En cas de
    doute (service injoignable, compte non rattaché) : ni ami, et refus si un blocage est possible."""
    me = _uid(deps)
    others = [m.uid for m in party.members.values() if m.uid and m.uid != me]
    if deps.accounts is None or not me or not others:
        return False, False
    try:
        rels = await deps.accounts.relations(me, others)
    except Exception:
        return False, True
    host = party.host.uid if party.host else None
    return bool(host and rels.get(host) and rels[host].friend), any(r.blocked for r in rels.values())


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


@router.delete("/{code}/queue/{item_id}")
async def remove_proposal(code: str, item_id: int, deps: ApiDeps = Depends(require_token)) -> dict:
    party = _party(code)
    _guard(lambda: party_service.unpropose(party, deps.user_id, item_id))
    return party_service.snapshot(party, deps.user_id)


@router.post("/{code}/chat")
async def chat(code: str, payload: ChatIn, deps: ApiDeps = Depends(require_token)) -> dict:
    party = _party(code)
    if deps.accounts is not None:
        try:
            offensive = await deps.accounts.text_offensive(payload.text)
        except Exception:
            offensive = False  # filtre indisponible : le signalement et la modération restent
        if offensive:
            raise HTTPException(400, "Message refusé : il contient un terme interdit.")
    _guard(lambda: party_service.say(party, deps.user_id, payload.text))
    return party_service.snapshot(party, deps.user_id)


@router.post("/{code}/skip")
async def vote_skip(code: str, deps: ApiDeps = Depends(require_token)) -> dict:
    party = _party(code)
    _guard(lambda: party_service.vote_skip(party, deps.user_id))
    return party_service.snapshot(party, deps.user_id)


@router.post("/{code}/command")
async def send_command(code: str, payload: CommandIn, deps: ApiDeps = Depends(require_token)) -> dict:
    party = _party(code)
    _guard(lambda: party_service.command(party, deps.user_id, payload.action))
    return party_service.snapshot(party, deps.user_id)


@router.post("/{code}/settings")
async def party_settings(code: str, payload: SettingsIn, deps: ApiDeps = Depends(require_token)) -> dict:
    party = _party(code)
    _guard(lambda: party_service.configure(
        party, deps.user_id, payload.open_controls, access=payload.access, locked=payload.locked,
        chat_enabled=payload.chat_enabled, max_participants=payload.max_participants, permissions=payload.permissions,
    ))
    return party_service.snapshot(party, deps.user_id)


@router.post("/{code}/invite")
async def create_invite(code: str, payload: InviteIn | None = None, deps: ApiDeps = Depends(require_token)) -> dict:
    party = _party(code)
    ttl = payload.ttl_seconds if payload else party_service.INVITE_DEFAULT_TTL
    token, expires = _guard(lambda: party_service.create_invite(party, deps.user_id, ttl))
    return {"token": token, "expires_at": datetime.fromtimestamp(expires, timezone.utc).isoformat()}


@router.delete("/{code}/invite")
async def revoke_invite(code: str, deps: ApiDeps = Depends(require_token)) -> dict:
    party = _party(code)
    _guard(lambda: party_service.revoke_invite(party, deps.user_id))
    return party_service.snapshot(party, deps.user_id)


@router.post("/{code}/ban")
async def ban_member(code: str, payload: MemberIn, deps: ApiDeps = Depends(require_token)) -> dict:
    party = _party(code)
    _guard(lambda: party_service.ban(party, deps.user_id, payload.member_id))
    return party_service.snapshot(party, deps.user_id)


@router.post("/{code}/mute")
async def mute_member(code: str, payload: MuteIn, deps: ApiDeps = Depends(require_token)) -> dict:
    party = _party(code)
    _guard(lambda: party_service.mute(party, deps.user_id, payload.member_id, payload.muted))
    return party_service.snapshot(party, deps.user_id)


@router.post("/{code}/moderator")
async def moderator(code: str, payload: ModeratorIn, deps: ApiDeps = Depends(require_token)) -> dict:
    party = _party(code)
    _guard(lambda: party_service.set_moderator(party, deps.user_id, payload.member_id, payload.moderator))
    return party_service.snapshot(party, deps.user_id)


@router.delete("/{code}/chat/{message_id}")
async def delete_chat_message(code: str, message_id: int, deps: ApiDeps = Depends(require_token)) -> dict:
    party = _party(code)
    _guard(lambda: party_service.delete_message(party, deps.user_id, message_id))
    return party_service.snapshot(party, deps.user_id)


@router.post("/{code}/transfer")
async def transfer_host(code: str, payload: MemberIn, deps: ApiDeps = Depends(require_token)) -> dict:
    party = _party(code)
    _guard(lambda: party_service.transfer(party, deps.user_id, payload.member_id))
    return party_service.snapshot(party, deps.user_id)


@router.post("/{code}/kick")
async def kick_member(code: str, payload: MemberIn, deps: ApiDeps = Depends(require_token)) -> dict:
    party = _party(code)
    _guard(lambda: party_service.kick(party, deps.user_id, payload.member_id))
    return party_service.snapshot(party, deps.user_id)
