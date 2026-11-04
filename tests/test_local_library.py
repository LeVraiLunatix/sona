"""Musique locale : indexation, service du fichier tel quel, substitution lossless."""

from __future__ import annotations

import subprocess
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.routers import stream
from app.providers.base import TrackInfo
from app.services import local_library

AUTH = {"Authorization": "Bearer test-token"}
FFMPEG = shutil.which("ffmpeg")
pytestmark = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg absent")


def make_audio(path: Path, *args: str, **tags: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = [x for k, v in tags.items() for x in ("-metadata", f"{k}={v}")]
    subprocess.run(
        [FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", *args, *meta, str(path)],
        check=True,
    )


@pytest.fixture
def music(tmp_path: Path) -> Path:
    root = tmp_path / "music"
    make_audio(root / "Artiste/Album/01 Titre.flac", "-sample_fmt", "s32", "-ar", "96000",
               title="Titre (Remastered)", artist="Artiste", album="Album", date="2020", track="1", isrc="FR-ABC-20-00001")
    make_audio(root / "Artiste/Album/02 Autre.mp3", "-b:a", "320k", title="Autre", artist="Artiste", album="Album", track="2")
    (root / "Artiste/Album/notes.txt").write_text("pas de l'audio")
    return root


@pytest.fixture
def client(tmp_path: Path, music: Path, monkeypatch):
    monkeypatch.setenv("API_TOKEN", "test-token")
    monkeypatch.setenv("ALLOWED_USER_IDS", "")
    monkeypatch.setenv("BOT_TOKEN", "")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "sona.db"))
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("LOCAL_MUSIC_DIR", str(music))
    import app.api.main as main_module

    with TestClient(main_module.app) as c:
        yield c


def test_normalize_ignores_case_accents_and_parentheses():
    assert local_library.normalize("Beyoncé", "Halo (Remastered 2020)") == local_library.normalize("beyonce", "HALO")
    assert local_library.normalize("A", "Song feat. B") == local_library.normalize("A", "Song")


def test_scan_reads_tags_and_true_quality(client, music):
    report = client.post("/local/scan", headers=AUTH).json()
    assert report["found"] == 2 and report["added_or_updated"] == 2 and report["unreadable"] == 0
    data = client.get("/local/tracks", headers=AUTH).json()
    assert data["total"] == 2
    flac, mp3 = data["tracks"]
    assert flac["title"] == "Titre (Remastered)" and flac["lossless"] is True and flac["year"] == "2020"
    assert flac["quality"].startswith("FLAC") and "kHz" in flac["quality"]
    assert mp3["lossless"] is False and mp3["quality"].startswith("MP3")
    # Relire sans changement ne retouche rien ; un fichier supprimé est oublié.
    assert client.post("/local/scan", headers=AUTH).json()["added_or_updated"] == 0
    (music / "Artiste/Album/02 Autre.mp3").unlink()
    assert client.post("/local/scan", headers=AUTH).json()["removed"] == 1
    assert client.get("/local/tracks", headers=AUTH, params={"q": "titre"}).json()["total"] == 1


def test_stream_serves_original_bytes_with_range(client, music):
    client.post("/local/scan", headers=AUTH)
    track = client.get("/local/tracks", headers=AUTH).json()["tracks"][0]
    original = (music / "Artiste/Album/01 Titre.flac").read_bytes()
    full = client.get(f"/stream/local/{track['source_id']}", headers=AUTH)
    assert full.status_code == 200 and full.content == original
    assert full.headers["content-type"] == "audio/flac" and full.headers["x-audio-lossless"] == "1"
    part = client.get(f"/stream/local/{track['source_id']}", headers={**AUTH, "Range": "bytes=0-99"})
    assert part.status_code == 206 and part.content == original[:100]
    assert client.get("/stream/local/inconnu", headers=AUTH).status_code == 404


def test_lossless_quality_swaps_other_source_for_local_file(client, music, monkeypatch):
    client.post("/local/scan", headers=AUTH)

    async def fake_track_for(deps, source, source_id):
        return TrackInfo(source="deezer", source_id="9", title="Titre", artist="Artiste", album=None, year=None,
                         duration_seconds=2, cover_url=None)

    monkeypatch.setattr(stream, "_track_for", fake_track_for)
    got = client.get("/stream/deezer/9", headers=AUTH, params={"quality": "lossless"})
    assert got.status_code == 200 and got.headers["content-type"] == "audio/flac"
    assert client.post("/stream/deezer/9/prepare", headers=AUTH, params={"quality": "lossless"}).json()["local"] is True


def test_cover_falls_back_to_folder_image(client, music):
    (music / "Artiste/Album/cover.jpg").write_bytes(b"\xff\xd8jpeg")
    client.post("/local/scan", headers=AUTH)
    track = client.get("/local/tracks", headers=AUTH).json()["tracks"][0]
    got = client.get(f"/local/cover/{track['source_id']}")
    assert got.status_code == 200 and got.content == b"\xff\xd8jpeg"


def test_disabled_without_music_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("API_TOKEN", "test-token")
    monkeypatch.setenv("ALLOWED_USER_IDS", "")
    monkeypatch.setenv("BOT_TOKEN", "")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "sona.db"))
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "b"))
    monkeypatch.delenv("LOCAL_MUSIC_DIR", raising=False)
    import app.api.main as main_module

    with TestClient(main_module.app) as c:
        assert c.get("/local/status", headers=AUTH).json() == {"enabled": False, "tracks": 0}
        assert c.post("/local/scan", headers=AUTH).status_code == 404
