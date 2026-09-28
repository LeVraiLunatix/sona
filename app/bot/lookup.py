from __future__ import annotations

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


async def get_track(deps: Deps, source: str, source_id: str) -> TrackInfo:
    if source == "deezer":
        return await deps.deezer.get_track(source_id)
    if source == "apple":
        return await deps.apple.get_track(source_id)
    if source == "spotify":
        return await deps.spotify.get_track(source_id)
    if source == "youtube":
        return await youtube.get_video_info(source_id)
    raise UnknownSourceError(source)


async def get_album(deps: Deps, source: str, source_id: str) -> AlbumInfo:
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


async def get_artist(deps: Deps, source: str, source_id: str) -> ArtistInfo:
    if source == "deezer":
        return await deps.deezer.get_artist(source_id)
    if source == "apple":
        return await deps.apple.get_artist(source_id)
    if source == "spotify":
        return await deps.spotify.get_artist(source_id)
    if source == "youtube":
        return await resolver.get_artist_info(source_id)
    raise UnknownSourceError(source)


async def get_artist_top_tracks(deps: Deps, source: str, source_id: str) -> list[TrackInfo]:
    if source == "deezer":
        return await deps.deezer.get_artist_top_tracks(source_id)
    if source == "apple":
        return await deps.apple.get_artist_top_tracks(source_id)
    if source == "spotify":
        return await deps.spotify.get_artist_top_tracks(source_id)
    if source == "youtube":
        return await resolver.get_artist_top_tracks_youtube(source_id)
    raise UnknownSourceError(source)


async def get_artist_albums(
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
