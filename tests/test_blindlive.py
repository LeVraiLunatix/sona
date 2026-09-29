"""Blind test en direct : salon, questions synchronisées, points, podium."""

from __future__ import annotations

from app.services import blindlive
from tests.test_party_blindtest_concerts import FakeDeezer, client, login  # noqa: F401


class Clock:
    def __init__(self, monkeypatch):
        self.t = 1_000_000.0
        monkeypatch.setattr(blindlive, "_now", lambda: self.t)

    def tick(self, seconds):
        self.t += seconds


def test_live_round_flow(client, monkeypatch):
    client.deps.deezer = FakeDeezer()
    clock = Clock(monkeypatch)
    alice, bob = login(client, "alice"), login(client, "bob")

    room = client.post("/blindlive", headers=alice).json()
    code = room["code"]
    assert room["is_host"] and room["phase"] == "lobby"
    assert client.post(f"/blindlive/{code}/join", headers=bob).json()["players"][1]["name"] == "Bob"

    # Seul l'hôte règle et lance ; le défi du jour n'est pas un thème.
    assert client.post(f"/blindlive/{code}/config", headers=bob, json={"mode": "chart"}).status_code == 403
    assert client.post(f"/blindlive/{code}/config", headers=alice, json={"mode": "daily"}).status_code == 400
    client.post(f"/blindlive/{code}/config", headers=alice, json={"mode": "chart", "count": 3, "label": "Top"})
    assert client.post(f"/blindlive/{code}/start", headers=bob).status_code == 403
    state = client.post(f"/blindlive/{code}/start", headers=alice).json()
    assert state["phase"] == "question" and state["total"] == 3 and state["label"] == "Top"
    q = state["question"]
    assert q["answer"] is None and q["track"] is None  # rien n'est dévoilé

    # Trop tôt : l'extrait n'a pas commencé.
    assert client.post(f"/blindlive/{code}/answer", headers=alice, json={"index": 0, "choice": 0}).status_code == 409

    room_obj = blindlive.get(code)
    good = room_obj.questions[0]["answer"]
    clock.tick(blindlive.LEAD_SECONDS + 2)
    state = client.post(f"/blindlive/{code}/answer", headers=alice, json={"index": 0, "choice": good}).json()
    assert state["phase"] == "question" and state["question"]["my_choice"] == good
    # Tout le monde a répondu : correction tout de suite.
    state = client.post(f"/blindlive/{code}/answer", headers=bob, json={"index": 0, "choice": (good + 1) % 4}).json()
    assert state["phase"] == "reveal"
    assert state["question"]["answer"] == good and state["question"]["track"]["title"]
    alice_row, bob_row = state["players"]
    assert alice_row["name"] == "Alice" and alice_row["gained"] == 100 + 130 and alice_row["was_right"]
    assert bob_row["gained"] == 0 and bob_row["was_right"] is False

    # Question suivante après la correction ; personne ne répond : fin du temps.
    clock.tick(blindlive.REVEAL_SECONDS + blindlive.LEAD_SECONDS)
    state = client.get(f"/blindlive/{code}", headers=bob).json()
    assert state["phase"] == "question" and state["question"]["index"] == 1
    assert client.post(f"/blindlive/{code}/answer", headers=bob, json={"index": 0, "choice": 0}).status_code == 409
    clock.tick(blindlive.QUESTION_SECONDS + blindlive.REVEAL_SECONDS + blindlive.LEAD_SECONDS
               + blindlive.QUESTION_SECONDS + blindlive.REVEAL_SECONDS + 1)
    state = client.get(f"/blindlive/{code}", headers=alice).json()
    assert state["phase"] == "finished" and len(state["tracks"]) == 3
    assert state["players"][0]["name"] == "Alice" and state["players"][0]["score"] == 230

    # Revanche : scores remis à zéro.
    state = client.post(f"/blindlive/{code}/start", headers=alice).json()
    assert state["phase"] == "question" and all(p["score"] == 0 for p in state["players"])

    # Les amis voient la partie ; l'hôte part : elle s'arrête.
    assert [r["code"] for r in client.get("/blindlive/active", headers=bob).json()] == [code]
    client.post(f"/blindlive/{code}/leave", headers=alice)
    assert client.get(f"/blindlive/{code}", headers=bob).status_code == 404


def test_live_not_enough_tracks(client):
    class Empty(FakeDeezer):
        async def get_chart_tracks(self, limit=50):
            return []

    client.deps.deezer = Empty()
    alice = login(client, "alice")
    code = client.post("/blindlive", headers=alice).json()["code"]
    client.post(f"/blindlive/{code}/config", headers=alice, json={"mode": "chart"})
    assert client.post(f"/blindlive/{code}/start", headers=alice).status_code == 422
    assert client.get("/blindlive/ZZZZZ", headers=alice).status_code == 404
