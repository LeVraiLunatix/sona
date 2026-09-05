from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.db.database import Database
from app.providers.base import AlbumInfo, ArtistInfo, TrackInfo

VALID_KINDS = ("track", "album", "artist")

QUALITY_CHOICES = {
    "best": "Meilleure disponible",
    "standard": "Standard (débit réduit)",
}
FORMAT_CHOICES = {
    "auto": "Automatique",
    "mp3": "MP3",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


INVITE_TTL_HOURS = 24


@dataclass(slots=True)
class UserSettings:
    quality: str
    format: str
    notifications: bool


@dataclass(slots=True)
class AllowedUser:
    user_id: int
    display_name: str | None
    is_admin: bool
    added_at: str


@dataclass(slots=True)
class LibraryItem:
    kind: str
    source: str
    source_id: str
    title: str
    subtitle: str | None
    cover_url: str | None
    added_at: str


@dataclass(slots=True)
class HistoryItem:
    source: str
    source_id: str
    title: str
    subtitle: str | None
    cover_url: str | None
    viewed_at: str


def _item_from_object(obj: TrackInfo | AlbumInfo | ArtistInfo) -> tuple[str, str, str, str | None]:
    if isinstance(obj, TrackInfo):
        subtitle = obj.artist + (f" • {obj.album}" if obj.album else "")
        return obj.source, obj.source_id, obj.title, subtitle
    if isinstance(obj, AlbumInfo):
        return obj.source, obj.source_id, obj.title, obj.artist
    if isinstance(obj, ArtistInfo):
        return obj.source, obj.source_id, obj.name, None
    raise TypeError(f"Type non supporté: {type(obj)!r}")


class Repository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def ensure_user(self, user_id: int) -> None:
        await self._db.conn.execute(
            "INSERT OR IGNORE INTO users (user_id, created_at) VALUES (?, ?)",
            (user_id, _now()),
        )
        await self._db.conn.commit()

    async def get_settings(self, user_id: int) -> UserSettings:
        await self.ensure_user(user_id)
        cursor = await self._db.conn.execute(
            "SELECT quality, format, notifications FROM users WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        return UserSettings(row["quality"], row["format"], bool(row["notifications"]))

    async def set_quality(self, user_id: int, quality: str) -> None:
        await self._db.conn.execute(
            "UPDATE users SET quality = ? WHERE user_id = ?", (quality, user_id)
        )
        await self._db.conn.commit()

    async def set_format(self, user_id: int, fmt: str) -> None:
        await self._db.conn.execute(
            "UPDATE users SET format = ? WHERE user_id = ?", (fmt, user_id)
        )
        await self._db.conn.commit()

    async def toggle_notifications(self, user_id: int) -> bool:
        settings = await self.get_settings(user_id)
        new_value = not settings.notifications
        await self._db.conn.execute(
            "UPDATE users SET notifications = ? WHERE user_id = ?",
            (int(new_value), user_id),
        )
        await self._db.conn.commit()
        return new_value

    # -- Bibliothèque ------------------------------------------------

    async def library_contains(self, user_id: int, kind: str, source: str, source_id: str) -> bool:
        cursor = await self._db.conn.execute(
            "SELECT 1 FROM library WHERE user_id=? AND kind=? AND source=? AND source_id=?",
            (user_id, kind, source, source_id),
        )
        return (await cursor.fetchone()) is not None

    async def library_add(self, user_id: int, kind: str, obj: TrackInfo | AlbumInfo | ArtistInfo) -> None:
        source, source_id, title, subtitle = _item_from_object(obj)
        cover_url = getattr(obj, "cover_url", None) or getattr(obj, "picture_url", None)
        await self._db.conn.execute(
            """INSERT OR IGNORE INTO library
               (user_id, kind, source, source_id, title, subtitle, cover_url, added_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, kind, source, source_id, title, subtitle, cover_url, _now()),
        )
        await self._db.conn.commit()

    async def library_remove(self, user_id: int, kind: str, source: str, source_id: str) -> None:
        await self._db.conn.execute(
            "DELETE FROM library WHERE user_id=? AND kind=? AND source=? AND source_id=?",
            (user_id, kind, source, source_id),
        )
        await self._db.conn.commit()

    async def library_list(
        self, user_id: int, kind: str, offset: int = 0, limit: int = 5
    ) -> tuple[list[LibraryItem], int]:
        cursor = await self._db.conn.execute(
            "SELECT COUNT(*) AS c FROM library WHERE user_id=? AND kind=?", (user_id, kind)
        )
        total = (await cursor.fetchone())["c"]
        cursor = await self._db.conn.execute(
            """SELECT kind, source, source_id, title, subtitle, cover_url, added_at
               FROM library WHERE user_id=? AND kind=?
               ORDER BY added_at DESC LIMIT ? OFFSET ?""",
            (user_id, kind, limit, offset),
        )
        rows = await cursor.fetchall()
        items = [LibraryItem(**dict(r)) for r in rows]
        return items, total

    # -- Historique --------------------------------------------------

    async def history_add(self, user_id: int, obj: TrackInfo | AlbumInfo | ArtistInfo) -> None:
        source, source_id, title, subtitle = _item_from_object(obj)
        cover_url = getattr(obj, "cover_url", None) or getattr(obj, "picture_url", None)
        await self._db.conn.execute(
            """INSERT INTO history (user_id, source, source_id, title, subtitle, cover_url, viewed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(user_id, source, source_id)
               DO UPDATE SET viewed_at=excluded.viewed_at, title=excluded.title,
                              subtitle=excluded.subtitle, cover_url=excluded.cover_url""",
            (user_id, source, source_id, title, subtitle, cover_url, _now()),
        )
        await self._db.conn.commit()

    async def history_list(
        self, user_id: int, offset: int = 0, limit: int = 5
    ) -> tuple[list[HistoryItem], int]:
        cursor = await self._db.conn.execute(
            "SELECT COUNT(*) AS c FROM history WHERE user_id=?", (user_id,)
        )
        total = (await cursor.fetchone())["c"]
        cursor = await self._db.conn.execute(
            """SELECT source, source_id, title, subtitle, cover_url, viewed_at
               FROM history WHERE user_id=? ORDER BY viewed_at DESC LIMIT ? OFFSET ?""",
            (user_id, limit, offset),
        )
        rows = await cursor.fetchall()
        return [HistoryItem(**dict(r)) for r in rows], total

    async def history_clear(self, user_id: int) -> None:
        await self._db.conn.execute("DELETE FROM history WHERE user_id=?", (user_id,))
        await self._db.conn.commit()

    # -- Cache audio Telegram -----------------------------------------

    async def cache_get(self, source: str, source_id: str, fmt: str, quality: str) -> str | None:
        cursor = await self._db.conn.execute(
            """SELECT telegram_file_id FROM audio_cache
               WHERE source=? AND source_id=? AND format=? AND quality=?""",
            (source, source_id, fmt, quality),
        )
        row = await cursor.fetchone()
        return row["telegram_file_id"] if row else None

    async def cache_set(
        self,
        source: str,
        source_id: str,
        fmt: str,
        quality: str,
        file_id: str,
        file_unique_id: str | None,
    ) -> None:
        await self._db.conn.execute(
            """INSERT INTO audio_cache
               (source, source_id, format, quality, telegram_file_id, telegram_file_unique_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(source, source_id, format, quality)
               DO UPDATE SET telegram_file_id=excluded.telegram_file_id,
                              telegram_file_unique_id=excluded.telegram_file_unique_id""",
            (source, source_id, fmt, quality, file_id, file_unique_id, _now()),
        )
        await self._db.conn.commit()

    # -- Accès (whitelist + invitations) -------------------------------

    async def bootstrap_admins(self, user_ids: list[int]) -> None:
        """Assure que les IDs configurés via .env existent en base comme admins.

        Idempotent : n'écrase jamais un utilisateur déjà présent (ex: un admin
        rétrogradé/retiré manuellement en base ne serait pas ré-ajouté... en
        fait si, par design : .env reste la source de vérité de démarrage).
        """
        for user_id in user_ids:
            await self._db.conn.execute(
                """INSERT INTO allowed_users (user_id, is_admin, added_by, added_at)
                   VALUES (?, 1, NULL, ?)
                   ON CONFLICT(user_id) DO UPDATE SET is_admin=1""",
                (user_id, _now()),
            )
        await self._db.conn.commit()

    async def is_allowed(self, user_id: int) -> bool:
        cursor = await self._db.conn.execute(
            "SELECT 1 FROM allowed_users WHERE user_id=?", (user_id,)
        )
        return (await cursor.fetchone()) is not None

    async def is_admin(self, user_id: int) -> bool:
        cursor = await self._db.conn.execute(
            "SELECT is_admin FROM allowed_users WHERE user_id=?", (user_id,)
        )
        row = await cursor.fetchone()
        return bool(row and row["is_admin"])

    async def set_admin(self, user_id: int, is_admin: bool) -> None:
        await self._db.conn.execute(
            "UPDATE allowed_users SET is_admin=? WHERE user_id=?", (int(is_admin), user_id)
        )
        await self._db.conn.commit()

    async def touch_display_name(self, user_id: int, display_name: str | None) -> None:
        if not display_name:
            return
        await self._db.conn.execute(
            "UPDATE allowed_users SET display_name=? WHERE user_id=?",
            (display_name, user_id),
        )
        await self._db.conn.commit()

    async def list_allowed_users(self) -> list[AllowedUser]:
        cursor = await self._db.conn.execute(
            "SELECT user_id, display_name, is_admin, added_at FROM allowed_users ORDER BY added_at ASC"
        )
        rows = await cursor.fetchall()
        return [
            AllowedUser(r["user_id"], r["display_name"], bool(r["is_admin"]), r["added_at"])
            for r in rows
        ]

    async def add_allowed_user(
        self, user_id: int, added_by: int | None, display_name: str | None = None
    ) -> None:
        await self._db.conn.execute(
            """INSERT OR IGNORE INTO allowed_users (user_id, display_name, is_admin, added_by, added_at)
               VALUES (?, ?, 0, ?, ?)""",
            (user_id, display_name, added_by, _now()),
        )
        await self._db.conn.commit()

    async def remove_allowed_user(self, user_id: int) -> None:
        await self._db.conn.execute(
            "DELETE FROM allowed_users WHERE user_id=? AND is_admin=0", (user_id,)
        )
        await self._db.conn.commit()

    async def create_invite(self, created_by: int) -> str:
        token = secrets.token_urlsafe(12)
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=INVITE_TTL_HOURS)).isoformat()
        await self._db.conn.execute(
            "INSERT INTO invites (token, created_by, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, created_by, _now(), expires_at),
        )
        await self._db.conn.commit()
        return token

    async def consume_invite(
        self, token: str, user_id: int, display_name: str | None
    ) -> bool:
        cursor = await self._db.conn.execute(
            "SELECT created_by, expires_at, used_by FROM invites WHERE token=?", (token,)
        )
        row = await cursor.fetchone()
        if row is None or row["used_by"] is not None:
            return False
        if row["expires_at"] < datetime.now(timezone.utc).isoformat():
            return False

        await self._db.conn.execute(
            "UPDATE invites SET used_by=?, used_at=? WHERE token=?", (user_id, _now(), token)
        )
        await self._db.conn.execute(
            """INSERT OR IGNORE INTO allowed_users (user_id, display_name, is_admin, added_by, added_at)
               VALUES (?, ?, 0, ?, ?)""",
            (user_id, display_name, row["created_by"], _now()),
        )
        await self._db.conn.commit()
        return True
