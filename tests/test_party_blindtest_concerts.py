"""Écoute ensemble, blind test et concerts — sans appel réseau réel."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.providers.base import TrackInfo
from app.providers.lastfm_auth import LastfmProfile, LastfmSession
from app.services import concerts, party

LEGACY = {"Authorization": "Bearer test-token"}


class FakeLastfm:
    async def get_session(self, token):
        return LastfmSession(username=token, key=f"sk-{token}")

    async def profile(self, username):
        return LastfmProfile(display_name=username.title(), avatar_url=None)

    async def scrobble(self, session_key, plays):
        pass

    async def update_now_playing(self, *args):
        pass


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("API_TOKEN", "test-token")
    monkeypatch.setenv("ALLOWED_USER_IDS", "")
    monkeypatch.setenv("BOT_TOKEN", "")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "sona.db"))
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("LASTFM_API_KEY", "cle")
    monkeypatch.setenv("LASTFM_API_SECRET", "secret")
    party.reset()
    concerts.reset()

    import app.api.main as main_module

    with TestClient(main_module.app) as test_client:
        main_module.app.state.deps.lastfm_auth = FakeLastfm()
        test_client.deps = main_module.app.state.deps
        yield test_client


def login(client, username):
    body = client.post("/auth/lastfm", json={"token": username}).json()
    if body["account"]["status"] != "approved":
        client.post(f"/admin/accounts/{body['account']['id']}/approve", headers=LEGACY)
    return {"Authorization": f"Bearer {body['session_token']}"}


TRACK = {"source": "deezer", "source_id": "1", "title": "Grabba", "artist": "Ziak"}


# -- Écoute ensemble -----------------------------------------------------------

def test_party_flow(client):
    host, guest = login(client, "alice"), login(client, "bob")
    created = client.post("/party", headers=host).json()
    code = created["code"]
    assert created["is_host"] and len(code) == 5

    # Bob voit la session d'Alice et la rejoint.
    active = client.get("/party/active", headers=guest).json()
    assert [p["code"] for p in active] == [code] and active[0]["joined"] is False
    joined = client.post(f"/party/{code.lower()}/join", headers=guest).json()
    assert joined["is_host"] is False
    assert [m["name"] for m in joined["members"]] == ["Alice", "Bob"]

    # Seule l'hôte pilote la lecture ; la position avance avec le temps.
    assert client.post(f"/party/{code}/state", headers=guest, json={"track": TRACK, "position": 0}).status_code == 403
    client.post(f"/party/{code}/state", headers=host, json={"track": TRACK, "position": 30, "paused": False})
    time.sleep(0.05)
    state = client.get(f"/party/{code}", headers=guest).json()
    assert state["track"]["title"] == "Grabba" and not state["paused"]
    assert 30 <= state["position"] < 31

    client.post(f"/party/{code}/state", headers=host, json={"track": TRACK, "position": 42, "paused": True})
    assert client.get(f"/party/{code}", headers=guest).json()["position"] == 42

    # Propositions et réactions.
    proposed = client.post(f"/party/{code}/queue", headers=guest, json={"track": {**TRACK, "source_id": "2"}}).json()
    item = proposed["queue"][0]
    assert item["by"] == "Bob"
    client.post(f"/party/{code}/react", headers=guest, json={"emoji": "🔥"})
    state = client.get(f"/party/{code}", headers=host).json()
    assert [r["emoji"] for r in state["reactions"]] == ["🔥"]
    assert client.post(f"/party/{code}/queue/consume", headers=guest, json={"ids": [item["id"]]}).status_code == 403
    assert client.post(f"/party/{code}/queue/consume", headers=host, json={"ids": [item["id"]]}).json()["queue"] == []

    # L'hôte part : la session s'arrête.
    client.post(f"/party/{code}/leave", headers=host)
    assert client.get(f"/party/{code}", headers=guest).status_code == 404


def test_party_needs_membership(client):
    host, stranger = login(client, "alice"), login(client, "carol")
    code = client.post("/party", headers=host).json()["code"]
    assert client.get(f"/party/{code}", headers=stranger).status_code == 403
    assert client.post("/party/ZZZZZ/join", headers=stranger).status_code == 404


# -- Blind test ----------------------------------------------------------------

class FakeDeezer:
    def __init__(self):
        self.tracks = {
            str(i): TrackInfo("deezer", str(i), f"Titre {i}", f"Artiste {i}", None, None, 180, f"https://c/{i}",
                              preview_url=f"https://preview/{i}.mp3")
            for i in range(20)
        }

    async def get_track(self, track_id):
        return self.tracks[track_id]

    async def get_chart_tracks(self, limit=50):
        return list(self.tracks.values())


def test_blindtest_round_scores_and_daily_leaderboard(client):
    client.deps.deezer = FakeDeezer()
    me = login(client, "alice")
    when = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    client.post("/plays", headers=me, json={"plays": [
        {"title": f"Titre {i}", "artist": f"Artiste {i}", "source": "deezer", "source_id": str(i), "played_at": when}
        for i in range(6)
    ]})
    round_ = client.get("/blindtest/round", headers=me).json()
    questions = round_["questions"]
    assert len(questions) == 10
    for q in questions:
        assert len(q["choices"]) == 4
        answer = q["choices"][q["answer"]]
        assert q["preview_url"].endswith(".mp3")
        assert answer["title"] == q["track"]["title"]
        assert len({c["artist"] for c in q["choices"]}) == 4

    daily_a = client.get("/blindtest/round", headers=me, params={"mode": "daily"}).json()
    daily_b = client.get("/blindtest/round", headers=me, params={"mode": "daily"}).json()
    assert [q["track"]["source_id"] for q in daily_a["questions"]] == [q["track"]["source_id"] for q in daily_b["questions"]]
    assert daily_a["already_played"] is False

    assert client.post("/blindtest/score", headers=me, json={"mode": "daily", "score": 900, "correct": 8, "total": 10}).json() == {"saved": True}
    # Le défi du jour ne compte qu'une fois.
    assert client.post("/blindtest/score", headers=me, json={"mode": "daily", "score": 1500, "correct": 10, "total": 10}).json() == {"saved": False}
    board = client.get("/blindtest/leaderboard", headers=me).json()
    assert board == [{"name": "Alice", "avatar_url": None, "is_me": True, "score": 900, "correct": 8, "total": 10}]
    assert client.get("/blindtest/round", headers=me, params={"mode": "daily"}).json()["already_played"] is True


# -- Concerts ------------------------------------------------------------------

def test_concerts_for_top_artists(client, monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if "Ziak" in request.url.path:
            return httpx.Response(200, json=[{
                "id": "e1", "datetime": "2026-11-20T20:00:00", "url": "https://bit.ly/x",
                "venue": {"name": "Zénith", "city": "Paris", "country": "France", "latitude": "48.89", "longitude": "2.39"},
                "offers": [{"type": "Tickets", "url": "https://tickets"}], "lineup": ["Ziak"],
            }])
        return httpx.Response(200, json=[])

    monkeypatch.setattr(concerts, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    me = login(client, "alice")
    when = datetime.now(timezone.utc).isoformat()
    client.post("/plays", headers=me, json={"plays": [
        {"title": "Grabba", "artist": "Ziak", "played_at": when},
        {"title": "Kuku", "artist": "Gazo", "played_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()},
    ]})
    events = client.get("/concerts", headers=me).json()
    assert len(events) == 1
    event = events[0]
    assert (event["artist"], event["city"], event["latitude"], event["url"]) == ("Ziak", "Paris", 48.89, "https://tickets")
    # Deuxième appel : servi depuis le cache.
    before = len(calls)
    client.get("/concerts", headers=me)
    assert len(calls) == before


class ArtistDeezer(FakeDeezer):
    """Un artiste (10 titres) et trois artistes proches."""

    def __init__(self):
        super().__init__()
        self.artist_tracks = {
            "ziak": [TrackInfo("deezer", f"z{i}", f"Ziak {i}", "Ziak", None, None, 180, None,
                               preview_url=f"https://p/z{i}.mp3") for i in range(10)],
        }
        for name in ("gazo", "sch", "kerchak"):
            self.artist_tracks[name] = [TrackInfo("deezer", f"{name}{i}", f"{name} {i}", name.upper(), None, None, 180,
                                                  None, preview_url=f"https://p/{name}{i}.mp3") for i in range(3)]

    async def get_artist_top_tracks(self, artist_id, limit=25):
        return self.artist_tracks[artist_id][:limit]

    async def get_related_artists(self, artist_id, limit=20):
        from app.providers.base import ArtistInfo

        return [ArtistInfo("deezer", n, n.upper(), None) for n in ("gazo", "sch", "kerchak")]


def test_blindtest_artist_mode_title_and_artist_guesses(client):
    client.deps.deezer = ArtistDeezer()
    me = login(client, "alice")

    by_title = client.get("/blindtest/round", headers=me, params={"mode": "artist", "ref": "ziak", "count": 5}).json()
    assert by_title["guess"] == "title"
    assert len(by_title["questions"]) == 5
    for q in by_title["questions"]:
        titles = [c["title"] for c in q["choices"]]
        assert len(set(titles)) == 4 and q["choices"][q["answer"]]["title"] == q["track"]["title"]

    by_artist = client.get("/blindtest/round", headers=me,
                           params={"mode": "artist", "ref": "ziak", "guess": "artist", "count": 4}).json()
    questions = by_artist["questions"]
    assert len(questions) == 4  # un artiste différent par question
    for q in questions:
        artists = [c["artist"] for c in q["choices"]]
        assert len(set(artists)) == 4
        assert artists[q["answer"]] == q["track"]["artist"]


def test_blindtest_chart_and_bad_mode(client):
    client.deps.deezer = FakeDeezer()
    me = login(client, "alice")
    assert len(client.get("/blindtest/round", headers=me, params={"mode": "chart", "count": 8}).json()["questions"]) == 8
    assert client.get("/blindtest/round", headers=me, params={"mode": "nope"}).status_code == 400
    assert client.get("/blindtest/round", headers=me, params={"mode": "playlist", "ref": "999"}).status_code == 404
