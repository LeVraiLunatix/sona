"""Liens Spotify quand l'API refuse ou n'est pas configurée.

Le 2026-09-16, des identifiants valides ont bien donné un jeton, puis un 403
sur chaque requête (« Active premium subscription required for the owner of
the app ») : sans repli, les liens de morceaux Spotify, qui fonctionnaient
sans identifiants, affichaient une erreur.
"""

import asyncio
import logging

import httpx
import pytest

from app.bot import errors
from app.providers import spotify
from app.providers.deezer import DeezerError
from app.providers.spotify import SpotifyClient, SpotifyError, SpotifyNotConfigured, SpotifyRefused
from app.services import preview

TRACK_ID = "0VjIjW4GlUZAMYd2vXMi3b"
PREMIUM = (
    "Active premium subscription required for the owner of the app. When the subscription "
    "status changes, it can take a few hours before requests are allowed again."
)
# Extrait réel de la page publique d'un morceau (balises d'aperçu). La balise
# placée dans <body> ne doit pas être lue.
PAGE = """<!DOCTYPE html><html><head>
<meta charset="utf-8"/>
<meta property="og:title" content="Blinding Lights"/>
<meta property="og:description" content="The Weeknd · After Hours · Song · 2020"/>
<meta property="og:image" content="https://i.scdn.co/image/grande"/>
<meta name="music:duration" content="200"/>
<meta name="music:release_date" content="2020-03-20"/>
<meta name="music:musician" content="https://open.spotify.com/artist/1Xyo4u8uXC1ZmMpatF05PJ"/>
<meta name="music:musician_description" content="The Weeknd"/>
</head><body><meta name="music:duration" content="999"/></body></html>"""
API_TRACK = {
    "id": TRACK_ID,
    "name": "Blinding Lights",
    "duration_ms": 200040,
    "artists": [{"id": "1Xyo4u8uXC1ZmMpatF05PJ", "name": "The Weeknd"}],
    "album": {
        "id": "4yP0hdKOZPNshxUOjY0cZj",
        "name": "After Hours",
        "release_date": "2020-03-20",
        "images": [{"url": "https://i.scdn.co/image/api"}],
    },
    "external_ids": {"isrc": "USUG11904206"},
}


class FakeSpotify:
    """Spotify simulé : jeton, API, oEmbed et page publique du morceau.

    `api_status` est un code HTTP, ou une liste de codes servis dans l'ordre.
    """

    def __init__(self, api_status=200, token_status=200, page=PAGE, page_status=200):
        self.api_status = api_status
        self.token_status = token_status
        self.page = page
        self.page_status = page_status
        self.requests = []

    def count(self, kind):
        return self.requests.count(kind)

    def handler(self, request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        if host == "accounts.spotify.com":
            self.requests.append("jeton")
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": "invalid_client"})
            return httpx.Response(200, json={"access_token": "jeton-factice", "expires_in": 3600})
        if host == "api.spotify.com":
            self.requests.append("api")
            status = self.api_status.pop(0) if isinstance(self.api_status, list) else self.api_status
            if status != 200:
                return httpx.Response(status, text=PREMIUM if status == 403 else "erreur")
            if path.startswith("/v1/tracks/"):
                return httpx.Response(200, json=API_TRACK)
            return httpx.Response(200, json={"id": "4yP0hdKOZPNshxUOjY0cZj", "name": "After Hours"})
        if path == "/oembed":
            self.requests.append("oembed")
            return httpx.Response(
                200, json={"title": "Blinding Lights", "thumbnail_url": "https://i.scdn.co/image/petite"}
            )
        if path.startswith("/track/"):
            self.requests.append("page")
            return httpx.Response(self.page_status, text=self.page)
        return httpx.Response(404)


def run(fake, action, configured=True):
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)) as http:
            client = SpotifyClient("id" if configured else None, "secret" if configured else None, client=http)
            return await action(client)

    return asyncio.run(scenario())


def warnings(caplog):
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]


@pytest.fixture
def clock(monkeypatch):
    """Horloge du provider pilotée à la main (celle d'asyncio reste intacte)."""
    now = [1000.0]
    monkeypatch.setattr(spotify, "_clock", lambda: now[0])
    return now


def test_the_api_is_used_when_it_answers():
    fake = FakeSpotify()
    track = run(fake, lambda c: c.get_track(TRACK_ID))
    assert (track.artist, track.isrc, track.duration_seconds) == ("The Weeknd", "USUG11904206", 200)
    assert fake.count("oembed") == 0


def test_a_refused_api_falls_back_to_the_public_data(caplog):
    fake = FakeSpotify(api_status=403)
    with caplog.at_level(logging.WARNING, logger="app.providers.spotify"):
        track = run(fake, lambda c: c.get_track(TRACK_ID))

    assert track.title == "Blinding Lights"
    assert (track.artist, track.album, track.year, track.duration_seconds) == ("The Weeknd", "After Hours", "2020", 200)
    assert track.cover_url == "https://i.scdn.co/image/grande"
    [message] = warnings(caplog)
    assert "API Spotify refusée (Premium exigé pour le propriétaire de l'app ?) : repli oEmbed" in message
    assert "HTTP 403" in message and "Active premium subscription required" in message


def test_the_refusal_is_remembered_for_an_hour(clock, caplog):
    fake = FakeSpotify(api_status=403)

    async def three_links(client):
        await client.get_track(TRACK_ID)
        await client.get_track(TRACK_ID)
        clock[0] += spotify.REFUSAL_COOLDOWN_SECONDS + 1
        await client.get_track(TRACK_ID)

    with caplog.at_level(logging.WARNING, logger="app.providers.spotify"):
        run(fake, three_links)

    # 1er lien : l'API refuse. 2e : elle n'est pas redemandée. 3e, une heure
    # plus tard : nouvel essai, nouveau refus, nouvel avertissement.
    assert fake.count("api") == 2
    assert fake.count("oembed") == 3
    assert len(warnings(caplog)) == 2


def test_rejected_credentials_also_fall_back():
    fake = FakeSpotify(token_status=400)
    track = run(fake, lambda c: c.get_track(TRACK_ID))
    assert track.artist == "The Weeknd"
    assert fake.count("api") == 0


def test_an_expired_token_is_renewed_before_concluding(caplog):
    fake = FakeSpotify(api_status=[401, 200])
    with caplog.at_level(logging.WARNING, logger="app.providers.spotify"):
        track = run(fake, lambda c: c.get_track(TRACK_ID))
    assert track.isrc == "USUG11904206"
    assert fake.count("jeton") == 2
    assert warnings(caplog) == []


def test_without_credentials_the_api_is_never_called():
    fake = FakeSpotify()
    track = run(fake, lambda c: c.get_track(TRACK_ID), configured=False)
    assert (track.artist, track.duration_seconds) == ("The Weeknd", 200)
    assert fake.count("api") == fake.count("jeton") == 0


def test_without_the_public_page_the_oembed_data_still_opens_the_link():
    fake = FakeSpotify(api_status=403, page="introuvable", page_status=404)
    track = run(fake, lambda c: c.get_track(TRACK_ID))
    assert (track.title, track.artist, track.duration_seconds) == ("Blinding Lights", "Artiste inconnu", None)
    assert track.cover_url == "https://i.scdn.co/image/petite"


def test_several_artists_and_escaped_characters_are_kept():
    page = (
        PAGE.replace('content="The Weeknd"', 'content="Lil Nas X, Billy Ray Cyrus"')
        .replace("The Weeknd · After Hours · Song · 2020", "Lil Nas X, Billy Ray Cyrus · 7 · Song · 2019")
        .replace('content="Blinding Lights"', 'content="Don&#x27;t Stop &amp; Go"')
    )
    track = run(FakeSpotify(page=page), lambda c: c.get_track(TRACK_ID), configured=False)
    assert (track.title, track.artist, track.album) == ("Don't Stop & Go", "Lil Nas X, Billy Ray Cyrus", "7")


def test_an_unknown_track_is_not_hidden_by_the_fallback():
    """Un 404 de l'API n'est pas un refus : la page publique ne ferait pas mieux."""
    fake = FakeSpotify(api_status=404)
    with pytest.raises(SpotifyError):
        run(fake, lambda c: c.get_track("inconnu"))
    assert fake.count("oembed") == 0


def test_albums_and_artists_say_why_they_are_unavailable():
    with pytest.raises(SpotifyRefused) as refused:
        run(FakeSpotify(api_status=403), lambda c: c.get_album("4yP0hdKOZPNshxUOjY0cZj"))
    assert errors.fetch_failed_text(refused.value) == errors.SPOTIFY_UNAVAILABLE

    with pytest.raises(SpotifyNotConfigured) as missing:
        run(FakeSpotify(), lambda c: c.get_artist("1Xyo4u8uXC1ZmMpatF05PJ"), configured=False)
    assert errors.fetch_failed_text(missing.value) == errors.SPOTIFY_UNAVAILABLE

    assert errors.fetch_failed_text(DeezerError("panne")) == errors.GENERIC_FETCH_FAILED


def test_the_public_page_gives_deezer_something_to_search():
    """Avec l'artiste tiré de la page, `complete_preview` peut enfin chercher l'extrait."""
    track = run(FakeSpotify(), lambda c: c.get_track(TRACK_ID), configured=False)
    assert preview._search_query(track) == "The Weeknd Blinding Lights"
