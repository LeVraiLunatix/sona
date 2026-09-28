"""Préparation et service du flux audio (`/stream`) : téléchargement
remplacé par un faux, aucun appel réseau."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.routers import stream

AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("API_TOKEN", "test-token")
    monkeypatch.setenv("ALLOWED_USER_IDS", "")
    monkeypatch.setenv("BOT_TOKEN", "")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "sona.db"))
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "backups"))
    stream._failures.clear()

    import app.api.main as main_module

    with TestClient(main_module.app) as test_client:
        yield test_client
    stream._failures.clear()


def test_prepare_then_stream_serves_the_file(client, tmp_path, monkeypatch):
    audio = tmp_path / "morceau.m4a"
    audio.write_bytes(b"audio")
    calls = []

    async def fake_download(deps, source, source_id, quality, fmt):
        calls.append(source_id)
        return audio

    monkeypatch.setattr(stream, "_resolve_and_download", fake_download)
    ready = client.post("/stream/deezer/42/prepare", headers=AUTH)
    assert ready.status_code == 200 and ready.json() == {"ready": True}

    served = client.get("/stream/deezer/42", headers=AUTH)
    assert served.status_code == 200
    assert served.content == b"audio"
    assert served.headers["content-type"] == "audio/mp4"
    assert calls == ["42", "42"]  # le faux ne remplit pas le cache disque


def test_failure_is_remembered_with_its_message(client, monkeypatch):
    calls = []

    async def failing_download(deps, source, source_id, quality, fmt):
        calls.append(source_id)
        raise HTTPException(404, "Aucune version fidèle de ce morceau n'a été trouvée.")

    monkeypatch.setattr(stream, "_resolve_and_download", failing_download)
    first = client.post("/stream/deezer/7/prepare", headers=AUTH)
    assert first.status_code == 404
    assert first.json()["detail"] == "Aucune version fidèle de ce morceau n'a été trouvée."

    # Nouvel essai immédiat, puis lecture : même réponse, sans retélécharger.
    assert client.post("/stream/deezer/7/prepare", headers=AUTH).status_code == 404
    assert client.get("/stream/deezer/7", headers=AUTH).status_code == 404
    assert calls == ["7"]


def test_prepare_rejects_unknown_quality(client):
    assert client.post("/stream/deezer/1/prepare", headers=AUTH, params={"quality": "ultra"}).status_code == 400
