"""Numéros de compte : jamais réutilisés, une seule création même sous requêtes simultanées,
et le compte provisoire verse ses données à l'ancien compte récupéré."""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.db.database import Database
from app.db.repository import Repository


def run(tmp_path: Path, scenario) -> None:
    async def main():
        db = Database(tmp_path / "a.db")
        await db.connect()
        try:
            await scenario(db, Repository(db))
        finally:
            await db.close()

    asyncio.run(main())


async def moments(db, user_id: int) -> list[str]:
    rows = await (await db.conn.execute("SELECT text FROM track_moments WHERE user_id=?", (user_id,))).fetchall()
    return [r["text"] for r in rows]


def test_parallel_first_requests_create_one_account(tmp_path):
    async def scenario(db, repo):
        got = await asyncio.gather(*(repo.ensure_account_for_uid("u", "bob", "Bob", None, False) for _ in range(6)))
        assert len({a.id for a in got}) == 1

    run(tmp_path, scenario)


def test_recovered_account_keeps_new_data_and_nobody_inherits_it(tmp_path):
    async def scenario(db, repo):
        old, _ = await repo.upsert_account("vieux", "Vieux", None, None, False, 1)
        temp = await repo.ensure_account_for_uid("alice", "alice", "Alice", None, False)
        await repo.moment_add(temp.user_id, "deezer", "1", 1.0, "x", "à Alice")
        await repo.relink_uid("alice", old.id)
        assert await moments(db, old.user_id) == ["à Alice"]
        assert await moments(db, temp.user_id) == []

        newcomer = await repo.ensure_account_for_uid("carol", "carol", "Carol", None, False)
        assert newcomer.user_id > temp.user_id
        await repo.delete_user_data(newcomer.user_id)
        again = await repo.ensure_account_for_uid("dan", "dan", "Dan", None, False)
        assert again.user_id > newcomer.user_id

    run(tmp_path, scenario)
