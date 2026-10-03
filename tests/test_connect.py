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


def test_pausing_the_pc_keeps_it_as_the_remote_target(client):
    """Mettre le PC en pause depuis l'iPhone (lui aussi en pause) : la
    lecture reste celle du PC — l'iPhone garde sa télécommande."""
    me = login(client, "alice")
    sync(client, me, "iphone-123", "iPhone", "iphone", {"queue": [NEXT], "position": 5, "paused": True})
    sync(client, me, "web-abcdef", "Chrome", state={"queue": [TRACK], "position": 20, "paused": False}, claim=True)
    sync(client, me, "web-abcdef", "Chrome", state={"queue": [TRACK], "position": 21, "paused": True})
    seen = sync(client, me, "iphone-123", "iPhone", "iphone", {"queue": [NEXT], "position": 5, "paused": True})
    assert seen["session"]["device_id"] == "web-abcdef" and seen["session"]["paused"]
    assert seen["session"]["track"]["title"] == "Titre"


def test_windows_app_is_a_connect_device_the_iphone_can_drive(client):
    """Sona pour Windows se signale en `desktop` : l'iPhone le voit et le pilote."""
    me = login(client, "alice")
    sync(client, me, "desk-abcdef", "PC du salon", "desktop", {"queue": [TRACK], "position": 3, "paused": False}, claim=True)
    seen = sync(client, me, "iphone-123", "iPhone", "iphone")
    pc = next(d for d in seen["devices"] if d["id"] == "desk-abcdef")
    assert pc["kind"] == "desktop" and pc["playing"]
    response = client.post("/connect/command", headers=me,
                           json={"device_id": "iphone-123", "target": "desk-abcdef", "action": "pause"})
    assert response.status_code == 204
    got = sync(client, me, "desk-abcdef", "PC du salon", "desktop", {"queue": [TRACK], "position": 4, "paused": False})
    assert [c["action"] for c in got["commands"]] == ["pause"]


def test_unknown_device_kind_is_refused(client):
    me = login(client, "alice")
    response = client.post("/connect/sync", headers=me, json={"device_id": "toaster-1", "name": "Grille-pain", "kind": "toaster"})
    assert response.status_code == 422


def test_waiting_device_is_woken_by_a_command():
    import asyncio
    import time as clock

    async def scenario():
        connect.sync(1, "web-abcdef", "Chrome", "web", None)
        connect.sync(1, "iphone-123", "iPhone", "iphone", {"queue": [TRACK], "paused": False})
        started = clock.monotonic()
        waiting = asyncio.create_task(connect.sync_wait(1, "web-abcdef", "Chrome", "web", None, wait=10))
        await asyncio.sleep(0.05)
        assert connect.command(1, "iphone-123", "web-abcdef", "pause")
        result = await waiting
        return clock.monotonic() - started, result

    elapsed, result = asyncio.run(scenario())
    assert elapsed < 1 and [c["action"] for c in result["commands"]] == ["pause"]


def test_waiting_device_is_woken_when_playback_moves():
    import asyncio

    async def scenario():
        connect.sync(1, "iphone-123", "iPhone", "iphone", None)
        waiting = asyncio.create_task(connect.sync_wait(1, "iphone-123", "iPhone", "iphone", None, wait=10))
        await asyncio.sleep(0.05)
        connect.sync(1, "web-abcdef", "Chrome", "web", {"queue": [TRACK], "paused": False}, claim=True)
        return await asyncio.wait_for(waiting, 2)

    result = asyncio.run(scenario())
    assert result["session"]["device_id"] == "web-abcdef" and result["active_device_id"] == "web-abcdef"


def test_each_device_reports_its_own_position(client, monkeypatch):
    """Le PC se pilote avec sa propre lecture, même quand la session du
    compte est celle de l'iPhone."""
    me = login(client, "alice")
    clock = [1000.0]
    monkeypatch.setattr(connect, "_now", lambda: clock[0])
    sync(client, me, "desktop-pc1234", "PC du salon", "desktop", {"queue": [TRACK], "position": 50, "paused": False})
    sync(client, me, "iphone-123", "iPhone", "iphone", {"queue": [NEXT], "position": 5, "paused": False}, claim=True)
    clock[0] += 4
    seen = sync(client, me, "iphone-123", "iPhone", "iphone", {"queue": [NEXT], "position": 9, "paused": False})
    pc = next(d for d in seen["devices"] if d["id"] == "desktop-pc1234")
    assert seen["session"]["device_id"] == "iphone-123"
    # Mis en pause par la prise de main de l'iPhone : position figée.
    assert pc["track"]["title"] == "Titre" and pc["position"] == 50 and pc["online"]


def test_saved_devices_stay_listed_when_offline(client, monkeypatch):
    me, bob = login(client, "alice"), login(client, "bob")
    clock = [1000.0]
    monkeypatch.setattr(connect, "_now", lambda: clock[0])
    # Jamais vu sur ce compte : refusé.
    assert client.post("/connect/saved", headers=me, json={"device_id": "desktop-pc1234"}).status_code == 404
    sync(client, me, "desktop-pc1234", "PC du salon", "desktop", {"queue": [TRACK], "position": 10, "paused": False})
    saved = client.post("/connect/saved", headers=me, json={"device_id": "desktop-pc1234"})
    assert saved.status_code == 200, saved.text
    item = saved.json()
    assert item["name"] == "PC du salon" and item["kind"] == "desktop" and item["online"] and item["playing"]
    # Un autre compte ne le voit pas et ne peut pas l'enregistrer.
    assert client.get("/connect/saved", headers=bob).json() == []
    assert client.post("/connect/saved", headers=bob, json={"device_id": "desktop-pc1234"}).status_code == 404
    # PC éteint : toujours là, hors ligne ; même après l'oubli de Sona Connect (24 h).
    clock[0] += 60
    listed = client.get("/connect/saved", headers=me).json()
    assert [d["id"] for d in listed] == ["desktop-pc1234"] and not listed[0]["online"] and not listed[0]["playing"]
    clock[0] += 2 * 24 * 3600
    listed = client.get("/connect/saved", headers=me).json()
    assert listed[0]["name"] == "PC du salon" and listed[0]["seen_seconds"] is None
    # Rallumé : de nouveau en ligne et pilotable.
    sync(client, me, "desktop-pc1234", "PC du salon", "desktop")
    assert client.get("/connect/saved", headers=me).json()[0]["online"]
    assert client.delete("/connect/saved/desktop-pc1234", headers=me).status_code == 204
    assert client.get("/connect/saved", headers=me).json() == []


def test_pc_registers_itself_and_stays_forgotten(client):
    """Sona pour Windows s'inscrit tout seul dans « Appareils » ; oublié, il
    ne revient pas tout seul (seulement si on l'ajoute de nouveau)."""
    me = login(client, "alice")
    sync(client, me, "web-abcdef", "Chrome")
    assert client.get("/connect/saved", headers=me).json() == []
    sync(client, me, "desktop-pc1234", "PC du salon", "desktop")
    assert [d["name"] for d in client.get("/connect/saved", headers=me).json()] == ["PC du salon"]
    assert client.delete("/connect/saved/desktop-pc1234", headers=me).status_code == 204
    connect.autosaved.clear()  # comme après un redémarrage du serveur
    sync(client, me, "desktop-pc1234", "PC du salon", "desktop")
    assert client.get("/connect/saved", headers=me).json() == []
    assert client.post("/connect/saved", headers=me, json={"device_id": "desktop-pc1234"}).status_code == 200
    assert len(client.get("/connect/saved", headers=me).json()) == 1


def test_rename_a_saved_device(client):
    me = login(client, "alice")
    sync(client, me, "desktop-pc1234", "DESKTOP-8F3K", "desktop")
    renamed = client.patch("/connect/saved/desktop-pc1234", headers=me, json={"name": "  Bureau  "})
    assert renamed.status_code == 200 and renamed.json()["name"] == "Bureau" and renamed.json()["renamed"]
    assert client.get("/connect/saved", headers=me).json()[0]["name"] == "Bureau"
    back = client.patch("/connect/saved/desktop-pc1234", headers=me, json={"name": ""}).json()
    assert back["name"] == "DESKTOP-8F3K" and not back["renamed"]
    assert client.patch("/connect/saved/nope-000000", headers=me, json={"name": "X"}).status_code == 404


def test_full_remote_options_and_queue(client):
    me = login(client, "alice")
    state = {"queue": [TRACK, NEXT], "index": 0, "position": 3, "paused": False, "name": "Mix",
             "shuffle": True, "repeat": "one", "liked": False}
    sync(client, me, "desktop-pc1234", "PC", "desktop", state)
    phone = sync(client, me, "iphone-123", "iPhone", "iphone")
    pc = next(d for d in phone["devices"] if d["id"] == "desktop-pc1234")
    assert pc["shuffle"] is True and pc["repeat"] == "one" and pc["liked"] is False
    queue = client.get("/connect/devices/desktop-pc1234/queue", headers=me).json()
    assert queue["index"] == 0 and queue["name"] == "Mix" and [t["title"] for t in queue["queue"]] == ["Titre", "Suivant"]
    for action, extra in (("shuffle", {}), ("repeat", {}), ("like", {}), ("play_index", {"index": 1})):
        sent = client.post("/connect/command", headers=me, json={"device_id": "iphone-123", "target": "desktop-pc1234",
                                                                  "action": action, **extra})
        assert sent.status_code == 204, sent.text
    got = sync(client, me, "desktop-pc1234", "PC", "desktop", state)
    assert [c["action"] for c in got["commands"]] == ["shuffle", "repeat", "like", "play_index"]
    assert got["commands"][-1]["index"] == 1
    assert client.get("/connect/devices/nope-000000/queue", headers=me).status_code == 404
