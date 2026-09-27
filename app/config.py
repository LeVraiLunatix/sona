from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def _parse_ids(raw: str | None) -> frozenset[int]:
    if not raw:
        return frozenset()
    ids = set()
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if chunk:
            ids.add(int(chunk))
    return frozenset(ids)


@dataclass(frozen=True)
class Settings:
    bot_token: str | None
    allowed_user_ids: frozenset[int]
    spotify_client_id: str | None
    spotify_client_secret: str | None
    ffmpeg_path: str
    database_path: Path
    youtube_cookies_file: Path | None
    backup_dir: Path
    downloads_dir: Path = field(default_factory=lambda: BASE_DIR / "data" / "cache")
    # API privée pour l'app iOS : jeton fixe à présenter dans l'en-tête
    # `Authorization: Bearer <token>`. None désactive l'API (pas de compte,
    # pas de whitelist Telegram côté API : usage strictement personnel).
    api_token: str | None = None
    # Identifiant utilisateur interne utilisé pour la bibliothèque, l'historique
    # et les réglages côté API (indépendant des `user_id` Telegram).
    api_user_id: int = 1
    stream_cache_dir: Path = field(default_factory=lambda: BASE_DIR / "data" / "stream_cache")

    @property
    def is_private_mode(self) -> bool:
        return len(self.allowed_user_ids) > 0


def resolve_youtube_cookies_file() -> Path | None:
    """Fichier de cookies YouTube : `YOUTUBE_COOKIES_FILE`, sinon
    `data/cookies.txt`. None s'il n'existe pas."""
    cookies_raw = os.getenv("YOUTUBE_COOKIES_FILE", "").strip()
    cookies_file = Path(cookies_raw) if cookies_raw else (BASE_DIR / "data" / "cookies.txt")
    if not cookies_file.is_absolute():
        cookies_file = BASE_DIR / cookies_file
    return cookies_file if cookies_file.is_file() else None


def load_settings() -> Settings:
    # Optionnel ici : seul le bot Telegram (run.py) en a besoin, pas l'API
    # (run_api.py), qui peut donc tourner sans jamais créer de bot Telegram.
    token = os.getenv("BOT_TOKEN", "").strip() or None

    db_path_raw = os.getenv("DATABASE_PATH", "data/sona.db").strip()
    db_path = Path(db_path_raw)
    if not db_path.is_absolute():
        db_path = BASE_DIR / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg = os.getenv("FFMPEG_PATH", "").strip() or shutil.which("ffmpeg") or "ffmpeg"

    downloads_dir = BASE_DIR / "data" / "cache"
    downloads_dir.mkdir(parents=True, exist_ok=True)

    cookies_file = resolve_youtube_cookies_file()

    backup_dir_raw = os.getenv("BACKUP_DIR", "data/backups").strip() or "data/backups"
    backup_dir = Path(backup_dir_raw)
    if not backup_dir.is_absolute():
        backup_dir = BASE_DIR / backup_dir

    stream_cache_dir = BASE_DIR / "data" / "stream_cache"
    stream_cache_dir.mkdir(parents=True, exist_ok=True)

    api_user_id_raw = os.getenv("API_USER_ID", "").strip()

    return Settings(
        bot_token=token,
        allowed_user_ids=_parse_ids(os.getenv("ALLOWED_USER_IDS")),
        spotify_client_id=os.getenv("SPOTIFY_CLIENT_ID", "").strip() or None,
        spotify_client_secret=os.getenv("SPOTIFY_CLIENT_SECRET", "").strip() or None,
        ffmpeg_path=ffmpeg,
        database_path=db_path,
        youtube_cookies_file=cookies_file,
        backup_dir=backup_dir,
        downloads_dir=downloads_dir,
        api_token=os.getenv("API_TOKEN", "").strip() or None,
        api_user_id=int(api_user_id_raw) if api_user_id_raw else 1,
        stream_cache_dir=stream_cache_dir,
    )
