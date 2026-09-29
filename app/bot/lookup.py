from __future__ import annotations

import copy
import random
import time
from collections.abc import Awaitable, Callable

from app.bot.deps import Deps
from app.providers import youtube
from app.providers.apple import AppleMusicClient, AppleMusicError
from app.providers.base import AlbumInfo, ArtistInfo, TrackInfo
from app.providers.deezer import DeezerError
from app.providers.spotify import SpotifyError
from app.providers.youtube import YoutubeError
from app.services import resolver

ProviderErrors = (DeezerError, AppleMusicError, SpotifyError, YoutubeError)


class UnknownSourceError(Exception):
    pass


# Fiches du catalogue (titre, album, artiste...) gardées en mémoire : la
# bibliothèque, l'accueil et les fiches redemandent sans cesse les mêmes, et
# chaque aller-retour vers Deezer coûte sur une petite machine. Les radios ne
# sont pas concernées (un nouveau tirage à chaque appel).
CACHE_TTL = 6 * 3600
CACHE_MAX = 4000
_cache: dict[tuple, tuple[float, object]] = {}


def clear_cache() -> None:
    _cache.clear()


async def _cached(kind: str, source: str, source_id: str, load: Callable[[], Awaitable]):
    key = (kind, source, source_id)
    now = time.monotonic()
    hit = _cache.get(key)
    if hit is not None and hit[0] > now:
        # Copie : un appelant qui complète la fiche (extrait, ISRC...) ne
        # doit pas modifier celle du cache.
        return copy.deepcopy(hit[1])
    value = await load()
    if len(_cache) >= CACHE_MAX:
        for old in sorted(_cache, key=lambda k: _cache[k][0])[: CACHE_MAX // 10]:
            del _cache[old]
    _cache[key] = (now + CACHE_TTL, value)
    return copy.deepcopy(value)


async def _get_track(deps: Deps, source: str, source_id: str) -> TrackInfo:
    if source == "deezer":
        return await deps.deezer.get_track(source_id)
    if source == "apple":
        return await deps.apple.get_track(source_id)
    if source == "spotify":
        return await deps.spotify.get_track(source_id)
    if source == "youtube":
        return await youtube.get_video_info(source_id)
    raise UnknownSourceError(source)


async def _get_album(deps: Deps, source: str, source_id: str) -> AlbumInfo:
    if source == "deezer":
        return await deps.deezer.get_album(source_id)
    if source == "apple":
        return await deps.apple.get_album(source_id)
    if source == "spotify":
        return await deps.spotify.get_album(source_id)
    if source == "youtube":
        return await youtube.get_playlist_info(source_id)
    raise UnknownSourceError(source)


async def get_playlist(deps: Deps, source: str, source_id: str) -> AlbumInfo:
    """Playlist, au même format qu'un album.

    Volontairement séparée de `get_album` : chez Deezer, les numéros de
    playlist et d'album vivent dans deux espaces distincts, et
    `/album/908622995` n'est pas `/playlist/908622995`. Confondre les deux
    ouvrirait un contenu qui n'a rien à voir.
    """
    if source == "deezer":
        return await deps.deezer.get_playlist(source_id)
    if source == "youtube":
        return await youtube.get_playlist_info(source_id)
    raise UnknownSourceError(source)


async def _get_artist(deps: Deps, source: str, source_id: str) -> ArtistInfo:
    if source == "deezer":
        return await deps.deezer.get_artist(source_id)
    if source == "apple":
        return await deps.apple.get_artist(source_id)
    if source == "spotify":
        return await deps.spotify.get_artist(source_id)
    if source == "youtube":
        return await resolver.get_artist_info(source_id)
    raise UnknownSourceError(source)


async def _get_artist_top_tracks(deps: Deps, source: str, source_id: str) -> list[TrackInfo]:
    if source == "deezer":
        return await deps.deezer.get_artist_top_tracks(source_id)
    if source == "apple":
        return await deps.apple.get_artist_top_tracks(source_id)
    if source == "spotify":
        return await deps.spotify.get_artist_top_tracks(source_id)
    if source == "youtube":
        return await resolver.get_artist_top_tracks_youtube(source_id)
    raise UnknownSourceError(source)


async def _get_related_artists(deps: Deps, source: str, source_id: str) -> list[ArtistInfo]:
    """Artistes similaires — seul Deezer expose cette donnée ; les autres
    sources renvoient une liste vide plutôt qu'une erreur (section masquée
    côté app)."""
    if source == "deezer":
        return await deps.deezer.get_related_artists(source_id)
    if source in ("apple", "spotify", "youtube"):
        return []
    raise UnknownSourceError(source)


async def get_artist_radio(deps: Deps, source: str, source_id: str) -> list[TrackInfo]:
    """Station d'un artiste : le vrai « mix » Deezer quand il existe, sinon
    ses titres populaires mélangés."""
    if source == "deezer":
        return await deps.deezer.get_artist_radio(source_id)
    tracks = list(await get_artist_top_tracks(deps, source, source_id))
    random.shuffle(tracks)
    return tracks


async def _get_artist_albums(
    deps: Deps, source: str, source_id: str
) -> tuple[list[AlbumInfo], list[AlbumInfo]]:
    if source == "deezer":
        return await deps.deezer.get_artist_albums(source_id)
    if source == "apple":
        return await deps.apple.get_artist_albums(source_id)
    if source == "spotify":
        return await deps.spotify.get_artist_albums(source_id)
    if source == "youtube":
        # YouTube Music a bien une notion d'album (`get_artist(...)["albums"]`),
        # mais son browseId n'est ni un id de playlist ni compatible avec
        # `youtube.get_playlist_info` (seul chemin actuel de `get_album` pour
        # cette source) : l'exposer ouvrirait un lien qui casse à l'arrivée.
        # Une vraie fiche artiste YouTube sans albums reste plus honnête que
        # des vignettes qui mènent à une erreur.
        return [], []
    raise UnknownSourceError(source)


# -- Versions en cache (voir `_cached`) ------------------------------------


async def get_track(deps: Deps, source: str, source_id: str) -> TrackInfo:
    return await _cached("get_track", source, source_id, lambda: _get_track(deps, source, source_id))


async def get_album(deps: Deps, source: str, source_id: str) -> AlbumInfo:
    return await _cached("get_album", source, source_id, lambda: _get_album(deps, source, source_id))


async def get_artist(deps: Deps, source: str, source_id: str) -> ArtistInfo:
    return await _cached("get_artist", source, source_id, lambda: _get_artist(deps, source, source_id))


async def get_artist_top_tracks(deps: Deps, source: str, source_id: str) -> list[TrackInfo]:
    return await _cached("get_artist_top_tracks", source, source_id, lambda: _get_artist_top_tracks(deps, source, source_id))


async def get_related_artists(deps: Deps, source: str, source_id: str) -> list[ArtistInfo]:
    return await _cached("get_related_artists", source, source_id, lambda: _get_related_artists(deps, source, source_id))


async def get_artist_albums(deps: Deps, source: str, source_id: str) -> tuple[list[AlbumInfo], list[AlbumInfo]]:
    return await _cached("get_artist_albums", source, source_id, lambda: _get_artist_albums(deps, source, source_id))
