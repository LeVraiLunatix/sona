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
from typing import Awaitable, Callable

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

# Rappel tant que l'état ne change pas : assez espacé pour ne pas harceler,
# assez fréquent pour qu'une session morte ne passe pas un week-end entier.
_REMINDER_SECONDS = 12 * 60 * 60

_last_check_at: float | None = None
_background_tasks: set[asyncio.Task] = set()

Notifier = Callable[[str], Awaitable[None]]

_notifier: Notifier | None = None
# Dernier état connu (None : jamais vérifié) et date de la dernière alerte,
# en mémoire : après un redémarrage, une session morte est signalée à nouveau.
_last_known_logged_in: bool | None = None
_last_alert_at: float | None = None

# Ce que l'admin doit faire, sans jamais recopier la moindre valeur de cookie.
_HOW_TO_REEXPORT = (
    "À refaire depuis le PC :\n"
    "1. Ouvre une fenêtre de navigation privée et connecte-toi sur youtube.com "
    "avec le compte du bot.\n"
    "2. Dans cette fenêtre, avec l'extension « Get cookies.txt LOCALLY », "
    "exporte les cookies de ce site uniquement — pas « Export All Cookies ».\n"
    "3. Ferme la fenêtre privée tout de suite, et ne la rouvre jamais : si un "
    "navigateur continue à se servir de cette session, Google fait tourner ses "
    "cookies et l'export est mort à son tour.\n"
    "4. Depuis le PC, installe le fichier sur le serveur (data/cookies.txt), "
    "puis redémarre Sona.\n\n"
    "Marche à suivre détaillée : README, section « Cookies YouTube »."
)
SESSION_BACK_MESSAGE = "✅ Session YouTube de nouveau connectée : les téléchargements repartent."


def session_lost_message(reminder: bool = False) -> str:
    titre = "⚠️ Cookies YouTube toujours expirés" if reminder else "⚠️ Cookies YouTube expirés"
    return (
        f"{titre}\n\n"
        "La session Google de Sona est déconnectée : les téléchargements vont "
        "buter sur « Sign in to confirm you're not a bot » et les morceaux "
        "paraîtront indisponibles.\n\n" + _HOW_TO_REEXPORT
    )


def register_notifier(notifier: Notifier | None) -> None:
    """Branche l'envoi des alertes aux administrateurs.

    Ce module ne connaît ni le bot ni la base : `run.py` lui passe une fonction
    au démarrage. Sans ça, il faudrait importer la couche Telegram depuis un
    service que la couche Telegram importe déjà — dépendance circulaire.
    """
    global _notifier
    _notifier = notifier


def session_alert(logged_in: bool | None, now: float) -> str | None:
    """Message à envoyer aux admins après une vérification, ou None.

    Met à jour l'état retenu au passage. On prévient au passage de connecté à
    déconnecté (y compris à la toute première vérification, un bot qui démarre
    avec des cookies morts est justement le cas à signaler) et au retour à la
    normale. Tant que l'état ne bouge pas, un rappel toutes les 12 h au plus.
    """
    global _last_known_logged_in, _last_alert_at
    if logged_in is None:
        # Vérification impossible ou page inattendue : ça ne prouve pas que la
        # session est morte, on ne réveille personne pour ça.
        return None

    previous, _last_known_logged_in = _last_known_logged_in, logged_in

    if logged_in:
        _last_alert_at = None
        # Rien à annoncer si la session n'avait jamais été vue déconnectée :
        # au démarrage, une session valide est la normale.
        return SESSION_BACK_MESSAGE if previous is False else None

    if previous is not False:
        _last_alert_at = now
        return session_lost_message()
    if _last_alert_at is None or now - _last_alert_at >= _REMINDER_SECONDS:
        _last_alert_at = now
        return session_lost_message(reminder=True)
    return None


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


async def check_session(cookies_file: Path, reason: str) -> bool | None:
    """Vérifie la session, journalise le verdict, et prévient les admins quand
    l'état change (ou toutes les 12 h tant qu'il ne revient pas à la normale).

    Un envoi qui échoue est journalisé mais ne remonte pas : une alerte perdue
    ne doit pas faire tomber la tâche de fond qui l'émet.
    """
    logged_in = await asyncio.to_thread(report_session, cookies_file, reason)
    message = session_alert(logged_in, time.monotonic())
    if message is None or _notifier is None:
        if message is not None:
            logger.warning("Aucun destinataire pour l'alerte de session YouTube")
        return logged_in
    try:
        await _notifier(message)
    except Exception as exc:
        logger.warning("Alerte de session YouTube non envoyée : %s", exc)
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
    task = asyncio.get_running_loop().create_task(check_session(cookies_file, reason))
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
