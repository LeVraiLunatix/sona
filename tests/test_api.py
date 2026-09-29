"""API HTTP privée (backend de l'app iOS) : auth, bibliothèque, historique,
réglages, sans appel réseau réel (les providers sont remplacés par des faux).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.providers.base import TrackInfo


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


AUTH = {"Authorization": "Bearer test-token"}


def test_health_requires_no_auth(client):
    assert client.get("/health").status_code == 200


def test_unauthenticated_requests_are_rejected(client):
    assert client.get("/settings").status_code == 401
    assert client.get("/settings", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_settings_roundtrip(client):
    got = client.get("/settings", headers=AUTH)
    assert got.status_code == 200
    assert got.json() == {"quality": "best", "format": "auto", "autoplay": True}

    updated = client.put("/settings", headers=AUTH, json={"quality": "standard", "autoplay": False})
    assert updated.status_code == 200
    assert updated.json() == {"quality": "standard", "format": "auto", "autoplay": False}

    bad = client.put("/settings", headers=AUTH, json={"quality": "lossless"})
    assert bad.status_code == 400


def test_library_and_history_flow(client):
    async def fake_get_track(track_id):
        return TrackInfo(
            source="deezer", source_id=track_id, title="Titre", artist="Artiste",
            album="Album", year="2024", duration_seconds=180, cover_url=None,
        )

    client.app_state.deps.deezer.get_track = fake_get_track

    added = client.post("/library/track", headers=AUTH, json={"source": "deezer", "source_id": "42"})
    assert added.status_code == 204

    listed = client.get("/library/track", headers=AUTH)
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "Titre"

    removed = client.delete("/library/track/deezer/42", headers=AUTH)
    assert removed.status_code == 204
    assert client.get("/library/track", headers=AUTH).json()["total"] == 0

    fetched = client.get("/tracks/deezer/42", headers=AUTH)
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "Titre"

    history = client.get("/history", headers=AUTH)
    assert history.status_code == 200
    assert history.json()["total"] == 1

    cleared = client.delete("/history", headers=AUTH)
    assert cleared.status_code == 204
    assert client.get("/history", headers=AUTH).json()["total"] == 0


def test_library_rejects_unknown_kind(client):
    assert client.get("/library/bogus", headers=AUTH).status_code == 400


def test_search_requires_query_or_id(client):
    assert client.get("/search", headers=AUTH).status_code == 400


def test_search_paginates_through_query_cache(client, monkeypatch):
    track = TrackInfo(
        source="deezer", source_id="1", title="Titre", artist="Artiste",
        album=None, year=None, duration_seconds=None, cover_url=None,
    )

    async def fake_search_tracks(query, index=0, limit=25, order=None):
        # Un seul résultat non vide : la cascade Deezer/iTunes/YouTube
        # (app/services/search.py) s'arrête là, sans appeler les autres
        # providers (qui feraient de vrais appels réseau en test).
        return [track], 1

    client.app_state.deps.deezer.search_tracks = fake_search_tracks

    first = client.get("/search", headers=AUTH, params={"q": "test"})
    assert first.status_code == 200
    assert first.json()["provider"] == "deezer"
    query_id = first.json()["query_id"]

    second = client.get("/search", headers=AUTH, params={"query_id": query_id, "offset": 5})
    assert second.status_code == 200
    assert second.json()["query_id"] == query_id

    assert client.get("/search", headers=AUTH, params={"query_id": "unknown"}).status_code == 404
