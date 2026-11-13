"""Écoute ensemble — sans appel réseau réel."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.providers.base import TrackInfo
from app.providers.lastfm_auth import LastfmProfile, LastfmSession
from app.services import party

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


def _party_with_guests(client, *names):
    host = login(client, "alice")
    code = client.post("/party", headers=host).json()["code"]
    guests = [login(client, n) for n in names]
    for g in guests:
        client.post(f"/party/{code}/join", headers=g)
    return code, host, guests


def test_party_chat_skip_and_history(client):
    code, host, (bob, carol) = _party_with_guests(client, "bob", "carol")
    client.post(f"/party/{code}/chat", headers=bob, json={"text": "  trop   bien  "})
    state = client.get(f"/party/{code}", headers=carol).json()
    assert [(m["by"], m["text"], m["mine"]) for m in state["messages"]] == [("Bob", "trop bien", False)]
    assert client.post(f"/party/{code}/chat", headers=bob, json={"text": "   "}).status_code == 400

    # Vote pour passer : rien en cours, puis la moitié des invités suffit.
    assert client.post(f"/party/{code}/skip", headers=bob).status_code == 409
    client.post(f"/party/{code}/state", headers=host, json={"track": TRACK, "position": 0, "paused": False})
    state = client.post(f"/party/{code}/skip", headers=bob).json()
    assert state["skip"] == {"votes": 1, "needed": 1, "voted": True}
    assert client.post(f"/party/{code}/skip", headers=host).status_code == 400
    # Nouveau titre : votes remis à zéro, titres déjà joués gardés.
    other = {**TRACK, "source_id": "2", "title": "Akimbo"}
    state = client.post(f"/party/{code}/state", headers=host, json={"track": other, "position": 0, "paused": False}).json()
    assert state["skip"]["votes"] == 0
    assert [t["title"] for t in state["history"]] == ["Akimbo", "Grabba"]


def test_party_shared_controls_and_proposals(client):
    code, host, (bob,) = _party_with_guests(client, "bob")
    assert client.post(f"/party/{code}/command", headers=bob, json={"action": "pause"}).status_code == 403
    assert client.post(f"/party/{code}/settings", headers=bob, json={"open_controls": True}).status_code == 403
    assert client.post(f"/party/{code}/settings", headers=host, json={"open_controls": True}).json()["open_controls"]
    assert client.post(f"/party/{code}/command", headers=bob, json={"action": "explode"}).status_code == 400
    bob_view = client.post(f"/party/{code}/command", headers=bob, json={"action": "next"}).json()
    assert bob_view["commands"] == []  # seul l'hôte voit (et exécute) les commandes
    assert [(c["action"], c["by"]) for c in client.get(f"/party/{code}", headers=host).json()["commands"]] == [("next", "Bob")]

    # Propositions : pas de doublon ; retirées par l'auteur ou l'hôte seulement.
    item = client.post(f"/party/{code}/queue", headers=bob, json={"track": TRACK}).json()["queue"][0]
    assert item["mine"] is True
    assert client.post(f"/party/{code}/queue", headers=host, json={"track": TRACK}).status_code == 409
    assert client.delete(f"/party/{code}/queue/{item['id']}", headers=bob).json()["queue"] == []


def test_party_host_handover_and_kick(client):
    code, host, (bob, carol) = _party_with_guests(client, "bob", "carol")
    members = {m["name"]: m["id"] for m in client.get(f"/party/{code}", headers=host).json()["members"]}

    # Retirer quelqu'un : il ne peut plus revenir.
    assert client.post(f"/party/{code}/kick", headers=bob, json={"member_id": members["Carol"]}).status_code == 403
    client.post(f"/party/{code}/kick", headers=host, json={"member_id": members["Carol"]})
    assert client.get(f"/party/{code}", headers=carol).status_code == 403
    assert client.post(f"/party/{code}/join", headers=carol).status_code == 403

    # Passer la main.
    state = client.post(f"/party/{code}/transfer", headers=host, json={"member_id": members["Bob"]}).json()
    assert state["is_host"] is False and state["host_name"] == "Bob"
    assert client.get(f"/party/{code}", headers=bob).json()["is_host"] is True

    # Téléphone de l'hôte (Bob) muet : Alice reprend la main, la session continue.
    session = party.get(code)
    session.members[session.host_user_id].last_seen -= party.HOST_TIMEOUT + 5
    state = client.get(f"/party/{code}", headers=host).json()
    assert state["is_host"] is True and [m["name"] for m in state["members"]] == ["Alice"]


def test_party_state_waits_for_a_change(client):
    code, host, (bob,) = _party_with_guests(client, "bob")
    version = client.get(f"/party/{code}", headers=bob).json()["version"]
    started = time.monotonic()
    same = client.get(f"/party/{code}", headers=bob, params={"since": version, "wait": 0.5}).json()
    assert same["version"] == version and time.monotonic() - started >= 0.4
    client.post(f"/party/{code}/state", headers=host, json={"track": TRACK, "position": 0})
    started = time.monotonic()
    changed = client.get(f"/party/{code}", headers=bob, params={"since": version, "wait": 5}).json()
    assert changed["version"] > version and time.monotonic() - started < 1


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







def test_proposals_are_limited_and_recent_titles_are_refused(client):
    code, host, (bob,) = _party_with_guests(client, "bob")
    other = lambda i: {"source": "deezer", "source_id": f"x{i}", "title": f"T{i}", "artist": "Ziak"}
    # Le titre qui joue (ou vient de passer) n'est pas reproposé.
    client.post(f"/party/{code}/state", headers=host, json={"track": TRACK, "position": 0, "paused": False})
    assert client.post(f"/party/{code}/queue", headers=bob, json={"track": TRACK}).status_code == 409
    # Cinq propositions en attente par personne, pas plus.
    for i in range(party.MAX_PER_USER):
        assert client.post(f"/party/{code}/queue", headers=bob, json={"track": other(i)}).status_code == 200
    assert client.post(f"/party/{code}/queue", headers=bob, json={"track": other(99)}).status_code == 429
    assert client.get(f"/party/{code}", headers=bob).json()["per_user"] == party.MAX_PER_USER
