"""Défis de la semaine et badges, calculés à partir des écoutes."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from app.services import stats as stats_service


def _challenge(key, title, icon, value, goal, unit):
    return {"id": key, "title": title, "icon": icon, "value": min(value, goal), "goal": goal, "unit": unit,
            "done": value >= goal}


async def compute(repo, user_id: int, tz_name: str | None, now: datetime | None = None) -> dict:
    tz = stats_service.resolve_tz(tz_name)
    now = (now or datetime.now(timezone.utc)).astimezone(tz)
    week = await stats_service.compute(repo, user_id, "week", 0, tz_name, now)
    week_plays = await repo.plays_between(user_id, week.start, week.end)

    # Album écouté en entier (ou presque) : le plus de titres différents d'un album.
    per_album: dict[tuple, set] = {}
    for p in week_plays:
        if p.album:
            per_album.setdefault((p.album.casefold(), p.artist.casefold()), set()).add(p.title.casefold())
    best_album = max((len(t) for t in per_album.values()), default=0)
    games = await repo.blindtest_games_since(user_id, week.start or "")

    challenges = [
        _challenge("discover", "Découvre 5 nouveaux artistes", "sparkle.magnifyingglass", len(week.discoveries), 5, "artistes"),
        _challenge("marathon", "3 heures de musique", "timer", week.minutes, 180, "min"),
        _challenge("variety", "20 artistes différents", "person.3.fill", week.artists, 20, "artistes"),
        _challenge("album", "Un album en entier (8 titres)", "square.stack.fill", best_album, 8, "titres"),
        _challenge("blindtest", "3 parties de blind test", "waveform.badge.magnifyingglass", games, 3, "parties"),
        _challenge("streak", "Écoute 7 jours d'affilée", "flame.fill", week.streak_days, 7, "jours"),
    ]

    # Badges : sur tout l'historique.
    plays = await repo.plays_between(user_id, None, None)
    hours = Counter(stats_service.parse_iso(p.played_at).astimezone(tz).hour for p in plays)
    artists = Counter(p.artist.casefold() for p in plays)
    top_artist_plays = artists.most_common(1)[0][1] if artists else 0
    minutes = sum(stats_service.seconds_of(p) for p in plays) // 60
    tiers = [
        ("plays100", "Premiers pas", "100 écoutes", "music.note", len(plays) >= 100),
        ("plays1000", "Mélomane", "1 000 écoutes", "music.note.list", len(plays) >= 1000),
        ("plays10000", "Légende", "10 000 écoutes", "crown.fill", len(plays) >= 10000),
        ("artists50", "Explorateur", "50 artistes différents", "globe.europe.africa.fill", len(artists) >= 50),
        ("artists250", "Encyclopédie", "250 artistes différents", "books.vertical.fill", len(artists) >= 250),
        ("night", "Oiseau de nuit", "100 écoutes entre minuit et 5 h", "moon.stars.fill",
         sum(hours[h] for h in range(0, 5)) >= 100),
        ("morning", "Lève-tôt", "100 écoutes entre 5 h et 8 h", "sunrise.fill", sum(hours[h] for h in range(5, 8)) >= 100),
        ("fan", "Fan absolu", "200 écoutes d'un même artiste", "heart.fill", top_artist_plays >= 200),
        ("hours100", "100 heures", "100 heures de musique", "headphones", minutes >= 6000),
        ("streak30", "Inarrêtable", "30 jours d'écoute d'affilée", "flame.fill", week.streak_days >= 30),
    ]
    badges = [{"id": k, "title": t, "description": d, "icon": i, "earned": e} for k, t, d, i, e in tiers]
    week_end = stats_service.parse_iso(week.end).astimezone(tz) if week.end else now + timedelta(days=7)
    return {
        "week_label": week.label,
        "ends_in_days": max(0, (week_end.date() - now.date()).days),
        "challenges": challenges,
        "badges": badges,
    }
