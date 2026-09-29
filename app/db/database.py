from __future__ import annotations

import logging
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"

# Colonnes ajoutées après la première mise en production : `CREATE TABLE IF NOT
# EXISTS` ne les ajoute pas à une base déjà créée, il faut un ALTER explicite.
# (table, colonne, définition SQL)
_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("allowed_users", "display_name", "TEXT"),
    ("allowed_users", "added_by", "INTEGER"),
    ("invites", "max_uses", "INTEGER NOT NULL DEFAULT 1"),
    ("invites", "uses", "INTEGER NOT NULL DEFAULT 0"),
    ("invites", "revoked", "INTEGER NOT NULL DEFAULT 0"),
    ("users", "autoplay", "INTEGER NOT NULL DEFAULT 1"),
    ("app_accounts", "share_listening", "INTEGER NOT NULL DEFAULT 1"),
    ("playlists", "visibility", "TEXT NOT NULL DEFAULT 'private'"),
    ("library", "data", "TEXT"),
    # Lieu approximatif de l'écoute (carte des écoutes), arrondi à ~1 km.
    ("plays", "lat", "REAL"),
    ("plays", "lon", "REAL"),
)


class Database:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON")
        schema = _SCHEMA_PATH.read_text(encoding="utf-8")
        await self._conn.executescript(schema)
        await self._migrate()
        await self._conn.commit()

    async def _migrate(self) -> None:
        """Ajoute les colonnes manquantes sur une base créée par une version
        antérieure. Sans ça, une requête sur une colonne récente échoue avec
        « no such column » — et côté Telegram, l'action de l'utilisateur ne
        produit simplement rien."""
        assert self._conn is not None
        for table, column, definition in _MIGRATIONS:
            cursor = await self._conn.execute(f"PRAGMA table_info({table})")
            existing = {row["name"] for row in await cursor.fetchall()}
            if not existing or column in existing:
                continue
            logger.info("Migration base : ajout de %s.%s", table, column)
            await self._conn.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Base de données non connectée.")
        return self._conn
