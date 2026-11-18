"""Vidéos animées d'Apple Music : choix du jeton, appariement des noms et flux
complet avec un faux transport httpx (aucun appel réseau)."""

from __future__ import annotations

import asyncio
import base64
import json

import httpx
import pytest

from app.services import apple_motion


def jwt(iss: str, exp: float) -> str:
    def enc(obj: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    return f"{enc({'typ': 'JWT', 'alg': 'ES256', 'kid': 'ABCDEFGHIJKLMNOP'})}.{enc({'iss': iss, 'exp': exp})}.{'s' * 30}"


@pytest.fixture(autouse=True)
def clean():
    apple_motion.reset()
    yield
    apple_motion.reset()
    apple_motion._client = None


def test_pick_token_keeps_the_web_player_one_and_skips_expired():
    script = f'a="{jwt("5IKPP2IECQ", 9e9)}";b="{jwt("AMPWebPlay", 9e9)}"'
    token, exp = apple_motion.pick_token(script, now=1000)
    assert json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))["iss"] == "AMPWebPlay"
    assert exp == 9e9
    assert apple_motion.pick_token(f'b="{jwt("AMPWebPlay", 1100)}"', now=1000) is None  # expire dans < 5 min


def test_pick_artist_requires_the_exact_name():
    results = [
        {"id": "1", "attributes": {"name": "Lil Uzi Vert Tribute"}},
        {"id": "2", "attributes": {"name": "Lil Uzi Vert"}},
    ]
    assert apple_motion.pick_artist(results, "lil uzi vert") == "2"
    assert apple_motion.pick_artist(results[:1], "Lil Uzi Vert") is None


def test_pick_album_ignores_editions_but_checks_the_artist():
    results = [
        {"id": "1", "attributes": {"name": "Luv Is Rage 2 (Deluxe)", "artistName": "Lil Uzi Vert"}},
        {"id": "2", "attributes": {"name": "Luv Is Rage 2", "artistName": "Autre"}},
    ]
    assert apple_motion.pick_album(results, "Luv Is Rage 2", "Lil Uzi Vert") == "1"
    assert apple_motion.pick_album(results[1:], "Luv Is Rage 2", "Lil Uzi Vert") is None


def test_album_motion_end_to_end_and_cache():
    token = jwt("AMPWebPlay", 9e9)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        if url.endswith("/fr/new"):
            return httpx.Response(200, text='<script src="/assets/index~abc.js"></script>')
        if "/assets/index" in url:
            return httpx.Response(200, text=f'x="{token}"')
        assert request.headers["authorization"] == f"Bearer {token}"
        if url.split("?")[0].endswith("/search"):
            return httpx.Response(200, json={"results": {"albums": {"data": [
                {"id": "9", "attributes": {"name": "After Hours", "artistName": "The Weeknd"}},
            ]}}})
        return httpx.Response(200, json={"data": [{"attributes": {"editorialVideo": {
            "motionTallVideo3x4": {"video": "https://mvod.itunes.apple.com/tall.m3u8"},
            "motionSquareVideo1x1": {"video": "http://pas-https/square.m3u8"},
        }}}]})

    apple_motion._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def run():
        first = await apple_motion.album_motion("After Hours", "The Weeknd")
        second = await apple_motion.album_motion("After Hours", "The Weeknd")
        return first, second

    first, second = asyncio.run(run())
    assert first == {"tall": "https://mvod.itunes.apple.com/tall.m3u8", "square": None}
    assert second == first
    assert len(calls) == 4  # page, script, recherche, fiche — rien de plus au 2e appel


def test_no_video_is_cached_as_nothing():
    token = jwt("AMPWebPlay", 9e9)

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/fr/new"):
            return httpx.Response(200, text='<script src="/assets/index~abc.js"></script>')
        if "/assets/index" in url:
            return httpx.Response(200, text=token)
        return httpx.Response(200, json={"results": {"artists": {"data": []}}})

    apple_motion._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert asyncio.run(apple_motion.artist_motion("Inconnu")) is None
