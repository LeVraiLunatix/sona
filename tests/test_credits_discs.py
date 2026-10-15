"""Artistes en featuring, disques d'un album, crédits d'un titre et paroles
plus tenaces — fournisseurs remplacés par de faux transports httpx."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.providers import deezer as deezer_module
from app.providers.base import TrackInfo
from app.providers.deezer import DeezerClient, _track_from_json
from app.providers.lrclib import LrclibClient
from app.providers.musicbrainz import MusicBrainzClient, parse_credits

AUTH = {"Authorization": "Bearer test-token"}


def test_deezer_track_reads_contributors_and_disc():
    track = _track_from_json({
        "id": 1, "title": "Titre", "artist": {"id": 10, "name": "Ziak"},
        "disk_number": 2, "track_position": 5,
        "contributors": [
            {"id": 10, "name": "Ziak", "role": "Main"},
            {"id": 11, "name": "Gazo", "role": "Featured"},
            {"id": 11, "name": "Gazo", "role": "Featured"},
        ],
    })
    assert (track.disc_number, track.track_number) == (2, 5)
    assert track.artists == [
        {"name": "Ziak", "source_id": "10", "role": "main"},
        {"name": "Gazo", "source_id": "11", "role": "featured"},
    ]


def test_deezer_album_gets_discs_and_feats_from_track_pages(monkeypatch):
    monkeypatch.setattr(deezer_module, "ALBUM_DETAIL_PAUSE", 0)
    details = {
        "1": {"disk_number": 1, "track_position": 1},
        "2": {"disk_number": 1, "track_position": 2, "contributors": [{"id": 7, "name": "Invité", "role": "Featured"}]},
        # Fiche indisponible : le titre suit le disque du précédent.
        "4": {"disk_number": 2, "track_position": 1},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/album/9":
            return httpx.Response(200, json={
                "id": 9, "title": "Double", "artist": {"id": 3, "name": "Artiste"}, "nb_tracks": 4,
                "tracks": {"data": [{"id": i, "title": f"T{i}", "artist": {"id": 3, "name": "Artiste"}} for i in (1, 2, 3, 4)]},
            })
        track_id = path.rsplit("/", 1)[1]
        if track_id in details:
            return httpx.Response(200, json={"id": int(track_id), "title": "x", "artist": {"id": 3, "name": "Artiste"}, **details[track_id]})
        return httpx.Response(200, json={"error": {"type": "DataException", "message": "no data", "code": 800}})

    client = DeezerClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    album = asyncio.run(client.get_album("9"))
    assert [t.disc_number for t in album.tracks] == [1, 1, 1, 2]
    assert [t.track_number for t in album.tracks] == [1, 2, None, 1]
    assert album.tracks[1].artists == [{"name": "Invité", "source_id": "7", "role": "featured"}]


def test_parse_musicbrainz_credits():
    recording = {"relations": [
        {"type": "producer", "target-type": "artist", "artist": {"name": "Beatmaker"}},
        {"type": "mix", "target-type": "artist", "artist": {"name": "Mixeur"}},
        {"type": "vocal", "target-type": "artist", "artist": {"name": "Chanteuse"}},
        {"type": "performance", "target-type": "work", "work": {"relations": [
            {"type": "composer", "target-type": "artist", "artist": {"name": "Compo"}},
            {"type": "lyricist", "target-type": "artist", "artist": {"name": "Parolier"}},
            {"type": "composer", "target-type": "artist", "artist": {"name": "Compo"}},
        ]}},
    ]}
    assert parse_credits(recording) == [
        {"role": "Compositeur", "names": ["Compo"]},
        {"role": "Parolier", "names": ["Parolier"]},
        {"role": "Producteur", "names": ["Beatmaker"]},
        {"role": "Mixage", "names": ["Mixeur"]},
    ]


def test_musicbrainz_looks_up_recording_by_isrc_and_caches(monkeypatch):
    monkeypatch.setattr("app.providers.musicbrainz.MIN_INTERVAL", 0)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.startswith("/ws/2/isrc/"):
            return httpx.Response(200, json={"recordings": [{"id": "abc"}]})
        return httpx.Response(200, json={"relations": [{"type": "producer", "target-type": "artist", "artist": {"name": "P"}}]})

    client = MusicBrainzClient(httpx.AsyncClient(base_url="https://musicbrainz.org/ws/2", transport=httpx.MockTransport(handler)))
    expected = [{"role": "Producteur", "names": ["P"]}]
    assert asyncio.run(client.credits_by_isrc("fr123")) == expected
    assert asyncio.run(client.credits_by_isrc("FR123")) == expected
    assert calls == ["/ws/2/isrc/FR123", "/ws/2/recording/abc"]


def test_lyrics_free_text_search_rescues_a_different_spelling():
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        if request.url.path == "/api/get":
            return httpx.Response(404)
        if "q" in request.url.params:
            return httpx.Response(200, json=[
                {"duration": 200, "artistName": "Autre Groupe", "syncedLyrics": "[00:01.00]Pas lui"},
                {"duration": 201, "artistName": "Aya Nakamura", "syncedLyrics": "[00:02.00]Lui"},
            ])
        return httpx.Response(200, json=[])

    client = LrclibClient(httpx.AsyncClient(base_url="https://lrclib.net/api", transport=httpx.MockTransport(handler)))
    lyrics = asyncio.run(client.get_lyrics("Djadja (feat. Maluma)", "Aya Nakamura, Maluma", None, 200))
    assert lyrics is not None and lyrics.lines[0].text == "Lui"
    # Titre nettoyé et artiste principal dès l'appel exact.
    assert {"track_name": "Djadja", "artist_name": "Aya Nakamura", "duration": "200"} in seen


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


def test_credits_endpoint(client):
    deps = client.app_state.deps

    async def get_track(track_id):
        return TrackInfo(
            "deezer", track_id, "Titre", "Ziak", "Album", "2024", 180, None, "10", "5", isrc="FR123",
            disc_number=2, track_number=3,
            artists=[{"name": "Ziak", "source_id": "10", "role": "main"}, {"name": "Gazo", "source_id": "11", "role": "featured"}],
        )

    async def album_meta(album_id):
        return {"label": "Un Label", "release_date": "2024-05-03", "genres": ["Rap"], "upc": None}

    async def credits_by_isrc(isrc):
        return [{"role": "Producteur", "names": ["P"]}]

    deps.deezer.get_track = get_track
    deps.deezer.get_album_meta = album_meta
    deps.musicbrainz.credits_by_isrc = credits_by_isrc

    full = client.get("/tracks/deezer/42/credits", headers=AUTH)
    assert full.status_code == 200
    body = full.json()
    assert body["label"] == "Un Label" and body["genres"] == ["Rap"]
    assert body["credits"] == [{"role": "Producteur", "names": ["P"]}]
    assert [a["name"] for a in body["artists"]] == ["Ziak", "Gazo"]
    assert (body["disc_number"], body["track_number"]) == (2, 3)

    light = client.get("/tracks/deezer/42/credits?details=false", headers=AUTH).json()
    assert light["label"] is None and light["credits"] == []
    assert [a["name"] for a in light["artists"]] == ["Ziak", "Gazo"]


def test_track_endpoint_exposes_feats_and_disc(client):
    async def get_track(track_id):
        return TrackInfo("deezer", track_id, "T", "A", None, None, None, None, disc_number=2, track_number=1,
                         artists=[{"name": "A", "source_id": "1", "role": "main"}])

    client.app_state.deps.deezer.get_track = get_track
    body = client.get("/tracks/deezer/77", headers=AUTH).json()
    assert body["disc_number"] == 2 and body["artists"][0]["name"] == "A"


def _album(uid: str, title: str, date: str, tracks: int = 10):
    from app.providers.base import AlbumInfo
    return AlbumInfo("deezer", uid, title, "A", "1", date[:4], None, tracks, None, release_date=date)


def test_album_versions_keep_newest_and_move_others_down():
    from app.services import album_versions as av

    assert av.base_title("Ipséité (Édition Deluxe)") == av.base_title("Ipséité") == "ipseite"
    assert av.base_title("Love (Is All)") == "loveisall"
    assert av.base_title("Album - Remastered 2011") == "album"
    albums = [
        _album("1", "Premier", "2019-01-01"),
        _album("2", "Second", "2021-03-01", 12),
        _album("3", "Second (Deluxe)", "2021-09-01", 18),
        _album("4", "Second (Édition Collector)", "2022-01-01", 20),
    ]
    main, others = av.split_versions(albums)
    assert [a.source_id for a in main] == ["4", "1"]
    assert [a.source_id for a in others] == ["3", "2"]
    assert [a.source_id for a in av.siblings(albums[2], albums)] == ["4", "2"]


def test_artist_top_tracks_sorted_by_rank_without_duplicates():
    def handler(request: httpx.Request) -> httpx.Response:
        mk = lambda i, t, r: {"id": i, "title": t, "title_short": t, "rank": r, "artist": {"id": 1, "name": "A"}}
        return httpx.Response(200, json={"data": [mk(1, "Bas", 10), mk(2, "Haut", 900), mk(3, "Haut", 500), mk(4, "Milieu", 100)]})

    client = DeezerClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    tracks = asyncio.run(client.get_artist_top_tracks("1"))
    assert [(t.title, t.source_id) for t in tracks] == [("Haut", "2"), ("Milieu", "4"), ("Bas", "1")]


def test_search_results_get_featured_artists(client):
    deps = client.app_state.deps

    async def search_tracks(query, index=0, limit=25, order=None):
        return [TrackInfo("deezer", "5", "Titre", "Favé", None, None, None, None)], 1

    async def get_track(track_id):
        return TrackInfo("deezer", track_id, "Titre", "Favé", None, None, None, None, artists=[
            {"name": "Favé", "source_id": "1", "role": "main"}, {"name": "RnBoi", "source_id": "2", "role": "featured"},
        ])

    deps.deezer.search_tracks = search_tracks
    deps.deezer.get_track = get_track
    body = client.get("/search", params={"q": "fave"}, headers=AUTH).json()
    assert [a["name"] for a in body["tracks"][0]["artists"]] == ["Favé", "RnBoi"]


def test_artist_bio_only_for_musicians():
    from app.services.artist_bio import pick_summary

    good = {"extract": "Favé est un rappeur français né en 1990, auteur de plusieurs albums.", "description": "rappeur",
            "content_urls": {"desktop": {"page": "https://fr.wikipedia.org/wiki/Fav%C3%A9"}}}
    assert pick_summary(good) == {"text": good["extract"], "url": "https://fr.wikipedia.org/wiki/Fav%C3%A9", "source": "Wikipédia"}
    assert pick_summary({"extract": "Favé est une commune de l'Orne située dans la région Normandie."}) is None
    assert pick_summary({"type": "disambiguation", "extract": "x" * 80}) is None


def test_artist_bio_and_concerts_endpoints(client, monkeypatch):
    from app.providers.base import ArtistInfo
    from app.services import artist_bio, concerts

    async def get_artist(artist_id):
        return ArtistInfo("deezer", artist_id, "Favé", None)

    async def get_bio(name):
        return {"text": f"Bio de {name}", "url": None, "source": "Wikipédia"} if name == "Favé" else None

    async def events(app_id, artist, picture=None):
        return [{"id": "1", "artist": artist, "datetime": "2026-12-01T20:00:00", "venue": "Zénith", "city": "Paris"}]

    client.app_state.deps.deezer.get_artist = get_artist
    monkeypatch.setattr(artist_bio, "get_bio", get_bio)
    monkeypatch.setattr(concerts, "artist_events", events)
    assert client.get("/artists/deezer/9/bio", headers=AUTH).json()["text"] == "Bio de Favé"
    assert client.get("/artists/deezer/9/concerts", headers=AUTH).json()[0]["venue"] == "Zénith"
