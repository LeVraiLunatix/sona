"""« Tout écouter » : boucle d'envoi partagée par l'album et l'artiste.

Le bouton n'existait que sur l'écran Album. La boucle (antispam, avancement,
comptage des échecs, message final) est maintenant dans `play_all_tracks`, et
l'écran des titres populaires s'en sert aussi.
"""

import asyncio
from types import SimpleNamespace

import pytest

from app.bot import keyboards, lookup, navigation
from app.bot.callbacks import ArtistCB
from app.bot.handlers import album, artist, track
from app.db.repository import UserSettings
from app.providers.base import AlbumInfo, ArtistInfo, TrackInfo
from app.services import antispam

USER = 7


def make_track(source_id, title):
    return TrackInfo(
        source="deezer",
        source_id=source_id,
        title=title,
        artist="PNL",
        album="Deux frères",
        year="2019",
        duration_seconds=200,
        cover_url=None,
    )


TRACKS = [make_track("1", "Au DD"), make_track("2", "Blanka"), make_track("3", "Déconnecté")]
ARTIST = ArtistInfo(source="deezer", source_id="42", name="PNL", picture_url=None)


def fake_callback(data="artist:playall:deezer:42"):
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


def fake_deps():
    sent = []

    async def send_message(chat_id, text, **_kwargs):
        sent.append(text)

    async def get_settings(_user_id):
        return UserSettings("best", "auto", notifications=True)

    deps = SimpleNamespace(
        bot=SimpleNamespace(send_message=send_message),
        repo=SimpleNamespace(get_settings=get_settings),
    )
    return deps, sent


@pytest.fixture
def envoi(monkeypatch):
    """Remplace l'envoi audio et l'affichage par des enregistreurs."""
    journal = []

    async def deliver(deps, chat_id, t, settings):
        journal.append(("son", t.source_id))
        return None

    async def show_status(deps, user_id, text):
        journal.append(("état", text))

    async def rerender(deps, user_id):
        journal.append(("rendu", None))

    monkeypatch.setattr(track, "deliver_track_audio", deliver)
    monkeypatch.setattr(navigation, "show_status", show_status)
    monkeypatch.setattr(navigation, "rerender", rerender)
    monkeypatch.setattr(navigation, "adopt_message", lambda *args, **kwargs: None)
    return journal


def test_every_track_is_sent_in_order_with_its_progress(envoi):
    deps, sent = fake_deps()

    failed = asyncio.run(track.play_all_tracks(deps, USER, USER, TRACKS))

    assert failed == 0
    assert envoi == [
        ("état", "Envoi 1/3…"),
        ("son", "1"),
        ("état", "Envoi 2/3…"),
        ("son", "2"),
        ("état", "Envoi 3/3…"),
        ("son", "3"),
        ("rendu", None),
    ]
    assert sent == []


def test_a_failure_does_not_stop_the_others_and_is_counted(monkeypatch, envoi):
    deps, sent = fake_deps()

    async def deliver(deps_, chat_id, t, settings):
        envoi.append(("son", t.source_id))
        return "Le téléchargement de ce morceau a échoué." if t.source_id == "2" else None

    monkeypatch.setattr(track, "deliver_track_audio", deliver)

    failed = asyncio.run(track.play_all_tracks(deps, USER, USER, TRACKS))

    assert failed == 1
    assert [call for call in envoi if call[0] == "son"] == [("son", "1"), ("son", "2"), ("son", "3")]
    # Message à part : après plusieurs minutes, la requête callback est expirée.
    assert sent == ["1 morceau(x) sur 3 n'ont pas pu être envoyés."]


def test_an_unexpected_error_is_counted_too(monkeypatch, envoi):
    deps, sent = fake_deps()

    async def deliver(deps_, chat_id, t, settings):
        raise RuntimeError("Telegram indisponible")

    monkeypatch.setattr(track, "deliver_track_audio", deliver)

    assert asyncio.run(track.play_all_tracks(deps, USER, USER, TRACKS)) == 3
    assert sent == ["3 morceau(x) sur 3 n'ont pas pu être envoyés."]
    # L'écran est redessiné quoi qu'il arrive : sinon il reste sur « Envoi 3/3… ».
    assert ("rendu", None) in envoi


def test_a_track_already_being_sent_is_skipped(envoi):
    """Double appui sur « Tout écouter » : le morceau en cours ne part pas deux fois."""
    deps, _sent = fake_deps()
    antispam.try_acquire(USER, "deezer:2")
    try:
        asyncio.run(track.play_all_tracks(deps, USER, USER, TRACKS))
    finally:
        antispam.release(USER, "deezer:2")

    assert [call for call in envoi if call[0] == "son"] == [("son", "1"), ("son", "3")]


def test_the_lock_is_released_after_the_run(envoi):
    deps, _sent = fake_deps()
    asyncio.run(track.play_all_tracks(deps, USER, USER, TRACKS[:1]))
    assert antispam.try_acquire(USER, "deezer:1")
    antispam.release(USER, "deezer:1")


# -- Écran des titres populaires --------------------------------------


def test_the_top_tracks_screen_offers_to_play_them_all():
    markup = keyboards.artist_top_tracks_keyboard(ARTIST, TRACKS)
    boutons = [b for row in markup.inline_keyboard for b in row]
    tout = [b for b in boutons if b.text == "Tout écouter"]
    assert len(tout) == 1
    assert tout[0].callback_data == ArtistCB(action="playall", source="deezer", id="42").pack()
    assert len(tout[0].callback_data.encode()) <= 64


def test_no_play_all_button_without_a_single_track():
    markup = keyboards.artist_top_tracks_keyboard(ARTIST, [])
    boutons = [b for row in markup.inline_keyboard for b in row]
    assert not [b for b in boutons if b.text == "Tout écouter"]


def test_playing_all_the_top_tracks_sends_them(monkeypatch, envoi):
    deps, _sent = fake_deps()

    async def get_top(deps_, source, source_id):
        assert (source, source_id) == ("deezer", "42")
        return TRACKS

    monkeypatch.setattr(lookup, "get_artist_top_tracks", get_top)
    callback, answers = fake_callback()

    asyncio.run(artist.on_artist_playall(callback, ArtistCB(action="playall", source="deezer", id="42"), deps))

    assert [call for call in envoi if call[0] == "son"] == [("son", "1"), ("son", "2"), ("son", "3")]
    assert answers == [(None, False)]


def test_an_artist_without_top_tracks_says_so(monkeypatch, envoi):
    deps, _sent = fake_deps()

    async def get_top(deps_, source, source_id):
        return []

    monkeypatch.setattr(lookup, "get_artist_top_tracks", get_top)
    callback, answers = fake_callback()

    asyncio.run(artist.on_artist_playall(callback, ArtistCB(action="playall", source="deezer", id="42"), deps))

    # L'alerte doit partir avant tout `answer()` vide, sinon Telegram l'ignore.
    assert answers == [("Aucun titre à écouter.", True)]
    assert not [call for call in envoi if call[0] == "son"]


def test_the_album_button_still_goes_through_the_shared_loop(monkeypatch, envoi):
    deps, _sent = fake_deps()

    async def get_album(deps_, source, source_id):
        return AlbumInfo(
            source="deezer",
            source_id="99",
            title="Deux frères",
            artist="PNL",
            artist_source_id="42",
            year="2019",
            cover_url=None,
            track_count=3,
            duration_seconds=600,
            tracks=TRACKS,
        )

    monkeypatch.setattr(lookup, "get_album", get_album)
    callback, answers = fake_callback(data="album:playall:deezer:99:1")

    asyncio.run(album.on_album_playall(callback, album.AlbumCB(action="playall", source="deezer", id="99"), deps))

    assert [call for call in envoi if call[0] == "son"] == [("son", "1"), ("son", "2"), ("son", "3")]
    assert answers == [(None, False)]
