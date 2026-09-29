"""Bon artiste, bonne photo dans les stats et le récap.

Les écoutes gardent l'identifiant d'artiste du titre joué, qui n'est pas
toujours celui de l'artiste affiché : titre venu d'Apple ou de YouTube
(pas de photo), featuring où l'identifiant est celui de l'autre artiste…
La carte « N°1 » montrait alors la pochette d'un autre (Favé à la place de
La Mano 1.9) et ouvrait la mauvaise fiche. Ici, chaque artiste classé est
vérifié par son nom sur Deezer : l'identifiant est gardé s'il correspond,
sinon l'artiste est retrouvé par recherche (homonyme le plus suivi).
"""

from __future__ import annotations

import asyncio
import logging

from app.providers.deezer import DeezerError
from app.services.artist_search import _key, rank_artists

logger = logging.getLogger(__name__)

# nom normalisé → (identifiant Deezer, photo), ou None si introuvable.
_cache: dict[str, tuple[str, str | None] | None] = {}


def reset() -> None:
    """Pour les tests."""
    _cache.clear()


async def _identify(deps, name: str, source: str | None, source_id: str | None) -> tuple[str, str | None] | None:
    wanted = _key(name)
    if wanted in _cache:
        return _cache[wanted]
    found = None
    try:
        if source == "deezer" and source_id:
            artist = await deps.deezer.get_artist(source_id)
            if _key(artist.name) == wanted:
                found = (artist.source_id, artist.picture_url)
        if found is None:
            candidates = rank_artists(name, await deps.deezer.search_artists(name, limit=5))
            exact = next((a for a in candidates if _key(a.name) == wanted), None)
            if exact is not None:
                found = (exact.source_id, exact.picture_url)
    except DeezerError as exc:
        logger.info("Photo de %s introuvable : %s", name, exc)
        return None  # pas mis en cache : on réessaiera
    _cache[wanted] = found
    return found


async def fix(deps, items: list, limit: int = 12) -> None:
    """Corrige sur place les `limit` premiers artistes classés (RankedItem) :
    identifiant Deezer vérifié et photo réelle dans `picture_url`."""
    head = items[:limit]

    async def one(item) -> None:
        found = await _identify(deps, item.name, item.source, item.source_id)
        if found is not None:
            item.source, item.source_id = "deezer", found[0]
            item.picture_url = found[1]

    try:
        await asyncio.wait_for(asyncio.gather(*(one(i) for i in head)), timeout=8)
    except asyncio.TimeoutError:
        logger.info("Photos d'artistes : délai dépassé, le reste viendra au prochain affichage")
