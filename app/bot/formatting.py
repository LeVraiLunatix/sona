from __future__ import annotations

from app.providers.base import TrackInfo


def track_duration(track: TrackInfo) -> str:
    return track.duration_label


def minutes_label(total_seconds: int | None) -> str:
    if not total_seconds:
        return "-- min"
    minutes = round(total_seconds / 60)
    return f"{minutes} min"


def tracks_label(count: int | None) -> str:
    if not count:
        return "0 titre"
    return f"{count} titre" + ("s" if count > 1 else "")


def result_line(index: int, track: TrackInfo) -> str:
    details = track.artist
    if track.album:
        details += f" • {track.album}"
    details += f" • {track.duration_label}"
    return f"{index}. {track.title}\n   {details}"


def escape(text: str) -> str:
    # Les écrans utilisent le mode texte brut par défaut (pas de HTML/Markdown),
    # ceci évite tout souci d'échappement dans les titres/artistes.
    return text
