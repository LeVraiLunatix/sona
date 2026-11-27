"""Radios construites sur de vraies playlists, plutôt que sur la seule station Deezer.

Pour chaque radio : les playlists des éditeurs Deezer du thème, la station
Deezer, et le classement Apple Music du genre quand il existe. Un titre pèse
d'autant plus que plusieurs sources le retiennent ; les titres joués sont ceux
de Deezer (Apple ne sert qu'à confirmer). Le réservoir est gardé 6 h, chaque
appel en tire une sélection différente.

Spotify n'y est pas : chercher ses playlists demande une application dont le
propriétaire paie Premium.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import time
import unicodedata

import httpx

from app.providers.base import TrackInfo
from app.providers.deezer import DeezerError, _track_from_json

logger = logging.getLogger(__name__)

TTL = 6 * 3600
PLAYLISTS = 6
POOL = 320
CHART_URL = "https://itunes.apple.com/{country}/rss/topsongs/limit=100{genre}/json"

# Radio -> (ce qu'on cherche chez les éditeurs Deezer, classement Apple (pays, genre) ou None).
THEMES: dict[str, tuple[str, tuple[str, int | None] | None]] = {
    "39021": ("rap français", ("fr", 18)), "30991": ("hip hop", ("us", 18)), "31021": ("rap us", ("us", 18)),
    "37101": ("old school hip hop", None), "40622": ("grime", None),
    "37151": ("hits du moment", ("fr", None)), "31061": ("pop", ("fr", 14)), "39604": ("chanson francophone", ("fr", 50000064)),
    "38305": ("80s hits", None), "30771": ("indie", ("fr", 20)), "44784": ("energy", None),
    "30881": ("r&b", ("us", 15)), "30811": ("old school r&b", None), "38445": ("motown", None),
    "30861": ("soul", None), "30831": ("funk", None), "30841": ("disco", None),
    "36891": ("deep house", None), "648": ("edm", ("fr", 7)), "30951": ("dance hits", ("fr", 17)),
    "30851": ("techno", None), "30621": ("electronic", ("fr", 7)), "37635": ("electro swing", None),
    "42182": ("rock", ("fr", 21)), "37765": ("classic rock", None), "30931": ("pop rock", None),
    "37031": ("hard rock", None), "30781": ("alternative", ("fr", 20)), "30901": ("metal", ("fr", 1153)),
    "38435": ("acoustic chill", None), "39051": ("mélancolie", None), "39031": ("cosy", None),
    "38225": ("concentration", None), "42924": ("chill", None), "45104": ("road trip", None),
    "38405": ("nouvelle scène française", None), "38395": ("chanson française", ("fr", 50000064)),
    "42522": ("variété française", ("fr", 50000064)),
    "30941": ("reggaeton", ("fr", 12)), "36791": ("latino", ("fr", 12)), "31091": ("reggae", ("fr", 24)),
    "39101": ("bossa nova", None), "87": ("world music", ("fr", 19)),
    "31031": ("jazz", ("fr", 11)), "31051": ("vocal jazz", None), "30661": ("classical", ("fr", 5)),
    "30701": ("film soundtrack", ("fr", 16)),
}

_pools: dict[str, tuple[float, list[tuple[float, TrackInfo]]]] = {}
_locks: dict[str, asyncio.Lock] = {}


def key(title: str, artist: str) -> str:
    """Le même morceau d'un service à l'autre : sans accents, parenthèses, invités ni ponctuation."""
    def flat(text: str) -> str:
        text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
        text = re.sub(r"[(\[].*?[)\]]|\s(feat|ft)\.? .*$| - .*$", "", text)
        return re.sub(r"[^a-z0-9]", "", text)

    return f"{flat(title)}|{flat(re.split(r',|&| et | x ', artist)[0])}"


def editorial(playlist: dict) -> bool:
    maker = ((playlist.get("user") or {}).get("name") or "").lower()
    return "deezer" in maker and any(word in maker for word in ("edit", "édit")) and (playlist.get("nb_tracks") or 0) >= 20


def merge(sources: list[tuple[float, list[TrackInfo]]], chart: set[str]) -> list[tuple[float, TrackInfo]]:
    """(poids, titres) par source → réservoir noté, du plus plébiscité au moins."""
    scores: dict[str, float] = {}
    tracks: dict[str, TrackInfo] = {}
    for weight, found in sources:
        for k, track in {key(t.title, t.artist): t for t in found}.items():  # une fois par source
            scores[k] = scores.get(k, 0) + weight
            tracks.setdefault(k, track)
    ranked = [(score + (1.5 if k in chart else 0), tracks[k]) for k, score in scores.items()]
    ranked.sort(key=lambda item: -item[0])
    return ranked[:POOL]


def draw(pool: list[tuple[float, TrackInfo]], limit: int, rand: random.Random | None = None) -> list[TrackInfo]:
    """Tirage au sort pondéré par la note : au plus 2 titres par artiste, jamais deux à la suite."""
    rand = rand or random.Random()
    shuffled = sorted(pool, key=lambda item: -(rand.random() ** (1 / item[0] ** 2)))
    picked: list[TrackInfo] = []
    waiting: list[TrackInfo] = []
    seen: dict[str, int] = {}
    for _, track in shuffled:
        who = track.artist_source_id or track.artist
        if seen.get(who, 0) >= 2:
            continue
        seen[who] = seen.get(who, 0) + 1
        if picked and (picked[-1].artist_source_id or picked[-1].artist) == who:
            waiting.append(track)
            continue
        picked.append(track)
        if waiting and (waiting[0].artist_source_id or waiting[0].artist) != who:
            picked.append(waiting.pop(0))
        if len(picked) >= limit:
            break
    return picked[:limit]


async def _chart(chart: tuple[str, int | None] | None) -> set[str]:
    if chart is None:
        return set()
    country, genre = chart
    url = CHART_URL.format(country=country, genre=f"/genre={genre}" if genre else "")
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
            entries = (await client.get(url)).raise_for_status().json()["feed"].get("entry", [])
        return {key(e["im:name"]["label"], e["im:artist"]["label"]) for e in entries}
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        logger.info("Classement Apple indisponible (%s %s) : %s", country, genre, exc)
        return set()


async def _tracks(deps, path: str) -> list[TrackInfo]:
    data = await deps.deezer._get(path, {"limit": 100})
    return [_track_from_json(d) for d in data.get("data", []) if d.get("readable", True)]


async def _build(deps, radio_id: str) -> list[tuple[float, TrackInfo]]:
    query, chart = THEMES[radio_id]
    found = await deps.deezer._get("/search/playlist", {"q": query, "limit": 50})
    chosen = [p["id"] for p in found.get("data", []) if editorial(p)][:PLAYLISTS]
    results = await asyncio.gather(
        *(_tracks(deps, f"/playlist/{pid}/tracks") for pid in chosen),
        _tracks(deps, f"/radio/{radio_id}/tracks"),
        return_exceptions=True,
    )
    *playlists, station = results
    sources = [(1.0, r) for r in playlists if isinstance(r, list)]
    if isinstance(station, list):
        sources.append((0.7, station))
    pool = merge(sources, await _chart(chart))
    logger.info("Radio %s : %d playlists d'éditeurs, %d titres", radio_id, len(chosen), len(pool))
    return pool


async def pool(deps, radio_id: str) -> list[tuple[float, TrackInfo]]:
    """Réservoir noté de la radio ; vide si elle n'a pas de thème ou si Deezer ne répond pas."""
    if radio_id not in THEMES:
        return []
    async with _locks.setdefault(radio_id, asyncio.Lock()):
        hit = _pools.get(radio_id)
        if hit and time.monotonic() - hit[0] < TTL:
            return hit[1]
        try:
            built = await _build(deps, radio_id)
        except DeezerError as exc:
            logger.warning("Radio %s : playlists indisponibles (%s)", radio_id, exc)
            return hit[1] if hit else []
        if built:
            _pools[radio_id] = (time.monotonic(), built)
        return built
