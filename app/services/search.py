from __future__ import annotations

import logging

from app.bot.deps import Deps
from app.providers.apple import AppleMusicError
from app.providers.base import TrackInfo
from app.providers.deezer import DeezerError
from app.services import query_cache
from app.services.resolver import search_tracks_youtube, search_tracks_youtube_raw

logger = logging.getLogger(__name__)

# iTunes et YouTube Music n'ont pas de décalage de pagination : on ramène un
# lot une fois, et on pagine dedans.
FALLBACK_POOL = 40


class SearchError(Exception):
    """Toutes les sources de recherche sont injoignables."""


def _scoped_query(text: str, artist_scope_name: str | None) -> str:
    return f"{artist_scope_name} {text}".strip() if artist_scope_name else text


async def _search_deezer(
    deps: Deps, cached: query_cache.CachedQuery, index: int, limit: int
) -> tuple[list[TrackInfo], int]:
    if cached.artist_scope_name:
        return await deps.deezer.search_tracks_by_artist(
            cached.artist_scope_name, cached.text, index=index, limit=limit
        )
    return await deps.deezer.search_tracks(cached.text, index=index, limit=limit)


async def _search_apple(
    deps: Deps, cached: query_cache.CachedQuery, index: int, limit: int
) -> tuple[list[TrackInfo], int]:
    pool = await deps.apple.search_tracks(
        _scoped_query(cached.text, cached.artist_scope_name), limit=FALLBACK_POOL
    )
    return pool[index : index + limit], len(pool)


async def _search_youtube(
    deps: Deps, cached: query_cache.CachedQuery, index: int, limit: int
) -> tuple[list[TrackInfo], int]:
    pool = await search_tracks_youtube(
        _scoped_query(cached.text, cached.artist_scope_name), limit=FALLBACK_POOL
    )
    return pool[index : index + limit], len(pool)


async def _search_youtube_raw(
    deps: Deps, cached: query_cache.CachedQuery, index: int, limit: int
) -> tuple[list[TrackInfo], int]:
    pool = await search_tracks_youtube_raw(
        _scoped_query(cached.text, cached.artist_scope_name), limit=FALLBACK_POOL
    )
    return pool[index : index + limit], len(pool)


_PROVIDERS = {
    "deezer": (_search_deezer, DeezerError),
    "apple": (_search_apple, AppleMusicError),
    "youtube": (_search_youtube, Exception),
    # Dernier recours : le moteur YouTube général (pas YouTube Music) tolère
    # mieux les requêtes tronquées/mal orthographiées ("eiak", "iak" →
    # "Ziak") — mais avec des métadonnées plus pauvres, d'où l'ordre.
    "youtube_raw": (_search_youtube_raw, Exception),
}
_ORDER = ("deezer", "apple", "youtube", "youtube_raw")


async def search_tracks(
    deps: Deps, cached: query_cache.CachedQuery, index: int = 0, limit: int = 5
) -> tuple[list[TrackInfo], int]:
    """Recherche un morceau en cascade sur Deezer, iTunes puis YouTube Music.

    Deezer reste la source principale (métadonnées riches, vraie pagination),
    mais elle est parfois injoignable ou ne connaît pas un titre : plutôt que
    d'annoncer « aucun résultat », on interroge les autres catalogues. La
    source retenue est mémorisée dans la recherche en cache pour que les pages
    suivantes restent cohérentes.

    Lève `SearchError` si aucune source n'a pu répondre (panne réseau) — c'est
    différent d'une recherche qui aboutit à zéro résultat.
    """
    order = (cached.provider,) if cached.provider else _ORDER
    failures = 0

    for name in order:
        search_fn, error_type = _PROVIDERS[name]
        try:
            tracks, total = await search_fn(deps, cached, index, limit)
        except error_type as exc:
            failures += 1
            logger.warning("Recherche %s indisponible pour %r: %s", name, cached.text, exc)
            continue
        if tracks:
            if cached.provider is None:
                cached.provider = name
                if name != "deezer":
                    logger.info("Recherche %r servie par %s", cached.text, name)
            return tracks, total
        if cached.provider == name:
            # Page au-delà des résultats disponibles chez la source retenue.
            return [], total

    if failures == len(order):
        raise SearchError("Aucune source de recherche disponible.")
    return [], 0
