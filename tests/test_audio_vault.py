"""Coffre audio Drivecord : un titre préparé est mis de côté dans un « salon
Discord » (faux, en mémoire), retrouvé quand le disque l'a effacé — même si
YouTube est en panne — et oublié quand on signale une mauvaise version."""

from __future__ import annotations

import dataclasses
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.routers import stream
from app.services import audio_vault
from app.services.discord_storage import Chunk, DiscordStorage, StorageError

AUTH = {"Authorization": "Bearer test-token"}
AUDIO = b"audio-" + bytes(range(256)) * 20


class FakeDiscord(DiscordStorage):
    def __init__(self) -> None:
        super().__init__("https://discord.test/webhook")
        self.files: dict[str, bytes] = {}
        self.broken = False

    async def put_chunk(self, data: bytes, filename: str, index: int) -> Chunk:
        mid = f"m{len(self.files)}"
        self.files[mid] = data
        return Chunk(index, len(data), mid, f"a{mid}", f"https://cdn.test/{mid}")

    async def read(self, chunk: Chunk) -> bytes:
        if self.broken or chunk.message_id not in self.files:
            raise StorageError("Discord 404")
        return self.files[chunk.message_id]

    async def delete(self, chunks: list[Chunk]) -> None:
        for chunk in chunks:
            self.files.pop(chunk.message_id, None)


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("API_TOKEN", "test-token")
    monkeypatch.setenv("ALLOWED_USER_IDS", "")
    monkeypatch.setenv("BOT_TOKEN", "")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "sona.db"))
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "backups"))
    stream._failures.clear()
    stream._live.clear()
    audio_vault._strikes.clear()
    audio_vault._pending.clear()

    async def no_live(deps, source, source_id, key):
        return None

    monkeypatch.setattr(stream, "_live_source", no_live)
    import app.api.main as main_module

    with TestClient(main_module.app) as test_client:
        test_client.vault = FakeDiscord()
        deps = test_client.app.state.deps
        deps.vault_storage = test_client.vault
        # Le cache du serveur dans le dossier du test, jamais dans data/ du projet.
        deps.settings = dataclasses.replace(deps.settings, stream_cache_dir=tmp_path / "stream_cache")
        yield test_client
    stream._failures.clear()
    stream._live.clear()


def downloader(tmp_path: Path, monkeypatch):
    calls = []

    async def fake_download(deps, source, source_id, quality, fmt):
        calls.append(source_id)
        # Comme le vrai téléchargement : le fichier atterrit dans le cache du serveur.
        dest = stream._persistent_path(deps, source, source_id, fmt, quality, ".m4a")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(AUDIO)
        await deps.repo.stream_cache_set(source, source_id, fmt, quality, str(dest), "audio/mp4")
        return dest

    monkeypatch.setattr(stream, "_resolve_and_download", fake_download)
    return calls


def wait_for(predicate, seconds=5.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def cached_file(client, source_id="42") -> Path:
    deps = client.app.state.deps
    return stream._persistent_path(deps, "deezer", source_id, "auto", "best", ".m4a")


def prepare_and_vault(client, tmp_path, monkeypatch):
    calls = downloader(tmp_path, monkeypatch)
    assert client.post("/stream/deezer/42/prepare", headers=AUTH).status_code == 200
    assert wait_for(lambda: bool(client.vault.files)), "le titre n'a pas été mis de côté"
    return calls


def test_prepared_track_is_put_aside_in_the_vault(client, tmp_path, monkeypatch):
    prepare_and_vault(client, tmp_path, monkeypatch)
    assert b"".join(client.vault.files.values()) == AUDIO


def test_track_erased_from_disk_comes_back_from_the_vault_without_downloading(client, tmp_path, monkeypatch):
    calls = prepare_and_vault(client, tmp_path, monkeypatch)
    cached_file(client).unlink()  # le cache du disque l'a effacé
    served = client.get("/stream/deezer/42", headers=AUTH)
    assert served.status_code == 200 and served.content == AUDIO
    assert calls == ["42"], "aucun nouveau téléchargement"
    assert cached_file(client).is_file()


def test_vault_still_serves_when_the_source_is_down(client, tmp_path, monkeypatch):
    prepare_and_vault(client, tmp_path, monkeypatch)
    cached_file(client).unlink()
    stream._failures[("deezer", "42", "auto", "best")] = (time.monotonic(), 502, "YouTube bloque le serveur")
    served = client.get("/stream/deezer/42", headers=AUTH)
    assert served.status_code == 200 and served.content == AUDIO


def test_unreadable_vault_falls_back_to_downloading_then_forgets_the_copy(client, tmp_path, monkeypatch):
    calls = prepare_and_vault(client, tmp_path, monkeypatch)
    client.vault.broken = True
    for expected_calls in (2, 3):
        cached_file(client).unlink()
        assert client.get("/stream/deezer/42", headers=AUTH).status_code == 200
        assert len(calls) == expected_calls
        # Laisse finir l'envoi en arrière-plan avant la requête suivante (sinon il serait « déjà en cours »).
        assert wait_for(lambda: not audio_vault._pending)
    # Deux échecs de lecture : la copie perdue est oubliée, et le titre retéléchargé
    # est remis de côté — le coffre se répare tout seul.
    assert wait_for(lambda: bool(client.vault.files))
    client.vault.broken = False
    cached_file(client).unlink()
    served = client.get("/stream/deezer/42", headers=AUTH)
    assert served.status_code == 200 and served.content == AUDIO
    assert len(calls) == 3, "la nouvelle copie a servi, sans quatrième téléchargement"


def test_wrong_version_forgets_the_vault_copy(client, tmp_path, monkeypatch):
    prepare_and_vault(client, tmp_path, monkeypatch)
    assert client.post("/stream/deezer/42/wrong-version", headers=AUTH).status_code == 200
    assert client.vault.files == {}


def test_vault_is_off_without_a_webhook(client, tmp_path, monkeypatch):
    client.app.state.deps.vault_storage = DiscordStorage(None)
    downloader(tmp_path, monkeypatch)
    assert client.post("/stream/deezer/42/prepare", headers=AUTH).status_code == 200
    time.sleep(0.3)
    assert client.vault.files == {}


def test_vault_can_be_switched_off(client, tmp_path, monkeypatch):
    deps = client.app.state.deps
    deps.settings = dataclasses.replace(deps.settings, audio_vault=False)
    downloader(tmp_path, monkeypatch)
    assert client.post("/stream/deezer/42/prepare", headers=AUTH).status_code == 200
    time.sleep(0.3)
    assert client.vault.files == {}


def test_oversized_file_is_not_kept(client, tmp_path, monkeypatch):
    monkeypatch.setattr(audio_vault, "MAX_FILE_BYTES", 10)
    downloader(tmp_path, monkeypatch)
    assert client.post("/stream/deezer/42/prepare", headers=AUTH).status_code == 200
    time.sleep(0.3)
    assert client.vault.files == {}


# -- Rattrapage : les titres déjà sur le disque partent peu à peu au coffre -----

def seed_disk(client, ids, tmp_path, missing=()):
    """Titres déjà en cache sur le disque (comme avant l'arrivée du coffre)."""
    deps = client.app.state.deps
    for i in ids:
        path = stream._persistent_path(deps, "deezer", i, "auto", "best", ".m4a")
        path.parent.mkdir(parents=True, exist_ok=True)
        if i not in missing:
            path.write_bytes(AUDIO + i.encode())
        client.portal.call(deps.repo.stream_cache_set, "deezer", i, "auto", "best", str(path), "audio/mp4")
        time.sleep(1.05)  # created_at est à la seconde : l'ordre « récents d'abord » doit se voir


def backfill(client, batch=4):
    return client.portal.call(audio_vault.backfill_once, client.app.state.deps, batch)


def test_backfill_sends_the_tracks_already_on_disk(client, tmp_path):
    audio_vault._skipped.clear()
    seed_disk(client, ["1", "2", "3"], tmp_path)
    assert backfill(client) == 3
    assert sorted(client.vault.files.values()) == sorted(AUDIO + i.encode() for i in "123")
    assert backfill(client) == 0, "tout est déjà dans le coffre"


def test_backfill_goes_by_batches_most_recent_first(client, tmp_path):
    audio_vault._skipped.clear()
    seed_disk(client, ["1", "2", "3"], tmp_path)
    assert backfill(client, batch=2) == 2
    assert sorted(client.vault.files.values()) == sorted([AUDIO + b"3", AUDIO + b"2"])
    assert backfill(client, batch=2) == 1


def test_backfill_skips_missing_files_without_retrying_them(client, tmp_path):
    audio_vault._skipped.clear()
    seed_disk(client, ["1", "2"], tmp_path, missing=("2",))
    assert backfill(client) == 1
    assert ("deezer", "2", "auto", "best") in audio_vault._skipped
    assert backfill(client) == 0


def test_backfill_does_nothing_when_off(client, tmp_path):
    audio_vault._skipped.clear()
    seed_disk(client, ["1"], tmp_path)
    deps = client.app.state.deps
    deps.settings = dataclasses.replace(deps.settings, audio_vault_backfill=False)
    assert backfill(client) == 0 and client.vault.files == {}
