"""Sona Connect : reprise d'un appareil à l'autre, télécommande, transfert."""

from app.services import connect
from tests.test_party_blindtest_concerts import client, login  # noqa: F401

TRACK = {"source": "deezer", "source_id": "1", "title": "Titre", "artist": "Artiste", "duration_seconds": 200}
NEXT = {"source": "deezer", "source_id": "2", "title": "Suivant", "artist": "Artiste"}


def sync(client, headers, device, name, kind="web", state=None, claim=False):
    body = {"device_id": device, "name": name, "kind": kind, "state": state, "claim": claim}
    response = client.post("/connect/sync", headers=headers, json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_resume_on_another_device(client, monkeypatch):
    me = login(client, "alice")
    clock = [1000.0]
    monkeypatch.setattr(connect, "_now", lambda: clock[0])
    sync(client, me, "iphone-123", "iPhone", "iphone",
         {"queue": [TRACK, NEXT], "index": 0, "position": 30, "paused": False, "name": "Mix"})
    clock[0] += 10
    seen = sync(client, me, "web-abcdef", "Chrome")
    session = seen["session"]
    assert session["device_name"] == "iPhone" and session["track"]["title"] == "Titre"
    assert session["position"] == 40 and not session["paused"]
    assert seen["active_device_id"] == "iphone-123"
    assert {d["name"] for d in seen["devices"]} == {"iPhone", "Chrome"}
    # L'iPhone se met en pause : la session garde la position.
    sync(client, me, "iphone-123", "iPhone", "iphone",
         {"queue": [TRACK, NEXT], "index": 0, "position": 41, "paused": True})
    clock[0] += 100
    later = sync(client, me, "web-abcdef", "Chrome")
    assert later["session"]["position"] == 41 and later["session"]["paused"]
    assert later["active_device_id"] is None


def test_remote_commands_and_transfer(client):
    me = login(client, "alice")
    sync(client, me, "iphone-123", "iPhone", "iphone", {"queue": [TRACK], "position": 12, "paused": False})
    sync(client, me, "web-abcdef", "Chrome")
    assert client.post("/connect/command", headers=me, json={
        "device_id": "web-abcdef", "target": "iphone-123", "action": "pause"}).status_code == 204
    got = sync(client, me, "iphone-123", "iPhone", "iphone", {"queue": [TRACK], "position": 13, "paused": False})
    assert [c["action"] for c in got["commands"]] == ["pause"] and got["commands"][0]["from"] == "Chrome"
    # « Écouter ici » sur le PC : le PC reçoit la file et la position, l'iPhone une pause.
    assert client.post("/connect/command", headers=me, json={
        "device_id": "web-abcdef", "target": "web-abcdef", "action": "transfer"}).status_code == 204
    web = sync(client, me, "web-abcdef", "Chrome")
    transfer = web["commands"][0]
    assert transfer["action"] == "transfer" and transfer["queue"][0]["title"] == "Titre" and transfer["position"] >= 13
    iphone = sync(client, me, "iphone-123", "iPhone", "iphone", {"queue": [TRACK], "position": 14, "paused": True})
    assert [c["action"] for c in iphone["commands"]] == ["pause"]
    assert client.post("/connect/command", headers=me, json={
        "device_id": "web-abcdef", "target": "nope-000000", "action": "pause"}).status_code == 404
    assert client.post("/connect/command", headers=me, json={
        "device_id": "web-abcdef", "target": "iphone-123", "action": "explode"}).status_code == 422


def test_claim_pauses_other_devices_and_accounts_are_separate(client):
    me, bob = login(client, "alice"), login(client, "bob")
    sync(client, me, "iphone-123", "iPhone", "iphone", {"queue": [TRACK], "paused": False})
    sync(client, me, "web-abcdef", "Chrome", state={"queue": [NEXT], "paused": False}, claim=True)
    got = sync(client, me, "iphone-123", "iPhone", "iphone", {"queue": [TRACK], "paused": True})
    assert [c["action"] for c in got["commands"]] == ["pause"]
    assert sync(client, bob, "web-bobbob", "Firefox")["session"] is None
