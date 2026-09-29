"""« Écouter sur la TV / PS5 » : association par code, lecture, commandes,
session rouverte quand YouTube l'a expirée."""

from __future__ import annotations

import httpx

from app.services import tv_cast
from tests.test_party_blindtest_concerts import client, login  # noqa: F401

TRACK = {"source": "deezer", "source_id": "1", "title": "Room", "artist": "Ziak"}
VIDEO = "abcdefghijk"


class FakeYouTube:
    """Faux serveur Lounge : association, jetons, sessions et commandes."""

    def __init__(self):
        self.commands: list[tuple[str, dict]] = []
        self.binds = 0
        self.expire_next_command = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        form = dict(httpx.QueryParams(request.content.decode()))
        if path.endswith("/pairing/get_screen"):
            if form.get("pairing_code") != "123456789012":
                return httpx.Response(404)
            return httpx.Response(200, json={"screen": {"screenId": "ps5", "name": "PS5 du salon", "loungeToken": "t1"}})
        if path.endswith("/pairing/get_lounge_token_batch"):
            return httpx.Response(200, json={"screens": [{"screenId": "ps5", "loungeToken": "t2"}]})
        if path.endswith("/bc/bind") and "SID" not in request.url.params:
            self.binds += 1
            return httpx.Response(200, text='52\n[[0,["c","SID1","",8]],[1,["S","GS1"]]]\n')
        if path.endswith("/bc/bind"):
            if self.expire_next_command:
                self.expire_next_command = False
                return httpx.Response(401, text="Expired")
            self.commands.append((form["req0__sc"], {k[5:]: v for k, v in form.items() if k.startswith("req0_") and k != "req0__sc"}))
            return httpx.Response(200)
        return httpx.Response(404)


def test_pair_play_and_control(client, monkeypatch):
    youtube = FakeYouTube()
    monkeypatch.setattr(tv_cast, "_http", lambda: httpx.AsyncClient(transport=httpx.MockTransport(youtube.handler)))

    async def known_video(repo, track, cookies_file=None):
        return VIDEO

    monkeypatch.setattr(tv_cast, "video_id_for", known_video)
    me = login(client, "alice")

    assert client.post("/tv/pair", headers=me, json={"code": "1111 2222"}).status_code == 400
    paired = client.post("/tv/pair", headers=me, json={"code": "1234 5678 9012"}).json()
    assert paired == {"screen_id": "ps5", "name": "PS5 du salon"}
    assert [s["name"] for s in client.get("/tv", headers=me).json()] == ["PS5 du salon"]

    got = client.post("/tv/ps5/play", headers=me, json={"tracks": [TRACK]})
    assert got.status_code == 200 and got.json() == {"video_id": VIDEO}
    assert youtube.commands[0] == ("setPlaylist", {"videoId": VIDEO, "currentTime": "0", "currentIndex": "0"})

    client.post("/tv/ps5/control", headers=me, json={"action": "pause"})
    client.post("/tv/ps5/control", headers=me, json={"action": "seek", "seconds": 42})
    assert youtube.commands[1:] == [("pause", {}), ("seekTo", {"newTime": "42"})]
    assert client.post("/tv/ps5/control", headers=me, json={"action": "explode"}).status_code == 400

    # Session expirée côté YouTube : jeton rafraîchi, session rouverte, commande rejouée.
    youtube.expire_next_command = True
    assert client.post("/tv/ps5/control", headers=me, json={"action": "next"}).status_code == 200
    assert youtube.commands[-1] == ("next", {}) and youtube.binds == 2

    # Un autre compte ne pilote pas cet écran.
    bob = login(client, "bob")
    assert client.post("/tv/ps5/control", headers=bob, json={"action": "play"}).status_code == 502

    client.delete("/tv/ps5", headers=me)
    assert client.get("/tv", headers=me).json() == []
