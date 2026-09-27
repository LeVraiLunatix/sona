from __future__ import annotations

import hmac

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.state import ApiDeps

_bearer = HTTPBearer(auto_error=False)


def get_deps(request: Request) -> ApiDeps:
    return request.app.state.deps


def require_token(
    deps: ApiDeps = Depends(get_deps),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> ApiDeps:
    """Vérifie `Authorization: Bearer <API_TOKEN>`.

    Une seule clé partagée : l'API est un usage personnel (voir README), pas
    un service multi-utilisateurs — inutile de reconstruire la whitelist et
    les invitations du bot Telegram ici. `hmac.compare_digest` évite qu'un
    timing attack ne devine le jeton caractère par caractère.
    """
    if not deps.settings.api_token:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "API désactivée : API_TOKEN manquant dans .env.",
        )
    if credentials is None or not hmac.compare_digest(credentials.credentials, deps.settings.api_token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Jeton invalide ou manquant.")
    return deps
