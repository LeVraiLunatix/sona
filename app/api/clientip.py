"""Adresse de l'appelant, derrière le reverse proxy local (Caddy)."""

from __future__ import annotations

from fastapi import Request


def client_ip(request: Request) -> str:
    """Celle que le proxy transmet quand la requête vient de la machine elle-même."""
    host = request.client.host if request.client else ""
    if host in ("127.0.0.1", "::1", "localhost", "testclient"):
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        return forwarded or host
    return host
