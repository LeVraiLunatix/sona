"""Endpoints de découverte de l'app iOS : recherche d'artistes/albums,
artistes similaires, stations d'artiste, radios thématiques — providers
remplacés par des faux, aucun appel réseau réel."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.routers import browse
from app.providers.base import AlbumInfo, ArtistInfo, TrackInfo
from app.providers.deezer import DeezerError
from app.services.artist_search import rank_artists

AUTH = {"Authorization": "Bearer test-token"}


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


def artist(name: str, source_id: str, fans: int | None = None, source: str = "deezer") -> ArtistInfo:
    return ArtistInfo(source=source, source_id=source_id, name=name, picture_url=None, fans=fans)


def track(source_id: str, source: str = "deezer") -> TrackInfo:
    return TrackInfo(
        source=source, source_id=source_id, title=f"Titre {source_id}", artist="Artiste",
        album=None, year=None, duration_seconds=180, cover_url=None,
    )


def test_rank_artists_puts_most_followed_exact_homonym_first():
    ranked = rank_artists("ziak", [
        artist("Ziak", "150843252", fans=248),
        artist("Ziak", "7668530", fans=626134),
        artist("Akis Ziak", "1", fans=3),
    ])
    assert [a.source_id for a in ranked] == ["7668530", "150843252", "1"]


def test_rank_artists_keeps_source_order_without_exact_match():
    ranked = rank_artists("eiak", [artist("Ziak", "1", fans=10), artist("Sia", "2", fans=9_000_000)])
    assert [a.name for a in ranked] == ["Ziak", "Sia"]


def test_search_artists_uses_deezer_and_exposes_fans(client):
    async def fake_search_artists(query, limit=10):
        assert query == "eiak"
        return [artist("Ziak", "7668530", fans=626134)]

    client.app_state.deps.deezer.search_artists = fake_search_artists
    got = client.get("/search/artists", headers=AUTH, params={"q": "eiak"})
    assert got.status_code == 200
    assert got.json() == [{
        "source": "deezer", "source_id": "7668530", "name": "Ziak", "picture_url": None, "fans": 626134,
    }]


def test_search_artists_falls_back_to_youtube_music(client, monkeypatch):
    async def empty(query, limit=10):
        return []

    async def fake_youtube(query, limit=10):
        return [artist("Underground", "UCxyz", source="youtube")]

    client.app_state.deps.deezer.search_artists = empty
    monkeypatch.setattr("app.api.routers.search.search_artists_youtube", fake_youtube)
    got = client.get("/search/artists", headers=AUTH, params={"q": "underground"})
    assert got.status_code == 200
    assert got.json()[0]["source"] == "youtube"


def test_search_artists_survives_deezer_outage(client, monkeypatch):
    async def broken(query, limit=10):
        raise DeezerError("503")

    async def no_youtube(query, limit=10):
        return []

    client.app_state.deps.deezer.search_artists = broken
    monkeypatch.setattr("app.api.routers.search.search_artists_youtube", no_youtube)
    got = client.get("/search/artists", headers=AUTH, params={"q": "x"})
    assert got.status_code == 200
    assert got.json() == []


def test_search_artists_rejects_blank_query(client):
    assert client.get("/search/artists", headers=AUTH, params={"q": "   "}).status_code == 400


def test_search_albums(client):
    async def fake_search_albums(query, limit=10):
        return [AlbumInfo(
            source="deezer", source_id="1075750472", title="MONSIEUR LOYAL", artist="Ziak",
            artist_source_id="7668530", year="2026", cover_url=None, track_count=14, duration_seconds=None,
        )]

    client.app_state.deps.deezer.search_albums = fake_search_albums
    got = client.get("/search/albums", headers=AUTH, params={"q": "ziak"})
    assert got.status_code == 200
    assert got.json()[0]["title"] == "MONSIEUR LOYAL"
    assert got.json()[0]["tracks"] == []


def test_related_artists_for_deezer_and_empty_elsewhere(client):
    async def fake_related(artist_id, limit=20):
        return [artist("Zola", "2")]

    client.app_state.deps.deezer.get_related_artists = fake_related
    assert client.get("/artists/deezer/1/related", headers=AUTH).json()[0]["name"] == "Zola"
    assert client.get("/artists/youtube/UCxyz/related", headers=AUTH).json() == []
    assert client.get("/artists/bogus/1/related", headers=AUTH).status_code == 400


def test_artist_radio_uses_deezer_mix(client):
    async def fake_radio(artist_id, limit=25):
        return [track("10"), track("11")]

    client.app_state.deps.deezer.get_artist_radio = fake_radio
    got = client.get("/artists/deezer/1/radio", headers=AUTH)
    assert got.status_code == 200
    assert [t["source_id"] for t in got.json()] == ["10", "11"]


def test_artist_radio_falls_back_to_shuffled_top_tracks(client):
    async def fake_top(artist_id, limit=25):
        return [track("1", "apple"), track("2", "apple"), track("3", "apple")]

    client.app_state.deps.apple.get_artist_top_tracks = fake_top
    got = client.get("/artists/apple/9/radio", headers=AUTH)
    assert got.status_code == 200
    assert sorted(t["source_id"] for t in got.json()) == ["1", "2", "3"]


def test_browse_radios_are_curated(client):
    got = client.get("/browse/radios", headers=AUTH)
    assert got.status_code == 200
    groups = got.json()
    assert len(groups) == len(browse.CURATED_RADIOS)
    first = groups[0]["radios"][0]
    assert first == {
        "id": "39021", "title": "Rap français",
        "picture_url": "https://api.deezer.com/radio/39021/image?size=xl",
    }
    titles = [r["title"].lower() for g in groups for r in g["radios"]]
    assert not any("test" in t or "festival" in t for t in titles)


def test_radio_tracks(client):
    async def fake_radio_tracks(radio_id, limit=25):
        assert radio_id == "39021"
        return [track("5")]

    client.app_state.deps.deezer.get_radio_tracks = fake_radio_tracks
    got = client.get("/radios/39021/tracks", headers=AUTH)
    assert got.status_code == 200
    assert got.json()[0]["source_id"] == "5"
    assert client.get("/radios/abc/tracks", headers=AUTH).status_code == 400


def test_radio_tracks_reports_deezer_outage(client):
    async def broken(radio_id, limit=25):
        raise DeezerError("503")

    client.app_state.deps.deezer.get_radio_tracks = broken
    assert client.get("/radios/1/tracks", headers=AUTH).status_code == 502
