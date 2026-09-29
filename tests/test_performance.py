"""Ce qui rend l'app plus rapide : fiches des titres gardées dans la
bibliothèque, cache du catalogue, réponses JSON compressées."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.providers.base import TrackInfo

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
        test_client.deps = main_module.app.state.deps
        yield test_client


def test_library_returns_full_tracks_and_catalog_is_cached(client):
    calls = []

    async def fake_get_track(track_id):
        calls.append(track_id)
        return TrackInfo("deezer", track_id, "Grabba", "Ziak", "Akimbo", "2021", 181, "https://c",
                         artist_source_id="7", album_source_id="8")

    client.deps.deezer.get_track = fake_get_track
    client.post("/library/track", headers=AUTH, json={"source": "deezer", "source_id": "1"})
    item = client.get("/library/track", headers=AUTH).json()["items"][0]
    assert item["track"]["artist_source_id"] == "7"
    assert item["track"]["duration_seconds"] == 181

    # Même titre redemandé : servi depuis le cache, sans rappeler Deezer.
    client.get("/tracks/deezer/1", headers=AUTH)
    client.get("/tracks/deezer/1", headers=AUTH)
    assert calls == ["1"]


def test_old_library_entries_are_completed_once_read(client):
    async def fake_get_track(track_id):
        return TrackInfo("deezer", track_id, "Titre", "Artiste", None, None, 100, None)

    client.deps.deezer.get_track = fake_get_track

    async def legacy_entry():
        conn = client.deps.repo._db.conn
        await conn.execute(
            """INSERT INTO library (user_id, kind, source, source_id, title, subtitle, cover_url, added_at)
               VALUES (?, 'track', 'deezer', '5', 'Titre', 'Artiste', NULL, '2024-01-01')""",
            (client.deps.settings.api_user_id,),
        )
        await conn.commit()

    client.portal.call(legacy_entry)
    assert client.get("/library/track", headers=AUTH).json()["items"][0]["track"] is None
    client.get("/tracks/deezer/5", headers=AUTH)
    assert client.get("/library/track", headers=AUTH).json()["items"][0]["track"]["duration_seconds"] == 100


def test_json_is_gzipped_but_not_audio(client, tmp_path):
    many = {"name": "x" * 50, "tracks": [
        {"source": "deezer", "source_id": str(i), "title": f"Titre {i}", "artist": "Artiste"} for i in range(40)
    ]}
    pid = client.post("/me/playlists", headers=AUTH, json=many).json()["id"]
    got = client.get(f"/me/playlists/{pid}", headers={**AUTH, "Accept-Encoding": "gzip"})
    assert got.headers.get("content-encoding") == "gzip"
    assert got.json()["track_count"] == 40
    # L'audio n'est jamais compressé (requêtes Range du lecteur).
    cached = tmp_path / "audio.m4a"
    cached.write_bytes(b"a" * 5000)
    client.portal.call(client.deps.repo.stream_cache_set, "deezer", "1", "auto", "best", str(cached), "audio/mp4")
    audio = client.get("/stream/deezer/1", headers={**AUTH, "Accept-Encoding": "gzip"})
    assert audio.status_code == 200
    assert audio.headers.get("content-encoding") != "gzip"
    assert len(audio.content) == 5000
