"""Vérifie que les cookies YouTube ouvrent encore une session connectée.

Le 2026-09-15, tous les téléchargements échouaient en « Sign in to confirm
you're not a bot » alors que `data/cookies.txt` était bien là : la session
Google exportée était morte, et YouTube servait sa page d'accueil avec
`"LOGGED_IN": false` malgré les cookies. Rien ne le signalait. Ce module pose
la question directement à YouTube — au démarrage, et quand une cascade de
téléchargement bute entièrement sur le mur anti-bot.

Vérification manuelle (utile sur le VPS juste après avoir déposé un nouvel
export) : `python -m app.services.youtube_session`.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

import yt_dlp

from app.config import resolve_youtube_cookies_file
from app.logging_config import setup_logging, ytdlp_logger

logger = logging.getLogger(__name__)

_HOME_URL = "https://www.youtube.com/"
_LOGGED_IN_RE = re.compile(r'"LOGGED_IN"\s*:\s*(true|false)')
# Le marqueur arrive dans les ~60 premiers Ko d'une page d'environ 1 Mo.
_MAX_PAGE_BYTES = 4 * 1024 * 1024
_SOCKET_TIMEOUT_SECONDS = 10
# Une vérification au démarrage, puis au plus une par quart d'heure quand les
# téléchargements échouent en rafale : inutile de marteler youtube.com.
_COOLDOWN_SECONDS = 15 * 60

_last_check_at: float | None = None
_background_tasks: set[asyncio.Task] = set()


def parse_logged_in(html: str) -> bool | None:
    """Lit le booléen "LOGGED_IN" de la configuration embarquée (ytcfg).

    None quand il est absent : page de consentement, HTML inattendu…"""
    match = _LOGGED_IN_RE.search(html)
    if match is None:
        return None
    return match.group(1) == "true"


def probe_logged_in(cookies_file: Path) -> bool | None:
    """Charge les cookies dans yt-dlp, récupère youtube.com et lit "LOGGED_IN".

    Travaille sur une copie temporaire : yt-dlp réécrit son `cookiefile` en se
    fermant, et une simple vérification ne doit pas toucher au fichier que
    les téléchargements utilisent. Les erreurs (réseau, fichier illisible)
    remontent à l'appelant.
    """
    # mkstemp crée le fichier en 0600 : la copie n'est lisible que par Sona.
    fd, tmp_name = tempfile.mkstemp(prefix="sona-cookies-", suffix=".txt")
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        shutil.copyfile(cookies_file, tmp_path)
        opts = {
            "cookiefile": str(tmp_path),
            "quiet": True,
            "socket_timeout": _SOCKET_TIMEOUT_SECONDS,
            "logger": ytdlp_logger,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            with ydl.urlopen(_HOME_URL) as response:
                html = response.read(_MAX_PAGE_BYTES).decode("utf-8", errors="replace")
    finally:
        tmp_path.unlink(missing_ok=True)
    return parse_logged_in(html)


def report_session(cookies_file: Path, reason: str) -> bool | None:
    """Vérifie la session et journalise le verdict.

    Ne lève jamais : un souci de vérification ne doit pas empêcher Sona de
    tourner. Aucun log ne contient la valeur d'un cookie, seulement le chemin
    du fichier."""
    try:
        logged_in = probe_logged_in(cookies_file)
    except Exception as exc:
        logger.warning("Vérification de la session YouTube impossible (%s) : %s", reason, exc)
        return None

    if logged_in is True:
        logger.info("Session YouTube active (%s) : les cookies de %s sont connectés", reason, cookies_file)
    elif logged_in is False:
        logger.warning(
            "Cookies YouTube déconnectés (%s) : youtube.com répond \"LOGGED_IN\": false avec %s. "
            "La session Google est morte, les téléchargements vont buter sur « Sign in to "
            "confirm you're not a bot ». Ré-exporte les cookies (README, section « Cookies YouTube »).",
            reason,
            cookies_file,
        )
    else:
        logger.warning(
            "Session YouTube indéterminée (%s) : \"LOGGED_IN\" absent de la page d'accueil "
            "(page de consentement ?)",
            reason,
        )
    return logged_in


def schedule_session_check(cookies_file: Path, reason: str) -> asyncio.Task | None:
    """Lance la vérification en tâche de fond, sans bloquer l'appelant.

    Retourne None si une vérification a déjà été lancée il y a moins d'un
    quart d'heure. À appeler depuis la boucle asyncio."""
    global _last_check_at
    now = time.monotonic()
    if _last_check_at is not None and now - _last_check_at < _COOLDOWN_SECONDS:
        return None
    _last_check_at = now
    task = asyncio.get_running_loop().create_task(asyncio.to_thread(report_session, cookies_file, reason))
    # La boucle ne garde qu'une référence faible vers ses tâches.
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


def main() -> int:
    setup_logging()
    cookies_file = resolve_youtube_cookies_file()
    if cookies_file is None:
        logger.error("Aucun fichier de cookies YouTube (data/cookies.txt, ou YOUTUBE_COOKIES_FILE dans .env)")
        return 2
    return 0 if report_session(cookies_file, "vérification manuelle") else 1


if __name__ == "__main__":
    raise SystemExit(main())
