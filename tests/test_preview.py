"""Extrait officiel retrouvé sur Deezer pour les morceaux qui n'en ont pas.

Sans extrait de 30 s, la vérification acoustique est sautée : Sona envoie ce
que le résolveur a choisi, sans preuve que c'est le bon enregistrement. C'est
le cas de tous les liens Spotify (l'oEmbed public ne donne ni durée, ni ISRC,
ni extrait — les identifiants de l'API ne sont pas configurés sur le serveur).
"""

import asyncio
import logging

from app.providers import deezer as deezer_provider
from app.providers import spotify as spotify_provider
from app.providers.base import TrackInfo
from app.providers.deezer import DeezerError
from app.services import preview

PREVIEW = "https://cdnt-preview.dzcdn.net/api/1/1/a/b/c.mp3"


def spotify_track(title="Au DD", artist="PNL", duration=None, isrc=None, preview_url=None):
    """Morceau tel que Sona le connaît en ouvrant un lien Spotify."""
    return TrackInfo(
        source="spotify",
        source_id="0VjIjW4GlUZAMYd2vXMi3b",
        title=title,
        artist=artist,
        album=None,
        year=None,
        duration_seconds=duration,
        cover_url=None,
        preview_url=preview_url,
        isrc=isrc,
    )


def deezer_track(title="Au DD", artist="PNL", duration=222, preview_url=PREVIEW, source_id="783257002"):
    return TrackInfo(
        source="deezer",
        source_id=source_id,
        title=title,
        artist=artist,
        album="Deux frères",
        year="2019",
        duration_seconds=duration,
        cover_url=None,
        preview_url=preview_url,
        isrc="FRX872000123",
    )


class FakeDeezer:
    """Client Deezer réduit à ce que le service appelle, sans réseau."""

    def __init__(self, by_isrc=None, results=(), error=None):
        self.by_isrc = by_isrc
        self.results = list(results)
        self.error = error
        self.isrc_calls = []
        self.queries = []

    async def get_track_by_isrc(self, isrc):
        self.isrc_calls.append(isrc)
        if self.error:
            raise self.error
        return self.by_isrc

    async def search_tracks(self, query, index=0, limit=25):
        self.queries.append((query, limit))
        if self.error:
            raise self.error
        return self.results[:limit], len(self.results)


def complete(track, deezer):
    return asyncio.run(preview.complete_preview(deezer, track))


# -- Ce que les providers rapportent ----------------------------------


def test_the_spotify_api_gives_the_preview_and_the_isrc():
    """Les deux servent à vérifier : l'extrait directement, l'ISRC pour aller
    chercher celui de Deezer quand Spotify n'en sert pas."""
    payload = {
        "id": "0VjIjW4GlUZAMYd2vXMi3b",
        "name": "Au DD",
        "duration_ms": 222000,
        "artists": [{"id": "7", "name": "PNL"}],
        "album": {"id": "9", "name": "Deux frères", "release_date": "2019-04-05", "images": []},
        "preview_url": "https://p.scdn.co/mp3-preview/abc",
        "external_ids": {"isrc": "FRX872000123"},
    }
    track = spotify_provider._track_from_json(payload)
    assert track.preview_url == "https://p.scdn.co/mp3-preview/abc"
    assert track.isrc == "FRX872000123"


def test_a_spotify_track_without_preview_keeps_its_isrc():
    payload = {
        "id": "x",
        "name": "Au DD",
        "artists": [],
        "album": {"id": "9", "name": "", "images": []},
        "preview_url": None,
        "external_ids": {"isrc": "FRX872000123"},
    }
    track = spotify_provider._track_from_json(payload)
    assert track.preview_url is None
    assert track.isrc == "FRX872000123"


def test_deezer_reports_the_isrc_of_a_track():
    track = deezer_provider._track_from_json(
        {"id": 783257002, "title": "Au DD", "preview": PREVIEW, "isrc": "FRX872000123"}
    )
    assert track.isrc == "FRX872000123"


def test_deezer_looks_up_a_recording_by_its_isrc(monkeypatch):
    appels = []

    async def fake_get(self, path, params=None):
        appels.append(path)
        return {"id": 783257002, "title": "Au DD", "preview": PREVIEW, "isrc": "FRX872000123"}

    monkeypatch.setattr(deezer_provider.DeezerClient, "_get", fake_get)
    client = deezer_provider.DeezerClient(client=object())
    found = asyncio.run(client.get_track_by_isrc("FRX872000123"))

    assert appels == ["/track/isrc:FRX872000123"]
    assert found.source_id == "783257002"


def test_an_unknown_isrc_is_not_a_failure(monkeypatch):
    """Deezer répond « no data » : c'est une réponse, pas une panne."""

    async def fake_get(self, path, params=None):
        raise DeezerError("{'code': 800, 'message': 'no data'}")

    monkeypatch.setattr(deezer_provider.DeezerClient, "_get", fake_get)
    client = deezer_provider.DeezerClient(client=object())
    assert asyncio.run(client.get_track_by_isrc("INCONNU")) is None


# -- Complétion de l'extrait -------------------------------------------


def test_the_isrc_brings_back_the_preview_and_the_duration():
    deezer = FakeDeezer(by_isrc=deezer_track())
    track = complete(spotify_track(isrc="FRX872000123"), deezer)

    assert track.preview_url == PREVIEW
    assert track.duration_seconds == 222
    # Le reste du morceau n'est pas touché : c'est la fiche Spotify qui est
    # affichée à l'utilisateur.
    assert (track.source, track.source_id, track.title) == ("spotify", "0VjIjW4GlUZAMYd2vXMi3b", "Au DD")
    assert deezer.isrc_calls == ["FRX872000123"]
    assert deezer.queries == []


def test_without_isrc_the_search_uses_artist_and_title():
    deezer = FakeDeezer(results=[deezer_track()])
    track = complete(spotify_track(), deezer)

    assert deezer.queries == [('artist:"PNL" track:"Au DD"', preview.SEARCH_LIMIT)]
    assert track.preview_url == PREVIEW
    assert track.duration_seconds == 222


def test_another_artist_is_never_taken(caplog):
    """Même titre, autre artiste : comparer contre cet extrait ferait rejeter
    le bon fichier."""
    caplog.set_level(logging.INFO, logger=preview.__name__)
    deezer = FakeDeezer(results=[deezer_track(artist="MC Solaar")])
    track = complete(spotify_track(), deezer)

    assert track.preview_url is None
    assert track.duration_seconds is None
    assert "écarté" in caplog.text


def test_a_remix_is_never_taken():
    deezer = FakeDeezer(results=[deezer_track(title="Au DD (Remix)")])
    assert complete(spotify_track(), deezer).preview_url is None


def test_a_different_title_is_never_taken():
    deezer = FakeDeezer(results=[deezer_track(title="Deux frères")])
    assert complete(spotify_track(), deezer).preview_url is None


def test_a_duration_too_far_off_is_never_taken():
    """Une réédition de trois minutes de plus n'est pas le même enregistrement."""
    deezer = FakeDeezer(by_isrc=deezer_track(duration=400))
    assert complete(spotify_track(duration=222, isrc="FRX872000123"), deezer).preview_url is None


def test_the_first_matching_result_wins():
    deezer = FakeDeezer(
        results=[
            deezer_track(title="Au DD (Instrumental)", source_id="1"),
            deezer_track(source_id="2"),
        ]
    )
    assert complete(spotify_track(), deezer).preview_url == PREVIEW


def test_a_result_without_preview_is_skipped():
    deezer = FakeDeezer(
        results=[deezer_track(source_id="1", preview_url=None), deezer_track(source_id="2")]
    )
    assert complete(spotify_track(), deezer).preview_url == PREVIEW


def test_an_isrc_edition_without_preview_falls_back_to_the_search():
    deezer = FakeDeezer(by_isrc=deezer_track(preview_url=None), results=[deezer_track()])
    track = complete(spotify_track(isrc="FRX872000123"), deezer)

    assert deezer.queries == [('artist:"PNL" track:"Au DD"', preview.SEARCH_LIMIT)]
    assert track.preview_url == PREVIEW


def test_an_unknown_artist_stops_everything():
    """Lien Spotify résolu par oEmbed : sans artiste, un titre seul ne prouve
    rien — « Hasta la Vista » existe chez plusieurs artistes."""
    deezer = FakeDeezer(results=[deezer_track()])
    track = complete(spotify_track(artist="Artiste inconnu"), deezer)

    assert deezer.queries == []
    assert track.preview_url is None


def test_a_track_that_already_has_a_preview_is_left_alone():
    deezer = FakeDeezer(results=[deezer_track()])
    track = complete(spotify_track(preview_url="https://p.scdn.co/mp3-preview/abc"), deezer)

    assert track.preview_url == "https://p.scdn.co/mp3-preview/abc"
    assert deezer.queries == [] and deezer.isrc_calls == []


def test_a_deezer_track_without_preview_is_not_looked_up_again():
    deezer = FakeDeezer(results=[deezer_track()])
    track = deezer_track(preview_url=None)

    assert complete(track, deezer).preview_url is None
    assert deezer.queries == [] and deezer.isrc_calls == []


def test_deezer_being_down_changes_nothing(caplog):
    caplog.set_level(logging.INFO, logger=preview.__name__)
    deezer = FakeDeezer(error=DeezerError("503"))

    track = complete(spotify_track(isrc="FRX872000123"), deezer)

    assert track.preview_url is None
    assert "impossible" in caplog.text


def test_the_delivery_completes_the_preview_before_resolving():
    """L'ordre compte : la vérification acoustique a besoin de l'extrait, et
    le résolveur de la durée."""
    import inspect

    from app.bot.handlers import track as track_handler

    source = inspect.getsource(track_handler.deliver_track_audio)
    assert source.index("complete_preview") < source.index("iter_audio_sources")
