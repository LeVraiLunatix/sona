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


# ── Défis entre amis : le classement de la semaine ─────────────────────────

BOARDS = [
    ("minutes", "Le plus de musique", "headphones", "min"),
    ("discoveries", "Le plus de découvertes", "sparkle.magnifyingglass", "artistes"),
    ("artists", "Le plus éclectique", "person.3.fill", "artistes"),
    ("night", "Oiseau de nuit (minuit – 5 h)", "moon.stars.fill", "écoutes"),
]


async def _week_scores(repo, user_id: int, tz_name: str | None, offset: int, now: datetime) -> dict:
    tz = stats_service.resolve_tz(tz_name)
    report = await stats_service.compute(repo, user_id, "week", offset, tz_name, now)
    plays = await repo.plays_between(user_id, report.start, report.end)
    night = sum(1 for p in plays if stats_service.parse_iso(p.played_at).astimezone(tz).hour < 5)
    return {"minutes": report.minutes, "discoveries": len(report.discoveries), "artists": report.artists, "night": night}


async def friends_boards(repo, user_id: int, tz_name: str | None, now: datetime | None = None) -> dict:
    """Classements de la semaine entre amis (comptes qui partagent leur
    écoute), et le champion de la semaine dernière (le plus de musique)."""
    now = now or datetime.now(timezone.utc)
    people = [a for a in await repo.list_accounts()
              if a.status == "approved" and (a.share_listening or a.user_id == user_id)]
    if not any(a.user_id != user_id for a in people):
        return {"boards": [], "champion": None}
    scores = {a.user_id: await _week_scores(repo, a.user_id, tz_name, 0, now) for a in people}
    names = {a.user_id: (a.display_name or a.lastfm_username, a.avatar_url) for a in people}
    boards = []
    for key, title, icon, unit in BOARDS:
        ranking = sorted(people, key=lambda a: (-scores[a.user_id][key], names[a.user_id][0].casefold()))
        boards.append({
            "id": key, "title": title, "icon": icon, "unit": unit,
            "ranking": [{"name": names[a.user_id][0], "avatar_url": names[a.user_id][1], "value": scores[a.user_id][key],
                         "me": a.user_id == user_id} for a in ranking if scores[a.user_id][key] > 0 or a.user_id == user_id][:10],
        })
    last = {a.user_id: (await _week_scores(repo, a.user_id, tz_name, -1, now))["minutes"] for a in people}
    best = max(people, key=lambda a: last[a.user_id])
    champion = {"name": names[best.user_id][0], "avatar_url": names[best.user_id][1], "minutes": last[best.user_id],
                "me": best.user_id == user_id} if last[best.user_id] > 0 else None
    return {"boards": boards, "champion": champion}
