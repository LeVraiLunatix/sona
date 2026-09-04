from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

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


@dataclass(slots=True)
class UserSettings:
    quality: str
    format: str
    notifications: bool


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
