"""Playlists intelligentes : des règles sur tes écoutes, recalculées à
chaque ouverture (« tes titres oubliés », « tes nuits »…)."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from app.db.repository import Play
from app.services import stats as stats_service

KINDS = {
    "on_repeat": ("En boucle", "Tes titres les plus écoutés ces 2 dernières semaines", "repeat"),
    "forgotten": ("Oubliés", "Des titres que tu adorais, pas écoutés depuis 3 mois", "clock.arrow.circlepath"),
    "discoveries": ("Découvertes du mois", "Les artistes que tu as découverts ce mois-ci", "sparkles"),
    "nights": ("Tes nuits", "Ce que tu écoutes entre 22 h et 5 h", "moon.stars.fill"),
    "mornings": ("Tes matins", "Ce que tu écoutes entre 5 h et 10 h", "sunrise.fill"),
    "crushes": ("Coups de cœur d'un jour", "Écoutés en boucle un jour… puis plus rien", "heart.circle.fill"),
}
LIMIT = 50


def _key(p: Play) -> tuple[str, str]:
    return (p.title.casefold(), p.artist.casefold())


def playable(plays: list[Play], keys: list[tuple[str, str]]) -> list[dict]:
    """Titres (dans l'ordre de `keys`) sous forme lisible par l'app : la
    dernière écoute connue de chacun, avec sa source."""
    latest: dict[tuple[str, str], Play] = {}
    for p in plays:
        if p.source and p.source_id:
            latest[_key(p)] = p
    out = []
    for key in keys:
        p = latest.get(key)
        if p is not None:
            out.append({
                "source": p.source, "source_id": p.source_id, "title": p.title, "artist": p.artist,
                "album": p.album, "cover_url": p.cover_url, "duration_seconds": p.duration_seconds,
                "artist_source_id": p.artist_source_id, "album_source_id": p.album_source_id,
            })
    return out


def _ranked(plays: list[Play], allowed=None) -> list[tuple[str, str]]:
    counts = Counter(_key(p) for p in plays if allowed is None or allowed(p))
    return [k for k, _ in counts.most_common(LIMIT)]


async def build(repo, user_id: int, kind: str, tz_name: str | None, now: datetime | None = None) -> list[dict]:
    tz = stats_service.resolve_tz(tz_name)
    now = (now or datetime.now(timezone.utc)).astimezone(tz)
    iso = stats_service.to_utc_iso
    plays = await repo.plays_between(user_id, iso(now - timedelta(days=730)), None)

    def hour(p: Play) -> int:
        return stats_service.parse_iso(p.played_at).astimezone(tz).hour

    if kind == "on_repeat":
        since = iso(now - timedelta(days=14))
        keys = _ranked([p for p in plays if p.played_at >= since])
    elif kind == "forgotten":
        cutoff = iso(now - timedelta(days=90))
        recent = {_key(p) for p in plays if p.played_at >= cutoff}
        counts = Counter(_key(p) for p in plays if p.played_at < cutoff)
        keys = [k for k, n in counts.most_common() if n >= 3 and k not in recent][:LIMIT]
    elif kind == "discoveries":
        month_start = iso(now.replace(day=1, hour=0, minute=0, second=0, microsecond=0))
        first_seen = await repo.plays_first_by_artist(user_id)
        new_artists = {a for a, first in first_seen.items() if first >= month_start}
        keys = _ranked([p for p in plays if p.played_at >= month_start and p.artist.casefold() in new_artists])
    elif kind == "nights":
        keys = _ranked(plays, lambda p: hour(p) >= 22 or hour(p) < 5)
    elif kind == "mornings":
        keys = _ranked(plays, lambda p: 5 <= hour(p) < 10)
    elif kind == "crushes":
        cutoff = iso(now - timedelta(days=30))
        per_day: dict[tuple[str, str], Counter] = defaultdict(Counter)
        for p in plays:
            per_day[_key(p)][stats_service.parse_iso(p.played_at).astimezone(tz).date()] += 1
        recent = {_key(p) for p in plays if p.played_at >= cutoff}
        crushes = [(max(days.values()), k) for k, days in per_day.items() if max(days.values()) >= 3 and k not in recent]
        keys = [k for _, k in sorted(crushes, reverse=True)][:LIMIT]
    else:
        return []
    return playable(plays, keys)
