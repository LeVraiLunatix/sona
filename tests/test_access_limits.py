"""Qui peut quoi : actions pour tous réservées à l'administrateur, invités sans actions lourdes, limites par compte."""

from __future__ import annotations

import base64
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import limits
from app.api.auth import _anonymous, require_admin
from app.api.routers import exclusives, local, stream


def deps(**kw):
    return SimpleNamespace(**{"is_admin": False, "is_guest": False, "user_id": 7, **kw})


def needs_admin(router, path: str, method: str) -> bool:
    route = next(r for r in router.routes if r.path == path and method in r.methods)
    return any(d.call is require_admin for d in route.dependant.dependencies)


def test_actions_that_affect_everyone_are_admin_only():
    assert needs_admin(stream.router, "/stream/{source}/{source_id}/wrong-version", "POST")
    assert needs_admin(local.router, "/local/scan", "POST")
    assert needs_admin(local.router, "/local/tracks", "GET")
    # Les exclus : tout le monde les écoute, seul l'administrateur les gère.
    for route in exclusives.router.routes:
        if route.methods & {"POST", "PUT", "PATCH", "DELETE"}:
            assert needs_admin(exclusives.router, route.path, next(iter(route.methods))), route.path
    assert not needs_admin(exclusives.router, "/exclusives", "GET")


def test_guests_cannot_run_heavy_actions_and_accounts_are_rate_limited():
    limits._hits.clear()
    with pytest.raises(HTTPException) as refused:
        limits.no_guest(deps(is_guest=True))
    assert refused.value.status_code == 403
    for _ in range(3):
        limits.check(deps(), "x", 3, 600)
    with pytest.raises(HTTPException) as full:
        limits.check(deps(), "x", 3, 600)
    assert full.value.status_code == 429
    limits.check(deps(user_id=8), "x", 3, 600)
    limits.check(deps(is_admin=True), "x", 3, 600)


def test_guest_claim_is_read_from_the_token():
    def jwt(claims):
        return "h." + base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=") + ".s"

    assert _anonymous(jwt({"is_anonymous": True}))
    assert not _anonymous(jwt({"is_anonymous": False}))
    assert not _anonymous("n'importe quoi")
