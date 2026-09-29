"""Concerts à venir des artistes qu'on écoute le plus (Bandsintown).

Les dates de chaque artiste sont gardées 12 h en mémoire : l'onglet qui les
affiche peut être rouvert souvent, les dates changent rarement. Le tri par
distance se fait dans l'app, qui connaît la position du téléphone.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx

from app.services import stats as stats_service

logger = logging.getLogger(__name__)

API_URL = "https://rest.bandsintown.com/artists/{name}/events"
CACHE_TTL = 12 * 3600
TOP_ARTISTS = 30
WINDOW_DAYS = 120

_cache: dict[str, tuple[float, list[dict]]] = {}
_client: httpx.AsyncClient | None = None


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=10, headers={"Accept": "application/json"})
    return _client


def reset() -> None:
    _cache.clear()


def _event(artist: str, picture: str | None, d: dict) -> dict | None:
    venue = d.get("venue") or {}
    when = d.get("datetime") or d.get("starts_at")
    if not when:
        return None
    offers = [o.get("url") for o in d.get("offers") or [] if isinstance(o, dict) and o.get("url")]

    def number(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    return {
        "id": str(d.get("id") or f"{artist}-{when}"),
        "artist": artist,
        "artist_picture_url": picture,
        "datetime": when,
        "venue": venue.get("name"),
        "city": venue.get("city"),
        "region": venue.get("region"),
        "country": venue.get("country"),
        "latitude": number(venue.get("latitude")),
        "longitude": number(venue.get("longitude")),
        "url": offers[0] if offers else d.get("url"),
        "lineup": [x for x in d.get("lineup") or [] if isinstance(x, str)],
    }


async def artist_events(app_id: str, artist: str, picture: str | None = None) -> list[dict]:
    key = artist.casefold()
    hit = _cache.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    events: list[dict] = []
    try:
        resp = await _http().get(API_URL.format(name=quote(artist, safe="")), params={"app_id": app_id, "date": "upcoming"})
        data = resp.json() if resp.status_code == 200 else []
        if isinstance(data, list):
            events = [e for e in (_event(artist, picture, d) for d in data if isinstance(d, dict)) if e]
        elif resp.status_code != 200:
            logger.info("Bandsintown %s pour %s : HTTP %s", artist, app_id, resp.status_code)
    except (httpx.HTTPError, ValueError) as exc:
        logger.info("Concerts de %s indisponibles : %s", artist, exc)
    _cache[key] = (time.monotonic() + CACHE_TTL, events)
    return events


async def upcoming_for_user(deps, user_id: int) -> list[dict]:
    since = stats_service.to_utc_iso(datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS))
    plays = await deps.repo.plays_between(user_id, since, None)
    if not plays:
        plays = await deps.repo.plays_recent(user_id, 500)
    artists = stats_service.top_artists(plays, limit=TOP_ARTISTS)
    semaphore = asyncio.Semaphore(4)

    async def one(item) -> list[dict]:
        async with semaphore:
            events = await artist_events(deps.settings.bandsintown_app_id, item.name, item.cover_url)
        # Rang d'écoute : l'app peut mettre en avant les artistes favoris.
        rank = artists.index(item) + 1
        return [{**e, "artist_rank": rank} for e in events]

    batches = await asyncio.gather(*(one(a) for a in artists))
    events = [e for batch in batches for e in batch]
    events.sort(key=lambda e: e["datetime"])
    return events
