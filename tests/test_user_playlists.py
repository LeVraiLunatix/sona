"""Playlists de l'app : API (création, ajout, ordre, retrait) et import
Deezer / Spotify / Apple Music, sans appel réseau réel."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.providers.apple import parse_playlist_page
from app.providers.base import ExternalPlaylist, TrackInfo
from app.providers.spotify import parse_embed_playlist
from app.services import playlist_import
from app.services.playlist_import import PlaylistLink, detect_playlist_link, is_same_track

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


def track(n: int, source: str = "deezer", **extra) -> dict:
    return {
        "source": source, "source_id": str(n), "title": f"Titre {n}", "artist": "Artiste",
        "album": "Album", "year": "2024", "duration_seconds": 180, "cover_url": f"https://img/{n}.jpg",
        "artist_source_id": "7", "album_source_id": "8", **extra,
    }


def test_playlist_crud_flow(client):
    created = client.post("/me/playlists", headers=AUTH, json={"name": "  Soirée  ", "tracks": [track(1)]})
    assert created.status_code == 201
    body = created.json()
    pid = body["id"]
    assert body["name"] == "Soirée"
    assert body["track_count"] == 1
    assert body["import_status"] == "done"

    added = client.post(f"/me/playlists/{pid}/tracks", headers=AUTH, json={"tracks": [track(2), track(3), track(1)]})
    assert added.status_code == 200
    entries = added.json()["entries"]
    assert [e["track"]["source_id"] for e in entries] == ["1", "2", "3", "1"]  # doublon permis
    assert added.json()["duration_seconds"] == 720
    assert added.json()["covers"] == ["https://img/1.jpg", "https://img/2.jpg", "https://img/3.jpg"]

    ids = [e["entry_id"] for e in entries]
    reordered = client.put(f"/me/playlists/{pid}/order", headers=AUTH, json={"entry_ids": [ids[2], ids[0]]})
    assert [e["entry_id"] for e in reordered.json()["entries"]] == [ids[2], ids[0], ids[1], ids[3]]

    removed = client.delete(f"/me/playlists/{pid}/tracks/{ids[3]}", headers=AUTH)
    assert [e["track"]["source_id"] for e in removed.json()["entries"]] == ["3", "1", "2"]

    renamed = client.patch(f"/me/playlists/{pid}", headers=AUTH, json={"name": "Nuit"})
    assert renamed.json()["name"] == "Nuit"

    listed = client.get("/me/playlists", headers=AUTH).json()
    assert [p["name"] for p in listed] == ["Nuit"]
    assert listed[0]["track_count"] == 3

    assert client.delete(f"/me/playlists/{pid}", headers=AUTH).status_code == 204
    assert client.get(f"/me/playlists/{pid}", headers=AUTH).status_code == 404
    assert client.get("/me/playlists", headers=AUTH).json() == []


def test_playlist_rejects_unknown_source_and_missing_playlist(client):
    pid = client.post("/me/playlists", headers=AUTH, json={"name": "A"}).json()["id"]
    bad = client.post(f"/me/playlists/{pid}/tracks", headers=AUTH, json={"tracks": [track(1, source="napster")]})
    assert bad.status_code == 400
    assert client.post("/me/playlists/999/tracks", headers=AUTH, json={"tracks": [track(1)]}).status_code == 404
    assert client.post("/me/playlists", headers=AUTH, json={"name": ""}).status_code == 422


def test_import_rejects_unknown_links(client):
    resp = client.post("/me/playlists/import", headers=AUTH, json={"url": "https://example.com/x"})
    assert resp.status_code == 400
    resp = client.post("/me/playlists/import", headers=AUTH, json={"url": "https://www.deezer.com/fr/track/3135556"})
    assert resp.status_code == 400
    assert "playlist" in resp.json()["detail"]


def test_import_deezer_playlist_in_background(client):
    deps = client.app_state.deps
    tracks = [TrackInfo("deezer", str(i), f"T{i}", "A", None, None, 200, None) for i in range(3)]

    async def fake_fetch(playlist_id, max_tracks=1000):
        assert playlist_id == "908622995"
        return ExternalPlaylist("Ma playlist", None, "https://cover", tracks)

    deps.deezer.get_playlist_for_import = fake_fetch
    started = client.post(
        "/me/playlists/import", headers=AUTH, json={"url": "Écoute https://www.deezer.com/fr/playlist/908622995 !"}
    )
    assert started.status_code == 202
    pid = started.json()["id"]

    for _ in range(50):
        detail = client.get(f"/me/playlists/{pid}", headers=AUTH).json()
        if detail["import_status"] != "importing":
            break
        client.portal.call(asyncio.sleep, 0.02)
    assert detail["import_status"] == "done"
    assert detail["name"] == "Ma playlist"
    assert detail["cover_url"] == "https://cover"
    assert [e["track"]["source_id"] for e in detail["entries"]] == ["0", "1", "2"]
    assert detail["import_total"] == 3 and detail["import_missing"] == 0


# -- Lecture des pages publiques ---------------------------------------

def test_parse_spotify_embed_playlist():
    data = {"props": {"pageProps": {"state": {"data": {"entity": {
        "type": "playlist",
        "name": "Rap FR",
        "coverArt": {"sources": [{"url": "https://small", "width": 60}, {"url": "https://big", "width": 640}]},
        "trackList": [
            {"uri": "spotify:track:AAA", "title": "Grabba", "subtitle": "Ziak, Gazo", "duration": 181000},
            {"uri": "spotify:episode:BBB", "title": "Podcast", "subtitle": "X", "duration": 1},
            {"uri": "spotify:track:CCC", "title": "Akimbo", "subtitle": "Ziak", "duration": 150500,
             "audioPreview": {"url": "https://preview"}},
        ],
    }}}}}}
    page = f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></html>'
    playlist = parse_embed_playlist(page)
    assert playlist.name == "Rap FR"
    assert playlist.cover_url == "https://big"
    assert [(t.source_id, t.title, t.artist, t.duration_seconds) for t in playlist.tracks] == [
        ("AAA", "Grabba", "Ziak, Gazo", 181),
        ("CCC", "Akimbo", "Ziak", 150),
    ]
    assert playlist.tracks[1].preview_url == "https://preview"


def test_parse_spotify_embed_without_data_raises():
    from app.providers.spotify import SpotifyError

    with pytest.raises(SpotifyError):
        parse_embed_playlist("<html>rien</html>")


def test_parse_apple_playlist_page():
    server_data = [{"intent": {}, "data": {"sections": [
        {"itemKind": "containerDetailHeaderLockup", "items": [{"title": "Rap FR"}]},
        {"itemKind": "trackLockup", "items": [
            {
                "title": "Grabba", "artistName": "Ziak", "duration": 181000,
                "contentDescriptor": {"identifiers": {"storeAdamID": "1573842211"}},
                "artwork": {"dictionary": {"url": "https://is1.mzstatic.com/a/{w}x{h}bb.{f}"}},
                "tertiaryLinks": [{"title": "Akimbo"}],
            },
            {
                "title": "Sans ID", "subtitleLinks": [{"title": "Gazo"}, {"title": "Tiakola"}],
                "duration": 200000,
                "contentDescriptor": {"url": "https://music.apple.com/fr/song/sans-id/1600000001"},
            },
        ]},
    ]}}]
    page = (
        '<html><head><meta name="apple:title" content="Rap FR">'
        '<meta property="og:image" content="https://cover.jpg"></head><body>'
        f'<script type="application/json" id="serialized-server-data">{json.dumps(server_data)}</script>'
        "</body></html>"
    )
    playlist, ids = parse_playlist_page(page)
    assert ids == []
    assert playlist.name == "Rap FR"
    assert playlist.cover_url == "https://cover.jpg"
    first, second = playlist.tracks
    assert (first.source_id, first.title, first.artist, first.album, first.duration_seconds) == (
        "1573842211", "Grabba", "Ziak", "Akimbo", 181,
    )
    assert first.cover_url == "https://is1.mzstatic.com/a/1000x1000bb.jpg"
    assert (second.source_id, second.artist) == ("1600000001", "Gazo, Tiakola")


def test_parse_apple_playlist_page_falls_back_to_song_ids():
    ld = {"@type": "MusicPlaylist", "name": "X", "track": [
        {"@type": "MusicRecording", "name": "A", "url": "https://music.apple.com/fr/song/a/111111"},
        {"@type": "MusicRecording", "name": "B", "url": "https://music.apple.com/fr/song/b/222222"},
    ]}
    page = (
        '<html><head><meta property="og:title" content="Chill - Playlist - Apple Music"></head>'
        f'<script type="application/ld+json" id="schema:music-playlist">{json.dumps(ld)}</script></html>'
    )
    playlist, ids = parse_playlist_page(page)
    assert playlist.name == "Chill"
    assert playlist.tracks == []
    assert ids == ["111111", "222222"]


# -- Détection des liens -----------------------------------------------

@pytest.mark.parametrize(
    ("text", "source", "ref"),
    [
        ("https://open.spotify.com/playlist/37i9dQZF1DX1X23oiQRTB5?si=abc", "spotify", "37i9dQZF1DX1X23oiQRTB5"),
        ("https://www.deezer.com/fr/playlist/908622995", "deezer", "908622995"),
        (
            "https://music.apple.com/fr/playlist/ma-playlist/pl.u-8aAVZAxCkLoD9m?l=fr",
            "apple",
            "https://music.apple.com/fr/playlist/ma-playlist/pl.u-8aAVZAxCkLoD9m",
        ),
    ],
)
def test_detect_playlist_link(text, source, ref):
    link = asyncio.run(detect_playlist_link(text))
    assert (link.source, link.ref) == (source, ref)


def test_detect_playlist_link_rejects_albums():
    with pytest.raises(playlist_import.PlaylistImportError):
        asyncio.run(detect_playlist_link("https://open.spotify.com/album/abc"))


# -- Rapprochement avec Deezer -----------------------------------------

def _t(title, artist, duration=180, source="spotify", source_id="x"):
    return TrackInfo(source, source_id, title, artist, None, None, duration, None)


def test_is_same_track():
    assert is_same_track(_t("Grabba (feat. Gazo)", "Ziak, Gazo"), _t("Grabba", "Ziak", 183, "deezer"))
    assert is_same_track(_t("Été", "Angèle"), _t("ete", "Angele", 181, "deezer"))
    assert not is_same_track(_t("Grabba", "Ziak"), _t("Grabba", "Ziak", 240, "deezer"))  # autre version
    assert not is_same_track(_t("Grabba", "Ziak"), _t("Grabba", "Quelqu'un", 180, "deezer"))
    assert not is_same_track(_t("Grabba", "Ziak"), _t("Autre", "Ziak", 180, "deezer"))


class FakeDeezer:
    def __init__(self, catalog):
        self.catalog = catalog
        self.queries = []

    async def get_track_by_isrc(self, isrc):
        return next((t for t in self.catalog if t.isrc == isrc), None)

    async def search_tracks(self, query, index=0, limit=25):
        self.queries.append(query)
        found = [t for t in self.catalog if t.title.lower() in query.lower()]
        return found, len(found)


class FakeRepo:
    def __init__(self):
        self.updates = []
        self.tracks = []

    async def playlist_update(self, playlist_id, **fields):
        self.updates.append(fields)

    async def playlist_add_tracks(self, playlist_id, tracks):
        self.tracks = tracks


def test_run_import_matches_on_deezer_and_keeps_order(monkeypatch):
    monkeypatch.setattr(playlist_import, "DEEZER_REQUESTS_PER_SECOND", 1000)
    grabba = TrackInfo("deezer", "1", "Grabba", "Ziak", "Akimbo", None, 181, "https://c1", isrc="FR1")
    akimbo = TrackInfo("deezer", "2", "Akimbo", "Ziak", "Akimbo", None, 150, "https://c2")
    source = [
        TrackInfo("spotify", "S1", "Grabba", "Ziak", None, None, 181, None, isrc="FR1"),
        TrackInfo("spotify", "S2", "Inconnu", "Personne", None, None, 100, None),
        TrackInfo("spotify", "S3", "Akimbo", "Ziak", None, None, 151, None),
        TrackInfo("apple", "", "Introuvable", "X", None, None, 100, None),
    ]

    class Spotify:
        async def get_playlist(self, playlist_id):
            return ExternalPlaylist("Import", "desc", None, source)

    class Deps:
        deezer = FakeDeezer([grabba, akimbo])
        spotify = Spotify()
        repo = FakeRepo()

    deps = Deps()
    asyncio.run(playlist_import.run_import(deps, 1, PlaylistLink("spotify", "abc", "https://x")))
    # Deezer si trouvé, sinon la source d'origine ; rien si l'origine est illisible.
    assert [t.uid for t in deps.repo.tracks] == ["deezer:1", "spotify:S2", "deezer:2"]
    final = deps.repo.updates[-1]
    assert final == {"import_status": "done", "import_done": 4, "import_missing": 1}
    assert deps.repo.updates[0]["name"] == "Import"


def test_run_import_reports_failure():
    class Spotify:
        async def get_playlist(self, playlist_id):
            from app.providers.spotify import SpotifyError

            raise SpotifyError("Playlist Spotify introuvable (privée ou supprimée ?)")

    class Deps:
        spotify = Spotify()
        repo = FakeRepo()

    deps = Deps()
    asyncio.run(playlist_import.run_import(deps, 1, PlaylistLink("spotify", "abc", "https://x")))
    assert deps.repo.updates == [
        {"import_status": "failed", "import_error": "Playlist Spotify introuvable (privée ou supprimée ?)"}
    ]


# -- Apple Music : au-delà des 300 titres de la page ---------------------

import httpx  # noqa: E402

from app.providers.apple import AppleMusicClient  # noqa: E402

FAKE_TOKEN = "eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCJ9." + "a" * 40 + "." + "b" * 40
PLAYLIST_URL = "https://music.apple.com/fr/playlist/ma-playlist/pl.u-8aAVZAxCkLoD9m"


def _apple_page(n_tracks: int) -> str:
    items = [
        {"title": f"T{i}", "artistName": "A", "duration": 1000,
         "contentDescriptor": {"identifiers": {"storeAdamID": str(100000 + i)}}}
        for i in range(n_tracks)
    ]
    data = [{"data": {"sections": [{"itemKind": "trackLockup", "items": items}]}}]
    return (
        '<html><head><meta name="apple:title" content="Grosse playlist"></head><body>'
        f'<script type="application/json" id="serialized-server-data">{json.dumps(data)}</script>'
        '<script type="module" crossorigin src="/assets/index~abc123.js"></script>'
        "</body></html>"
    )


def _media_item(i: int) -> dict:
    return {"id": str(100000 + i), "type": "songs", "attributes": {
        "name": f"T{i}", "artistName": "A", "albumName": "Album", "durationInMillis": 200000,
        "isrc": f"ISRC{i}", "releaseDate": "2024-01-01",
        "artwork": {"url": "https://is1.mzstatic.com/x/{w}x{h}bb.jpg"},
    }}


def test_apple_playlist_reads_past_the_page_limit_with_the_web_api():
    seen_auth = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith(PLAYLIST_URL):
            return httpx.Response(200, text=_apple_page(300))
        if url == "https://music.apple.com/assets/index~abc123.js":
            return httpx.Response(200, text=f'var a="x";const t="{FAKE_TOKEN}";')
        if "amp-api.music.apple.com" in url:
            seen_auth.append(request.headers.get("authorization"))
            offset = int(request.url.params.get("offset", "0"))
            batch = [_media_item(i) for i in range(offset, min(offset + 100, 550))]
            body = {"data": batch}
            if offset + 100 < 550:
                body["next"] = f"/v1/catalog/fr/playlists/pl.u-8aAVZAxCkLoD9m/tracks?offset={offset + 100}"
            return httpx.Response(200, json=body)
        return httpx.Response(404)

    client = AppleMusicClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    playlist = asyncio.run(client.get_playlist(PLAYLIST_URL))
    assert playlist.name == "Grosse playlist"
    assert len(playlist.tracks) == 550
    assert playlist.tracks[549].isrc == "ISRC549"
    assert playlist.tracks[0].cover_url == "https://is1.mzstatic.com/x/1000x1000bb.jpg"
    assert set(seen_auth) == {f"Bearer {FAKE_TOKEN}"}
    assert len(seen_auth) == 6


def test_apple_playlist_falls_back_to_the_page_without_token():
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(PLAYLIST_URL):
            return httpx.Response(200, text=_apple_page(300))
        return httpx.Response(200, text="pas de jeton ici")

    client = AppleMusicClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    playlist = asyncio.run(client.get_playlist(PLAYLIST_URL))
    assert len(playlist.tracks) == 300


def test_reimport_replaces_tracks_and_keeps_name(client):
    deps = client.app_state.deps
    rounds = [
        [TrackInfo("deezer", str(i), f"T{i}", "A", None, None, 200, None) for i in range(3)],
        [TrackInfo("deezer", str(i), f"T{i}", "A", None, None, 200, None) for i in range(5)],
    ]

    async def fake_fetch(playlist_id, max_tracks=1000):
        return ExternalPlaylist("Nom d'origine", None, None, rounds.pop(0))

    deps.deezer.get_playlist_for_import = fake_fetch

    def wait_done(pid):
        for _ in range(50):
            detail = client.get(f"/me/playlists/{pid}", headers=AUTH).json()
            if detail["import_status"] != "importing":
                return detail
            client.portal.call(asyncio.sleep, 0.02)
        raise AssertionError("import jamais terminé")

    pid = client.post(
        "/me/playlists/import", headers=AUTH, json={"url": "https://www.deezer.com/playlist/1"}
    ).json()["id"]
    assert wait_done(pid)["track_count"] == 3
    client.patch(f"/me/playlists/{pid}", headers=AUTH, json={"name": "Renommée"})

    assert client.post(f"/me/playlists/{pid}/reimport", headers=AUTH).status_code == 202
    detail = wait_done(pid)
    assert detail["import_status"] == "done"
    assert detail["name"] == "Renommée"
    assert [e["track"]["source_id"] for e in detail["entries"]] == ["0", "1", "2", "3", "4"]

    manual = client.post("/me/playlists", headers=AUTH, json={"name": "Perso"}).json()["id"]
    assert client.post(f"/me/playlists/{manual}/reimport", headers=AUTH).status_code == 400
