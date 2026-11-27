"""« Mes fichiers » : seuls de vrais audios passent, réécrits au propre, visibles de leur seul propriétaire."""

from __future__ import annotations

import io
import math
import shutil
import struct
import wave

import pytest

from app.services import uploads
from app.services.discord_storage import DiscordStorage, StorageError
from tests.test_audio_vault import FakeDiscord
from tests.test_api_browse import AUTH, client  # noqa: F401  (client : fixture)

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg absent")


def tone(seconds: float = 2.0) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(i / 5))) for i in range(int(8000 * seconds))))
    return out.getvalue()


def test_sniff_knows_audio_and_refuses_the_rest():
    assert uploads.sniff(b"ID3\x04" + b"\0" * 12) == "mp3"
    assert uploads.sniff(b"\0\0\0\x20ftypM4A " + b"\0" * 4) == "m4a"
    assert uploads.sniff(tone()[:16]) == "wav"
    for bad in (b"MZ\x90\x00", b"<html><script>", b"#EXTM3U\n", b"PK\x03\x04", b"\x7fELF", b""):
        assert uploads.sniff(bad) is None, bad


def test_names_and_tags_are_cleaned(tmp_path):
    empty = tmp_path / "x"
    empty.write_bytes(b"rien")
    assert uploads.describe(empty, "..\\..\\Daft Punk - One\x00 More‮ Time.mp3") == ("One More Time", "Daft Punk", None)
    assert uploads.describe(empty, "")[:2] == ("Sans titre", "Artiste inconnu")


@pytest.fixture
def box(client, tmp_path):
    client.app.state.deps.settings = __import__("dataclasses").replace(client.app.state.deps.settings, uploads_dir=tmp_path / "envois")
    client.app.state.deps.vault_storage = DiscordStorage(None)  # sans webhook : tout reste sur le disque
    return client, tmp_path / "envois"


def send(client, data: bytes, name: str = "Moi - Mon son.wav"):
    return client.post("/uploads", params={"filename": name}, content=data, headers=AUTH)


@needs_ffmpeg
def test_upload_listen_add_to_a_playlist_and_delete(box):
    client, folder = box
    # Charge utile ajoutée à la fin : elle ne doit pas survivre à la réécriture.
    got = send(client, tone() + b"<script>alert(1)</script>MZ-charge")
    assert got.status_code == 201, got.text
    track = got.json()
    assert (track["source"], track["title"], track["artist"], track["duration_seconds"]) == ("upload", "Mon son", "Moi", 2)
    (stored,) = folder.iterdir()
    assert stored.suffix == ".flac" and stored.read_bytes().startswith(b"fLaC")
    assert b"alert(1)" not in stored.read_bytes() and stored.stem != "Moi - Mon son"

    listed = client.get("/uploads", headers=AUTH).json()
    assert [t["source_id"] for t in listed["tracks"]] == [track["source_id"]] and listed["used_bytes"] > 0
    assert any(i["source_id"] == track["source_id"] for i in client.get("/library/track", headers=AUTH).json()["items"])

    played = client.get(f"/stream/upload/{track['source_id']}", headers=AUTH)
    assert played.status_code == 200 and played.headers["content-type"] == "audio/flac"
    assert client.get(f"/stream/upload/{track['source_id']}").status_code == 401

    playlist = client.post("/me/playlists", json={"name": "À moi", "tracks": [track]}, headers=AUTH)
    assert playlist.status_code == 201, playlist.text

    assert client.delete(f"/uploads/{track['source_id']}", headers=AUTH).status_code == 204
    assert list(folder.iterdir()) == []
    assert client.get(f"/stream/upload/{track['source_id']}", headers=AUTH).status_code == 404
    assert client.get(f"/me/playlists/{playlist.json()['id']}", headers=AUTH).json()["entries"] == []


@needs_ffmpeg
def test_fake_audio_too_big_and_full_space_are_refused(box, monkeypatch):
    client, folder = box
    for payload in (b"MZ" + b"\0" * 5000, b"<html></html>" * 100, b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"pas du son" * 200):
        assert send(client, payload, "piege.mp3").status_code == 415
    monkeypatch.setattr(uploads, "MAX_FILE_BYTES", 1000)
    assert send(client, tone()).status_code == 413
    monkeypatch.setattr(uploads, "MAX_FILE_BYTES", 10**8)
    monkeypatch.setattr(uploads, "MAX_FILES", 0)
    assert send(client, tone()).status_code == 413
    assert not folder.exists() or list(folder.iterdir()) == []


@needs_ffmpeg
def test_files_live_on_drivecord_and_come_back_when_the_copy_is_gone(box):
    client, folder = box
    drive = client.app.state.deps.vault_storage = FakeDiscord()
    track = send(client, tone()).json()
    assert drive.files
    (copy,) = (folder / "cache").iterdir()
    original = copy.read_bytes()
    copy.unlink()
    played = client.get(f"/stream/upload/{track['source_id']}", headers=AUTH)
    assert played.status_code == 200 and played.content == original
    assert client.delete(f"/uploads/{track['source_id']}", headers=AUTH).status_code == 204
    assert not drive.files and list((folder / "cache").iterdir()) == []

    async def broken(parts, filename):
        raise StorageError("en panne")

    drive.store = broken
    assert send(client, tone()).status_code == 502
    assert client.get("/uploads", headers=AUTH).json()["tracks"] == []
    assert [p for p in folder.rglob("*") if p.is_file()] == []


def test_admins_get_ten_gigabytes_others_the_configured_quota():
    from types import SimpleNamespace

    from app.api.routers.uploads import _quota

    settings = SimpleNamespace(upload_quota_mb=1024)
    assert _quota(SimpleNamespace(settings=settings, is_admin=False)) == 1024**3
    assert _quota(SimpleNamespace(settings=settings, is_admin=True)) == 10 * 1024**3


def test_another_account_cannot_read_my_file(tmp_path):
    import asyncio

    from app.db.database import Database
    from app.db.repository import Repository

    async def main():
        db = Database(tmp_path / "a.db")
        await db.connect()
        repo = Repository(db)
        row = {"id": "f1", "user_id": 1, "title": "t", "artist": "a", "album": None, "duration_seconds": 2, "mime": "audio/flac", "size": 10, "path": "x.flac"}
        try:
            assert await repo.upload_add(row, 5, 100)
            assert not await repo.upload_add({**row, "id": "f2", "size": 95}, 5, 100)  # quota
            assert await repo.upload_get(2, "f1") is None and await repo.upload_delete(2, "f1") is None
            assert "path" not in (await repo.export_user_data(1))["uploads"][0]
        finally:
            await db.close()

    asyncio.run(main())
