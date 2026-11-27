"""Routes de serveur à serveur pour `sona-accounts` (export, suppression, modération de contenu, sessions).

Protégées par le secret partagé `x-sona-internal` (comparaison en temps constant) ; absentes de la documentation
publique. Si le secret n'est pas configuré, TOUTES répondent 503 : jamais ouvertes par défaut.
"""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel

from app.api.auth import get_deps
from app.api.state import ApiDeps
from app.services import party as party_service
from app.services import uploads

router = APIRouter(prefix="/internal", tags=["interne"], include_in_schema=False)


async def internal(deps: ApiDeps = Depends(get_deps), x_sona_internal: str = Header("")) -> ApiDeps:
    secret = deps.settings.sona_internal_secret
    if not secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Routes internes non configurées.")
    if not hmac.compare_digest(x_sona_internal.encode(), secret.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refusé.")
    return deps


async def _user_id(deps: ApiDeps, uid: str) -> int | None:
    account = await deps.repo.account_for_uid(uid)
    return account.user_id if account else None


@router.get("/users/{uid}/export")
async def export_user(uid: str, deps: ApiDeps = Depends(internal)) -> dict:
    user_id = await _user_id(deps, uid)
    # Renvoyé tel quel : sona-accounts l'insère sous la clé « music » de l'export complet.
    return await deps.repo.export_user_data(user_id) if user_id is not None else {}


@router.delete("/users/{uid}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_user(uid: str, deps: ApiDeps = Depends(internal)) -> None:
    user_id = await _user_id(deps, uid)
    if user_id is not None:
        party_service.leave_all(user_id)
        for row in await deps.repo.upload_list(user_id):  # les fichiers eux-mêmes, avant leurs fiches
            await uploads.remove(deps, row)
        await deps.repo.delete_user_data(user_id)


class ContentIn(BaseModel):
    owner: str | None = None


@router.post("/content/{kind}/{ref}/{action}")
async def moderate_content(kind: str, ref: str, action: str, payload: ContentIn, deps: ApiDeps = Depends(internal)) -> dict:
    """Masquer (repasse la playlist en privé) ou supprimer un contenu signalé."""
    if kind != "playlist" or action not in ("hide", "delete") or not ref.isdigit():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Contenu ou action inconnus.")
    owner = await _user_id(deps, payload.owner) if payload.owner else None
    if owner is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Propriétaire introuvable.")
    if action == "hide":
        done = await deps.repo.playlist_set_visibility(int(ref), owner, "private")
    else:
        done = await deps.repo.playlist_get(owner, int(ref)) is not None
        if done:
            await deps.repo.playlist_delete(owner, int(ref))
    if not done:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Playlist introuvable.")
    return {"ok": True}


class SessionActionIn(BaseModel):
    user: str | None = None
    message_id: int | None = None


@router.post("/sessions/{code}/{action}")
async def moderate_session(code: str, action: str, payload: SessionActionIn, deps: ApiDeps = Depends(internal)) -> dict:
    """`close` (ferme), `kick` (retire une personne), `delete_message` (supprime un message du chat)."""
    try:
        party = party_service.get(code)
    except party_service.PartyError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    if action == "close":
        party_service.close(code)
    elif action == "kick":
        member = next((m for m in party.members.values() if m.uid == payload.user), None)
        if member is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Membre introuvable.")
        party.banned.add(member.user_id)
        party_service.leave(party, member.user_id)
    elif action == "delete_message":
        before = len(party.messages)
        party.messages = [m for m in party.messages if m.id != payload.message_id]
        if len(party.messages) == before:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Message introuvable.")
        party.bump()
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Action inconnue : {action}")
    return {"ok": True}
