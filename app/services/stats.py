"""Stats d'écoute, façon Last.fm / Wrapped, recalculées pour n'importe quelle
période à partir de la table `plays`.

Les découpages (jour, heure, semaine) se font dans le fuseau de
l'utilisateur, pas en UTC : une écoute à 0 h 30 à Paris compte pour le bon
jour. D'où un calcul en Python sur les écoutes de la période plutôt qu'en
SQL (SQLite ne connaît pas les fuseaux) — quelques dizaines de milliers de
lignes au pire, largement assez rapide pour un usage personnel.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.db.repository import Play

PERIODS = ("day", "week", "month", "year", "all")
# Durée retenue quand ni le temps réellement écouté ni la durée du titre ne
# sont connus (imports Last.fm) : la moyenne d'un titre pop.
DEFAULT_TRACK_SECONDS = 210
TOP_LIMIT = 25

MONTHS_FR = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)
MONTHS_SHORT_FR = ("janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc.")
WEEKDAYS_FR = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
WEEKDAYS_SHORT_FR = ("Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim")


def to_utc_iso(moment: datetime) -> str:
    """Format unique des horodatages en base : comparables comme chaînes."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def resolve_tz(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "Europe/Paris")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("Europe/Paris")


@dataclass(slots=True)
class Range:
    period: str
    start: datetime | None  # local, inclus ; None = depuis toujours
    end: datetime | None    # local, exclu
    label: str


def period_range(period: str, offset: int, now: datetime) -> Range:
    """Période `period` décalée de `offset` (0 = en cours, -1 = précédente),
    bornes dans le fuseau de `now`."""
    tz = now.tzinfo
    today = now.date()

    def at(d: date) -> datetime:
        return datetime(d.year, d.month, d.day, tzinfo=tz)

    if period == "day":
        d = today + timedelta(days=offset)
        label = "Aujourd'hui" if offset == 0 else "Hier" if offset == -1 else f"{WEEKDAYS_FR[d.weekday()]} {d.day} {MONTHS_FR[d.month - 1]}"
        return Range(period, at(d), at(d + timedelta(days=1)), label.capitalize())
    if period == "week":
        monday = today - timedelta(days=today.weekday()) + timedelta(weeks=offset)
        sunday = monday + timedelta(days=6)
        if offset == 0:
            label = "Cette semaine"
        elif offset == -1:
            label = "La semaine dernière"
        else:
            label = f"Du {monday.day} {MONTHS_SHORT_FR[monday.month - 1]} au {sunday.day} {MONTHS_SHORT_FR[sunday.month - 1]}"
        return Range(period, at(monday), at(monday + timedelta(days=7)), label)
    if period == "month":
        index = today.year * 12 + (today.month - 1) + offset
        year, month = divmod(index, 12)
        first = date(year, month + 1, 1)
        nxt = date(year + (month + 1) // 12, (month + 1) % 12 + 1, 1)
        label = f"{MONTHS_FR[first.month - 1]} {first.year}".capitalize()
        return Range(period, at(first), at(nxt), label)
    if period == "year":
        year = today.year + offset
        return Range(period, at(date(year, 1, 1)), at(date(year + 1, 1, 1)), str(year))
    return Range("all", None, None, "Depuis toujours")


@dataclass(slots=True)
class RankedItem:
    name: str
    subtitle: str | None
    plays: int
    minutes: int
    cover_url: str | None
    source: str | None
    source_id: str | None
    # Photo de l'artiste (vérifiée par son nom, voir services/artist_photos).
    picture_url: str | None = None


@dataclass(slots=True)
class Bucket:
    label: str
    plays: int
    minutes: int


@dataclass(slots=True)
class StatsReport:
    period: str
    offset: int
    label: str
    start: str | None
    end: str | None
    plays: int
    minutes: int
    artists: int
    tracks: int
    albums: int
    previous_plays: int
    top_artists: list[RankedItem] = field(default_factory=list)
    top_tracks: list[RankedItem] = field(default_factory=list)
    top_albums: list[RankedItem] = field(default_factory=list)
    timeline: list[Bucket] = field(default_factory=list)
    hours: list[int] = field(default_factory=list)
    weekdays: list[int] = field(default_factory=list)
    discoveries: list[RankedItem] = field(default_factory=list)
    top_hour: int | None = None
    top_weekday: str | None = None
    streak_days: int = 0
    first_play: str | None = None


def seconds_of(play: Play) -> int:
    if play.listened_seconds:
        return play.listened_seconds
    if play.duration_seconds:
        return play.duration_seconds
    return DEFAULT_TRACK_SECONDS


def _rank(
    plays: list[Play], key, name, subtitle, source_id, limit: int = TOP_LIMIT
) -> list[RankedItem]:
    counts: Counter = Counter()
    seconds: Counter = Counter()
    sample: dict = {}
    covers: dict = {}
    for p in plays:
        k = key(p)
        if k is None:
            continue
        counts[k] += 1
        seconds[k] += seconds_of(p)
        sample[k] = p  # la plus récente (écoutes triées chronologiquement)
        if p.cover_url:
            covers[k] = p.cover_url
    ranked = sorted(counts, key=lambda k: (-counts[k], -seconds[k]))[:limit]
    return [
        RankedItem(
            name=name(sample[k]),
            subtitle=subtitle(sample[k]),
            plays=counts[k],
            minutes=seconds[k] // 60,
            cover_url=covers.get(k),
            source=sample[k].source,
            source_id=source_id(sample[k]),
        )
        for k in ranked
    ]


def top_artists(plays: list[Play], limit: int = TOP_LIMIT) -> list[RankedItem]:
    return _rank(plays, lambda p: p.artist.casefold(), lambda p: p.artist, lambda p: None,
                 lambda p: p.artist_source_id, limit)


def top_tracks(plays: list[Play], limit: int = TOP_LIMIT) -> list[RankedItem]:
    return _rank(plays, lambda p: (p.title.casefold(), p.artist.casefold()), lambda p: p.title,
                 lambda p: p.artist, lambda p: p.source_id, limit)


def top_albums(plays: list[Play], limit: int = TOP_LIMIT) -> list[RankedItem]:
    return _rank(plays, lambda p: (p.album.casefold(), p.artist.casefold()) if p.album else None,
                 lambda p: p.album or "", lambda p: p.artist, lambda p: p.album_source_id, limit)


def _timeline(plays: list[Play], rng: Range, tz, now: datetime) -> list[Bucket]:
    """Courbe de la période : par heure (jour), par jour (semaine, mois), par
    mois (année), par année (depuis toujours)."""
    counts: Counter = Counter()
    seconds: Counter = Counter()

    def add(key, p):
        counts[key] += 1
        seconds[key] += seconds_of(p)

    local = [(parse_iso(p.played_at).astimezone(tz), p) for p in plays]
    if rng.period == "day":
        for moment, p in local:
            add(moment.hour, p)
        keys = [(h, f"{h} h") for h in range(24)]
    elif rng.period in ("week", "month"):
        for moment, p in local:
            add(moment.date(), p)
        day, keys = rng.start.date(), []
        while day < rng.end.date():
            label = WEEKDAYS_SHORT_FR[day.weekday()] if rng.period == "week" else str(day.day)
            keys.append((day, label))
            day += timedelta(days=1)
    elif rng.period == "year":
        for moment, p in local:
            add(moment.month, p)
        keys = [(m, MONTHS_SHORT_FR[m - 1]) for m in range(1, 13)]
    else:
        for moment, p in local:
            add(moment.year, p)
        years = sorted(counts) or [now.year]
        keys = [(y, str(y)) for y in range(years[0], max(years[-1], now.year) + 1)]
    return [Bucket(label, counts[k], seconds[k] // 60) for k, label in keys]


def streak_days(timestamps: list[str], tz, today: date) -> int:
    """Jours consécutifs avec au moins une écoute, jusqu'à aujourd'hui (ou
    hier, pour ne pas casser la série avant la première écoute du jour)."""
    days = {parse_iso(t).astimezone(tz).date() for t in timestamps}
    cursor = today if today in days else today - timedelta(days=1)
    streak = 0
    while cursor in days:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def build_report(
    rng: Range,
    offset: int,
    plays: list[Play],
    previous_plays: int,
    first_by_artist: dict[str, str],
    all_timestamps: list[str],
    now: datetime,
) -> StatsReport:
    tz = now.tzinfo
    hours = [0] * 24
    weekdays = [0] * 7
    for p in plays:
        moment = parse_iso(p.played_at).astimezone(tz)
        hours[moment.hour] += 1
        weekdays[moment.weekday()] += 1

    start_iso = to_utc_iso(rng.start) if rng.start else None
    end_iso = to_utc_iso(rng.end) if rng.end else None
    discovered = []
    if start_iso:
        new_keys = {k for k, first in first_by_artist.items() if first >= start_iso and (not end_iso or first < end_iso)}
        discovered = [a for a in top_artists(plays, limit=500) if a.name.casefold() in new_keys][:15]

    return StatsReport(
        period=rng.period,
        offset=offset,
        label=rng.label,
        start=start_iso,
        end=end_iso,
        plays=len(plays),
        minutes=sum(seconds_of(p) for p in plays) // 60,
        artists=len({p.artist.casefold() for p in plays}),
        tracks=len({(p.title.casefold(), p.artist.casefold()) for p in plays}),
        albums=len({(p.album.casefold(), p.artist.casefold()) for p in plays if p.album}),
        previous_plays=previous_plays,
        top_artists=top_artists(plays),
        top_tracks=top_tracks(plays),
        top_albums=top_albums(plays),
        timeline=_timeline(plays, rng, tz, now),
        hours=hours,
        weekdays=weekdays,
        discoveries=discovered,
        top_hour=max(range(24), key=lambda h: hours[h]) if plays else None,
        top_weekday=WEEKDAYS_FR[max(range(7), key=lambda d: weekdays[d])] if plays else None,
        streak_days=streak_days(all_timestamps, tz, now.date()),
        first_play=all_timestamps[0] if all_timestamps else None,
    )


async def compute(repo, user_id: int, period: str, offset: int, tz_name: str | None, now: datetime | None = None) -> StatsReport:
    tz = resolve_tz(tz_name)
    now = (now or datetime.now(timezone.utc)).astimezone(tz)
    rng = period_range(period, offset, now)
    start = to_utc_iso(rng.start) if rng.start else None
    end = to_utc_iso(rng.end) if rng.end else None
    plays = await repo.plays_between(user_id, start, end)

    previous = 0
    if rng.period != "all":
        prev = period_range(period, offset - 1, now)
        previous = len(await repo.plays_between(user_id, to_utc_iso(prev.start), to_utc_iso(prev.end)))

    first_by_artist = await repo.plays_first_by_artist(user_id)
    timestamps = await repo.plays_days(user_id)
    return build_report(rng, offset, plays, previous, first_by_artist, timestamps, now)

