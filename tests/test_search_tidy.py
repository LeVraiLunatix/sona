"""Recherche plus propre : doublons de version écartés, titre exact en tête,
et suggestions pendant la frappe (providers remplacés par des faux)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.providers.base import ArtistInfo, TrackInfo
from app.providers.deezer import DeezerError
from app.services.search import tidy_results

AUTH = {"Authorization": "Bearer test-token"}


def t(source_id: str, title: str, artist: str = "Ziak", album: str = "Album") -> TrackInfo:
    return TrackInfo(
        source="deezer", source_id=source_id, title=title, artist=artist, album=album,
        year=None, duration_seconds=180, cover_url=None,
    )


def ids(tracks: list[TrackInfo]) -> list[str]:
    return [x.source_id for x in tracks]


def test_same_song_on_several_releases_appears_once():
    found = tidy_results("joli", [
        t("1", "Joli", album="Album"), t("2", "Joli", album="Single"), t("3", "Joli (feat. Ninho)", album="Réédition"),
        t("4", "Joli - Radio Edit", album="Compilation"),
    ])
    assert ids(found) == ["1"]


def test_remix_live_and_acoustic_stay_separate_results():
    found = tidy_results("joli", [
        t("1", "Joli"), t("2", "Joli (Remix)"), t("3", "Joli - Live à Bercy"), t("4", "Joli (Acoustic)"), t("5", "Joli (Remix)"),
    ])
    assert ids(found) == ["1", "2", "3", "4"]


def test_two_artists_with_the_same_title_are_kept():
    assert ids(tidy_results("", [t("1", "Joli", "Ziak"), t("2", "Joli", "Ninho")])) == ["1", "2"]


def test_exact_title_comes_first_and_order_is_otherwise_kept():
    found = tidy_results("joli", [t("1", "Jolie vie"), t("2", "Joli (Remix)"), t("3", "Joli"), t("4", "Joli monde")])
    assert ids(found) == ["3", "1", "2", "4"]


def test_empty_query_only_removes_duplicates():
    assert ids(tidy_results("", [t("1", "A"), t("2", "A"), t("3", "B")])) == ["1", "3"]


# -- Suggestions -------------------------------------------------------------

@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("API_TOKEN", "test-token")
    monkeypatch.setenv("ALLOWED_USER_IDS", "")
    monkeypatch.setenv("BOT_TOKEN", "")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "sona.db"))
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "backups"))

    import app.api.main as main_module
    from app.api.routers import search as search_router

    search_router._suggest_cache.clear()
    with TestClient(main_module.app) as test_client:
        test_client.app_state = main_module.app.state
        yield test_client


def test_suggest_returns_artists_then_titles(client):
    async def artists(query, limit=10):
        return [ArtistInfo(source="deezer", source_id="9", name="Ziak", picture_url="p.jpg", fans=5)]

    async def tracks(query, index=0, limit=25, order=None):
        return [t("1", "Joli"), t("2", "Joli", album="Single")], 2

    client.app_state.deps.deezer.search_artists = artists
    client.app_state.deps.deezer.search_tracks = tracks
    got = client.get("/search/suggest", params={"q": "zia"}, headers=AUTH).json()
    assert [(s["kind"], s["text"]) for s in got] == [("artist", "Ziak"), ("track", "Joli")]
    assert got[0]["picture_url"] == "p.jpg" and got[1]["subtitle"] == "Ziak"


def test_suggest_ignores_one_letter_and_survives_a_broken_source(client):
    async def broken(*args, **kwargs):
        raise DeezerError("panne")

    async def tracks(query, index=0, limit=25, order=None):
        return [t("1", "Joli")], 1

    client.app_state.deps.deezer.search_artists = broken
    client.app_state.deps.deezer.search_tracks = tracks
    assert client.get("/search/suggest", params={"q": "z"}, headers=AUTH).json() == []
    got = client.get("/search/suggest", params={"q": "jol"}, headers=AUTH).json()
    assert [s["kind"] for s in got] == ["track"]


def test_suggest_is_cached_for_a_minute(client):
    calls = []

    async def artists(query, limit=10):
        calls.append(query)
        return []

    async def tracks(query, index=0, limit=25, order=None):
        return [t("1", "Joli")], 1

    client.app_state.deps.deezer.search_artists = artists
    client.app_state.deps.deezer.search_tracks = tracks
    client.get("/search/suggest", params={"q": "joli"}, headers=AUTH)
    client.get("/search/suggest", params={"q": "JOLI"}, headers=AUTH)
    assert len(calls) == 1


def test_main_search_applies_tidy_on_first_page_only(client):
    async def tracks(query, index=0, limit=25, order=None):
        return [t("1", "Jolie vie"), t("2", "Joli"), t("3", "Joli", album="Single")], 3

    client.app_state.deps.deezer.search_tracks = tracks
    first = client.get("/search", params={"q": "joli"}, headers=AUTH).json()
    assert [x["source_id"] for x in first["tracks"]] == ["2", "1"]
