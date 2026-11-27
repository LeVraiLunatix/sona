"""Réglage « Lecture automatique » : base, migration et écran Paramètres."""

import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace

import aiosqlite

from app.db.database import Database
from app.db.repository import Repository, UserSettings

USER = 7

# Schéma de la table `users` d'avant le réglage : une base de production en est
# là, et `CREATE TABLE IF NOT EXISTS` ne la touche pas.
OLD_USERS_TABLE = """CREATE TABLE users (
    user_id INTEGER PRIMARY KEY,
    quality TEXT NOT NULL DEFAULT 'best',
    format TEXT NOT NULL DEFAULT 'auto',
    notifications INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
)"""


def with_repo(scenario):
    """Ouvre une base neuve dans un dossier temporaire et joue `scenario`."""

    async def run():
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "sona.db")
            await db.connect()
            try:
                await scenario(Repository(db))
            finally:
                await db.close()

    asyncio.run(run())


def test_autoplay_is_on_by_default():
    async def scenario(repo):
        assert (await repo.get_settings(USER)).autoplay is True

    with_repo(scenario)


def test_the_setting_is_remembered():
    async def scenario(repo):
        assert await repo.toggle_autoplay(USER) is False
        assert (await repo.get_settings(USER)).autoplay is False
        assert await repo.toggle_autoplay(USER) is True
        assert (await repo.get_settings(USER)).autoplay is True

    with_repo(scenario)


def test_autoplay_does_not_disturb_the_other_settings():
    async def scenario(repo):
        # Comme depuis l'écran Paramètres, qui lit les réglages avant d'en
        # changer un : c'est cette lecture qui crée la ligne de l'utilisateur.
        await repo.get_settings(USER)
        await repo.set_quality(USER, "standard")
        await repo.toggle_notifications(USER)
        await repo.toggle_autoplay(USER)
        s = await repo.get_settings(USER)
        assert (s.quality, s.notifications, s.autoplay) == ("standard", False, False)

    with_repo(scenario)


def test_an_old_database_gets_the_column_and_keeps_playing():
    """Sans migration, la lecture des réglages échoue en « no such column » —
    côté Telegram, l'écran Paramètres ne s'affiche simplement plus."""

    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.db"
            conn = await aiosqlite.connect(path)
            await conn.execute(OLD_USERS_TABLE)
            await conn.execute(
                "INSERT INTO users (user_id, quality, format, notifications, created_at) "
                "VALUES (?, 'standard', 'mp3', 0, '2026-01-01T00:00:00+00:00')",
                (USER,),
            )
            await conn.commit()
            await conn.close()

            db = Database(path)
            await db.connect()
            try:
                repo = Repository(db)
                s = await repo.get_settings(USER)
                # Les réglages existants sont intacts, le nouveau est actif —
                # c'est le comportement que l'utilisateur connaît déjà.
                assert (s.quality, s.format, s.notifications) == ("standard", "mp3", False)
                assert s.autoplay is True
                assert await repo.toggle_autoplay(USER) is False
            finally:
                await db.close()

    asyncio.run(scenario())


# -- Écran Paramètres --------------------------------------------------
