"""Comptes de l'app : connexion Last.fm, validation par un admin, sessions,
données séparées par compte, scrobbling — Last.fm remplacé par un faux."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.providers.lastfm_auth import LastfmAuthClient, LastfmProfile, LastfmSession, sign

LEGACY = {"Authorization": "Bearer test-token"}


class FakeLastfm:
    def __init__(self):
        self.scrobbled = []
        self.now_playing = []

    async def get_token(self):
        return "jeton-bureau"

    async def get_session(self, token):
        return LastfmSession(username=token, key=f"sk-{token}")

    async def profile(self, username):
        return LastfmProfile(display_name=username.title(), avatar_url=None)

    async def scrobble(self, session_key, plays):
        self.scrobbled.append((session_key, [p.title for p in plays]))

    async def update_now_playing(self, session_key, title, artist, album, duration):
        self.now_playing.append((session_key, title, artist, duration))


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

    import app.api.main as main_module

    with TestClient(main_module.app) as test_client:
        fake = FakeLastfm()
        main_module.app.state.deps.lastfm_auth = fake
        test_client.fake_lastfm = fake
        yield test_client


def login(client, username):
    got = client.post("/auth/lastfm", json={"token": username})
    assert got.status_code == 200, got.text
    body = got.json()
    return {"Authorization": f"Bearer {body['session_token']}"}, body["account"]


def test_auth_config_gives_the_lastfm_login_url(client):
    config = client.get("/auth/config").json()
    assert config["lastfm_enabled"] is True
    assert config["auth_url"].startswith("https://www.last.fm/api/auth/?api_key=cle&cb=encre")


def test_callback_bounces_back_to_the_app(client):
    assert client.get("/auth/config").json()["api_key"] == "cle"
    got = client.get("/auth/lastfm/callback", params={"token": "abc"}, follow_redirects=False)
    assert got.status_code == 302
    assert got.headers["location"] == "encre://lastfm?token=abc"


def test_installed_web_app_gets_a_login_token(client):
    """Sona web installé : jeton demandé au serveur, page d'autorisation
    ouverte avec ce jeton, puis échange habituel."""
    got = client.post("/auth/lastfm/token").json()
    assert got["token"] == "jeton-bureau"
    assert got["auth_url"] == "https://www.last.fm/api/auth/?api_key=cle&token=jeton-bureau"


def test_owner_is_admin_and_keeps_legacy_data(client):
    client.post("/library/track", headers=LEGACY, json={"source": "deezer", "source_id": "1"})  # ignoré si réseau absent
    client.put("/settings", headers=LEGACY, json={"quality": "standard"})

    owner, account = login(client, "proprio")  # casse différente de LASTFM_USER
    assert account["status"] == "approved" and account["is_admin"] is True
    assert client.get("/settings", headers=owner).json()["quality"] == "standard"


def test_new_user_waits_for_admin_approval(client):
    owner, _ = login(client, "Proprio")
    guest, account = login(client, "copain")
    assert account["status"] == "pending" and account["is_admin"] is False

    blocked = client.get("/settings", headers=guest)
    assert blocked.status_code == 403
    assert "attente" in blocked.json()["detail"]
    assert client.get("/auth/me", headers=guest).json()["status"] == "pending"

    # Un non-admin ne voit pas le panel.
    accounts = client.get("/admin/accounts", headers=owner).json()
    assert [a["username"] for a in accounts] == ["copain", "Proprio"]  # en attente d'abord
    guest_id = accounts[0]["id"]

    approved = client.post(f"/admin/accounts/{guest_id}/approve", headers=owner).json()
    assert approved["status"] == "approved"
    settings = client.get("/settings", headers=guest)
    assert settings.status_code == 200
    # Données séparées : les réglages du propriétaire ne fuient pas.
    client.put("/settings", headers=owner, json={"quality": "standard"})
    assert settings.json()["quality"] == "best"
    assert client.get("/admin/accounts", headers=guest).status_code == 403

    # Révocation : les sessions sont fermées.
    client.post(f"/admin/accounts/{guest_id}/reject", headers=owner)
    assert client.get("/settings", headers=guest).status_code == 401
    _, again = login(client, "copain")
    assert again["status"] == "rejected"


def test_admin_cannot_revoke_self_and_logout_closes_session(client):
    owner, account = login(client, "Proprio")
    assert client.post(f"/admin/accounts/{account['id']}/reject", headers=owner).status_code == 400
    assert client.post("/auth/logout", headers=owner).status_code == 204
    assert client.get("/auth/me", headers=owner).status_code == 401


def test_legacy_token_still_works_as_admin(client):
    me = client.get("/auth/me", headers=LEGACY).json()
    assert me["is_admin"] is True and me["status"] == "approved"
    assert client.get("/admin/accounts", headers=LEGACY).status_code == 200


def test_plays_are_scrobbled_to_lastfm_once(client):
    owner, _ = login(client, "Proprio")
    body = {"plays": [{"title": "Room", "artist": "Ziak", "played_at": "2026-09-01T10:00:00Z", "listened_seconds": 120}]}
    assert client.post("/plays", headers=owner, json=body).json() == {"added": 1}
    assert client.post("/plays", headers=owner, json=body).json() == {"added": 0}
    deadline = time.monotonic() + 2
    while not client.fake_lastfm.scrobbled and time.monotonic() < deadline:
        time.sleep(0.05)
    assert client.fake_lastfm.scrobbled == [("sk-Proprio", ["Room"])]

    client.put("/auth/me", headers=owner, json={"scrobble_to_lastfm": False})
    body["plays"][0]["played_at"] = "2026-09-01T11:00:00Z"
    client.post("/plays", headers=owner, json=body)
    time.sleep(0.2)
    assert len(client.fake_lastfm.scrobbled) == 1


def test_signature_follows_lastfm_rules():
    params = {"method": "auth.getSession", "api_key": "k", "token": "t", "format": "json"}
    import hashlib

    assert sign(params, "s") == hashlib.md5(b"api_keykmethodauth.getSessiontokents").hexdigest()


def test_login_token_request_is_signed():
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        return httpx.Response(200, json={"token": "T0K"})

    client = LastfmAuthClient("k", "s", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert asyncio.run(client.get_token()) == "T0K"
    assert seen[0]["method"] == "auth.getToken" and seen[0]["api_sig"] == sign({"method": "auth.getToken", "api_key": "k"}, "s")


def test_session_exchange_and_scrobble_requests():
    seen = []

    def handler(request):
        if request.method == "GET":
            seen.append(dict(request.url.params))
            return httpx.Response(200, json={"session": {"name": "Moi", "key": "SK"}})
        form = dict(x.split("=", 1) for x in request.content.decode().split("&"))
        seen.append(form)
        return httpx.Response(200, json={"scrobbles": {}})

    from app.db.repository import Play

    client = LastfmAuthClient("k", "s", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    session = asyncio.run(client.get_session("tok"))
    assert (session.username, session.key) == ("Moi", "SK")
    assert seen[0]["api_sig"] and seen[0]["method"] == "auth.getSession"

    asyncio.run(client.scrobble("SK", [Play(played_at="2026-01-01T00:00:00+00:00", title="T", artist="A")]))
    assert seen[1]["method"] == "track.scrobble" and seen[1]["timestamp%5B0%5D"] == "1767225600"


def test_library_accepts_the_app_page_size(client):
    # L'app charge jusqu'à 200 éléments (bibliothèque, état « J'aime ») :
    # la limite de 100 renvoyait 422 et laissait ces écrans vides.
    assert client.get("/library/track", headers=LEGACY, params={"limit": 200}).status_code == 200


def test_now_playing_is_sent_to_lastfm_live(client):
    owner, _ = login(client, "Proprio")
    got = client.post("/plays/now", headers=owner, json={"title": "Grabba", "artist": "Ziak", "duration_seconds": 142})
    assert got.status_code == 204
    deadline = time.monotonic() + 2
    while not client.fake_lastfm.now_playing and time.monotonic() < deadline:
        time.sleep(0.05)
    assert client.fake_lastfm.now_playing == [("sk-Proprio", "Grabba", "Ziak", 142)]

    # Scrobbling coupé : rien n'est envoyé.
    client.put("/auth/me", headers=owner, json={"scrobble_to_lastfm": False})
    client.post("/plays/now", headers=owner, json={"title": "Room", "artist": "Ziak"})
    time.sleep(0.2)
    assert len(client.fake_lastfm.now_playing) == 1
    # Ancien jeton (pas de compte Last.fm) : accepté, sans effet.
    assert client.post("/plays/now", headers=LEGACY, json={"title": "X", "artist": "Y"}).status_code == 204
