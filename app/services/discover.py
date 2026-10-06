"""Découverte : « Si tu aimes ce titre » (une radio faite uniquement
d'artistes que tu n'as jamais écoutés) et le mix « selon la météo »
(l'humeur du moment : pluie, soleil, nuit, soirée…)."""

from __future__ import annotations

import asyncio
import random
from datetime import datetime

import httpx

from app.bot import lookup
from app.providers.base import TrackInfo
from app.services import stats as stats_service

# ── Radio « artistes inconnus » ─────────────────────────────────────────────


async def unknown_artists_radio(deps, user_id: int, source: str, artist_id: str, artist_name: str = "",
                                per_artist: int = 3, max_artists: int = 10) -> list[TrackInfo]:
    """Les artistes proches de celui du titre, sauf ceux déjà écoutés : leurs
    titres phares, mélangés artiste par artiste."""
    related = await lookup.get_related_artists(deps, source, artist_id)
    plays = await deps.repo.plays_between(user_id, None, None)
    known = {p.artist.casefold() for p in plays} | {artist_name.casefold()}
    fresh = [a for a in related if a.name.casefold() not in known][:max_artists]
    if not fresh:
        return []

    async def top(artist):
        try:
            return (await lookup.get_artist_top_tracks(deps, artist.source, artist.source_id))[:per_artist]
        except Exception:  # noqa: BLE001 — un artiste en panne n'arrête pas la radio
            return []

    batches = await asyncio.gather(*(top(a) for a in fresh))
    out: list[TrackInfo] = []
    for i in range(per_artist):
        for batch in batches:
            if i < len(batch):
                out.append(batch[i])
    return out


# ── Mix « selon la météo » ──────────────────────────────────────────────────

# Radios Deezer (voir routers/browse.py) par humeur.
MOODS = {
    "pluie": ("Jour de pluie", "🌧️", "Du doux pour regarder la pluie tomber", ["38435", "39051", "39031"]),
    "neige": ("Il neige", "❄️", "Au chaud, avec un plaid", ["39031", "38435", "39101"]),
    "nuit": ("Nuit", "🌙", "Pour les heures calmes", ["42924", "36891", "38225"]),
    "soiree": ("Soirée", "🎉", "Vendredi, samedi : on monte le son", ["37151", "30951", "648"]),
    "matin": ("Bon réveil", "☀️", "De quoi bien commencer la journée", ["31061", "39604", "38435"]),
    "soleil": ("Grand soleil", "😎", "Ça sent l'été", ["30941", "36791", "37151"]),
    "gris": ("Ciel gris", "☁️", "Indé et mélancolie légère", ["30771", "30781", "39051"]),
    "journee": ("Pour ta journée", "🎧", "Ce qui donne de l'élan", ["44784", "37151", "31061"]),
}


def weather_label(code: int | None) -> str | None:
    if code is None:
        return None
    if code in (0, 1):
        return "Ensoleillé"
    if code == 2:
        return "Éclaircies"
    if code in (3, 45, 48):
        return "Couvert"
    if 51 <= code <= 67 or 80 <= code <= 82:
        return "Pluie"
    if 71 <= code <= 77 or code in (85, 86):
        return "Neige"
    if code >= 95:
        return "Orage"
    return None


def pick_mood(now: datetime, code: int | None = None, temperature: float | None = None, is_day: bool = True) -> str:
    """L'humeur du moment, d'après l'heure, le jour et (si connue) la météo."""
    hour, weekday = now.hour, now.weekday()
    if hour >= 23 or hour < 5:
        return "nuit"
    if weekday in (4, 5) and hour >= 19:
        return "soiree"
    if code is not None:
        if 51 <= code <= 67 or 80 <= code <= 82 or code >= 95:
            return "pluie"
        if 71 <= code <= 77 or code in (85, 86):
            return "neige"
        if code in (0, 1, 2) and is_day and (temperature or 0) >= 20:
            return "soleil"
        if code in (3, 45, 48):
            return "gris"
    if 5 <= hour < 10:
        return "matin"
    return "journee"


async def fetch_weather(lat: float, lon: float) -> dict | None:
    """Météo du moment (Open-Meteo : gratuit, sans clé ; la position n'est pas gardée)."""
    url = "https://api.open-meteo.com/v1/forecast"
    params = {"latitude": round(lat, 2), "longitude": round(lon, 2), "current": "temperature_2m,weather_code,is_day"}
    try:
        async with httpx.AsyncClient(timeout=4) as http:
            res = await http.get(url, params=params)
            res.raise_for_status()
            cur = res.json().get("current") or {}
    except (httpx.HTTPError, ValueError):
        return None
    code = cur.get("weather_code")
    return {"code": code, "temperature": cur.get("temperature_2m"), "is_day": bool(cur.get("is_day", 1)),
            "label": weather_label(code)}


async def mood_mix(deps, tz_name: str | None, lat: float | None = None, lon: float | None = None,
                   now: datetime | None = None, weather: dict | None = None, limit: int = 30) -> dict:
    tz = stats_service.resolve_tz(tz_name)
    now = (now or datetime.now(tz)).astimezone(tz)
    if weather is None and lat is not None and lon is not None:
        weather = await fetch_weather(lat, lon)
    mood = pick_mood(now, weather and weather.get("code"), weather and weather.get("temperature"),
                     weather.get("is_day", True) if weather else True)
    title, emoji, subtitle, radios = MOODS[mood]
    batches = await asyncio.gather(*(deps.deezer.get_radio_tracks(r) for r in radios[:2]), return_exceptions=True)
    lists = [b for b in batches if isinstance(b, list)]
    tracks: list[TrackInfo] = []
    seen = set()
    for i in range(max((len(b) for b in lists), default=0)):
        for b in lists:
            if i < len(b) and (b[i].source, b[i].source_id) not in seen:
                seen.add((b[i].source, b[i].source_id))
                tracks.append(b[i])
    random.Random(f"{now.date()}-{now.hour}").shuffle(tracks)
    return {"mood": mood, "title": title, "emoji": emoji, "subtitle": subtitle, "weather": weather,
            "tracks": tracks[:limit]}
