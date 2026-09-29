from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import asdict, dataclass, field
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
    # Titres ajoutés depuis que la fiche complète est gardée.
    track: TrackInfo | None = None


def _library_item(row) -> LibraryItem:
    d = dict(row)
    data = d.pop("data", None)
    track = None
    if data:
        try:
            track = TrackInfo(**json.loads(data))
        except (ValueError, TypeError):
            track = None
    return LibraryItem(**d, track=track)


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


@dataclass(slots=True)
class Play:
    played_at: str
    title: str
    artist: str
    album: str | None = None
    source: str | None = None
    source_id: str | None = None
    artist_source_id: str | None = None
    album_source_id: str | None = None
    cover_url: str | None = None
    duration_seconds: int | None = None
    listened_seconds: int | None = None
    origin: str = "sona"


_PLAY_COLUMNS = (
    "played_at, title, artist, album, source, source_id, artist_source_id, album_source_id, "
    "cover_url, duration_seconds, listened_seconds, origin"
)


@dataclass(slots=True)
class Account:
    id: int
    lastfm_username: str
    display_name: str | None
    avatar_url: str | None
    status: str
    is_admin: bool
    user_id: int
    lastfm_session_key: str | None
    scrobble_to_lastfm: bool
    created_at: str
    decided_at: str | None
    # Visible des autres comptes : « en train d'écouter », écoutes, profil.
    share_listening: bool = True


PLAYLIST_VISIBILITIES = ("private", "friends", "collaborative")


@dataclass(slots=True)
class Playlist:
    id: int
    user_id: int
    name: str
    description: str | None
    cover_url: str | None
    origin: str | None
    origin_url: str | None
    import_status: str
    import_total: int | None
    import_done: int
    import_missing: int
    import_error: str | None
    # private : pour soi ; friends : visible des amis ; collaborative : les
    # amis peuvent aussi y ajouter / retirer / déplacer des titres.
    visibility: str
    created_at: str
    updated_at: str
    track_count: int = 0
    duration_seconds: int = 0
    # Pochettes des premiers morceaux : mosaïque quand la playlist n'a pas
    # d'image à elle.
    covers: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PlaylistEntry:
    entry_id: int
    track: TrackInfo


_PLAYLIST_COLUMNS = (
    "id, user_id, name, description, cover_url, origin, origin_url, import_status, import_total, "
    "import_done, import_missing, import_error, visibility, created_at, updated_at"
)
_PLAYLIST_TRACK_COLUMNS = (
    "source, source_id, title, artist, album, year, duration_seconds, cover_url, "
    "artist_source_id, album_source_id"
)


ACCOUNT_STATUSES = ("pending", "approved", "rejected")
# Espace de données des comptes de l'app, au-delà des identifiants Telegram
# (quelques milliards au plus) : jamais de collision avec un utilisateur du bot.
ACCOUNT_USER_ID_BASE = 100_000_000_000


def _account(row) -> Account:
    d = dict(row)
    d["is_admin"] = bool(d["is_admin"])
    d["scrobble_to_lastfm"] = bool(d["scrobble_to_lastfm"])
    d["share_listening"] = bool(d.get("share_listening", 1))
    d.pop("decided_by", None)
    return Account(**d)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


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
        # Sans ligne existante, l'UPDATE ne toucherait rien : le réglage
        # choisi depuis l'app était perdu en silence.
        await self.ensure_user(user_id)
        await self._db.conn.execute(
            "UPDATE users SET quality = ? WHERE user_id = ?", (quality, user_id)
        )
        await self._db.conn.commit()

    async def set_format(self, user_id: int, fmt: str) -> None:
        # Sans ligne existante, l'UPDATE ne toucherait rien : le réglage
        # choisi depuis l'app était perdu en silence.
        await self.ensure_user(user_id)
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

    async def library_add(
        self, user_id: int, kind: str, obj: TrackInfo | AlbumInfo | ArtistInfo, added_at: str | None = None
    ) -> bool:
        """Ajoute à la bibliothèque ; False si l'élément y était déjà."""
        source, source_id, title, subtitle = _item_from_object(obj)
        cover_url = getattr(obj, "cover_url", None) or getattr(obj, "picture_url", None)
        data = json.dumps(asdict(obj)) if isinstance(obj, TrackInfo) else None
        cursor = await self._db.conn.execute(
            """INSERT OR IGNORE INTO library
               (user_id, kind, source, source_id, title, subtitle, cover_url, added_at, data)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, kind, source, source_id, title, subtitle, cover_url, added_at or _now(), data),
        )
        await self._db.conn.commit()
        return bool(cursor.rowcount)

    async def library_get(self, user_id: int, kind: str, source: str, source_id: str) -> LibraryItem | None:
        cursor = await self._db.conn.execute(
            """SELECT kind, source, source_id, title, subtitle, cover_url, added_at, data
               FROM library WHERE user_id=? AND kind=? AND source=? AND source_id=?""",
            (user_id, kind, source, source_id),
        )
        row = await cursor.fetchone()
        return _library_item(row) if row else None

    async def library_fill_track(self, user_id: int, track: TrackInfo) -> None:
        """Complète la fiche d'un titre ajouté avant qu'on la garde."""
        await self._db.conn.execute(
            "UPDATE library SET data=? WHERE user_id=? AND kind='track' AND source=? AND source_id=? AND data IS NULL",
            (json.dumps(asdict(track)), user_id, track.source, track.source_id),
        )
        await self._db.conn.commit()

    async def library_has_title(self, user_id: int, title: str, artist: str) -> bool:
        """Un titre de même nom et même artiste est-il déjà dans la
        bibliothèque (quelle que soit sa source) ?"""
        cursor = await self._db.conn.execute(
            """SELECT 1 FROM library WHERE user_id=? AND kind='track'
               AND lower(title)=lower(?) AND lower(subtitle) LIKE lower(?) || '%' LIMIT 1""",
            (user_id, title, artist),
        )
        return (await cursor.fetchone()) is not None

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
            """SELECT kind, source, source_id, title, subtitle, cover_url, added_at, data
               FROM library WHERE user_id=? AND kind=?
               ORDER BY added_at DESC LIMIT ? OFFSET ?""",
            (user_id, kind, limit, offset),
        )
        rows = await cursor.fetchall()
        items = [_library_item(r) for r in rows]
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

    # -- Écoutes (stats) ---------------------------------------------

    async def plays_add(self, user_id: int, plays: list[Play]) -> list[Play]:
        """Ajoute des écoutes ; les doublons exacts (même instant, titre,
        artiste) sont ignorés — un import relancé ou une écoute renvoyée par
        l'app après une coupure réseau ne compte pas deux fois. Renvoie les
        écoutes réellement ajoutées."""
        added: list[Play] = []
        for p in plays:
            cursor = await self._db.conn.execute(
                f"INSERT OR IGNORE INTO plays (user_id, {_PLAY_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    user_id, p.played_at, p.title, p.artist, p.album, p.source, p.source_id,
                    p.artist_source_id, p.album_source_id, p.cover_url, p.duration_seconds,
                    p.listened_seconds, p.origin,
                ),
            )
            if cursor.rowcount:
                added.append(p)
        await self._db.conn.commit()
        return added

    async def plays_timestamps(self, user_id: int, origin: str) -> set[str]:
        cursor = await self._db.conn.execute(
            "SELECT played_at FROM plays WHERE user_id=? AND origin=?", (user_id, origin)
        )
        return {r["played_at"] for r in await cursor.fetchall()}

    async def plays_between(self, user_id: int, start: str | None, end: str | None) -> list[Play]:
        """Écoutes de [start, end[ (horodatages ISO UTC), ordre chronologique."""
        clauses, params = ["user_id=?"], [user_id]
        if start:
            clauses.append("played_at >= ?")
            params.append(start)
        if end:
            clauses.append("played_at < ?")
            params.append(end)
        cursor = await self._db.conn.execute(
            f"SELECT {_PLAY_COLUMNS} FROM plays WHERE {' AND '.join(clauses)} ORDER BY played_at",
            params,
        )
        return [Play(**dict(r)) for r in await cursor.fetchall()]

    async def plays_recent(self, user_id: int, limit: int = 50) -> list[Play]:
        cursor = await self._db.conn.execute(
            f"SELECT {_PLAY_COLUMNS} FROM plays WHERE user_id=? ORDER BY played_at DESC LIMIT ?",
            (user_id, limit),
        )
        return [Play(**dict(r)) for r in await cursor.fetchall()]

    async def plays_first_by_artist(self, user_id: int) -> dict[str, str]:
        """Première écoute de chaque artiste (clé : nom en minuscules) — pour
        repérer les découvertes d'une période."""
        cursor = await self._db.conn.execute(
            "SELECT lower(artist) AS k, MIN(played_at) AS first FROM plays WHERE user_id=? GROUP BY lower(artist)",
            (user_id,),
        )
        return {r["k"]: r["first"] for r in await cursor.fetchall()}

    async def plays_days(self, user_id: int) -> list[str]:
        """Horodatages de toutes les écoutes (pour la série de jours)."""
        cursor = await self._db.conn.execute(
            "SELECT played_at FROM plays WHERE user_id=? ORDER BY played_at", (user_id,)
        )
        return [r["played_at"] for r in await cursor.fetchall()]

    async def plays_latest(self, user_id: int, origin: str) -> str | None:
        cursor = await self._db.conn.execute(
            "SELECT MAX(played_at) AS m FROM plays WHERE user_id=? AND origin=?", (user_id, origin)
        )
        row = await cursor.fetchone()
        return row["m"] if row else None

    # -- Comptes de l'app (connexion Last.fm) ---------------------------

    async def account_by_username(self, username: str) -> Account | None:
        cursor = await self._db.conn.execute(
            "SELECT * FROM app_accounts WHERE lastfm_username=? COLLATE NOCASE", (username,)
        )
        row = await cursor.fetchone()
        return _account(row) if row else None

    async def account_by_id(self, account_id: int) -> Account | None:
        cursor = await self._db.conn.execute("SELECT * FROM app_accounts WHERE id=?", (account_id,))
        row = await cursor.fetchone()
        return _account(row) if row else None

    async def upsert_account(
        self,
        username: str,
        display_name: str | None,
        avatar_url: str | None,
        session_key: str | None,
        is_admin: bool,
        legacy_user_id: int,
    ) -> tuple[Account, bool]:
        """Crée le compte à la première connexion (en attente, sauf admin),
        ou met à jour son profil et sa clé Last.fm. Renvoie (compte, créé)."""
        existing = await self.account_by_username(username)
        if existing is not None:
            await self._db.conn.execute(
                """UPDATE app_accounts SET display_name=?, avatar_url=?, lastfm_session_key=COALESCE(?, lastfm_session_key),
                   is_admin=MAX(is_admin, ?), status=CASE WHEN ? THEN 'approved' ELSE status END WHERE id=?""",
                (display_name, avatar_url, session_key, int(is_admin), int(is_admin), existing.id),
            )
            await self._db.conn.commit()
            return await self.account_by_id(existing.id), False

        # Le premier admin garde les données de l'ancien jeton unique.
        cursor = await self._db.conn.execute("SELECT 1 FROM app_accounts WHERE user_id=?", (legacy_user_id,))
        takes_legacy = is_admin and await cursor.fetchone() is None
        cursor = await self._db.conn.execute("SELECT COALESCE(MAX(id), 0) + 1 AS n FROM app_accounts")
        next_id = (await cursor.fetchone())["n"]
        user_id = legacy_user_id if takes_legacy else ACCOUNT_USER_ID_BASE + next_id
        now = _now()
        cursor = await self._db.conn.execute(
            """INSERT INTO app_accounts (lastfm_username, display_name, avatar_url, status, is_admin, user_id,
                                         lastfm_session_key, created_at, decided_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (username, display_name, avatar_url, "approved" if is_admin else "pending", int(is_admin),
             user_id, session_key, now, now if is_admin else None),
        )
        await self._db.conn.commit()
        return await self.account_by_id(cursor.lastrowid), True

    async def list_accounts(self) -> list[Account]:
        cursor = await self._db.conn.execute(
            """SELECT * FROM app_accounts
               ORDER BY CASE status WHEN 'pending' THEN 0 WHEN 'approved' THEN 1 ELSE 2 END, created_at DESC"""
        )
        return [_account(r) for r in await cursor.fetchall()]

    async def set_account_status(self, account_id: int, status: str, decided_by: int | None) -> None:
        await self._db.conn.execute(
            "UPDATE app_accounts SET status=?, decided_at=?, decided_by=? WHERE id=?",
            (status, _now(), decided_by, account_id),
        )
        if status != "approved":
            await self._db.conn.execute("DELETE FROM app_sessions WHERE account_id=?", (account_id,))
        await self._db.conn.commit()

    async def set_account_admin(self, account_id: int, is_admin: bool) -> None:
        await self._db.conn.execute("UPDATE app_accounts SET is_admin=? WHERE id=?", (int(is_admin), account_id))
        await self._db.conn.commit()

    async def account_by_user_id(self, user_id: int) -> Account | None:
        cursor = await self._db.conn.execute("SELECT * FROM app_accounts WHERE user_id=?", (user_id,))
        row = await cursor.fetchone()
        return _account(row) if row else None

    async def set_account_sharing(self, account_id: int, enabled: bool) -> None:
        await self._db.conn.execute(
            "UPDATE app_accounts SET share_listening=? WHERE id=?", (int(enabled), account_id)
        )
        await self._db.conn.commit()

    async def set_account_scrobbling(self, account_id: int, enabled: bool) -> None:
        await self._db.conn.execute(
            "UPDATE app_accounts SET scrobble_to_lastfm=? WHERE id=?", (int(enabled), account_id)
        )
        await self._db.conn.commit()

    async def create_session(self, account_id: int) -> str:
        token = secrets.token_urlsafe(32)
        now = _now()
        await self._db.conn.execute(
            "INSERT INTO app_sessions (token_hash, account_id, created_at, last_used_at) VALUES (?, ?, ?, ?)",
            (_hash_token(token), account_id, now, now),
        )
        await self._db.conn.commit()
        return token

    async def account_for_session(self, token: str) -> Account | None:
        cursor = await self._db.conn.execute(
            """SELECT a.* FROM app_sessions s JOIN app_accounts a ON a.id = s.account_id
               WHERE s.token_hash=?""",
            (_hash_token(token),),
        )
        row = await cursor.fetchone()
        return _account(row) if row else None

    async def delete_session(self, token: str) -> None:
        await self._db.conn.execute("DELETE FROM app_sessions WHERE token_hash=?", (_hash_token(token),))
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

    async def stream_cache_delete(self, source: str, source_id: str) -> list[str]:
        """Oublie les fichiers en cache d'un morceau (tous formats) ; renvoie
        leurs chemins, à supprimer du disque."""
        cursor = await self._db.conn.execute(
            "SELECT file_path FROM stream_cache WHERE source=? AND source_id=?", (source, source_id)
        )
        paths = [r["file_path"] for r in await cursor.fetchall()]
        await self._db.conn.execute("DELETE FROM stream_cache WHERE source=? AND source_id=?", (source, source_id))
        await self._db.conn.commit()
        return paths

    async def stream_source_set(self, source: str, source_id: str, video_id: str) -> None:
        await self._db.conn.execute(
            """INSERT INTO stream_sources (source, source_id, video_id, updated_at) VALUES (?, ?, ?, ?)
               ON CONFLICT(source, source_id) DO UPDATE SET video_id=excluded.video_id, updated_at=excluded.updated_at""",
            (source, source_id, video_id, _now()),
        )
        await self._db.conn.commit()

    async def stream_source_get(self, source: str, source_id: str) -> str | None:
        cursor = await self._db.conn.execute(
            "SELECT video_id FROM stream_sources WHERE source=? AND source_id=?", (source, source_id)
        )
        row = await cursor.fetchone()
        return row["video_id"] if row else None

    async def reject_source(self, source: str, source_id: str, video_id: str) -> None:
        await self._db.conn.execute(
            """INSERT OR IGNORE INTO rejected_sources (source, source_id, video_id, rejected_at)
               VALUES (?, ?, ?, ?)""",
            (source, source_id, video_id, _now()),
        )
        await self._db.conn.execute(
            "DELETE FROM stream_sources WHERE source=? AND source_id=? AND video_id=?", (source, source_id, video_id)
        )
        await self._db.conn.commit()

    async def rejected_sources(self, source: str, source_id: str) -> set[str]:
        cursor = await self._db.conn.execute(
            "SELECT video_id FROM rejected_sources WHERE source=? AND source_id=?", (source, source_id)
        )
        return {r["video_id"] for r in await cursor.fetchall()}

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

    # -- Playlists ---------------------------------------------------

    async def playlist_create(
        self,
        user_id: int,
        name: str,
        description: str | None = None,
        *,
        origin: str | None = None,
        origin_url: str | None = None,
        import_status: str = "done",
    ) -> int:
        now = _now()
        cursor = await self._db.conn.execute(
            """INSERT INTO playlists
               (user_id, name, description, origin, origin_url, import_status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, name, description, origin, origin_url, import_status, now, now),
        )
        await self._db.conn.commit()
        return cursor.lastrowid

    async def _playlist_extras(self, playlist: Playlist) -> Playlist:
        cursor = await self._db.conn.execute(
            """SELECT COUNT(*) AS c, COALESCE(SUM(duration_seconds), 0) AS d
               FROM playlist_tracks WHERE playlist_id=?""",
            (playlist.id,),
        )
        row = await cursor.fetchone()
        playlist.track_count, playlist.duration_seconds = row["c"], row["d"]
        cursor = await self._db.conn.execute(
            """SELECT cover_url FROM playlist_tracks
               WHERE playlist_id=? AND cover_url IS NOT NULL
               ORDER BY position LIMIT 12""",
            (playlist.id,),
        )
        covers: list[str] = []
        for r in await cursor.fetchall():
            if r["cover_url"] not in covers:
                covers.append(r["cover_url"])
        playlist.covers = covers[:4]
        return playlist

    async def playlist_get(self, user_id: int, playlist_id: int) -> Playlist | None:
        cursor = await self._db.conn.execute(
            f"SELECT {_PLAYLIST_COLUMNS} FROM playlists WHERE id=? AND user_id=?",
            (playlist_id, user_id),
        )
        row = await cursor.fetchone()
        return await self._playlist_extras(Playlist(**dict(row))) if row else None

    async def playlist_list(self, user_id: int, include_collaborative: bool = False) -> list[Playlist]:
        """Playlists du compte ; avec `include_collaborative`, aussi celles que
        les autres ont ouvertes à tous (playlists à plusieurs)."""
        if include_collaborative:
            cursor = await self._db.conn.execute(
                f"""SELECT {_PLAYLIST_COLUMNS} FROM playlists
                    WHERE user_id=? OR visibility='collaborative' ORDER BY updated_at DESC""",
                (user_id,),
            )
        else:
            cursor = await self._db.conn.execute(
                f"SELECT {_PLAYLIST_COLUMNS} FROM playlists WHERE user_id=? ORDER BY updated_at DESC",
                (user_id,),
            )
        return [await self._playlist_extras(Playlist(**dict(r))) for r in await cursor.fetchall()]

    async def playlist_by_id(self, playlist_id: int) -> Playlist | None:
        """Playlist quel que soit son propriétaire (droits vérifiés par l'appelant)."""
        cursor = await self._db.conn.execute(
            f"SELECT {_PLAYLIST_COLUMNS} FROM playlists WHERE id=?", (playlist_id,)
        )
        row = await cursor.fetchone()
        return await self._playlist_extras(Playlist(**dict(row))) if row else None

    async def playlists_shared_by(self, user_id: int) -> list[Playlist]:
        cursor = await self._db.conn.execute(
            f"""SELECT {_PLAYLIST_COLUMNS} FROM playlists
                WHERE user_id=? AND visibility IN ('friends', 'collaborative') ORDER BY updated_at DESC""",
            (user_id,),
        )
        return [await self._playlist_extras(Playlist(**dict(r))) for r in await cursor.fetchall()]

    async def playlist_update(self, playlist_id: int, **fields) -> None:
        """Met à jour les colonnes données (nom, description, pochette, état
        d'import...) et la date de modification."""
        allowed = {
            "name", "description", "cover_url", "import_status", "import_total",
            "import_done", "import_missing", "import_error", "visibility",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"Colonnes inconnues : {sorted(unknown)}")
        fields["updated_at"] = _now()
        assignments = ", ".join(f"{k}=?" for k in fields)
        await self._db.conn.execute(
            f"UPDATE playlists SET {assignments} WHERE id=?", (*fields.values(), playlist_id)
        )
        await self._db.conn.commit()

    async def playlist_delete(self, user_id: int, playlist_id: int) -> None:
        await self._db.conn.execute(
            "DELETE FROM playlist_tracks WHERE playlist_id IN (SELECT id FROM playlists WHERE id=? AND user_id=?)",
            (playlist_id, user_id),
        )
        await self._db.conn.execute("DELETE FROM playlists WHERE id=? AND user_id=?", (playlist_id, user_id))
        await self._db.conn.commit()

    async def playlist_tracks(self, playlist_id: int) -> list[PlaylistEntry]:
        cursor = await self._db.conn.execute(
            f"SELECT id, {_PLAYLIST_TRACK_COLUMNS} FROM playlist_tracks WHERE playlist_id=? ORDER BY position, id",
            (playlist_id,),
        )
        entries = []
        for r in await cursor.fetchall():
            d = dict(r)
            entry_id = d.pop("id")
            entries.append(PlaylistEntry(entry_id=entry_id, track=TrackInfo(**d)))
        return entries

    async def playlist_add_tracks(self, playlist_id: int, tracks: list[TrackInfo]) -> None:
        """Ajoute des morceaux à la fin de la playlist, dans l'ordre donné."""
        if not tracks:
            return
        cursor = await self._db.conn.execute(
            "SELECT COALESCE(MAX(position), -1) AS p FROM playlist_tracks WHERE playlist_id=?",
            (playlist_id,),
        )
        position = (await cursor.fetchone())["p"] + 1
        now = _now()
        await self._db.conn.executemany(
            f"""INSERT INTO playlist_tracks (playlist_id, position, {_PLAYLIST_TRACK_COLUMNS}, added_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    playlist_id, position + i, t.source, t.source_id, t.title, t.artist, t.album,
                    t.year, t.duration_seconds, t.cover_url, t.artist_source_id, t.album_source_id, now,
                )
                for i, t in enumerate(tracks)
            ],
        )
        await self._db.conn.execute("UPDATE playlists SET updated_at=? WHERE id=?", (now, playlist_id))
        await self._db.conn.commit()

    async def playlist_clear_tracks(self, playlist_id: int) -> None:
        await self._db.conn.execute("DELETE FROM playlist_tracks WHERE playlist_id=?", (playlist_id,))
        await self._db.conn.commit()

    async def playlist_remove_entry(self, playlist_id: int, entry_id: int) -> None:
        await self._db.conn.execute(
            "DELETE FROM playlist_tracks WHERE playlist_id=? AND id=?", (playlist_id, entry_id)
        )
        await self._db.conn.execute("UPDATE playlists SET updated_at=? WHERE id=?", (_now(), playlist_id))
        await self._db.conn.commit()

    async def playlist_reorder(self, playlist_id: int, entry_ids: list[int]) -> None:
        """Nouvel ordre : `entry_ids` d'abord, dans cet ordre ; les entrées
        absentes de la liste (ajoutées entre-temps) gardent leur ordre, à la
        suite."""
        current = [e.entry_id for e in await self.playlist_tracks(playlist_id)]
        known = set(current)
        ordered = [e for e in dict.fromkeys(entry_ids) if e in known]
        ordered += [e for e in current if e not in set(ordered)]
        await self._db.conn.executemany(
            "UPDATE playlist_tracks SET position=? WHERE id=? AND playlist_id=?",
            [(i, e, playlist_id) for i, e in enumerate(ordered)],
        )
        await self._db.conn.execute("UPDATE playlists SET updated_at=? WHERE id=?", (_now(), playlist_id))
        await self._db.conn.commit()

    async def playlists_fail_interrupted_imports(self) -> None:
        """Au démarrage : un import resté « en cours » a été coupé par un
        redémarrage du serveur, il ne reprendra pas."""
        await self._db.conn.execute(
            """UPDATE playlists SET import_status='failed',
               import_error='Import interrompu (redémarrage du serveur) : relance-le.'
               WHERE import_status='importing'"""
        )
        await self._db.conn.commit()

    # -- Blind test ----------------------------------------------------

    async def blindtest_add_score(
        self, user_id: int, mode: str, day: str, score: int, correct: int, total: int
    ) -> None:
        await self._db.conn.execute(
            """INSERT INTO blindtest_scores (user_id, mode, day, score, correct, total, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_id, mode, day, score, correct, total, _now()),
        )
        await self._db.conn.commit()

    async def blindtest_daily_played(self, user_id: int, day: str) -> bool:
        cursor = await self._db.conn.execute(
            "SELECT 1 FROM blindtest_scores WHERE user_id=? AND mode='daily' AND day=? LIMIT 1", (user_id, day)
        )
        return (await cursor.fetchone()) is not None

    async def blindtest_leaderboard(self, mode: str, day: str | None, limit: int = 30) -> list[dict]:
        """Meilleur score de chacun (du jour pour le défi, de tous les temps sinon)."""
        clauses, params = ["mode=?"], [mode]
        if day:
            clauses.append("day=?")
            params.append(day)
        cursor = await self._db.conn.execute(
            f"""SELECT user_id, MAX(score) AS score, MAX(correct) AS correct, MAX(total) AS total
                FROM blindtest_scores WHERE {' AND '.join(clauses)}
                GROUP BY user_id ORDER BY score DESC LIMIT ?""",
            (*params, limit),
        )
        return [dict(r) for r in await cursor.fetchall()]

    # -- Analyse audio (AutoMix) ----------------------------------------

    async def analysis_get(self, source: str, source_id: str) -> dict | None:
        cursor = await self._db.conn.execute(
            """SELECT loudness, start, mix_out, end_time, duration FROM track_analysis
               WHERE source=? AND source_id=?""",
            (source, source_id),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def analysis_set(
        self, source: str, source_id: str, loudness: float, start: float, mix_out: float, end: float, duration: float
    ) -> None:
        await self._db.conn.execute(
            """INSERT INTO track_analysis (source, source_id, loudness, start, mix_out, end_time, duration, analyzed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(source, source_id) DO UPDATE SET loudness=excluded.loudness, start=excluded.start,
               mix_out=excluded.mix_out, end_time=excluded.end_time, duration=excluded.duration,
               analyzed_at=excluded.analyzed_at""",
            (source, source_id, loudness, start, mix_out, end, duration, _now()),
        )
        await self._db.conn.commit()

    async def analysis_delete(self, source: str, source_id: str) -> None:
        await self._db.conn.execute("DELETE FROM track_analysis WHERE source=? AND source_id=?", (source, source_id))
        await self._db.conn.commit()
