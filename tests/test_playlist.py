"""Playlists Deezer : écran au gabarit Album, identifiants bien séparés.

Un lien de playlist Deezer était reconnu par `link_detect` mais refusé par
`links.py`. Et il ne pouvait pas passer par l'écran Album : chez Deezer,
`/album/908622995` et `/playlist/908622995` sont deux contenus sans rapport.
"""

import asyncio
from types import SimpleNamespace

import pytest

from app.services import lookup
from app.providers import deezer as deezer_provider
from app.providers.base import AlbumInfo, TrackInfo

USER = 7

PLAYLIST_JSON = {
    "id": 908622995,
    "title": "Rap FR",
    "duration": 1800,
    "nb_tracks": 3,
    "picture_medium": "https://e-cdns-images.dzcdn.net/images/playlist/250.jpg",
    "picture_xl": "https://e-cdns-images.dzcdn.net/images/playlist/1000.jpg",
    "creator": {"id": "42", "name": "Lunatix"},
    "tracks": {
        "data": [
            {
                "id": 1,
                "title": "Au DD",
                "duration": 222,
                "preview": "https://cdnt-preview.dzcdn.net/1.mp3",
                "artist": {"id": "7", "name": "PNL"},
                "album": {"id": "9", "title": "Deux frères", "cover_xl": "https://c/xl.jpg"},
            },
            {
                "id": 2,
                "title": "Bande organisée",
                "duration": 300,
                "artist": {"id": "8", "name": "13 Organisé"},
                "album": {"id": "10", "title": "13 Organisé"},
            },
            {
                "id": 3,
                "title": "Djadja",
                "duration": 174,
                "artist": {"id": "11", "name": "Aya Nakamura"},
                "album": {"id": "12", "title": "Nakamura"},
            },
        ]
    },
}


def make_track(index):
    return TrackInfo(
        source="deezer",
        source_id=str(index),
        title=f"Titre {index}",
        artist=f"Artiste {index}",
        album=None,
        year=None,
        duration_seconds=200,
        cover_url=None,
    )


def make_playlist(tracks):
    return AlbumInfo(
        source="deezer",
        source_id="908622995",
        title="Rap FR",
        artist="Lunatix",
        artist_source_id=None,
        year=None,
        cover_url=None,
        track_count=len(tracks),
        duration_seconds=200 * len(tracks),
        tracks=tracks,
    )


def fake_callback(data="pl:view:deezer:908622995:1"):
    answers = []

    async def answer(text=None, show_alert=False):
        answers.append((text, show_alert))

    callback = SimpleNamespace(
        answer=answer,
        data=data,
        from_user=SimpleNamespace(id=USER),
        message=SimpleNamespace(chat=SimpleNamespace(id=USER), photo=None),
    )
    return callback, answers


# -- Provider ---------------------------------------------------------


def test_a_deezer_playlist_reads_like_an_album(monkeypatch):
    async def fake_get(self, path, params=None):
        assert path == "/playlist/908622995"
        return PLAYLIST_JSON

    monkeypatch.setattr(deezer_provider.DeezerClient, "_get", fake_get)
    client = deezer_provider.DeezerClient(client=object())

    pl = asyncio.run(client.get_playlist("908622995"))

    assert (pl.source, pl.source_id, pl.title) == ("deezer", "908622995", "Rap FR")
    # Une playlist n'a pas d'artiste : son créateur tient ce rôle à l'écran.
    assert pl.artist == "Lunatix"
    assert pl.artist_source_id is None
    assert pl.track_count == 3 and pl.duration_seconds == 1800
    assert pl.cover_url.endswith("1000.jpg")
    # Chaque morceau garde son propre artiste et son propre album.
    assert [t.artist for t in pl.tracks] == ["PNL", "13 Organisé", "Aya Nakamura"]
    assert pl.tracks[0].album == "Deux frères"
    assert pl.tracks[0].preview_url == "https://cdnt-preview.dzcdn.net/1.mp3"


# -- Identifiants séparés ---------------------------------------------


def test_lookup_asks_the_playlist_endpoint():
    appels = []

    async def get_playlist(source_id):
        appels.append(source_id)
        return make_playlist([make_track(1)])

    async def get_album(source_id):
        raise AssertionError("une playlist ne doit jamais passer par /album")

    deps = SimpleNamespace(deezer=SimpleNamespace(get_playlist=get_playlist, get_album=get_album))

    asyncio.run(lookup.get_playlist(deps, "deezer", "908622995"))
    assert appels == ["908622995"]


def test_a_spotify_playlist_has_no_endpoint():
    deps = SimpleNamespace()
    with pytest.raises(lookup.UnknownSourceError):
        asyncio.run(lookup.get_playlist(deps, "spotify", "37i9dQ"))


# -- Écran -------------------------------------------------------------


# -- Lien collé ---------------------------------------------------------
