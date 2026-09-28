from __future__ import annotations

import hmac
from dataclasses import replace

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.state import ApiDeps

_bearer = HTTPBearer(auto_error=False)

PENDING_MESSAGE = "Compte en attente de validation par un administrateur."
REJECTED_MESSAGE = "Accès à l'app refusé par un administrateur."


def get_deps(request: Request) -> ApiDeps:
    return request.app.state.deps


def bearer_token(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Connexion requise.")
    return credentials.credentials


async def identify(deps: ApiDeps = Depends(get_deps), token: str = Depends(bearer_token)) -> ApiDeps:
    """L'appelant, quel que soit l'état de son compte : l'ancien jeton unique
    `API_TOKEN` (administrateur, données de API_USER_ID), ou une session de
    l'app ouverte avec Last.fm. `hmac.compare_digest` : pas de timing attack."""
    if deps.settings.api_token and hmac.compare_digest(token, deps.settings.api_token):
        return replace(deps, is_admin=True)
    account = await deps.repo.account_for_session(token)
    if account is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expirée ou invalide : reconnecte-toi.")
    return replace(deps, account=account, is_admin=account.is_admin, user_id_override=account.user_id)


async def require_token(deps: ApiDeps = Depends(identify)) -> ApiDeps:
    """Toutes les routes de l'app : compte accepté par un administrateur."""
    if deps.account is not None and deps.account.status != "approved":
        message = PENDING_MESSAGE if deps.account.status == "pending" else REJECTED_MESSAGE
        raise HTTPException(status.HTTP_403_FORBIDDEN, message)
    return deps


async def require_admin(deps: ApiDeps = Depends(require_token)) -> ApiDeps:
    if not deps.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Réservé aux administrateurs.")
    return deps
