"""Préparation et service du flux audio (`/stream`) : téléchargement
remplacé par un faux, aucun appel réseau."""

from __future__ import annotations

import time
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.routers import stream
from app.services.live_stream import LiveSource

AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("API_TOKEN", "test-token")
    monkeypatch.setenv("ALLOWED_USER_IDS", "")
    monkeypatch.setenv("BOT_TOKEN", "")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "sona.db"))
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "backups"))
    stream._failures.clear()
    stream._live.clear()

    async def no_live(deps, source, source_id, key):
        return None

    # Par défaut, pas de flux direct : chaque test qui en veut un le fournit.
    monkeypatch.setattr(stream, "_live_source", no_live)

    import app.api.main as main_module

    with TestClient(main_module.app) as test_client:
        yield test_client
    stream._failures.clear()
    stream._live.clear()


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


def test_stream_relays_youtube_directly_and_caches_in_background(client, tmp_path, monkeypatch):
    audio = tmp_path / "verifie.m4a"
    audio.write_bytes(b"fichier verifie")
    downloads = []

    async def fake_download(deps, source, source_id, quality, fmt):
        downloads.append(source_id)
        return audio

    async def live(deps, source, source_id, key):
        return LiveSource(url="https://rr1.googlevideo.test/videoplayback?id=1", headers={"User-Agent": "yt"})

    def upstream(request):
        assert request.headers["range"] == "bytes=0-3"
        assert request.headers["user-agent"] == "yt"
        return httpx.Response(206, content=b"AUDI", headers={"Content-Range": "bytes 0-3/1000", "Content-Length": "4"})

    monkeypatch.setattr(stream, "_resolve_and_download", fake_download)
    monkeypatch.setattr(stream, "_live_source", live)
    monkeypatch.setattr(stream, "_proxy_client", httpx.AsyncClient(transport=httpx.MockTransport(upstream)))

    got = client.get("/stream/deezer/5", headers={**AUTH, "Range": "bytes=0-3"})
    assert got.status_code == 206
    assert got.content == b"AUDI"
    assert got.headers["content-range"] == "bytes 0-3/1000"
    assert got.headers["content-type"] == "audio/mp4"

    # Le fichier vérifié se prépare en arrière-plan pendant la lecture.
    deadline = time.monotonic() + 2
    while not downloads and time.monotonic() < deadline:
        time.sleep(0.05)
    assert downloads == ["5"]


def test_stream_falls_back_to_download_when_relay_fails(client, tmp_path, monkeypatch):
    audio = tmp_path / "morceau.m4a"
    audio.write_bytes(b"audio complet")

    async def fake_download(deps, source, source_id, quality, fmt):
        return audio

    async def live(deps, source, source_id, key):
        return LiveSource(url="https://rr1.googlevideo.test/videoplayback?id=2", headers={})

    monkeypatch.setattr(stream, "_resolve_and_download", fake_download)
    monkeypatch.setattr(stream, "_live_source", live)
    monkeypatch.setattr(stream, "_proxy_client", httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(403))
    ))

    got = client.get("/stream/deezer/6", headers=AUTH)
    assert got.status_code == 200
    assert got.content == b"audio complet"


def test_download_failure_message_names_the_cause():
    from app.services.downloader import DownloadError

    try:
        raise DownloadError("Téléchargement audio impossible.") from RuntimeError(
            "ERROR: [youtube] abc: Requested format is not available\nsuite"
        )
    except DownloadError as exc:
        assert stream._download_failure(exc) == (
            "Téléchargement audio impossible : [youtube] abc: Requested format is not available"
        )
    assert "cookies" in stream._download_failure(DownloadError("x", bot_wall=True))
