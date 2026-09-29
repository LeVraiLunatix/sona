"""Sona Connect : un seul lecteur pour tous les appareils d'un compte
(l'iPhone, Sona web sur un ou plusieurs ordinateurs), comme Spotify Connect.

Chaque appareil se signale toutes les quelques secondes (`sync`) avec son
état de lecture ; il reçoit en retour la liste des appareils, la dernière
lecture du compte (pour reprendre ailleurs) et les commandes qu'un autre
appareil lui a envoyées (pause, suivant, « écoute ici »…).

Gardé en mémoire seulement : c'est un état de l'instant.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

ONLINE_SECONDS = 15        # appareil considéré connecté
FORGET_SECONDS = 24 * 3600  # appareil oublié
MAX_QUEUE = 150
MAX_COMMANDS = 20
ACTIONS = {"play", "pause", "toggle", "next", "previous", "seek", "volume", "transfer"}


@dataclass
class Device:
    id: str
    name: str
    kind: str
    last_seen: float = 0.0
    playing: bool = False
    track: dict | None = None
    volume: float | None = None


@dataclass
class Account:
    devices: dict[str, Device] = field(default_factory=dict)
    commands: dict[str, list[dict]] = field(default_factory=dict)
    # Dernière lecture du compte, sur n'importe quel appareil.
    session: dict | None = None


_accounts: dict[int, Account] = {}


def _now() -> float:
    return time.time()


def reset() -> None:
    """Pour les tests."""
    _accounts.clear()


def _account(user_id: int) -> Account:
    account = _accounts.setdefault(user_id, Account())
    now = _now()
    for device_id in [d.id for d in account.devices.values() if now - d.last_seen > FORGET_SECONDS]:
        account.devices.pop(device_id, None)
        account.commands.pop(device_id, None)
    return account


def _online(device: Device, now: float) -> bool:
    return now - device.last_seen <= ONLINE_SECONDS


def _position(session: dict, now: float) -> float:
    """Position actuelle de la lecture (elle avance toute seule si elle joue)."""
    position = session["position"]
    if not session["paused"]:
        position += now - session["at"]
    duration = (session.get("track") or {}).get("duration_seconds")
    return max(0.0, min(position, float(duration)) if duration else position)


def sync(user_id: int, device_id: str, name: str, kind: str, state: dict | None, claim: bool = False) -> dict:
    """Un appareil se signale. `state` : sa lecture (None s'il ne joue
    rien) ; `claim` : on vient d'y lancer la lecture à la main — les autres
    appareils qui jouent se mettent en pause (un seul lecteur à la fois)."""
    now = _now()
    account = _account(user_id)
    device = account.devices.get(device_id) or Device(id=device_id, name=name, kind=kind)
    device.name, device.kind, device.last_seen = name, kind, now
    account.devices[device_id] = device

    if state and state.get("queue"):
        queue = state["queue"][:MAX_QUEUE]
        index = max(0, min(int(state.get("index") or 0), len(queue) - 1))
        paused = bool(state.get("paused"))
        device.playing = not paused
        device.track = queue[index]
        device.volume = state.get("volume")
        current = account.session
        # La session suit l'appareil qui joue ; un appareil en pause ne la
        # reprend pas à celui qui joue ailleurs.
        if not paused or current is None or current["device_id"] == device_id or not _session_playing(account, now):
            account.session = {
                "device_id": device_id, "device_name": name, "queue": queue, "index": index,
                "position": float(state.get("position") or 0), "paused": paused, "at": now,
                "name": state.get("name") or "", "track": queue[index],
            }
        if claim and not paused:
            for other in account.devices.values():
                if other.id != device_id and other.playing and _online(other, now):
                    _push(account, other.id, {"action": "pause", "from": name})
                    other.playing = False
    else:
        device.playing = False
        device.track = None

    commands = account.commands.pop(device_id, [])
    return snapshot(user_id, device_id) | {"commands": commands}


def _session_playing(account: Account, now: float) -> bool:
    session = account.session
    if not session or session["paused"]:
        return False
    device = account.devices.get(session["device_id"])
    return device is not None and _online(device, now) and device.playing


def snapshot(user_id: int, device_id: str | None = None) -> dict:
    now = _now()
    account = _account(user_id)
    session = account.session
    active = session["device_id"] if session and _session_playing(account, now) else None
    devices = sorted(
        (d for d in account.devices.values() if _online(d, now) or d.id == device_id),
        key=lambda d: (d.id != device_id, d.name.casefold()),
    )
    return {
        "devices": [{
            "id": d.id, "name": d.name, "kind": d.kind, "is_me": d.id == device_id,
            "playing": d.playing and _online(d, now), "track": d.track, "volume": d.volume,
        } for d in devices],
        "active_device_id": active,
        "session": None if session is None else {
            "device_id": session["device_id"], "device_name": session["device_name"],
            "queue": session["queue"], "index": session["index"], "name": session["name"],
            "track": session["track"], "position": round(_position(session, now), 2),
            "paused": not active, "age_seconds": round(now - session["at"], 1),
        },
    }


def _push(account: Account, device_id: str, command: dict) -> None:
    queue = account.commands.setdefault(device_id, [])
    queue.append(command)
    del queue[:-MAX_COMMANDS]


def command(user_id: int, from_device: str, target: str, action: str, payload: dict | None = None) -> bool:
    """Commande envoyée à un autre appareil ; relevée à son prochain `sync`.
    `transfer` : « écoute sur cet appareil » — la cible reprend la session
    (file, titre, position) et l'appareil qui jouait se met en pause."""
    if action not in ACTIONS:
        raise ValueError(action)
    now = _now()
    account = _account(user_id)
    device = account.devices.get(target)
    if device is None or not _online(device, now):
        return False
    sender = account.devices.get(from_device)
    body = {"action": action, "from": sender.name if sender else "", **(payload or {})}
    if action == "transfer":
        session = account.session
        if not session:
            return False
        body.update({
            "queue": session["queue"], "index": session["index"], "name": session["name"],
            "position": round(_position(session, now), 2),
        })
        for other in account.devices.values():
            if other.id != target and other.playing and _online(other, now):
                _push(account, other.id, {"action": "pause", "from": device.name})
                other.playing = False
    _push(account, target, body)
    return True
