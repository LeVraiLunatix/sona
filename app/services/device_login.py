"""Connexion d'un appareil sans clavier (TV…) par QR code, façon « code d'appareil ».

L'appareil demande un code (`start`), l'affiche en QR code, puis interroge le
serveur (`poll`). Sur un appareil déjà connecté (téléphone, site), on ouvre le
lien du QR code et on autorise (`approve`) : l'appareil reçoit alors sa propre
session de compte, que l'on peut révoquer comme les autres (déconnexion).

Gardé en mémoire seulement, comme `connect` : une demande dure quelques minutes.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field

TTL_SECONDS = 600
POLL_INTERVAL = 3
MAX_PENDING = 200
LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"  # sans I ni O (confondus avec 1 et 0)


@dataclass
class Request:
    device_code: str
    user_code: str
    name: str
    created: float = field(default_factory=time.time)
    session_token: str | None = None
    account: object | None = None
    denied: bool = False

    def expired(self, now: float | None = None) -> bool:
        return (now or time.time()) - self.created > TTL_SECONDS


_requests: dict[str, Request] = {}


def reset() -> None:
    """Pour les tests."""
    _requests.clear()


def _purge() -> None:
    now = time.time()
    for code in [c for c, r in _requests.items() if r.expired(now)]:
        _requests.pop(code, None)


def normalize(user_code: str) -> str:
    """« abcd efgh », « ABCD-EFGH »… -> « ABCD-EFGH »."""
    letters = "".join(ch for ch in user_code.upper() if ch.isalpha())
    return f"{letters[:4]}-{letters[4:8]}" if len(letters) >= 8 else letters


def start(name: str) -> Request | None:
    """Nouvelle demande, ou None si trop de demandes sont en attente."""
    _purge()
    if len(_requests) >= MAX_PENDING:
        return None
    user_code = "".join(secrets.choice(LETTERS) for _ in range(8))
    request = Request(
        device_code=secrets.token_urlsafe(24), user_code=f"{user_code[:4]}-{user_code[4:]}", name=name.strip()[:60] or "Appareil",
    )
    _requests[request.device_code] = request
    return request


def by_user_code(user_code: str) -> Request | None:
    _purge()
    wanted = normalize(user_code)
    return next((r for r in _requests.values() if r.user_code == wanted and r.session_token is None and not r.denied), None)


def by_device_code(device_code: str) -> Request | None:
    _purge()
    return _requests.get(device_code)


def consume(device_code: str) -> None:
    _requests.pop(device_code, None)
