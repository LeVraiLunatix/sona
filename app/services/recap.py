"""Récap façon Wrapped d'une période (mois par défaut), présenté en story
dans l'app : les chiffres des stats, plus ce qui fait une bonne story —
ta « personnalité » d'écoute, ton plus gros jour, ton premier son, ta place
parmi tes amis.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from app.db.repository import Play
from app.services import stats as stats_service
from app.services.stats import MONTHS_FR, WEEKDAYS_FR, parse_iso, seconds_of

NIGHT_HOURS = {22, 23, 0, 1, 2, 3, 4}
MORNING_HOURS = {5, 6, 7, 8, 9}


def available_message(period: str) -> str:
    """Quand sort le récap de la période en cours."""
    if period == "week":
        return "Le récap de la semaine sera disponible lundi, une fois la semaine terminée."
    if period == "year":
        return "Le récap de l'année sera disponible le 1er janvier."
    today = datetime.now(timezone.utc).date()
    following = MONTHS_FR[today.month % 12]
    return f"Le récap du mois sera disponible le 1er {following}, une fois le mois terminé."


def personality(plays: list[Play], new_artists: int, tz) -> dict:
    """Un profil parmi quelques-uns, d'après la façon d'écouter."""
    total = len(plays)
    artists = Counter(p.artist.casefold() for p in plays)
    tracks = Counter((p.title.casefold(), p.artist.casefold()) for p in plays)
    hours = Counter(parse_iso(p.played_at).astimezone(tz).hour for p in plays)
    top_artist_share = artists.most_common(1)[0][1] / total
    top_track_plays = tracks.most_common(1)[0][1]
    variety = len(artists) / total
    night = sum(hours[h] for h in NIGHT_HOURS) / total
    morning = sum(hours[h] for h in MORNING_HOURS) / total
    discovery = new_artists / max(1, len(artists))

    traits = {
        "fidélité": round(top_artist_share, 2),
        "variété": round(variety, 2),
        "découverte": round(discovery, 2),
        "nuit": round(night, 2),
    }
    if top_artist_share >= 0.3:
        profile = ("Le fan absolu", "💘", "Un artiste a régné sur ta période. Tu ne fais pas les choses à moitié.")
    elif top_track_plays >= 25:
        profile = ("L'obsessionnel", "🔁", f"Un titre écouté {top_track_plays} fois. Quand tu aimes, tu repasses en boucle.")
    elif night >= 0.35:
        profile = ("L'oiseau de nuit", "🌙", "Ta musique vit surtout après 22 h.")
    elif discovery >= 0.35 and len(artists) >= 10:
        profile = ("L'explorateur", "🧭", "Toujours à la recherche de nouveaux sons : beaucoup d'artistes découverts.")
    elif variety >= 0.4:
        profile = ("Le touche-à-tout", "🎨", "Beaucoup d'artistes différents, jamais deux fois la même ambiance.")
    elif morning >= 0.3:
        profile = ("Le lève-tôt", "🌅", "La musique t'accompagne dès le matin.")
    else:
        profile = ("Le fidèle", "🎧", "Tes classiques, tes habitudes, ta bande-son.")
    title, emoji, description = profile
    return {"title": title, "emoji": emoji, "description": description, "traits": traits}


def biggest_day(plays: list[Play], tz) -> dict | None:
    minutes: Counter = Counter()
    for p in plays:
        minutes[parse_iso(p.played_at).astimezone(tz).date()] += seconds_of(p)
    if not minutes:
        return None
    day, seconds = minutes.most_common(1)[0]
    label = f"{WEEKDAYS_FR[day.weekday()]} {day.day} {MONTHS_FR[day.month - 1]}"
    return {"label": label, "minutes": seconds // 60}


def _track_out(p: Play) -> dict:
    return {
        "source": p.source or "deezer", "source_id": p.source_id or "", "title": p.title, "artist": p.artist,
        "album": p.album, "cover_url": p.cover_url, "duration_seconds": p.duration_seconds,
        "artist_source_id": p.artist_source_id, "album_source_id": p.album_source_id,
    }


def most_played_play(plays: list[Play]) -> Play | None:
    """L'écoute la plus récente du titre le plus écouté (de quoi le relancer)."""
    if not plays:
        return None
    tracks = Counter((p.title.casefold(), p.artist.casefold()) for p in plays)
    best = tracks.most_common(1)[0][0]
    candidates = [p for p in plays if (p.title.casefold(), p.artist.casefold()) == best]
    return next((p for p in reversed(candidates) if p.source_id), candidates[-1])


async def compute(deps, user_id: int, period: str, offset: int, tz_name: str | None, now: datetime | None = None) -> dict:
    report = await stats_service.compute(deps.repo, user_id, period, offset, tz_name, now)
    tz = stats_service.resolve_tz(tz_name)
    plays = await deps.repo.plays_between(user_id, report.start, report.end)

    previous_minutes = 0
    if period != "all":
        moment = (now or datetime.now(timezone.utc)).astimezone(tz)
        prev = stats_service.period_range(period, offset - 1, moment)
        previous = await deps.repo.plays_between(
            user_id, stats_service.to_utc_iso(prev.start), stats_service.to_utc_iso(prev.end)
        )
        previous_minutes = sum(seconds_of(p) for p in previous) // 60

    # Classement parmi les amis qui partagent leur écoute, au temps d'écoute.
    board = []
    for account in await deps.repo.list_accounts():
        if account.status != "approved" or (account.user_id != user_id and not account.share_listening):
            continue
        theirs = await deps.repo.plays_between(account.user_id, report.start, report.end)
        board.append((account.user_id, sum(seconds_of(p) for p in theirs) // 60))
    if all(uid != user_id for uid, _ in board):
        board.append((user_id, report.minutes))
    board.sort(key=lambda row: -row[1])
    rank = next(i for i, (uid, _) in enumerate(board) if uid == user_id) + 1

    first = plays[0] if plays else None
    favourite = most_played_play(plays)
    return {
        "period": report.period,
        "offset": report.offset,
        "label": report.label,
        "plays": report.plays,
        "minutes": report.minutes,
        "previous_minutes": previous_minutes,
        "artists": report.artists,
        "tracks": report.tracks,
        "top_artists": report.top_artists[:5],
        "top_tracks": report.top_tracks[:5],
        "top_albums": report.top_albums[:3],
        "discoveries": report.discoveries[:5],
        "discovered_count": len(report.discoveries),
        "top_hour": report.top_hour,
        "top_weekday": report.top_weekday,
        "streak_days": report.streak_days,
        "biggest_day": biggest_day(plays, tz),
        "first_track": _track_out(first) if first else None,
        "favourite_track": _track_out(favourite) if favourite else None,
        "personality": personality(plays, len(report.discoveries), tz) if plays else None,
        "friends_rank": {"rank": rank, "total": len(board)} if len(board) > 1 else None,
    }
