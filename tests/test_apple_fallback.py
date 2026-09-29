"""Titre Apple absent du catalogue américain : cherché dans le catalogue
français, sinon lu d'après la fiche enregistrée avec la playlist."""

from __future__ import annotations

import asyncio

import httpx

from app.api.routers import stream
from app.providers.apple import AppleMusicClient, AppleMusicError
from app.providers.base import TrackInfo
from tests.test_wrong_version import client  # noqa: F401

SONG = {"wrapperType": "track", "trackId": 42, "trackName": "Lettre à une femme", "artistName": "Ninho",
        "collectionName": "Destin", "trackTimeMillis": 157000}


def test_lookup_tries_the_french_catalogue_first():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        country = request.url.params.get("country")
        seen.append(country)
        return httpx.Response(200, json={"results": [SONG] if country == "fr" else []})

    apple = AppleMusicClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    track = asyncio.run(apple.get_track("42"))
    assert track.title == "Lettre à une femme" and seen == ["fr"]


def test_lookup_falls_back_to_the_default_catalogue():
    def handler(request: httpx.Request) -> httpx.Response:
        found = request.url.params.get("country") is None
        return httpx.Response(200, json={"results": [SONG] if found else []})

    apple = AppleMusicClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert asyncio.run(apple.get_track("42")).artist == "Ninho"


def test_stream_uses_the_saved_track_when_the_source_forgot_it(client, monkeypatch):
    deps = client.deps

    async def gone(*args, **kwargs):
        raise AppleMusicError("Morceau introuvable sur Apple Music.")

    monkeypatch.setattr(stream.lookup, "get_track", gone)

    async def scenario():
        playlist_id = await deps.repo.playlist_create(0, "Import", origin="apple")
        await deps.repo.playlist_add_tracks(playlist_id, [
            TrackInfo("apple", "42", "Lettre à une femme", "Ninho", "Destin", None, 157, None),
        ])
        found = await stream._track_for(deps, "apple", "42")
        assert (found.title, found.artist, found.duration_seconds) == ("Lettre à une femme", "Ninho", 157)
        try:
            await stream._track_for(deps, "apple", "999")
        except AppleMusicError:
            return True
        return False

    assert client.portal.call(scenario)
