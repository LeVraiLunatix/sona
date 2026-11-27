"""Faux service de comptes pour les tests du serveur musique : amitiés, blocages, réglages de visibilité,
jetons Supabase — sans réseau. La vraie règle de visibilité est testée côté Rust (rust/sona-accounts) sur Postgres."""

from __future__ import annotations

import asyncio

from app.services.sona_accounts import Identity, InvalidToken, Relation, Sanctioned


class FakeAccounts:
    def __init__(self) -> None:
        self.tokens: dict[str, Identity] = {}
        self.sanctioned: dict[str, tuple[str, str | None]] = {}
        self.friends: dict[str, set[str]] = {}
        self.blocks: set[tuple[str, str]] = set()
        # uid -> permissions que cette personne accorde à ses amis (toutes accordées par défaut)
        self.grants: dict[str, dict[str, bool]] = {}
        self.profile_data: dict[str, dict] = {}
        self.offensive_words: set[str] = {"interdit"}
        self.scrobbles: list[tuple] = []
        self.down = False

    # -- identités -----------------------------------------------------
    def add_user(self, token: str, uid: str, username: str, role: str = "user", status: str = "active") -> None:
        self.tokens[token] = Identity(uid=uid, username=username, role=role, status=status)
        self.profile_data[uid] = {"id": uid, "username": username, "display_name": username.title(), "avatar_url": None, "status": status}

    async def verify(self, token: str) -> Identity:
        if self.down:
            from app.services.sona_accounts import Unavailable

            raise Unavailable("down")
        if token in self.sanctioned:
            raise Sanctioned(self.sanctioned[token][0], self.sanctioned[token][1], None)
        who = self.tokens.get(token)
        if who is None:
            raise InvalidToken()
        return who

    async def profiles(self, ids):
        return {i: self.profile_data[i] for i in ids if i in self.profile_data}

    async def profile(self, uid):
        return self.profile_data.get(uid, {})

    # -- relations -----------------------------------------------------
    def befriend(self, a: str, b: str) -> None:
        self.friends.setdefault(a, set()).add(b)
        self.friends.setdefault(b, set()).add(a)

    def block(self, a: str, b: str) -> None:
        self.blocks.add((a, b))

    def grant(self, uid: str, **perms: bool) -> None:
        self.grants.setdefault(uid, {}).update(perms)

    async def friend_ids(self, uid):
        return sorted(f for f in self.friends.get(uid, set()) if (uid, f) not in self.blocks and (f, uid) not in self.blocks)

    async def relations(self, viewer, others):
        out = {}
        for o in others:
            blocked = (viewer, o) in self.blocks or (o, viewer) in self.blocks
            friend = o in self.friends.get(viewer, set())
            g = self.grants.get(o, {})
            ok = friend and not blocked
            out[o] = Relation(
                friend=friend, blocked=blocked, visible=not blocked,
                presence=ok and g.get("presence", True), history=ok and g.get("history", True),
                stats=ok and g.get("stats", True), playlists=ok and g.get("playlists", True), profile=ok and g.get("profile", True),
            )
        return out

    async def text_offensive(self, text):
        return any(w in text.lower() for w in self.offensive_words)

    async def scrobble(self, uid, kind, artist, track, album, duration, timestamp):
        self.scrobbles.append((uid, kind, artist, track))

    async def adopt_lastfm(self, uid, username, session_key):
        return True

    async def aclose(self) -> None:
        pass


def install(client) -> FakeAccounts:
    fake = FakeAccounts()
    client.deps.accounts = fake
    return fake


def link(client, account_id: int, uid: str) -> None:
    """Rattache un compte (ouvert avec une session Last.fm de test) à un UUID du faux service."""
    client.portal.call(client.deps.repo.relink_uid, uid, account_id)


def befriend(client, fake: FakeAccounts, *accounts: dict) -> None:
    """Rend amis des comptes créés par `login()` (leurs sessions de test restent valables)."""
    uids = []
    for acc in accounts:
        uid = f"uid-{acc['id']}"
        link(client, acc["id"], uid)
        fake.profile_data.setdefault(uid, {"id": uid, "username": acc["username"], "display_name": acc["display_name"], "avatar_url": None, "status": "active"})
        uids.append(uid)
    for i, a in enumerate(uids):
        for b in uids[i + 1:]:
            fake.befriend(a, b)


def befriend_all(client, fake: FakeAccounts, headers: dict) -> None:
    """Rattache la personne connectée avec `headers` au faux service et la rend amie avec toutes celles déjà rattachées
    (pratique quand un test a besoin d'un cercle d'amis sans s'intéresser à la façon dont il se forme)."""
    me = client.get("/auth/me", headers=headers).json()
    uid = f"uid-{me['id']}"
    link(client, me["id"], uid)
    fake.profile_data.setdefault(uid, {"id": uid, "username": me["username"], "display_name": me["display_name"], "avatar_url": None, "status": "active"})
    for other in list(fake.profile_data):
        if other != uid and other.startswith("uid-"):
            fake.befriend(uid, other)
