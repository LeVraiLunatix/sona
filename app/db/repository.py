from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

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


# Une invitation trop courte est la première cause d'échec côté invité :
# le lien est souvent ouvert le lendemain, voire plus tard.
INVITE_TTL_HOURS = 24 * 7


class InviteResult(str, Enum):
    """Issue d'une tentative d'utilisation d'un lien d'invitation."""

    OK = "ok"
    UNKNOWN = "unknown"
    EXPIRED = "expired"
    EXHAUSTED = "exhausted"
    REVOKED = "revoked"
    ALREADY_ALLOWED = "already_allowed"


@dataclass(slots=True)
class UserSettings:
    quality: str
    format: str
    notifications: bool
    # Lecture automatique : choisir un morceau envoie le son dans la foulée.
    # Désactivée, seul le bouton « Écouter » déclenche un envoi.
    autoplay: bool = True


@dataclass(slots=True)
class AllowedUser:
    user_id: int
    display_name: str | None
    is_admin: bool
    added_at: str


@dataclass(slots=True)
class Invite:
    token: str
    created_by: int
    created_at: str
    expires_at: str
    max_uses: int
    uses: int
    revoked: bool


@dataclass(slots=True)
class AccessRequest:
    user_id: int
    display_name: str | None
    username: str | None
    requested_at: str
    status: str


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
            "SELECT quality, format, notifications, autoplay FROM users WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        return UserSettings(
            row["quality"], row["format"], bool(row["notifications"]), bool(row["autoplay"])
        )

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

    async def toggle_autoplay(self, user_id: int) -> bool:
        settings = await self.get_settings(user_id)
        new_value = not settings.autoplay
        await self._db.conn.execute(
            "UPDATE users SET autoplay = ? WHERE user_id = ?",
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

    async def cache_get_many(
        self, keys: list[tuple[str, str]], fmt: str, quality: str
    ) -> dict[tuple[str, str], str]:
        """Cherche plusieurs morceaux d'un coup dans le cache audio.

        Sert au panneau de suggestions (mode inline), qui est interrogé à
        chaque frappe : une requête par résultat serait du gaspillage."""
        if not keys:
            return {}
        placeholders = ",".join("?" for _ in keys)
        cursor = await self._db.conn.execute(
            f"""SELECT source, source_id, telegram_file_id FROM audio_cache
                WHERE format=? AND quality=? AND source_id IN ({placeholders})""",
            (fmt, quality, *(source_id for _, source_id in keys)),
        )
        rows = await cursor.fetchall()
        found = {(r["source"], r["source_id"]): r["telegram_file_id"] for r in rows}
        # Le filtre SQL ne porte que sur source_id : on recoupe la source ici.
        return {key: found[key] for key in keys if key in found}

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

    # -- Cache audio persistant (API / app iOS) ------------------------

    async def stream_cache_get(
        self, source: str, source_id: str, fmt: str, quality: str
    ) -> tuple[str, str] | None:
        """Renvoie `(file_path, content_type)` si le morceau est déjà sur
        disque pour ce format/cette qualité, sinon None."""
        cursor = await self._db.conn.execute(
            """SELECT file_path, content_type FROM stream_cache
               WHERE source=? AND source_id=? AND format=? AND quality=?""",
            (source, source_id, fmt, quality),
        )
        row = await cursor.fetchone()
        return (row["file_path"], row["content_type"]) if row else None

    async def stream_cache_set(
        self, source: str, source_id: str, fmt: str, quality: str, file_path: str, content_type: str
    ) -> None:
        await self._db.conn.execute(
            """INSERT INTO stream_cache (source, source_id, format, quality, file_path, content_type, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(source, source_id, format, quality)
               DO UPDATE SET file_path=excluded.file_path, content_type=excluded.content_type""",
            (source, source_id, fmt, quality, file_path, content_type, _now()),
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

    async def list_admins(self) -> list[int]:
        cursor = await self._db.conn.execute(
            "SELECT user_id FROM allowed_users WHERE is_admin=1 ORDER BY added_at ASC"
        )
        return [row["user_id"] for row in await cursor.fetchall()]

    # -- Invitations ---------------------------------------------------

    async def create_invite(self, created_by: int, max_uses: int = 1) -> str:
        token = secrets.token_urlsafe(12)
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=INVITE_TTL_HOURS)).isoformat()
        await self._db.conn.execute(
            """INSERT INTO invites (token, created_by, created_at, expires_at, max_uses, uses, revoked)
               VALUES (?, ?, ?, ?, ?, 0, 0)""",
            (token, created_by, _now(), expires_at, max(1, max_uses)),
        )
        await self._db.conn.commit()
        return token

    async def get_invite(self, token: str) -> Invite | None:
        cursor = await self._db.conn.execute(
            """SELECT token, created_by, created_at, expires_at, max_uses, uses, revoked
               FROM invites WHERE token=?""",
            (token,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return Invite(
            token=row["token"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            max_uses=row["max_uses"],
            uses=row["uses"],
            revoked=bool(row["revoked"]),
        )

    async def revoke_invite(self, token: str) -> None:
        await self._db.conn.execute("UPDATE invites SET revoked=1 WHERE token=?", (token,))
        await self._db.conn.commit()

    async def consume_invite(
        self, token: str, user_id: int, display_name: str | None
    ) -> tuple[InviteResult, int | None]:
        """Tente d'utiliser une invitation.

        Retourne `(résultat, id de l'auteur de l'invitation)`. L'id permet à
        l'appelant de prévenir l'admin que son lien vient de servir. Le
        résultat détaillé (expiré / épuisé / inconnu) est indispensable :
        répondre « bot privé » à quelqu'un qui présente un lien périmé lui
        laisse croire que le bot est cassé.
        """
        invite = await self.get_invite(token)
        if invite is None:
            return InviteResult.UNKNOWN, None
        if invite.revoked:
            return InviteResult.REVOKED, invite.created_by
        if invite.expires_at < _now():
            return InviteResult.EXPIRED, invite.created_by
        if await self.is_allowed(user_id):
            return InviteResult.ALREADY_ALLOWED, invite.created_by
        if invite.uses >= invite.max_uses:
            return InviteResult.EXHAUSTED, invite.created_by

        # `uses < max_uses` dans le UPDATE : deux invités qui cliquent en même
        # temps sur le même lien à usage unique ne peuvent pas passer tous les deux.
        cursor = await self._db.conn.execute(
            "UPDATE invites SET uses = uses + 1, used_by=?, used_at=? WHERE token=? AND uses < max_uses",
            (user_id, _now(), token),
        )
        if cursor.rowcount == 0:
            await self._db.conn.commit()
            return InviteResult.EXHAUSTED, invite.created_by

        await self._db.conn.execute(
            """INSERT OR IGNORE INTO allowed_users (user_id, display_name, is_admin, added_by, added_at)
               VALUES (?, ?, 0, ?, ?)""",
            (user_id, display_name, invite.created_by, _now()),
        )
        await self._db.conn.commit()
        return InviteResult.OK, invite.created_by

    # -- Demandes d'accès ----------------------------------------------

    async def record_access_request(
        self, user_id: int, display_name: str | None, username: str | None
    ) -> bool:
        """Enregistre (ou rafraîchit) une demande d'accès.

        Retourne True si c'est une nouvelle demande à notifier, False si une
        demande est déjà en attente (pour ne pas spammer les admins)."""
        cursor = await self._db.conn.execute(
            "SELECT status FROM access_requests WHERE user_id=?", (user_id,)
        )
        row = await cursor.fetchone()
        is_new = row is None or row["status"] != "pending"
        await self._db.conn.execute(
            """INSERT INTO access_requests (user_id, display_name, username, requested_at, status)
               VALUES (?, ?, ?, ?, 'pending')
               ON CONFLICT(user_id) DO UPDATE SET
                   display_name=excluded.display_name,
                   username=excluded.username,
                   requested_at=excluded.requested_at,
                   status='pending',
                   resolved_by=NULL,
                   resolved_at=NULL""",
            (user_id, display_name, username, _now()),
        )
        await self._db.conn.commit()
        return is_new

    async def list_access_requests(self, status: str = "pending") -> list[AccessRequest]:
        cursor = await self._db.conn.execute(
            """SELECT user_id, display_name, username, requested_at, status
               FROM access_requests WHERE status=? ORDER BY requested_at ASC""",
            (status,),
        )
        rows = await cursor.fetchall()
        return [
            AccessRequest(
                user_id=r["user_id"],
                display_name=r["display_name"],
                username=r["username"],
                requested_at=r["requested_at"],
                status=r["status"],
            )
            for r in rows
        ]

    async def get_access_request(self, user_id: int) -> AccessRequest | None:
        cursor = await self._db.conn.execute(
            """SELECT user_id, display_name, username, requested_at, status
               FROM access_requests WHERE user_id=?""",
            (user_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return AccessRequest(
            user_id=row["user_id"],
            display_name=row["display_name"],
            username=row["username"],
            requested_at=row["requested_at"],
            status=row["status"],
        )

    async def resolve_access_request(self, user_id: int, status: str, admin_id: int) -> None:
        await self._db.conn.execute(
            "UPDATE access_requests SET status=?, resolved_by=?, resolved_at=? WHERE user_id=?",
            (status, admin_id, _now(), user_id),
        )
        await self._db.conn.commit()
