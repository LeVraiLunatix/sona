"""« Il y a un an… » : ce que tu écoutais à la même date les années passées."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from app.services import stats as stats_service
from app.services.stats import MONTHS_FR


async def memories(repo, user_id: int, tz_name: str | None, today: date | None = None) -> list[dict]:
    tz = stats_service.resolve_tz(tz_name)
    today = today or datetime.now(tz).date()
    out = []
    for years in range(1, 6):
        try:
            day = today.replace(year=today.year - years)
        except ValueError:  # 29 février
            day = today.replace(year=today.year - years, day=28)
        # Le jour même, à un jour près : un souvenir plus facile à trouver.
        start = datetime(day.year, day.month, day.day, tzinfo=tz) - timedelta(days=1)
        end = start + timedelta(days=3)
        plays = await repo.plays_between(user_id, stats_service.to_utc_iso(start), stats_service.to_utc_iso(end))
        if not plays:
            continue
        tracks = stats_service.top_tracks(plays, limit=10)
        playable = []
        for item in tracks:
            sample = next((p for p in reversed(plays) if p.title == item.name and p.artist == item.subtitle), None)
            if sample and sample.source and sample.source_id:
                playable.append({
                    "source": sample.source, "source_id": sample.source_id, "title": sample.title,
                    "artist": sample.artist, "album": sample.album, "cover_url": sample.cover_url,
                    "duration_seconds": sample.duration_seconds, "artist_source_id": sample.artist_source_id,
                    "album_source_id": sample.album_source_id,
                })
        if playable:
            label = "Il y a un an" if years == 1 else f"Il y a {years} ans"
            out.append({
                "years_ago": years, "label": label,
                "date_label": f"{day.day} {MONTHS_FR[day.month - 1]} {day.year}",
                "plays": len(plays), "tracks": playable,
            })
    return out
