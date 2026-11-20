"""Connexion d'un appareil sans clavier (TV…) par QR code, façon « code d'appareil ».

L'appareil demande un code (`start`), l'affiche en QR code, puis interroge le
serveur (`poll`). Sur un appareil déjà connecté (téléphone, site), on ouvre le
lien du QR code et on autorise (`approve`) : l'appareil reçoit alors sa propre
session de compte, que l'on peut révoquer comme les autres (déconnexion).

Gardé en mémoire seulement, comme `connect` : une demande dure quelques minutes.
"""

from __future__ import annotations

import ipaddress
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
    # Réseau de l'appareil qui demande (voir `network_key`) : sert à proposer la
    # demande aux appareils du compte qui sont sur le même réseau, sans QR code.
    network: str = ""

    def expired(self, now: float | None = None) -> bool:
        return (now or time.time()) - self.created > TTL_SECONDS


_requests: dict[str, Request] = {}
# Comptes dont un appareil s'est signalé récemment depuis un réseau : réseau -> {compte: dernière vue}.
_watchers: dict[str, dict[int, float]] = {}
WATCH_SECONDS = 120


def reset() -> None:
    """Pour les tests."""
    _requests.clear()
    _watchers.clear()


def network_key(ip: str) -> str:
    """Le « réseau » d'une adresse : l'IPv4 telle quelle (derrière la même box,
    tous les appareils ont la même), ou le préfixe /64 d'une IPv6 (commun à
    tout un réseau local). Vide si l'adresse est inconnue."""
    try:
        addr = ipaddress.ip_address((ip or "").strip())
    except ValueError:
        return ""
    if addr.version == 6:
        if addr.ipv4_mapped is not None:
            return str(addr.ipv4_mapped)
        return f"{ipaddress.ip_network(f'{addr}/64', strict=False).network_address}/64"
    return str(addr)


def seen(network: str, user_id: int) -> None:
    """Un appareil de ce compte vient de se signaler depuis ce réseau."""
    if network:
        _watchers.setdefault(network, {})[user_id] = time.time()


def watchers_of(network: str) -> list[int]:
    """Comptes à prévenir d'une demande arrivée de ce réseau."""
    now = time.time()
    found = _watchers.get(network, {})
    for user_id in [u for u, at in found.items() if now - at > WATCH_SECONDS]:
        found.pop(user_id, None)
    return list(found)


def nearby(network: str) -> list[Request]:
    """Demandes en attente venues du même réseau que l'appelant."""
    _purge()
    if not network:
        return []
    return [r for r in _requests.values() if r.network == network and r.session_token is None and not r.denied]


def _purge() -> None:
    now = time.time()
    for code in [c for c, r in _requests.items() if r.expired(now)]:
        _requests.pop(code, None)


def normalize(user_code: str) -> str:
    """« abcd efgh », « ABCD-EFGH »… -> « ABCD-EFGH »."""
    letters = "".join(ch for ch in user_code.upper() if ch.isalpha())
    return f"{letters[:4]}-{letters[4:8]}" if len(letters) >= 8 else letters


def start(name: str, network: str = "") -> Request | None:
    """Nouvelle demande, ou None si trop de demandes sont en attente."""
    _purge()
    if len(_requests) >= MAX_PENDING:
        return None
    user_code = "".join(secrets.choice(LETTERS) for _ in range(8))
    request = Request(
        device_code=secrets.token_urlsafe(24), user_code=f"{user_code[:4]}-{user_code[4:]}", name=name.strip()[:60] or "Appareil",
        network=network,
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
