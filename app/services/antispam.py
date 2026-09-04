from __future__ import annotations

_in_flight: set[tuple[int, str]] = set()


def try_acquire(user_id: int, track_uid: str) -> bool:
    """Retourne True si le traitement peut démarrer, False s'il est déjà en cours."""
    key = (user_id, track_uid)
    if key in _in_flight:
        return False
    _in_flight.add(key)
    return True


def release(user_id: int, track_uid: str) -> None:
    _in_flight.discard((user_id, track_uid))
