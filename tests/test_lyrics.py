"""Paroles via LRCLIB : analyse LRC, stratégie de recherche et endpoint
`/lyrics` — LRCLIB remplacé par un faux transport httpx, aucun appel réseau."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.providers.lrclib import (
    LrclibClient, Lyrics, LyricsError, LyricsLine, clean_title, main_artist, parse_lrc,
)

AUTH = {"Authorization": "Bearer test-token"}


def fake_lrclib(handler) -> LrclibClient:
    calls: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    client = LrclibClient(httpx.AsyncClient(
        base_url="https://lrclib.net/api", transport=httpx.MockTransport(record),
    ))
    client.calls = calls  # type: ignore[attr-defined]
    return client


def test_parse_lrc_sorts_and_expands_repeated_timestamps():
    lines = parse_lrc("[ar:Artiste]\n[00:12.50]Couplet\n[00:05.00][01:00.10]Refrain\n[00:20.00]\n")
    assert lines == [
        LyricsLine(5.0, "Refrain"), LyricsLine(12.5, "Couplet"),
        LyricsLine(20.0, ""), LyricsLine(60.1, "Refrain"),
    ]


def test_clean_title_and_main_artist():
    assert clean_title("Yesterday - Remastered 2009") == "Yesterday"
    assert clean_title("Djadja (feat. Maluma)") == "Djadja"
    assert clean_title("Love (Is All)") == "Love (Is All)"
    assert main_artist("Aya Nakamura, Ninho") == "Aya Nakamura"
    assert main_artist("Ziak x Gazo") == "Ziak"
    assert main_artist("Malcolm X") == "Malcolm X"


def test_exact_match_returns_synced_lyrics_and_is_cached():
    def handler(request):
        assert request.url.path == "/api/get"
        assert request.url.params["duration"] == "200"
        return httpx.Response(200, json={"syncedLyrics": "[00:01.00]Salut", "plainLyrics": "Salut"})

    client = fake_lrclib(handler)
    first = asyncio.run(client.get_lyrics("Titre", "Artiste", "Album", 200))
    second = asyncio.run(client.get_lyrics("Titre", "Artiste", "Album", 200))
    assert first == Lyrics(synced=True, lines=[LyricsLine(1.0, "Salut")])
    assert second == first
    assert len(client.calls) == 1


def test_falls_back_to_search_with_cleaned_title_and_matching_duration():
    def handler(request):
        if request.url.path == "/api/get":
            return httpx.Response(404, json={"code": 404, "name": "TrackNotFound"})
        assert request.url.params["track_name"] == "Djadja"
        assert request.url.params["artist_name"] == "Aya Nakamura"
        return httpx.Response(200, json=[
            {"duration": 300, "syncedLyrics": "[00:01.00]Mauvaise version"},
            {"duration": 171, "plainLyrics": "Brut seulement"},
            {"duration": 170, "syncedLyrics": "[00:02.00]Bonne version"},
        ])

    lyrics = asyncio.run(fake_lrclib(handler).get_lyrics("Djadja (feat. Maluma)", "Aya Nakamura, Maluma", None, 170))
    assert lyrics == Lyrics(synced=True, lines=[LyricsLine(2.0, "Bonne version")])


def test_plain_lyrics_of_another_version_rather_than_nothing():
    def handler(request):
        if request.url.path == "/api/get":
            return httpx.Response(404)
        return httpx.Response(200, json=[{"duration": 400, "syncedLyrics": "[00:01.00]A", "plainLyrics": "A\nB"}])

    lyrics = asyncio.run(fake_lrclib(handler).get_lyrics("Titre", "Artiste", None, 180))
    assert lyrics == Lyrics(synced=False, lines=[LyricsLine(None, "A"), LyricsLine(None, "B")])


def test_instrumental_and_not_found():
    instrumental = fake_lrclib(lambda r: httpx.Response(200, json={"instrumental": True}))
    assert asyncio.run(instrumental.get_lyrics("T", "A", None, 100)) == Lyrics(synced=False, instrumental=True)

    nothing = fake_lrclib(lambda r: httpx.Response(404) if r.url.path == "/api/get" else httpx.Response(200, json=[]))
    assert asyncio.run(nothing.get_lyrics("T", "A", None, 100)) is None


def test_server_error_raises():
    broken = fake_lrclib(lambda r: httpx.Response(503))
    with pytest.raises(LyricsError):
        asyncio.run(broken.get_lyrics("T", "A", None, 100))


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("API_TOKEN", "test-token")
    monkeypatch.setenv("ALLOWED_USER_IDS", "")
    monkeypatch.setenv("BOT_TOKEN", "")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "sona.db"))
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "backups"))

    import app.api.main as main_module

    with TestClient(main_module.app) as test_client:
        test_client.app_state = main_module.app.state
        yield test_client


def test_lyrics_endpoint(client):
    async def fake_get_lyrics(title, artist, album=None, duration=None):
        assert (title, artist, album, duration) == ("Titre", "Artiste", "Album", 200)
        return Lyrics(synced=True, lines=[LyricsLine(1.5, "Salut")])

    client.app_state.deps.lrclib.get_lyrics = fake_get_lyrics
    got = client.get("/lyrics", headers=AUTH, params={
        "title": "Titre", "artist": "Artiste", "album": "Album", "duration": 200,
    })
    assert got.status_code == 200
    assert got.json() == {"synced": True, "instrumental": False, "lines": [{"time": 1.5, "text": "Salut", "words": None}]}


def test_lyrics_endpoint_not_found_and_upstream_error(client):
    async def none(*args, **kwargs):
        return None

    async def broken(*args, **kwargs):
        raise LyricsError("LRCLIB injoignable")

    client.app_state.deps.lrclib.get_lyrics = none
    assert client.get("/lyrics", headers=AUTH, params={"title": "T", "artist": "A"}).status_code == 404
    client.app_state.deps.lrclib.get_lyrics = broken
    assert client.get("/lyrics", headers=AUTH, params={"title": "T", "artist": "A"}).status_code == 502
    assert client.get("/lyrics", params={"title": "T", "artist": "A"}).status_code == 401


def test_parse_enhanced_lrc_word_timings():
    lines = parse_lrc("[00:10.00]<00:10.00>Je <00:10.50>suis <00:11.20>là\n[00:05.00][00:30.00]Refrain simple")
    assert [line.text for line in lines] == ["Refrain simple", "Je suis là", "Refrain simple"]
    enhanced = lines[1]
    assert [(w.time, w.text.strip()) for w in enhanced.words] == [(10.0, "Je"), (10.5, "suis"), (11.2, "là")]
    assert lines[0].words is None
