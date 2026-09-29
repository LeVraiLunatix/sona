"""Carte des écoutes : où tu as écouté quoi. Les écoutes portent un lieu
arrondi à ~1 km (jamais plus précis) ; on les regroupe par zone de ~5 km."""

from __future__ import annotations

from collections import defaultdict

from app.services import stats as stats_service

CELL = 0.05  # degrés : ~5 km


async def places(repo, user_id: int, since: str | None = None) -> list[dict]:
    plays = [p for p in await repo.plays_between(user_id, since, None) if p.lat is not None and p.lon is not None]
    groups: dict[tuple[int, int], list] = defaultdict(list)
    for p in plays:
        groups[(round(p.lat / CELL), round(p.lon / CELL))].append(p)
    out = []
    for group in groups.values():
        top = stats_service.top_tracks(group, limit=5)
        artists = stats_service.top_artists(group, limit=1)
        sample = next((p for p in reversed(group) if p.source and p.source_id), group[-1])
        out.append({
            "lat": round(sum(p.lat for p in group) / len(group), 3),
            "lon": round(sum(p.lon for p in group) / len(group), 3),
            "plays": len(group),
            "top_artist": artists[0].name if artists else None,
            "top_tracks": [{"title": t.name, "artist": t.subtitle, "plays": t.plays} for t in top],
            "cover_url": top[0].cover_url if top else sample.cover_url,
            "first": group[0].played_at,
            "last": group[-1].played_at,
            "track": {
                "source": sample.source, "source_id": sample.source_id, "title": sample.title,
                "artist": sample.artist, "cover_url": sample.cover_url,
            } if sample.source and sample.source_id else None,
        })
    return sorted(out, key=lambda g: -g["plays"])
