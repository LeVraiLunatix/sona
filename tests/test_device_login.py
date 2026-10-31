"""Connexion d'un appareil (TV) par QR code : demande, autorisation depuis un appareil connecté, session."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.services import device_login
from tests.test_accounts import FakeLastfm, LEGACY, login


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
    monkeypatch.setenv("SONA_WEB_URL", "https://exemple.test/web")
    monkeypatch.delenv("ADMIN_LASTFM_USERS", raising=False)
    device_login.reset()

    import app.api.main as main_module

    with TestClient(main_module.app) as test_client:
        main_module.app.state.deps.lastfm_auth = FakeLastfm()
        yield test_client


def start(client, name="TV du salon"):
    got = client.post("/auth/device/start", json={"name": name})
    assert got.status_code == 200, got.text
    return got.json()


def test_start_gives_a_code_and_a_link_to_open_on_the_phone(client):
    body = start(client)
    assert len(body["user_code"]) == 9 and body["user_code"][4] == "-"
    assert body["verify_url"] == f"https://exemple.test/web/?link={body['user_code']}"
    assert body["expires_in"] == device_login.TTL_SECONDS and body["interval"] >= 1
    assert client.post("/auth/device/poll", json={"device_code": body["device_code"]}).json() == {"status": "pending"}


def test_approving_hands_the_tv_its_own_session(client):
    owner, account = login(client, "Proprio")
    body = start(client)
    seen = client.get(f"/auth/device/{body['user_code']}", headers=owner).json()
    assert seen["name"] == "TV du salon"

    # le code se saisit aussi en minuscules, avec ou sans tiret
    typed = body["user_code"].lower().replace("-", " ")
    assert client.post("/auth/device/approve", headers=owner, json={"user_code": typed}).json()["ok"] is True

    got = client.post("/auth/device/poll", json={"device_code": body["device_code"]}).json()
    assert got["status"] == "approved" and got["account"]["username"] == account["username"]
    tv = {"Authorization": f"Bearer {got['session_token']}"}
    assert client.get("/auth/me", headers=tv).json()["username"] == account["username"]
    assert got["session_token"] != owner["Authorization"].split()[1]

    # la session n'est remise qu'une fois
    assert client.post("/auth/device/poll", json={"device_code": body["device_code"]}).status_code == 410
    # et se révoque comme les autres
    assert client.post("/auth/logout", headers=tv).status_code == 204
    assert client.get("/auth/me", headers=tv).status_code == 401


def test_only_a_logged_in_approved_account_can_approve(client):
    body = start(client)
    assert client.post("/auth/device/approve", json={"user_code": body["user_code"]}).status_code == 401
    # le jeton unique du serveur n'a pas de compte à partager
    assert client.post("/auth/device/approve", headers=LEGACY, json={"user_code": body["user_code"]}).status_code == 400
    login(client, "Proprio")
    waiting, _ = login(client, "copain")  # en attente de validation
    assert client.post("/auth/device/approve", headers=waiting, json={"user_code": body["user_code"]}).status_code == 403
    assert client.post("/auth/device/poll", json={"device_code": body["device_code"]}).json() == {"status": "pending"}


def test_unknown_expired_or_denied_codes(client, monkeypatch):
    owner, _ = login(client, "Proprio")
    assert client.post("/auth/device/approve", headers=owner, json={"user_code": "ZZZZ-ZZZZ"}).status_code == 404
    assert client.post("/auth/device/poll", json={"device_code": "x" * 20}).status_code == 410

    refused = start(client)
    client.post("/auth/device/deny", headers=owner, json={"user_code": refused["user_code"]})
    assert client.post("/auth/device/poll", json={"device_code": refused["device_code"]}).status_code == 410

    old = start(client)
    monkeypatch.setattr(device_login, "TTL_SECONDS", -1)
    assert client.post("/auth/device/poll", json={"device_code": old["device_code"]}).status_code == 410
    assert client.post("/auth/device/approve", headers=owner, json={"user_code": old["user_code"]}).status_code == 404


def test_the_number_of_pending_requests_is_capped(client, monkeypatch):
    monkeypatch.setattr(device_login, "MAX_PENDING", 2)
    start(client)
    start(client)
    assert client.post("/auth/device/start", json={}).status_code == 429
