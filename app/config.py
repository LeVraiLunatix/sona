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
    bot_token: str
    allowed_user_ids: frozenset[int]
    spotify_client_id: str | None
    spotify_client_secret: str | None
    ffmpeg_path: str
    database_path: Path
    downloads_dir: Path = field(default_factory=lambda: BASE_DIR / "data" / "cache")

    @property
    def is_private_mode(self) -> bool:
        return len(self.allowed_user_ids) > 0


def load_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "BOT_TOKEN manquant. Copie .env.example vers .env et renseigne le "
            "token fourni par @BotFather."
        )

    db_path_raw = os.getenv("DATABASE_PATH", "data/sona.db").strip()
    db_path = Path(db_path_raw)
    if not db_path.is_absolute():
        db_path = BASE_DIR / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg = os.getenv("FFMPEG_PATH", "").strip() or shutil.which("ffmpeg") or "ffmpeg"

    downloads_dir = BASE_DIR / "data" / "cache"
    downloads_dir.mkdir(parents=True, exist_ok=True)

    return Settings(
        bot_token=token,
        allowed_user_ids=_parse_ids(os.getenv("ALLOWED_USER_IDS")),
        spotify_client_id=os.getenv("SPOTIFY_CLIENT_ID", "").strip() or None,
        spotify_client_secret=os.getenv("SPOTIFY_CLIENT_SECRET", "").strip() or None,
        ffmpeg_path=ffmpeg,
        database_path=db_path,
        downloads_dir=downloads_dir,
    )
