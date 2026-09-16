"""Playlists Deezer : écran au gabarit Album, identifiants bien séparés.

Un lien de playlist Deezer était reconnu par `link_detect` mais refusé par
`links.py`. Et il ne pouvait pas passer par l'écran Album : chez Deezer,
`/album/908622995` et `/playlist/908622995` sont deux contenus sans rapport.
"""

import asyncio
from types import SimpleNamespace

import pytest

from app.bot import errors, keyboards, lookup, navigation
from app.bot.callbacks import AlbumCB, PlaylistCB
from app.bot.handlers import links, playlist
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


@pytest.fixture
def ecrans(monkeypatch):
    """Navigation neutralisée : on note les écrans demandés."""
    vus = []

    async def goto(deps, user_id, chat_id, screen, **_kwargs):
        vus.append(screen)

    async def replace_top(deps, user_id, screen):
        vus.append(screen)

    monkeypatch.setattr(navigation, "goto", goto)
    monkeypatch.setattr(navigation, "replace_top", replace_top)
    monkeypatch.setattr(navigation, "adopt_message", lambda *args, **kwargs: None)
    return vus


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


def test_a_playlist_button_is_not_an_album_button():
    """Même numéro, deux contenus sans rapport : les callbacks ne doivent pas
    se confondre."""
    playlist_cb = PlaylistCB(action="view", source="deezer", id="908622995").pack()
    album_cb = AlbumCB(action="view", source="deezer", id="908622995").pack()

    assert playlist_cb != album_cb
    assert PlaylistCB.unpack(playlist_cb).id == "908622995"
    with pytest.raises(ValueError):
        AlbumCB.unpack(playlist_cb)
    assert len(playlist_cb.encode()) <= 64


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


def test_the_screen_paginates_and_offers_to_play_everything(monkeypatch):
    rendu = {}
    tracks = [make_track(i) for i in range(1, 13)]

    async def get_playlist(deps, source, source_id):
        return make_playlist(tracks)

    async def show_text(bot, target, text, markup):
        rendu["text"], rendu["markup"] = text, markup
        return target

    monkeypatch.setattr(lookup, "get_playlist", get_playlist)
    monkeypatch.setattr(playlist, "show_text", show_text)

    asyncio.run(
        playlist.render_playlist(
            SimpleNamespace(bot=None), None, USER, {"source": "deezer", "id": "908622995", "page": 2}
        )
    )

    assert "Playlist de Lunatix" in rendu["text"]
    assert "12 titres" in rendu["text"]
    # Page 2 : les titres 6 à 10, numérotés dans la playlist entière.
    assert "6. Titre 6 — Artiste 6" in rendu["text"]
    assert "Titre 1 " not in rendu["text"]

    boutons = [b for row in rendu["markup"].inline_keyboard for b in row]
    assert [b.text for b in boutons if b.text == "2/3"] == ["2/3"]
    tout = [b for b in boutons if b.text == "Tout écouter"]
    assert tout[0].callback_data == PlaylistCB(action="playall", source="deezer", id="908622995").pack()
    # Les pages se suivent avec le callback de playlist, jamais celui d'album.
    suivante = [b for b in boutons if b.text == "→"][0]
    assert PlaylistCB.unpack(suivante.callback_data).page == 3


def test_no_play_all_button_on_an_empty_playlist():
    markup = keyboards.playlist_keyboard(make_playlist([]), 1, 1, [])
    boutons = [b for row in markup.inline_keyboard for b in row]
    assert not [b for b in boutons if b.text == "Tout écouter"]


def test_playing_everything_sends_the_whole_playlist(monkeypatch, ecrans):
    tracks = [make_track(1), make_track(2)]
    envoyes = []

    async def get_playlist(deps, source, source_id):
        return make_playlist(tracks)

    async def play_all_tracks(deps, user_id, chat_id, liste):
        envoyes.extend(t.source_id for t in liste)
        return 0

    monkeypatch.setattr(lookup, "get_playlist", get_playlist)
    monkeypatch.setattr(playlist, "play_all_tracks", play_all_tracks)
    callback, answers = fake_callback("pl:playall:deezer:908622995:1")

    asyncio.run(
        playlist.on_playlist_playall(
            callback, PlaylistCB(action="playall", source="deezer", id="908622995"), SimpleNamespace()
        )
    )

    assert envoyes == ["1", "2"]
    assert answers == [(None, False)]


def test_an_empty_playlist_says_so(monkeypatch, ecrans):
    async def get_playlist(deps, source, source_id):
        return make_playlist([])

    monkeypatch.setattr(lookup, "get_playlist", get_playlist)
    callback, answers = fake_callback("pl:playall:deezer:908622995:1")

    asyncio.run(
        playlist.on_playlist_playall(
            callback, PlaylistCB(action="playall", source="deezer", id="908622995"), SimpleNamespace()
        )
    )

    assert answers == [("Aucun morceau à écouter.", True)]


# -- Lien collé ---------------------------------------------------------


def test_a_pasted_deezer_playlist_opens_the_playlist_screen(ecrans):
    message = SimpleNamespace(from_user=SimpleNamespace(id=USER), chat=SimpleNamespace(id=USER))
    lien = SimpleNamespace(source="deezer", kind="playlist", ref="908622995")

    asyncio.run(links._handle_detected_link(SimpleNamespace(), message, lien))

    assert ecrans[-1].kind == "playlist"
    assert ecrans[-1].params == {"source": "deezer", "id": "908622995", "page": 1}


def test_a_youtube_playlist_still_works(ecrans):
    message = SimpleNamespace(from_user=SimpleNamespace(id=USER), chat=SimpleNamespace(id=USER))
    lien = SimpleNamespace(source="youtube", kind="playlist", ref="PLabc")

    asyncio.run(links._handle_detected_link(SimpleNamespace(), message, lien))

    assert ecrans[-1].kind == "playlist"
    assert ecrans[-1].params == {"source": "youtube", "id": "PLabc", "page": 1}


def test_a_spotify_playlist_is_refused_with_a_clear_message(monkeypatch, ecrans):
    """« Lien non reconnu » laisserait croire à un lien cassé."""
    affiche = {}

    async def show_text(bot, target, text, markup):
        affiche["text"] = text
        return target

    monkeypatch.setattr(links, "show_text", show_text)
    monkeypatch.setattr(navigation, "current_target", lambda user_id: None)
    monkeypatch.setattr(navigation, "set_target", lambda user_id, target: None)
    message = SimpleNamespace(from_user=SimpleNamespace(id=USER), chat=SimpleNamespace(id=USER))
    lien = SimpleNamespace(source="spotify", kind="playlist", ref="37i9dQ")

    asyncio.run(links._handle_detected_link(SimpleNamespace(bot=None), message, lien))

    assert affiche["text"] == errors.PLAYLIST_UNSUPPORTED
    assert "Spotify" in affiche["text"] and "Apple Music" in affiche["text"]


def test_an_apple_playlist_is_refused_too(monkeypatch, ecrans):
    affiche = {}

    async def show_text(bot, target, text, markup):
        affiche["text"] = text
        return target

    monkeypatch.setattr(links, "show_text", show_text)
    monkeypatch.setattr(navigation, "current_target", lambda user_id: None)
    monkeypatch.setattr(navigation, "set_target", lambda user_id, target: None)
    message = SimpleNamespace(from_user=SimpleNamespace(id=USER), chat=SimpleNamespace(id=USER))
    lien = SimpleNamespace(source="apple", kind="playlist", ref="pl.123")

    asyncio.run(links._handle_detected_link(SimpleNamespace(bot=None), message, lien))

    assert affiche["text"] == errors.PLAYLIST_UNSUPPORTED
