"""Limites des actions lourdes, par compte : le serveur est petit et l'inscription ouverte.

En mémoire (un seul processus d'API) ; un redémarrage remet les compteurs à zéro, ce qui est sans gravité.
Les administrateurs ne sont pas limités.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, status

from app.api.auth import require_token
from app.api.state import ApiDeps

_hits: defaultdict[tuple[str, int], deque[float]] = defaultdict(deque)


def check(deps: ApiDeps, name: str, maximum: int, window: float) -> None:
    """Au plus `maximum` fois par `window` secondes pour ce compte ; sinon 429."""
    if deps.is_admin:
        return
    now = time.monotonic()
    hits = _hits[(name, deps.user_id)]
    while hits and now - hits[0] > window:
        hits.popleft()
    if len(hits) >= maximum:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Trop de demandes d'affilée : réessaie dans quelques minutes.")
    hits.append(now)


def no_guest(deps: ApiDeps) -> None:
    if deps.is_guest and not deps.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Crée un compte pour utiliser cette fonction.")


def heavy(name: str, maximum: int, window: float = 600.0):
    """Dépendance : compte (pas un invité) et pas trop souvent."""

    async def dependency(deps: ApiDeps = Depends(require_token)) -> ApiDeps:
        no_guest(deps)
        check(deps, name, maximum, window)
        return deps

    return dependency
