from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable

from yt_dlp.utils import remove_terminal_sequences


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Bruit connu, peu utile en usage normal.
    logging.getLogger("httpx").setLevel(logging.WARNING)


# Avertissements yt-dlp qui expliquent un mur « Sign in to confirm you're not
# a bot » ou des formats introuvables : session/cookies, et moteur JavaScript.
# Ceux-là doivent se voir ; le reste (formats écartés, PO token…) part en DEBUG.
_IMPORTANT_WARNING_RE = re.compile(
    r"cookie|sign in|logged|login|account|javascript runtime", re.IGNORECASE
)
# yt-dlp ignore `only_once` dès qu'un logger est branché : sans ce filtre, un
# même avertissement de cookies revient après chaque requête d'une extraction.
_REPEAT_WINDOW_SECONDS = 60.0
_MAX_REMEMBERED = 256


class YtDlpLogger:
    """Branche les messages de yt-dlp sur `logging` au lieu de les jeter.

    `no_warnings` taisait tout, y compris « The provided YouTube account
    cookies are no longer valid » : le 2026-09-15, une session Google morte
    n'a laissé aucune trace dans les logs. Passé via l'option `logger`,
    yt-dlp confie ses messages à cet objet, que `no_warnings` soit mis ou non.
    """

    def __init__(self, logger: logging.Logger, clock: Callable[[], float] = time.monotonic) -> None:
        self._logger = logger
        self._clock = clock
        self._lock = threading.Lock()
        self._recent: dict[str, float] = {}

    def debug(self, msg: str) -> None:
        # yt-dlp y envoie tout ce qu'il afficherait à l'écran (progression…).
        self._logger.debug("%s", _clean(msg))

    def info(self, msg: str) -> None:
        self._logger.debug("%s", _clean(msg))

    def warning(self, msg: str) -> None:
        text = _clean(msg)
        if not _IMPORTANT_WARNING_RE.search(text):
            self._logger.debug("%s", text)
        elif self._first_in_window(text):
            self._logger.warning("%s", text)

    def error(self, msg: str) -> None:
        # Sans logger, yt-dlp écrivait ses erreurs sur stderr même en `quiet` :
        # elles restent visibles.
        self._logger.error("%s", _clean(msg))

    def _first_in_window(self, text: str) -> bool:
        now = self._clock()
        with self._lock:
            last = self._recent.get(text)
            if last is not None and now - last < _REPEAT_WINDOW_SECONDS:
                return False
            if len(self._recent) >= _MAX_REMEMBERED:
                self._recent.clear()
            self._recent[text] = now
            return True


def _clean(msg: object) -> str:
    return remove_terminal_sequences(str(msg)).strip()


# Instance partagée par tous les appels yt-dlp (téléchargement, recherche,
# vérification de session) : les messages sortent sous le logger "yt_dlp".
ytdlp_logger = YtDlpLogger(logging.getLogger("yt_dlp"))
