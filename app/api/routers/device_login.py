"""Connexion d'un appareil par QR code (voir services/device_login.py) : la TV
affiche un QR code, on l'autorise depuis un appareil connecté."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.api.auth import get_deps, identify, require_token
from app.api.routers.accounts import AccountOut
from app.api.state import ApiDeps
from app.services import device_login

router = APIRouter(prefix="/auth/device", tags=["connexion par QR code"])


class StartIn(BaseModel):
    name: str = Field("", max_length=60)


class StartOut(BaseModel):
    device_code: str
    user_code: str
    verify_url: str
    expires_in: int
    interval: int


class PollIn(BaseModel):
    device_code: str = Field(min_length=10, max_length=100)


class CodeIn(BaseModel):
    user_code: str = Field(min_length=4, max_length=20)


def _verify_url(request: Request, deps: ApiDeps, user_code: str) -> str:
    base = deps.settings.web_app_url or (
        f"{deps.settings.share_base_url}/web" if deps.settings.share_base_url else f"{str(request.base_url).rstrip('/')}/web"
    )
    return f"{base.rstrip('/')}/?link={user_code}"


@router.post("/start", response_model=StartOut)
async def start(payload: StartIn, request: Request, deps: ApiDeps = Depends(get_deps)) -> StartOut:
    """L'appareil (sans compte) demande un code ; il affichera `verify_url` en QR code."""
    created = device_login.start(payload.name)
    if created is None:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Trop de connexions en attente : réessaie dans quelques minutes.")
    return StartOut(
        device_code=created.device_code, user_code=created.user_code, verify_url=_verify_url(request, deps, created.user_code),
        expires_in=device_login.TTL_SECONDS, interval=device_login.POLL_INTERVAL,
    )


@router.post("/poll")
async def poll(payload: PollIn, deps: ApiDeps = Depends(get_deps)) -> dict:
    """`pending` tant que personne n'a autorisé ; `approved` (une seule fois) avec la session ;
    410 si le code a expiré ou a été refusé."""
    found = device_login.by_device_code(payload.device_code)
    if found is None or found.expired():
        raise HTTPException(status.HTTP_410_GONE, "Code expiré : relance la connexion.")
    if found.denied:
        device_login.consume(found.device_code)
        raise HTTPException(status.HTTP_410_GONE, "Connexion refusée depuis l'autre appareil.")
    if found.session_token is None:
        return {"status": "pending"}
    device_login.consume(found.device_code)
    return {"status": "approved", "session_token": found.session_token, "account": AccountOut.from_account(found.account)}


@router.get("/{user_code}")
async def details(user_code: str, deps: ApiDeps = Depends(identify)) -> dict:
    """Ce que l'appareil connecté voit avant d'autoriser : le nom de l'appareil qui demande."""
    found = device_login.by_user_code(user_code)
    if found is None or found.expired():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Code inconnu ou expiré.")
    return {"user_code": found.user_code, "name": found.name, "expires_in": int(device_login.TTL_SECONDS - (time.time() - found.created))}


@router.post("/approve")
async def approve(payload: CodeIn, deps: ApiDeps = Depends(require_token)) -> dict:
    """Autorise l'appareil : il reçoit sa propre session sur ce compte."""
    if deps.account is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Connecte-toi avec ton compte alyra (pas avec le jeton du serveur) pour autoriser un appareil.",
        )
    found = device_login.by_user_code(payload.user_code)
    if found is None or found.expired():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Code inconnu ou expiré : relance la connexion sur l'appareil.")
    found.session_token = await deps.repo.create_session(deps.account.id)
    found.account = deps.account
    return {"ok": True, "name": found.name}


@router.post("/deny")
async def deny(payload: CodeIn, deps: ApiDeps = Depends(identify)) -> dict:
    found = device_login.by_user_code(payload.user_code)
    if found is not None:
        found.denied = True
    return {"ok": True}
