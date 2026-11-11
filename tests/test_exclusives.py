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


def test_credits_of_an_exclusive_do_not_fail(client):
    track = _add(client).json()
    got = client.get(f"/tracks/exclusive/{track['source_id']}/credits", headers=AUTH)
    assert got.status_code == 200
    assert got.json()["artists"][0]["name"] == "Un Artiste" and got.json()["release_date"] == "2019"


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


FLAC = b"fLaC" + bytes(range(200)) * 30


@pytest.fixture
def card_by_suffix(monkeypatch):
    """Les faux fichiers n'ont pas de vrais tags : la « fiche » dépend de l'extension."""
    from app.services import exclusives

    def read_file(root, path):
        if path.suffix == ".flac":
            return {"codec": "FLAC", "lossless": 1, "bitrate": None, "sample_rate": 96000, "bit_depth": 24}
        return {"codec": "MP3", "lossless": 0, "bitrate": 320000, "sample_rate": 44100, "bit_depth": None}

    monkeypatch.setattr(exclusives.local_library, "read_file", read_file)


def _add_flac(client, exclusive_id):
    return client.post(f"/exclusives/{exclusive_id}/versions", params={"filename": "master.flac"}, content=FLAC,
                       headers={**AUTH, "Content-Type": "audio/flac"})


def test_quality_is_read_from_the_file(client, card_by_suffix):
    track = _add(client).json()
    assert track["quality"] == "MP3 320 kbps" and track["lossless"] is False and track["versions"] == 1


def test_extra_lossless_version_is_picked_by_the_quality_setting(client, card_by_suffix):
    track = _add(client).json()
    sid = track["source_id"]
    added = _add_flac(client, sid)
    assert added.status_code == 201, added.text
    assert added.json()["quality"] == "FLAC 24 bits / 96 kHz" and added.json()["lossless"] is True and added.json()["versions"] == 2

    def get(**params):
        return client.get(f"/stream/exclusive/{sid}", params=params, headers=AUTH).content

    assert get() == FLAC  # meilleure disponible
    assert get(quality="lossless") == FLAC
    assert get(quality="standard") == AUDIO  # la plus légère
    versions = client.get(f"/exclusives/{sid}/versions", headers=AUTH).json()["versions"]
    assert [v["label"] for v in versions] == ["MP3 320 kbps", "FLAC 24 bits / 96 kHz"]
    assert get(version="main") == AUDIO
    assert get(version=versions[1]["id"]) == FLAC


def test_lossless_setting_falls_back_to_the_only_version(client, card_by_suffix):
    sid = _add(client).json()["source_id"]
    assert client.get(f"/stream/exclusive/{sid}", params={"quality": "lossless"}, headers=AUTH).content == AUDIO


def test_remove_a_version_and_the_original_stays(client, card_by_suffix):
    sid = _add(client).json()["source_id"]
    _add_flac(client, sid)
    storage = client.app.state.deps.exclusive_storage
    count = len(storage.files)
    vid = client.get(f"/exclusives/{sid}/versions", headers=AUTH).json()["versions"][1]["id"]
    done = client.delete(f"/exclusives/{sid}/versions/{vid}", headers=AUTH)
    assert done.status_code == 200 and done.json()["versions"] == 1
    assert len(storage.files) == count - 1
    assert client.delete(f"/exclusives/{sid}/versions/main", headers=AUTH).status_code == 404
    assert client.get(f"/stream/exclusive/{sid}", headers=AUTH).content == AUDIO


def test_deleting_an_exclusive_removes_every_version_from_discord(client, card_by_suffix):
    sid = _add(client).json()["source_id"]
    _add_flac(client, sid)
    assert client.delete(f"/exclusives/{sid}", headers=AUTH).status_code == 204
    assert not client.app.state.deps.exclusive_storage.files


def test_bad_version_files_are_refused(client):
    sid = _add(client).json()["source_id"]
    bad = client.post(f"/exclusives/{sid}/versions", params={"filename": "n.txt"}, content=b"x",
                      headers={**AUTH, "Content-Type": "text/plain"})
    assert bad.status_code == 415


# -- Identités et discographie (page d'un artiste « à identités ») -------------------

def _release_track(client, title, persona, album, number, order, kind=None, ctype="audio/mpeg"):
    params = {"title": title, "artist": persona, "artist_source": "deezer", "artist_source_id": "169773547",
              "filename": f"{title}.mp3", "persona": persona, "album": album, "track_number": number,
              "release_order": order}
    if kind:
        params["album_kind"] = kind
    return client.post("/exclusives", params=params, content=AUDIO, headers={**AUTH, "Content-Type": ctype})


def _set_personas(client, names):
    return client.put("/artists/deezer/169773547/personas", json={"names": names}, headers=AUTH)


def test_personas_are_set_in_order_without_duplicates(client):
    assert client.get("/artists/deezer/169773547/personas", headers=AUTH).json() == {"personas": []}
    got = _set_personas(client, ["FEMTOGO", " baby hayabusa ", "femtogo", "", "reggie petrucci"])
    assert got.json() == {"personas": ["FEMTOGO", "baby hayabusa", "reggie petrucci"]}
    assert client.get("/artists/deezer/169773547/personas", headers=AUTH).json()["personas"] == [
        "FEMTOGO", "baby hayabusa", "reggie petrucci"]
    assert _set_personas(client, []).json() == {"personas": []}


def test_personas_can_only_be_set_by_an_admin(client):
    assert client.put("/artists/deezer/1/personas", json={"names": ["x"]}).status_code == 401


def test_a_title_exists_once_per_persona_and_album(client):
    assert _release_track(client, "NEMBUTAL", "FEMTOGO", "NAMELESS BELLIGERENT", 1, 6).status_code == 201
    again = _release_track(client, "nembutal", "femtogo", "nameless belligerent", 1, 6)
    assert again.status_code == 409
    # Même titre dans une autre sortie, ou pour une autre identité : autorisé.
    assert _release_track(client, "NEMBUTAL", "FEMTOGO", "archives", 1, 8).status_code == 201
    assert _release_track(client, "NEMBUTAL", "baby hayabusa", "NAMELESS BELLIGERENT", 1, 1).status_code == 201
    assert len(client.get("/exclusives", headers=AUTH).json()["tracks"]) == 3


def test_discography_groups_by_persona_then_release_with_tracks_in_order(client):
    _set_personas(client, ["FEMTOGO", "baby hayabusa"])
    # Envoyés dans le désordre : la page range par identité, par rang de sortie, par numéro de piste.
    _release_track(client, "GEISER", "baby hayabusa", "Faded Flower Story", 2, 5)
    _release_track(client, "Novitchok", "FEMTOGO", "Sely - Novitchok", 1, 2, kind="single")
    _release_track(client, "SIEGFRIED", "FEMTOGO", "One Man Army", 1, 3)
    _release_track(client, "BLACKHAWK", "FEMTOGO", "One Man Army", 2, 3)
    _release_track(client, "SCOPOLAMINE", "FEMTOGO", "BRAVO-6", 3, 1)  # piste 3 puis piste 1 : tri par numéro
    _release_track(client, "VENTABLACK", "FEMTOGO", "BRAVO-6", 1, 1)
    # Un exclu sans identité (ancien format) n'est dans aucune sortie.
    client.post("/exclusives", params={"title": "Perdu", "artist": "FEMTOGO", "artist_source": "deezer",
                                       "artist_source_id": "169773547", "filename": "x.mp3"},
                content=AUDIO, headers={**AUTH, "Content-Type": "audio/mpeg"})
    got = client.get("/artists/deezer/169773547/discography", headers=AUTH).json()
    assert got["personas"] == ["FEMTOGO", "baby hayabusa"]
    assert [(r["persona"], r["album"], r["kind"], r["track_count"]) for r in got["releases"]] == [
        ("FEMTOGO", "BRAVO-6", "album", 2),
        ("FEMTOGO", "Sely - Novitchok", "single", 1),
        ("FEMTOGO", "One Man Army", "album", 2),
        ("baby hayabusa", "Faded Flower Story", "single", 1),
    ]
    bravo = got["releases"][0]
    assert [t["title"] for t in bravo["tracks"]] == ["VENTABLACK", "SCOPOLAMINE"]
    assert bravo["tracks"][0]["artist"] == "FEMTOGO" and bravo["tracks"][0]["album"] == "BRAVO-6"
    assert bravo["tracks"][0]["artist_source_id"] == "169773547"


def test_release_cover_is_the_first_real_cover(client):
    from app.services import exclusives as ex

    rows = [
        {"id": "a", "persona": "P", "album": "A", "album_kind": None, "release_order": 1, "cover_chunks": None},
        {"id": "b", "persona": "P", "album": "A", "album_kind": None, "release_order": 1, "cover_chunks": "[...]"},
    ]
    tracks = [
        {"source_id": "a", "title": "Un", "track_number": 1, "cover_url": "/neutre", "year": None, "duration_seconds": 10},
        {"source_id": "b", "title": "Deux", "track_number": 2, "cover_url": "/vraie", "year": None, "duration_seconds": 20},
    ]
    release = ex.build_releases(["P"], tracks, rows)[0]
    assert release["cover_url"] == "/vraie" and release["duration_seconds"] == 30 and release["kind"] == "album"


def test_patch_moves_an_existing_exclusive_into_a_release(client):
    created = _add(client).json()
    patched = client.patch(f"/exclusives/{created['source_id']}", headers=AUTH, json={
        "persona": "reggie petrucci", "album": "CONFESSIONAL INTOXICATION", "track_number": 4, "release_order": 4,
        "artist": "reggie petrucci"})
    assert patched.status_code == 200
    body = patched.json()
    assert (body["persona"], body["album"], body["track_number"], body["artist"]) == (
        "reggie petrucci", "CONFESSIONAL INTOXICATION", 4, "reggie petrucci")


def test_ep_is_a_release_kind_of_its_own(client):
    _set_personas(client, ["FEMTOGO"])
    for n, title in enumerate(["ADATA", "Draga Daï"], 1):
        assert _release_track(client, title, "FEMTOGO", "La Bête", n, 7, kind="ep").status_code == 201
    assert _release_track(client, "MKII", "FEMTOGO", "MKII", 1, 4, kind="single").status_code == 201
    assert _release_track(client, "ZAGA", "FEMTOGO", "archives", 1, 8, kind="album").status_code == 201
    kinds = {r["album"]: r["kind"] for r in client.get("/artists/deezer/169773547/discography", headers=AUTH).json()["releases"]}
    assert kinds == {"La Bête": "ep", "MKII": "single", "archives": "album"}
    # Un type inconnu retombe sur la valeur par défaut : un titre = single, plusieurs = album.
    assert _release_track(client, "X", "FEMTOGO", "Autre", 1, 9, kind="mixtape").status_code == 201
    assert {r["album"]: r["kind"] for r in client.get("/artists/deezer/169773547/discography", headers=AUTH).json()["releases"]}["Autre"] == "single"
