from __future__ import annotations

import asyncio
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.auth import bearer_token, get_deps, identify, require_admin
from app.api.state import ApiDeps
from app.db.repository import Account
from app.providers.lastfm_auth import APP_CALLBACK, AUTH_URL, LastfmAuthError

logger = logging.getLogger(__name__)
router = APIRouter(tags=["comptes"])


class AccountOut(BaseModel):
    id: int | None
    username: str
    display_name: str | None
    avatar_url: str | None
    status: str
    is_admin: bool
    scrobble_to_lastfm: bool
    created_at: str | None

    @classmethod
    def from_account(cls, a: Account) -> "AccountOut":
        return cls(
            id=a.id, username=a.lastfm_username, display_name=a.display_name, avatar_url=a.avatar_url,
            status=a.status, is_admin=a.is_admin, scrobble_to_lastfm=a.scrobble_to_lastfm, created_at=a.created_at,
        )


class AuthConfigOut(BaseModel):
    lastfm_enabled: bool
    auth_url: str | None


class LastfmLoginIn(BaseModel):
    token: str


class LoginOut(BaseModel):
    session_token: str
    account: AccountOut


class MeUpdate(BaseModel):
    scrobble_to_lastfm: bool | None = None


def _legacy_account(deps: ApiDeps) -> AccountOut:
    """L'ancien jeton unique (API_TOKEN) : administrateur sans compte Last.fm."""
    return AccountOut(
        id=None, username=deps.settings.lastfm_user or "admin", display_name="Administrateur", avatar_url=None,
        status="approved", is_admin=True, scrobble_to_lastfm=False, created_at=None,
    )


@router.get("/auth/config", response_model=AuthConfigOut)
async def auth_config(deps: ApiDeps = Depends(get_deps)) -> AuthConfigOut:
    """Publique : l'app en a besoin avant toute connexion."""
    if deps.lastfm_auth is None or not deps.settings.lastfm_api_key:
        return AuthConfigOut(lastfm_enabled=False, auth_url=None)
    url = str(httpx.URL(AUTH_URL, params={"api_key": deps.settings.lastfm_api_key, "cb": APP_CALLBACK}))
    return AuthConfigOut(lastfm_enabled=True, auth_url=url)


@router.post("/auth/lastfm", response_model=LoginOut)
async def login_with_lastfm(payload: LastfmLoginIn, deps: ApiDeps = Depends(get_deps)) -> LoginOut:
    """Échange le jeton renvoyé par Last.fm contre une session de l'app. Un
    nouveau compte attend la validation d'un administrateur (sauf les
    pseudos de ADMIN_LASTFM_USERS, acceptés d'office)."""
    if deps.lastfm_auth is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Connexion Last.fm non configurée : LASTFM_API_KEY et LASTFM_API_SECRET dans le .env du serveur.",
        )
    try:
        session = await deps.lastfm_auth.get_session(payload.token)
    except LastfmAuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    profile = await deps.lastfm_auth.profile(session.username)
    is_admin = session.username.casefold() in deps.settings.admin_lastfm_users
    account, created = await deps.repo.upsert_account(
        session.username, profile.display_name, profile.avatar_url, session.key, is_admin, deps.settings.api_user_id,
    )
    if created and account.status == "pending":
        asyncio.create_task(_notify_admins(deps, account))
    token = await deps.repo.create_session(account.id)
    return LoginOut(session_token=token, account=AccountOut.from_account(account))


@router.get("/auth/me", response_model=AccountOut)
async def me(deps: ApiDeps = Depends(identify)) -> AccountOut:
    """Accessible même en attente : l'app s'en sert pour savoir si l'accès a
    été accordé."""
    return AccountOut.from_account(deps.account) if deps.account else _legacy_account(deps)


@router.put("/auth/me", response_model=AccountOut)
async def update_me(payload: MeUpdate, deps: ApiDeps = Depends(identify)) -> AccountOut:
    if deps.account is None:
        return _legacy_account(deps)
    if payload.scrobble_to_lastfm is not None:
        await deps.repo.set_account_scrobbling(deps.account.id, payload.scrobble_to_lastfm)
    return AccountOut.from_account(await deps.repo.account_by_id(deps.account.id))


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def logout(deps: ApiDeps = Depends(get_deps), token: str = Depends(bearer_token)) -> None:
    await deps.repo.delete_session(token)


# -- Administration ---------------------------------------------------------


@router.get("/admin/accounts", response_model=list[AccountOut])
async def list_accounts(deps: ApiDeps = Depends(require_admin)) -> list[AccountOut]:
    return [AccountOut.from_account(a) for a in await deps.repo.list_accounts()]


@router.post("/admin/accounts/{account_id}/{action}", response_model=AccountOut)
async def decide(account_id: int, action: str, deps: ApiDeps = Depends(require_admin)) -> AccountOut:
    """`approve` (accorder l'accès), `reject` (refuser / révoquer : ses
    sessions sont fermées), `promote` / `demote` (droits d'admin)."""
    target = await deps.repo.account_by_id(account_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Compte introuvable.")
    is_self = deps.account is not None and deps.account.id == account_id
    if is_self and action in ("reject", "demote"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Impossible de te retirer ton propre accès.")
    decided_by = deps.account.id if deps.account else None
    if action == "approve":
        await deps.repo.set_account_status(account_id, "approved", decided_by)
    elif action == "reject":
        await deps.repo.set_account_status(account_id, "rejected", decided_by)
    elif action in ("promote", "demote"):
        await deps.repo.set_account_admin(account_id, action == "promote")
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Action inconnue : {action}")
    return AccountOut.from_account(await deps.repo.account_by_id(account_id))


async def _notify_admins(deps: ApiDeps, account: Account) -> None:
    """Prévient les admins du bot Telegram qu'une demande d'accès attend
    (au mieux : une notification ratée ne bloque rien)."""
    token = deps.settings.bot_token
    if not token:
        return
    name = account.display_name or account.lastfm_username
    text = (
        f"🔔 Nouvelle demande d'accès à l'app Encre : {name} (Last.fm : {account.lastfm_username}).\n"
        "Accepte-la depuis l'app : Réglages → Administration."
    )
    try:
        admins = await deps.repo.list_admins()
        async with httpx.AsyncClient(timeout=10) as client:
            for chat_id in admins:
                await client.post(f"https://api.telegram.org/bot{token}/sendMessage", data={"chat_id": chat_id, "text": text})
    except Exception as exc:
        logger.info("Notification Telegram de la demande d'accès impossible : %s", exc)
