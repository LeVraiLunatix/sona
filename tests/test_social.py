"""Amis (« en train d'écouter », affinité, profil), playlists partagées et à
plusieurs, mixes de l'accueil, et titres aimés synchronisés avec Last.fm —
sans appel réseau réel."""

from __future__ import annotations

import asyncio
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.routers.friends import compatibility
from app.providers.base import ArtistInfo, TrackInfo
from app.providers.lastfm_auth import LastfmProfile, LastfmSession, LovedTrack
from app.services import mixes, presence

LEGACY = {"Authorization": "Bearer test-token"}


class FakeLastfm:
    def __init__(self):
        self.loves = []
        self.loved = []

    async def get_session(self, token):
        return LastfmSession(username=token, key=f"sk-{token}")

    async def profile(self, username):
        return LastfmProfile(display_name=username.title(), avatar_url=None)

    async def scrobble(self, session_key, plays):
        pass

    async def update_now_playing(self, session_key, title, artist, album, duration):
        pass

    async def love(self, session_key, title, artist):
        self.loves.append(("love", session_key, title, artist))

    async def unlove(self, session_key, title, artist):
        self.loves.append(("unlove", session_key, title, artist))

    async def loved_tracks(self, username, max_tracks=2000):
        return self.loved


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("API_TOKEN", "test-token")
    monkeypatch.setenv("ALLOWED_USER_IDS", "")
    monkeypatch.setenv("BOT_TOKEN", "")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "sona.db"))
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("LASTFM_API_KEY", "cle")
    monkeypatch.setenv("LASTFM_API_SECRET", "secret")
    monkeypatch.setenv("LASTFM_USER", "Proprio")
    monkeypatch.delenv("ADMIN_LASTFM_USERS", raising=False)
    presence.reset()
    mixes._cache.clear()

    import app.api.main as main_module

    with TestClient(main_module.app) as test_client:
        fake = FakeLastfm()
        main_module.app.state.deps.lastfm_auth = fake
        test_client.fake_lastfm = fake
        test_client.deps = main_module.app.state.deps
        yield test_client


def login(client, username):
    body = client.post("/auth/lastfm", json={"token": username}).json()
    headers = {"Authorization": f"Bearer {body['session_token']}"}
    account = body["account"]
    if account["status"] != "approved":
        client.post(f"/admin/accounts/{account['id']}/approve", headers=LEGACY)
    return headers, account


def play(title, artist, days_ago=1, **extra):
    when = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return {"title": title, "artist": artist, "played_at": when.isoformat(), **extra}


def wait_for(client, predicate, tries=100):
    for _ in range(tries):
        if predicate():
            return
        client.portal.call(asyncio.sleep, 0.02)
    raise AssertionError("condition jamais atteinte")


def test_compatibility():
    assert compatibility(Counter({"a": 10}), Counter({"a": 10})) == 100
    assert compatibility(Counter({"a": 10}), Counter({"b": 10})) == 0
    assert compatibility(Counter({"a": 5}), Counter({"a": 10})) is None  # trop peu d'écoutes


def test_friends_now_playing_and_profile(client):
    alice, _ = login(client, "alice")
    bob, bob_account = login(client, "bob")

    # Alice et Bob écoutent surtout Ziak.
    client.post("/plays", headers=alice, json={"plays": [play(f"T{i}", "Ziak", i % 5 + 1) for i in range(12)]})
    client.post("/plays", headers=bob, json={"plays": [
        *[play(f"T{i}", "Ziak", i % 5 + 1) for i in range(10)],
        play("Autre", "Gazo", 2, source="deezer", source_id="9"),
    ]})

    client.post("/plays/now", headers=bob, json={
        "title": "Grabba", "artist": "Ziak", "duration_seconds": 180,
        "source": "deezer", "source_id": "42", "cover_url": "https://c",
    })

    friends = client.get("/friends", headers=alice).json()
    names = [f["username"] for f in friends]
    assert names[0] == "bob"  # en train d'écouter : en tête
    assert "alice" not in names
    bob_out = friends[0]
    assert bob_out["now_playing"]["track"]["source_id"] == "42"
    assert bob_out["last_play"]["title"] in {"Autre", "T0", "T5"}
    assert bob_out["compatibility"] >= 90

    profile = client.get(f"/friends/{bob_account['id']}", headers=alice).json()
    assert profile["shared_artists"] == ["Ziak"]
    assert profile["top_artists"][0]["name"] == "Ziak"
    assert len(profile["recent"]) == 11

    # Pause : plus « en train d'écouter ».
    client.delete("/plays/now", headers=bob)
    assert client.get("/friends", headers=alice).json()[0]["now_playing"] is None

    # Écoute privée : Bob disparaît de la liste.
    assert client.put("/auth/me", headers=bob, json={"share_listening": False}).json()["share_listening"] is False
    assert "bob" not in [f["username"] for f in client.get("/friends", headers=alice).json()]
    assert client.get(f"/friends/{bob_account['id']}", headers=alice).status_code == 404


def test_shared_and_collaborative_playlists(client):
    alice, _ = login(client, "alice")
    bob, bob_account = login(client, "bob")
    track = {"source": "deezer", "source_id": "1", "title": "T", "artist": "A", "album": None, "year": None,
             "duration_seconds": 100, "cover_url": None, "artist_source_id": None, "album_source_id": None}

    pid = client.post("/me/playlists", headers=bob, json={"name": "Soirée", "tracks": [track]}).json()["id"]
    # Privée : invisible pour Alice.
    assert client.get(f"/me/playlists/{pid}", headers=alice).status_code == 404

    client.patch(f"/me/playlists/{pid}", headers=bob, json={"visibility": "friends"})
    seen = client.get(f"/me/playlists/{pid}", headers=alice).json()
    assert seen["is_owner"] is False and seen["can_edit"] is False and seen["owner_name"] == "Bob"
    assert client.post(f"/me/playlists/{pid}/tracks", headers=alice, json={"tracks": [track]}).status_code == 404
    assert client.patch(f"/me/playlists/{pid}", headers=alice, json={"name": "x"}).status_code == 404
    profile = client.get(f"/friends/{bob_account['id']}", headers=alice).json()
    assert [p["name"] for p in profile["playlists"]] == ["Soirée"]
    assert pid not in [p["id"] for p in client.get("/me/playlists", headers=alice).json()]

    client.patch(f"/me/playlists/{pid}", headers=bob, json={"visibility": "collaborative"})
    added = client.post(f"/me/playlists/{pid}/tracks", headers=alice, json={"tracks": [track]})
    assert added.status_code == 200 and added.json()["track_count"] == 2
    listed = client.get("/me/playlists", headers=alice).json()
    assert [p["name"] for p in listed if not p["is_owner"]] == ["Soirée"]
    assert client.delete(f"/me/playlists/{pid}", headers=alice).status_code == 404

    assert client.patch(f"/me/playlists/{pid}", headers=bob, json={"visibility": "public"}).status_code == 400


class FakeDeezer:
    def __init__(self):
        self.catalog = {
            "Grabba": TrackInfo("deezer", "1", "Grabba", "Ziak", "A", None, 180, "https://c1"),
        }

    async def search_artists(self, name, limit=10):
        return [ArtistInfo("deezer", f"id-{name}", name, None)]

    async def get_artist_radio(self, artist_id, limit=25):
        base = artist_id.removeprefix("id-")
        return [TrackInfo("deezer", f"{base}-{i}", f"{base} radio {i}", base, None, None, 200, f"https://{base}/{i}")
                for i in range(3)]

    async def get_related_artists(self, artist_id, limit=20):
        return [ArtistInfo("deezer", "id-Gazo", "Gazo", None), ArtistInfo("deezer", "id-Nouveau", "Nouveau", None)]

    async def get_artist_top_tracks(self, artist_id, limit=25):
        base = artist_id.removeprefix("id-")
        return [TrackInfo("deezer", f"{base}-top{i}", f"{base} top {i}", base, None, None, 200, None) for i in range(3)]

    async def get_track_by_isrc(self, isrc):
        return None

    async def search_tracks(self, query, index=0, limit=25):
        found = [t for title, t in self.catalog.items() if title.lower() in query.lower()]
        return found, len(found)

    async def get_track(self, track_id):
        return next(t for t in self.catalog.values() if t.source_id == track_id)


def test_home_mixes(client):
    client.deps.deezer = FakeDeezer()
    me, _ = login(client, "alice")
    client.post("/plays", headers=me, json={"plays": [
        *[play("Grabba", "Ziak", i + 1, source="deezer", source_id="1") for i in range(4)],
        *[play("Kuku", "Gazo", i + 1) for i in range(3)],
    ]})
    got = client.get("/home/mixes", headers=me).json()
    by_id = {m["id"]: m for m in got}
    assert by_id["daily"]["subtitle"] == "Ziak, Gazo"
    assert [t["title"] for t in by_id["daily"]["tracks"][:2]] == ["Ziak radio 0", "Gazo radio 0"]
    # Gazo déjà écouté : seul « Nouveau » est une découverte.
    assert {t["artist"] for t in by_id["discoveries"]["tracks"]} == {"Nouveau"}
    assert "repeat" not in by_id  # moins de 5 titres en boucle
    assert len(by_id["daily"]["covers"]) == 4


def test_library_likes_sync_to_lastfm(client):
    client.deps.deezer = FakeDeezer()
    me, _ = login(client, "alice")
    assert client.post("/library/track", headers=me, json={"source": "deezer", "source_id": "1"}).status_code == 204
    client.delete("/library/track/deezer/1", headers=me)
    wait_for(client, lambda: len(client.fake_lastfm.loves) == 2)
    assert client.fake_lastfm.loves == [
        ("love", "sk-alice", "Grabba", "Ziak"),
        ("unlove", "sk-alice", "Grabba", "Ziak"),
    ]


def test_import_lastfm_loved_tracks(client, monkeypatch):
    from app.services import playlist_import

    monkeypatch.setattr(playlist_import, "DEEZER_REQUESTS_PER_SECOND", 1000)
    client.deps.deezer = FakeDeezer()
    client.fake_lastfm.loved = [
        LovedTrack("Grabba", "Ziak", datetime(2024, 5, 1, tzinfo=timezone.utc)),
        LovedTrack("Introuvable", "Personne", None),
    ]
    me, _ = login(client, "alice")
    started = client.post("/library/lastfm-loved/import", headers=me)
    assert started.status_code == 202
    wait_for(client, lambda: not client.get("/library/lastfm-loved/import", headers=me).json()["running"])
    status = client.get("/library/lastfm-loved/import", headers=me).json()
    assert status == {"running": False, "total": 2, "done": 2, "added": 1, "missing": 1, "error": None}
    items = client.get("/library/track", headers=me).json()["items"]
    assert [(i["title"], i["added_at"][:10]) for i in items] == [("Grabba", "2024-05-01")]


def test_mix_seed_picks_the_most_followed_homonym():
    class Deezer:
        async def search_artists(self, name, limit=10):
            return [
                ArtistInfo("deezer", "petit", "Pnl", None, fans=14_000),
                ArtistInfo("deezer", "vrai", "PNL", None, fans=3_000_000),
                ArtistInfo("deezer", "autre", "PNL Tribute", None, fans=9_000_000),
            ]

    assert asyncio.run(mixes._deezer_artist_id(Deezer(), "PNL", None, None)) == "vrai"
    # Identifiant Deezer déjà connu (écoute faite dans l'app) : gardé tel quel.
    assert asyncio.run(mixes._deezer_artist_id(Deezer(), "PNL", "deezer", "42")) == "42"
