"""Exclus : ajout par l'admin, stockage (faux Discord en mémoire), page artiste, lecture."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.services.discord_storage import Chunk, DiscordStorage, StorageError

AUTH = {"Authorization": "Bearer test-token"}


class FakeDiscord(DiscordStorage):
    """Un « salon Discord » en mémoire : mêmes méthodes, aucun réseau."""

    def __init__(self) -> None:
        super().__init__("https://discord.test/webhook")
        self.files: dict[str, bytes] = {}
        self.fail_on_part: int | None = None

    async def put_chunk(self, data: bytes, filename: str, index: int) -> Chunk:
        if self.fail_on_part == index:
            raise StorageError("Discord en panne")
        mid = f"m{len(self.files)}"
        self.files[mid] = data
        return Chunk(index, len(data), mid, f"a{mid}", f"https://cdn.test/{mid}")

    async def read(self, chunk: Chunk) -> bytes:
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
    monkeypatch.setenv("EXCLUSIVES_CACHE_DIR", str(tmp_path / "exclusives"))
    import app.api.main as main_module

    with TestClient(main_module.app) as test_client:
        test_client.app.state.deps.exclusive_storage = FakeDiscord()
        yield test_client


AUDIO = b"ID3" + bytes(range(256)) * 40


def _add(client, ctype="audio/mpeg", **params):
    query = {"title": "Jamais sorti", "artist": "Un Artiste", "artist_source": "deezer", "artist_source_id": "42",
             "year": "2019", "filename": "demo.mp3", **params}
    return client.post("/exclusives", params=query, content=AUDIO, headers={**AUTH, "Content-Type": ctype})


def test_status_reports_disabled_without_webhook(client):
    client.app.state.deps.exclusive_storage = DiscordStorage(None)
    assert client.get("/exclusives/status", headers=AUTH).json() == {"enabled": False, "can_add": False}
    assert _add(client).status_code == 503


def test_add_then_listed_on_artist_page_with_tag_and_year(client):
    created = _add(client)
    assert created.status_code == 201, created.text
    track = created.json()
    assert track["source"] == "exclusive" and track["tag"] == "Exclu" and track["year"] == "2019"
    assert track["artist_source"] == "deezer" and track["artist_source_id"] == "42"

    on_page = client.get("/artists/deezer/42/exclusives", params={"name": "Un Artiste"}, headers=AUTH).json()["tracks"]
    assert [t["source_id"] for t in on_page] == [track["source_id"]]
    assert client.get("/artists/deezer/99/exclusives", headers=AUTH).json()["tracks"] == []
    assert len(client.get("/exclusives", headers=AUTH).json()["tracks"]) == 1


def test_unreleased_kind_changes_the_tag(client):
    track = _add(client, kind="inedit").json()
    assert track["tag"] == "Inédit"


def test_artist_typed_without_profile_matches_by_name(client):
    _add(client, artist_source="", artist_source_id="", artist="Un Artiste")
    found = client.get("/artists/deezer/42/exclusives", params={"name": "un artiste"}, headers=AUTH).json()["tracks"]
    assert len(found) == 1


def test_stream_returns_the_exact_file_and_supports_ranges(client):
    track = _add(client).json()
    prepared = client.post(f"/stream/exclusive/{track['source_id']}/prepare", headers=AUTH)
    assert prepared.json() == {"ready": True}
    full = client.get(f"/stream/exclusive/{track['source_id']}", headers=AUTH)
    assert full.status_code == 200 and full.content == AUDIO
    part = client.get(f"/stream/exclusive/{track['source_id']}", headers={**AUTH, "Range": "bytes=3-9"})
    assert part.status_code == 206 and part.content == AUDIO[3:10]


def test_track_details_route_knows_exclusives(client):
    track = _add(client).json()
    got = client.get(f"/tracks/exclusive/{track['source_id']}", headers=AUTH)
    assert got.status_code == 200 and got.json()["title"] == "Jamais sorti"
    assert client.get("/tracks/exclusive/nope", headers=AUTH).status_code == 404


def test_cover_falls_back_to_a_neutral_svg(client):
    track = _add(client).json()
    cover = client.get(f"/exclusives/cover/{track['source_id']}")
    assert cover.status_code == 200 and cover.headers["content-type"].startswith("image/svg+xml")


def test_custom_cover_is_stored_and_served(client):
    track = _add(client).json()
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    done = client.post(f"/exclusives/{track['source_id']}/cover", content=png, headers={**AUTH, "Content-Type": "image/png"})
    assert done.status_code == 200
    cover = client.get(f"/exclusives/cover/{track['source_id']}")
    assert cover.content == png and cover.headers["content-type"] == "image/png"


def test_edit_and_delete_clean_up_discord(client):
    track = _add(client).json()
    storage = client.app.state.deps.exclusive_storage
    assert storage.files
    edited = client.patch(f"/exclusives/{track['source_id']}", json={"year": "2021", "kind": "inedit"}, headers=AUTH).json()
    assert edited["year"] == "2021" and edited["tag"] == "Inédit"
    assert client.patch(f"/exclusives/{track['source_id']}", json={"kind": "x"}, headers=AUTH).status_code == 400
    assert client.delete(f"/exclusives/{track['source_id']}", headers=AUTH).status_code == 204
    assert not storage.files
    assert client.get("/exclusives", headers=AUTH).json()["tracks"] == []


def test_failed_discord_upload_leaves_nothing_behind(client):
    storage = client.app.state.deps.exclusive_storage
    storage.fail_on_part = 0
    assert _add(client).status_code == 502
    assert client.get("/exclusives", headers=AUTH).json()["tracks"] == []
    assert not storage.files


def test_bad_inputs_are_refused(client):
    assert _add(client, ctype="text/plain", filename="notes.txt").status_code == 415
    empty = client.post("/exclusives", params={"title": "x", "artist": "y", "filename": "a.mp3"}, content=b"",
                        headers={**AUTH, "Content-Type": "audio/mpeg"})
    assert empty.status_code == 400
    assert client.get("/exclusives").status_code in (401, 403)


def test_only_admins_can_add(client):
    assert client.post("/exclusives", params={"title": "x", "artist": "y", "filename": "a.mp3"}, content=AUDIO).status_code in (401, 403)
