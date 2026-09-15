import asyncio
import tempfile
from pathlib import Path

from app.db.database import Database
from app.db.repository import InviteResult, Repository
from app.services.invites import build_invite_link, extract_invite_token


def run(coro):
    return asyncio.run(coro)


# -- Extraction du jeton ------------------------------------------------
#
# Telegram ne transmet pas toujours le paramètre `?start=` (conversation déjà
# existante côté invité) : toutes ces écritures doivent mener au même jeton.

TOKEN = "Ab3-d_EfGh12ijkL"


def test_token_from_start_command():
    assert extract_invite_token(f"/start invite_{TOKEN}") == TOKEN


def test_token_from_prefixed_payload():
    assert extract_invite_token(f"invite_{TOKEN}") == TOKEN


def test_token_from_raw_token():
    assert extract_invite_token(TOKEN) == TOKEN


def test_token_from_pasted_link():
    assert extract_invite_token(build_invite_link("sona_bot", TOKEN)) == TOKEN


def test_token_from_pasted_link_in_sentence():
    text = f"tiens voilà : {build_invite_link('sona_bot', TOKEN)} à bientôt"
    assert extract_invite_token(text) == TOKEN


def test_plain_start_has_no_token():
    assert extract_invite_token("/start") is None


def test_ordinary_text_is_not_a_token():
    assert extract_invite_token("salut ça va") is None


def test_music_link_is_not_a_token():
    assert extract_invite_token("https://open.spotify.com/track/3n3Ppam7vgaVa1iaRUc9Lp") is None


# -- Cycle de vie d'une invitation --------------------------------------


def _with_repo(fn):
    async def wrapper():
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "test.db")
            await db.connect()
            try:
                await fn(Repository(db))
            finally:
                await db.close()

    return run(wrapper())


def test_single_use_invite_grants_then_is_exhausted():
    async def scenario(repo: Repository):
        await repo.bootstrap_admins([1])
        token = await repo.create_invite(1)

        result, inviter = await repo.consume_invite(token, 2, "Pote")
        assert result is InviteResult.OK
        assert inviter == 1
        assert await repo.is_allowed(2)

        result, _ = await repo.consume_invite(token, 3, "Autre")
        assert result is InviteResult.EXHAUSTED
        assert not await repo.is_allowed(3)

    _with_repo(scenario)


def test_unknown_token_is_reported_as_unknown():
    async def scenario(repo: Repository):
        result, inviter = await repo.consume_invite("pas-un-jeton", 2, "Pote")
        assert result is InviteResult.UNKNOWN
        assert inviter is None

    _with_repo(scenario)


def test_already_allowed_user_is_not_charged_a_use():
    async def scenario(repo: Repository):
        await repo.bootstrap_admins([1])
        token = await repo.create_invite(1, max_uses=2)
        await repo.consume_invite(token, 2, "Pote")

        result, _ = await repo.consume_invite(token, 2, "Pote")
        assert result is InviteResult.ALREADY_ALLOWED
        invite = await repo.get_invite(token)
        assert invite.uses == 1

    _with_repo(scenario)


def test_multi_use_invite_serves_several_people():
    async def scenario(repo: Repository):
        await repo.bootstrap_admins([1])
        token = await repo.create_invite(1, max_uses=3)
        for user_id in (10, 11, 12):
            result, _ = await repo.consume_invite(token, user_id, f"u{user_id}")
            assert result is InviteResult.OK
        result, _ = await repo.consume_invite(token, 13, "u13")
        assert result is InviteResult.EXHAUSTED

    _with_repo(scenario)


def test_revoked_invite_is_refused():
    async def scenario(repo: Repository):
        await repo.bootstrap_admins([1])
        token = await repo.create_invite(1)
        await repo.revoke_invite(token)
        result, _ = await repo.consume_invite(token, 2, "Pote")
        assert result is InviteResult.REVOKED

    _with_repo(scenario)


def test_expired_invite_is_refused():
    async def scenario(repo: Repository):
        await repo.bootstrap_admins([1])
        token = await repo.create_invite(1)
        await repo._db.conn.execute(
            "UPDATE invites SET expires_at=? WHERE token=?", ("2000-01-01T00:00:00+00:00", token)
        )
        await repo._db.conn.commit()
        result, _ = await repo.consume_invite(token, 2, "Pote")
        assert result is InviteResult.EXPIRED

    _with_repo(scenario)


# -- Demandes d'accès ---------------------------------------------------


def test_access_request_is_notified_once_then_resolved():
    async def scenario(repo: Repository):
        await repo.bootstrap_admins([1])
        assert await repo.record_access_request(2, "Pote", "pote") is True
        assert await repo.record_access_request(2, "Pote", "pote") is False
        assert [r.user_id for r in await repo.list_access_requests()] == [2]

        await repo.add_allowed_user(2, added_by=1, display_name="Pote")
        await repo.resolve_access_request(2, "approved", 1)
        assert await repo.list_access_requests() == []
        assert await repo.is_allowed(2)

    _with_repo(scenario)


def test_admins_are_listed_for_notification():
    async def scenario(repo: Repository):
        await repo.bootstrap_admins([1, 5])
        await repo.add_allowed_user(2, added_by=1)
        assert sorted(await repo.list_admins()) == [1, 5]

    _with_repo(scenario)


def test_old_database_without_new_invite_columns_is_migrated():
    """Une base créée avant l'ajout de max_uses/uses/revoked doit continuer à
    fonctionner : sans migration, la requête échoue et l'invité ne voit
    strictement rien se passer."""

    async def scenario():
        import aiosqlite

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.db"
            conn = await aiosqlite.connect(path)
            await conn.execute(
                """CREATE TABLE invites (
                       token TEXT PRIMARY KEY, created_by INTEGER NOT NULL,
                       created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
                       used_by INTEGER, used_at TEXT)"""
            )
            await conn.commit()
            await conn.close()

            db = Database(path)
            await db.connect()
            repo = Repository(db)
            token = await repo.create_invite(1)
            result, _ = await repo.consume_invite(token, 2, "Pote")
            assert result is InviteResult.OK
            await db.close()

    run(scenario())
