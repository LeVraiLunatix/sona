from __future__ import annotations

import base64
import hmac
import json
from dataclasses import replace

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.state import ApiDeps
from app.services import sona_accounts as sa

_bearer = HTTPBearer(auto_error=False)

class SanctionedError(Exception):
    """Compte banni ou suspendu : réponse 403 `{error: "sanctioned", status, reason, until}` (écran de sanction du site)."""

    def __init__(self, status: str, reason: str | None, until: str | None) -> None:
        super().__init__(status)
        self.body = {"error": "sanctioned", "status": status, "reason": reason, "until": until}


PENDING_MESSAGE = "Compte en attente de validation par un administrateur."
REJECTED_MESSAGE = "Accès à l'app refusé par un administrateur."


def get_deps(request: Request) -> ApiDeps:
    return request.app.state.deps


def bearer_token(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    if credentials is not None and credentials.credentials:
        return credentials.credentials
    # Lecteur web : une balise <audio> ne sait pas envoyer d'en-tête, le jeton
    # passe alors dans l'adresse — seulement pour lire un flux audio.
    token = request.query_params.get("token", "")
    if token and request.method == "GET" and request.url.path.startswith("/stream/"):
        return token
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Connexion requise.")


async def identify(deps: ApiDeps = Depends(get_deps), token: str = Depends(bearer_token)) -> ApiDeps:
    """L'appelant, quel que soit l'état de son compte : l'ancien jeton unique
    `API_TOKEN` (administrateur, données de API_USER_ID), ou une session de
    l'app ouverte avec Last.fm. `hmac.compare_digest` : pas de timing attack."""
    if deps.settings.api_token and hmac.compare_digest(token, deps.settings.api_token):
        return replace(deps, is_admin=True)
    if deps.accounts is not None and sa.looks_like_jwt(token):
        return await _identify_supabase(deps, token)
    account = await deps.repo.account_for_session(token)
    if account is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expirée ou invalide : reconnecte-toi.")
    return replace(deps, account=account, is_admin=account.is_admin, user_id_override=account.user_id)


async def _identify_supabase(deps: ApiDeps, token: str) -> ApiDeps:
    """Jeton Supabase : le service de comptes vérifie la signature et relit le statut à chaque appel (un compte
    banni ou suspendu est refusé tout de suite, avec la raison pour l'écran de sanction)."""
    try:
        who = await deps.accounts.verify(token)
    except sa.InvalidToken:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expirée ou invalide : reconnecte-toi.") from None
    except sa.Sanctioned as exc:
        raise SanctionedError(exc.status, exc.reason, exc.until) from None
    except sa.Unavailable:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Service de comptes indisponible.") from None
    profiles = await _profile_of(deps, who.uid)
    account = await deps.repo.ensure_account_for_uid(
        who.uid, who.username, profiles.get("display_name") or who.username, profiles.get("avatar_url"), who.is_admin
    )
    return replace(deps, account=account, is_admin=who.is_admin, user_id_override=account.user_id, is_guest=_anonymous(token))


def _anonymous(token: str) -> bool:
    """Réclamation `is_anonymous` du jeton. Lue seulement APRÈS sa vérification par le service de comptes."""
    try:
        part = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))).get("is_anonymous") is True
    except (IndexError, ValueError, AttributeError):
        return False


async def _profile_of(deps: ApiDeps, uid: str) -> dict:
    try:
        return await deps.accounts.profile(uid)
    except Exception:
        return {}


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
