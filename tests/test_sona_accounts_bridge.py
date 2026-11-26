"""Serveur musique ↔ service de comptes : jetons Supabase, amis réels (plus de « tout le monde est ami »), règles des sessions
d'écoute, routes internes, rattachement d'un ancien compte, scrobbling. Le service de comptes est remplacé par un faux."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.providers.lastfm_auth import LastfmProfile, LastfmSession
from app.services import party, presence
from tests import social_support

SECRET = "secret-interne"
INTERNAL = {"x-sona-internal": SECRET}
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
    monkeypatch.setenv("INTERNAL_API_SECRET", SECRET)
    party.reset()
    presence.reset()

    import app.api.main as main_module

    with TestClient(main_module.app) as test_client:
        main_module.app.state.deps.lastfm_auth = FakeLastfm()
        test_client.deps = main_module.app.state.deps
        test_client.fake = social_support.install(test_client)
        yield test_client


def person(client, name: str, role: str = "user") -> dict:
    token = f"{name}.jwt.signature"
    client.fake.add_user(token, f"uid-{name}", name, role)
    return {"Authorization": f"Bearer {token}"}


TRACK = {"source": "deezer", "source_id": "1", "title": "Grabba", "artist": "Ziak"}


# -- Identité -------------------------------------------------------------


def test_supabase_token_opens_an_account_with_its_own_data(client):
    alice, bob = person(client, "alice"), person(client, "bob")
    me = client.get("/auth/me", headers=alice).json()
    assert me["status"] == "approved" and me["display_name"] == "Alice"
    client.post("/plays", headers=alice, json={"plays": [{"title": "T", "artist": "A", "source": "deezer", "source_id": "1"}]})
    assert len(client.get("/plays/recent", headers=alice).json()) == 1
    assert client.get("/plays/recent", headers=bob).json() == []
    # Même personne, même espace de données ; pas de doublon de compte.
    assert client.get("/auth/me", headers=alice).json()["id"] == me["id"]


def test_invalid_banned_and_unreachable(client):
    assert client.get("/auth/me", headers={"Authorization": "Bearer faux.jeton.ici"}).status_code == 401
    banned = person(client, "troll")
    client.fake.sanctioned["troll.jwt.signature"] = ("banned", "spam")
    got = client.get("/auth/me", headers=banned)
    assert got.status_code == 403 and got.json() == {"error": "sanctioned", "status": "banned", "reason": "spam", "until": None}
    ok = person(client, "ok")
    client.fake.down = True
    assert client.get("/auth/me", headers=ok).status_code == 503
    client.fake.down = False
    # L'ancien jeton administrateur continue de marcher.
    assert client.get("/auth/me", headers=LEGACY).status_code == 200


def test_roles_come_from_the_accounts_service(client):
    admin = person(client, "boss", "admin")
    user = person(client, "alice")
    assert client.get("/auth/me", headers=admin).json()["is_admin"] is True
    assert client.get("/auth/me", headers=user).json()["is_admin"] is False
    assert client.get("/admin/accounts", headers=user).status_code == 403


# -- Plus de « tout le monde est ami » ---------------------------------------


def test_strangers_see_nothing_of_each_other(client):
    alice, bob = person(client, "alice"), person(client, "bob")
    client.post("/plays/now", headers=bob, json={"title": "Grabba", "artist": "Ziak", "duration_seconds": 180})
    client.post("/plays", headers=bob, json={"plays": [{"title": "T", "artist": "A", "source": "deezer", "source_id": "1"}]})
    assert client.get("/friends", headers=alice).json() == []
    bob_id = client.get("/auth/me", headers=bob).json()["id"]
    assert client.get(f"/friends/{bob_id}", headers=alice).status_code == 404
    client.post("/party", headers=bob)
    assert client.get("/party/active", headers=alice).json() == []
    client.post("/moments/deezer/1", headers=bob, json={"position": 10, "emoji": "🔥"})
    assert client.get("/moments/deezer/1", headers=alice).json() == []


def test_friends_see_what_they_are_allowed_to(client):
    alice, bob = person(client, "alice"), person(client, "bob")
    client.fake.befriend("uid-alice", "uid-bob")
    client.get("/auth/me", headers=alice)
    client.get("/auth/me", headers=bob)
    client.post("/plays/now", headers=bob, json={"title": "Grabba", "artist": "Ziak", "duration_seconds": 180})
    shown = client.get("/friends", headers=alice).json()
    assert [f["username"] for f in shown] == ["Bob"] and shown[0]["now_playing"]["track"]["title"] == "Grabba"
    # Bob coupe la présence : même ami, plus rien en direct.
    client.fake.grant("uid-bob", presence=False)
    assert client.get("/friends", headers=alice).json()[0]["now_playing"] is None
    # Blocage : disparition totale, dans les deux sens.
    client.fake.block("uid-alice", "uid-bob")
    assert client.get("/friends", headers=alice).json() == []
    assert client.get("/friends", headers=bob).json() == []


def test_accounts_service_down_shows_nothing(client):
    alice = person(client, "alice")
    client.fake.befriend("uid-alice", "uid-bob")
    client.get("/auth/me", headers=alice)

    async def boom(*_):
        raise RuntimeError("down")

    client.fake.friend_ids = boom
    assert client.get("/friends", headers=alice).json() == []


def test_without_accounts_service_nobody_is_a_friend(client):
    client.deps.accounts = None
    legacy = client.post("/auth/lastfm", json={"token": "vieux"}).json()
    client.post(f"/admin/accounts/{legacy['account']['id']}/approve", headers=LEGACY)
    headers = {"Authorization": f"Bearer {legacy['session_token']}"}
    assert client.get("/friends", headers=headers).json() == []


# -- Sessions d'écoute -----------------------------------------------------


def three(client):
    host, friend, stranger = person(client, "host"), person(client, "friend"), person(client, "stranger")
    client.fake.befriend("uid-host", "uid-friend")
    for h in (host, friend, stranger):
        client.get("/auth/me", headers=h)
    code = client.post("/party", headers=host).json()["code"]
    return host, friend, stranger, code


def test_default_access_is_friends_only_with_a_neutral_refusal(client):
    host, friend, stranger, code = three(client)
    refused = client.post(f"/party/{code}/join", headers=stranger)
    assert refused.status_code == 404 and refused.json()["detail"] == "Cette session n'est pas disponible."
    joined = client.post(f"/party/{code}/join", headers=friend).json()
    assert joined["access"] == "friends" and joined["role"] == "listener" and len(joined["members"]) == 2


def test_open_with_code_and_invite_access(client):
    host, friend, stranger, code = three(client)
    client.post(f"/party/{code}/settings", headers=host, json={"access": "link"})
    assert client.post(f"/party/{code}/join", headers=stranger).status_code == 200
    client.post(f"/party/{code}/leave", headers=stranger)
    client.post(f"/party/{code}/settings", headers=host, json={"access": "invite"})
    assert client.post(f"/party/{code}/join", headers=friend).status_code == 404  # ami, mais pas d'invitation
    invite = client.post(f"/party/{code}/invite", headers=host, json={"ttl_seconds": 3600}).json()
    assert client.post(f"/party/{code}/join", headers=stranger, json={"invite": "mauvais"}).status_code == 404
    assert client.post(f"/party/{code}/join", headers=stranger, json={"invite": invite["token"]}).status_code == 200
    # Le jeton n'est jamais conservé en clair.
    assert invite["token"] not in repr(party.get(code).__dict__)
    # Révocation : le même lien ne marche plus.
    client.post(f"/party/{code}/leave", headers=stranger)
    client.delete(f"/party/{code}/invite", headers=host)
    assert client.post(f"/party/{code}/join", headers=stranger, json={"invite": invite["token"]}).status_code == 404


def test_expired_invite_is_refused(client):
    host, _, stranger, code = three(client)
    client.post(f"/party/{code}/settings", headers=host, json={"access": "invite"})
    invite = client.post(f"/party/{code}/invite", headers=host, json={"ttl_seconds": 3600}).json()
    party.get(code).invite_expires = 0
    assert client.post(f"/party/{code}/join", headers=stranger, json={"invite": invite["token"]}).status_code == 404


def test_lock_and_participant_limit(client):
    host, friend, _, code = three(client)
    client.post(f"/party/{code}/settings", headers=host, json={"locked": True})
    assert client.post(f"/party/{code}/join", headers=friend).status_code == 404
    client.post(f"/party/{code}/settings", headers=host, json={"locked": False, "max_participants": 2})
    assert client.post(f"/party/{code}/join", headers=friend).status_code == 200
    other = person(client, "other")
    client.fake.befriend("uid-host", "uid-other")
    assert client.post(f"/party/{code}/join", headers=other).status_code == 404  # pleine
    assert client.post(f"/party/{code}/settings", headers=host, json={"max_participants": 51}).status_code == 422
    assert client.post(f"/party/{code}/settings", headers=friend, json={"locked": True}).status_code == 403


def test_block_during_and_before_a_session(client):
    host, friend, _, code = three(client)
    client.fake.block("uid-friend", "uid-host")
    assert client.post(f"/party/{code}/join", headers=friend).status_code == 404
    client.fake.blocks.clear()
    client.post(f"/party/{code}/join", headers=friend)
    other = person(client, "other")
    client.fake.befriend("uid-host", "uid-other")
    client.fake.block("uid-other", "uid-friend")  # un membre bloque l'arrivant
    assert client.post(f"/party/{code}/join", headers=other).status_code == 404


def test_moderation_roles(client):
    host, friend, _, code = three(client)
    mod, listener = person(client, "mod"), person(client, "listener")
    for p in ("mod", "listener"):
        client.fake.befriend("uid-host", f"uid-{p}")
        client.get("/auth/me", headers={"Authorization": f"Bearer {p}.jwt.signature"})
    for h in (friend, mod, listener):
        client.post(f"/party/{code}/join", headers=h)
    state = client.get(f"/party/{code}", headers=host).json()
    ids = {m["name"]: m["id"] for m in state["members"]}
    # Nommer un modérateur : l'hôte seulement.
    assert client.post(f"/party/{code}/moderator", headers=friend, json={"member_id": ids["Mod"], "moderator": True}).status_code == 403
    state = client.post(f"/party/{code}/moderator", headers=host, json={"member_id": ids["Mod"], "moderator": True}).json()
    assert next(m for m in state["members"] if m["name"] == "Mod")["role"] == "moderator"
    assert client.get(f"/party/{code}", headers=mod).json()["role"] == "moderator"
    # Un modérateur coupe le chat d'un auditeur, mais n'agit ni sur l'hôte ni sur un autre modérateur.
    state = client.post(f"/party/{code}/mute", headers=mod, json={"member_id": ids["Listener"], "muted": True}).json()
    assert next(m for m in state["members"] if m["name"] == "Listener")["muted"] is True
    assert client.post(f"/party/{code}/chat", headers=listener, json={"text": "salut"}).status_code == 403
    assert client.post(f"/party/{code}/ban", headers=mod, json={"member_id": ids["Host"]}).status_code == 403
    assert client.post(f"/party/{code}/kick", headers=friend, json={"member_id": ids["Listener"]}).status_code == 403
    # Bannir : la personne sort et ne peut plus revenir ; expulser : elle peut revenir.
    client.post(f"/party/{code}/ban", headers=mod, json={"member_id": ids["Listener"]})
    assert client.post(f"/party/{code}/join", headers=listener).status_code == 404
    client.post(f"/party/{code}/kick", headers=mod, json={"member_id": ids["Friend"]})
    assert client.post(f"/party/{code}/join", headers=friend).status_code == 200


def test_chat_switch_filter_and_message_removal(client):
    host, friend, _, code = three(client)
    client.post(f"/party/{code}/join", headers=friend)
    assert client.post(f"/party/{code}/chat", headers=friend, json={"text": "ceci est interdit"}).status_code == 400
    state = client.post(f"/party/{code}/chat", headers=friend, json={"text": "salut tout le monde"}).json()
    message = state["messages"][0]
    assert message["uid"] == "uid-friend"
    assert client.delete(f"/party/{code}/chat/{message['id']}", headers=friend).status_code == 403
    assert client.delete(f"/party/{code}/chat/{message['id']}", headers=host).json()["messages"] == []
    client.post(f"/party/{code}/settings", headers=host, json={"chat_enabled": False})
    assert client.post(f"/party/{code}/chat", headers=friend, json={"text": "encore"}).status_code == 403


def test_permissions_for_proposals_and_commands(client):
    host, friend, _, code = three(client)
    client.post(f"/party/{code}/join", headers=friend)
    client.post(f"/party/{code}/settings", headers=host, json={"permissions": {"add_tracks": "host"}})
    assert client.post(f"/party/{code}/queue", headers=friend, json={"track": TRACK}).status_code == 403
    assert client.post(f"/party/{code}/command", headers=friend, json={"action": "pause"}).status_code == 403
    client.post(f"/party/{code}/settings", headers=host, json={"permissions": {"pause": "everyone"}})
    assert client.post(f"/party/{code}/command", headers=friend, json={"action": "pause"}).status_code == 200
    assert client.post(f"/party/{code}/settings", headers=host, json={"permissions": {"pause": "personne"}}).status_code == 400


# -- Routes internes -------------------------------------------------------


def test_internal_routes_need_the_secret(client):
    assert client.get("/internal/users/uid-x/export").status_code in (401, 422)
    assert client.get("/internal/users/uid-x/export", headers={"x-sona-internal": "faux"}).status_code == 401
    assert client.get("/internal/users/uid-x/export", headers=INTERNAL).status_code == 200


def test_internal_routes_closed_without_a_secret(client):
    object.__setattr__(client.deps.settings, "sona_internal_secret", None)
    assert client.get("/internal/users/uid-x/export", headers=INTERNAL).status_code == 503


def test_export_and_delete_remove_everything(client):
    alice = person(client, "alice")
    client.post("/plays", headers=alice, json={"plays": [{"title": "T", "artist": "A", "source": "deezer", "source_id": "1"}]})
    client.post("/me/playlists", headers=alice, json={"name": "Ma liste", "tracks": [{**TRACK, "album": None, "year": None, "duration_seconds": 1, "cover_url": None, "artist_source_id": None, "album_source_id": None}]})
    data = client.get("/internal/users/uid-alice/export", headers=INTERNAL).json()["music"]
    assert len(data["plays"]) == 1 and data["playlists"][0]["name"] == "Ma liste" and len(data["playlist_tracks"]) == 1
    assert client.delete("/internal/users/uid-alice", headers=INTERNAL).status_code == 204
    assert client.get("/internal/users/uid-alice/export", headers=INTERNAL).json()["music"] == {}
    # Un nouveau jeton de la même personne repart d'un espace vide.
    assert client.get("/plays/recent", headers=alice).json() == []
    assert client.delete("/internal/users/inconnu", headers=INTERNAL).status_code == 204  # idempotent


def test_internal_playlist_hide_and_delete(client):
    alice = person(client, "alice")
    pid = client.post("/me/playlists", headers=alice, json={"name": "Signalée", "tracks": []}).json()["id"]
    client.put(f"/me/playlists/{pid}", headers=alice, json={"visibility": "friends"})
    assert client.post(f"/internal/content/playlist/{pid}/hide", headers=INTERNAL, json={"owner": "uid-alice"}).status_code == 200
    assert next(p for p in client.get("/me/playlists", headers=alice).json() if p["id"] == pid)["visibility"] == "private"
    assert client.post(f"/internal/content/playlist/{pid}/delete", headers=INTERNAL, json={"owner": "uid-intrus"}).status_code == 404
    assert client.post(f"/internal/content/playlist/{pid}/delete", headers=INTERNAL, json={"owner": "uid-alice"}).status_code == 200
    assert all(p["id"] != pid for p in client.get("/me/playlists", headers=alice).json())


def test_internal_session_moderation(client):
    host, friend, _, code = three(client)
    client.post(f"/party/{code}/join", headers=friend)
    message_id = client.post(f"/party/{code}/chat", headers=friend, json={"text": "oups"}).json()["messages"][0]["id"]
    assert client.post(f"/internal/sessions/{code}/delete_message", headers=INTERNAL, json={"message_id": message_id}).status_code == 200
    assert client.post(f"/internal/sessions/{code}/kick", headers=INTERNAL, json={"user": "uid-friend"}).status_code == 200
    assert client.post(f"/party/{code}/join", headers=friend).status_code == 404  # retiré par la modération : banni
    assert client.post(f"/internal/sessions/{code}/close", headers=INTERNAL, json={}).status_code == 200
    assert client.get(f"/party/{code}", headers=host).status_code == 404


# -- Ancien compte -----------------------------------------------------------


def test_link_a_legacy_account_keeps_its_data(client):
    legacy = client.post("/auth/lastfm", json={"token": "vieux"}).json()
    client.post(f"/admin/accounts/{legacy['account']['id']}/approve", headers=LEGACY)
    old = {"Authorization": f"Bearer {legacy['session_token']}"}
    client.post("/plays", headers=old, json={"plays": [{"title": "Souvenir", "artist": "A", "source": "deezer", "source_id": "9"}]})
    new = person(client, "alice")
    assert client.get("/plays/recent", headers=new).json() == []
    linked = client.post("/auth/link-legacy", headers=new, json={"token": "vieux"})
    assert linked.status_code == 200
    assert [p["title"] for p in client.get("/plays/recent", headers=new).json()] == ["Souvenir"]
    # L'ancienne session ne donne plus accès à ce compte ; on ne peut le rattacher qu'une fois.
    assert client.get("/plays/recent", headers=old).status_code == 401
    bob = person(client, "bob")
    assert client.post("/auth/link-legacy", headers=bob, json={"token": "vieux"}).status_code == 409
    assert client.post("/auth/link-legacy", headers=bob, json={"token": "inconnu"}).status_code == 404


def test_link_needs_a_sona_account_and_an_approved_legacy_account(client):
    assert client.post("/auth/link-legacy", headers=LEGACY, json={"token": "x"}).status_code == 400
    client.post("/auth/lastfm", json={"token": "attente"})  # jamais accepté
    assert client.post("/auth/link-legacy", headers=person(client, "alice"), json={"token": "attente"}).status_code == 403


# -- Scrobbling --------------------------------------------------------------


def test_scrobbles_go_through_the_accounts_service(client):
    alice = person(client, "alice")
    client.post("/plays/now", headers=alice, json={"title": "Grabba", "artist": "Ziak", "duration_seconds": 180})
    client.post("/plays", headers=alice, json={"plays": [{"title": "T1", "artist": "A", "source": "deezer", "source_id": "1"}]})
    import time

    for _ in range(50):
        if len(client.fake.scrobbles) >= 2:
            break
        time.sleep(0.05)
    assert ("uid-alice", "now_playing", "Ziak", "Grabba") in client.fake.scrobbles
    assert ("uid-alice", "scrobble", "A", "T1") in client.fake.scrobbles


def test_link_waits_for_lastfm_authorisation_without_signing_out(client):
    from app.providers.lastfm_auth import LastfmAuthError

    async def not_yet(token):
        raise LastfmAuthError("Last.fm : Unauthorized Token")

    client.deps.lastfm_auth.get_session = not_yet
    got = client.post("/auth/link-legacy", headers=person(client, "alice"), json={"token": "t"})
    assert got.status_code == 400 and got.json()["detail"].startswith("Autorise d'abord")


def test_auth_config_gives_the_native_apps_only_public_values(client):
    got = client.get("/auth/config").json()
    assert got["supabase_url"] is None and got["supabase_anon_key"] is None
    object.__setattr__(client.deps.settings, "supabase_url", "https://x.supabase.co")
    object.__setattr__(client.deps.settings, "supabase_anon_key", "anon-publique")
    got = client.get("/auth/config").json()
    assert got["supabase_url"] == "https://x.supabase.co" and got["supabase_anon_key"] == "anon-publique"
    assert SECRET not in str(got)
