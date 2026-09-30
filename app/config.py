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
    # Import de l'historique Last.fm dans les stats d'écoute (optionnel) :
    # clé API gratuite (https://www.last.fm/api/account/create) + pseudo.
    # Taille maximale des fichiers audio gardés pour l'app (data/stream_cache) :
    # au-delà, les titres écoutés il y a le plus longtemps sont supprimés.
    stream_cache_max_mb: int = 2048
    lastfm_api_key: str | None = None
    lastfm_user: str | None = None
    # Secret partagé de l'application Last.fm : nécessaire à la connexion
    # « Se connecter avec Last.fm » de l'app et au scrobbling.
    lastfm_api_secret: str | None = None
    # Pseudos Last.fm administrateurs de l'app (acceptés d'office, accès au
    # panel d'admin). Par défaut : LASTFM_USER.
    admin_lastfm_users: frozenset[str] = frozenset()
    # Identifiant d'application Bandsintown (concerts des artistes écoutés).
    bandsintown_app_id: str = "sona-app"
    # Karaoké (app/services/karaoke.py) : pistes voix / instru séparées par
    # IA, gardées dans `karaoke_dir` (les plus anciennes supprimées au-delà
    # de la taille max), et modèle de séparation téléchargé dans
    # `models_dir` à la première utilisation — jamais dans le dépôt.
    karaoke_dir: Path = field(default_factory=lambda: BASE_DIR / "data" / "karaoke")
    models_dir: Path = field(default_factory=lambda: BASE_DIR / "data" / "models")
    karaoke_cache_max_mb: int = 1500
    # Cœurs donnés au calcul (en priorité basse : l'API passe toujours avant).
    karaoke_threads: int = 2

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

    def data_dir(name: str, default: str) -> Path:
        raw = Path(os.getenv(name, "").strip() or default)
        return raw if raw.is_absolute() else BASE_DIR / raw

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
        stream_cache_max_mb=int(os.getenv("STREAM_CACHE_MAX_MB", "").strip() or 2048),
        lastfm_api_key=os.getenv("LASTFM_API_KEY", "").strip() or None,
        lastfm_user=os.getenv("LASTFM_USER", "").strip() or None,
        bandsintown_app_id=os.getenv("BANDSINTOWN_APP_ID", "").strip() or "sona-app",
        lastfm_api_secret=os.getenv("LASTFM_API_SECRET", "").strip() or None,
        karaoke_dir=data_dir("KARAOKE_DIR", "data/karaoke"),
        models_dir=data_dir("MODELS_DIR", "data/models"),
        karaoke_cache_max_mb=int(os.getenv("KARAOKE_CACHE_MAX_MB", "").strip() or 1500),
        karaoke_threads=int(os.getenv("KARAOKE_THREADS", "").strip() or min(2, os.cpu_count() or 1)),
        admin_lastfm_users=frozenset(
            name.strip().casefold()
            for name in (os.getenv("ADMIN_LASTFM_USERS") or os.getenv("LASTFM_USER") or "").split(",")
            if name.strip()
        ),
    )
