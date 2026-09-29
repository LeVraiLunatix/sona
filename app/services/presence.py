"""« En train d'écouter » de chaque compte, pour l'onglet Amis.

Gardé en mémoire seulement : c'est un état de l'instant, sans intérêt après
un redémarrage. Une entrée s'efface d'elle-même une fois le titre fini (sa
durée, plus une marge), ou quand l'app signale une pause.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.providers.base import TrackInfo

# Durée retenue quand l'app n'envoie pas celle du titre.
DEFAULT_DURATION = 300
GRACE_SECONDS = 30


@dataclass(slots=True)
class NowPlaying:
    track: TrackInfo
    started_at: datetime

    def expires_at(self) -> datetime:
        duration = self.track.duration_seconds or DEFAULT_DURATION
        return self.started_at + timedelta(seconds=duration + GRACE_SECONDS)


_current: dict[int, NowPlaying] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def set_playing(user_id: int, track: TrackInfo, position_seconds: float = 0) -> None:
    """Titre lancé (ou repris à `position_seconds`)."""
    _current[user_id] = NowPlaying(track=track, started_at=_now() - timedelta(seconds=max(0, position_seconds)))


def clear(user_id: int) -> None:
    _current.pop(user_id, None)


def get(user_id: int) -> NowPlaying | None:
    entry = _current.get(user_id)
    if entry is None:
        return None
    if _now() > entry.expires_at():
        _current.pop(user_id, None)
        return None
    return entry


def reset() -> None:
    """Pour les tests."""
    _current.clear()
