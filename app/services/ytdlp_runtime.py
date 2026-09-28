"""Moteur JavaScript pour yt-dlp.

Depuis fin 2025, yt-dlp doit exécuter le JavaScript du lecteur YouTube
(déchiffrement des signatures et du paramètre `n`) pour obtenir les flux
audio. Sans moteur utilisable, YouTube ne livre plus aucun format audio et
*tous* les téléchargements échouent. Par défaut yt-dlp ne cherche que Deno
dans le PATH : on lui donne explicitement celui installé par pip
(`yt-dlp[deno]`, dans le venv — absent du PATH quand pm2 lance
`.venv/bin/python`), plus Node/Bun/QuickJS s'ils existent sur la machine,
en secours.
"""

from __future__ import annotations

import logging
import shutil
from functools import lru_cache

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def js_runtimes() -> dict[str, dict]:
    runtimes: dict[str, dict] = {}
    deno_path = None
    try:
        from deno import find_deno_bin

        deno_path = find_deno_bin()
    except Exception:  # paquet absent, ou binaire introuvable pour cette plateforme
        deno_path = shutil.which("deno")
    if deno_path:
        runtimes["deno"] = {"path": deno_path}
    for name, executable in (("node", "node"), ("bun", "bun"), ("quickjs", "qjs")):
        path = shutil.which(executable)
        if path:
            runtimes[name] = {"path": path}
    if runtimes:
        logger.info("Moteurs JavaScript pour yt-dlp : %s", ", ".join(runtimes))
    else:
        logger.error(
            "Aucun moteur JavaScript pour yt-dlp (deno, node, bun, qjs) : les téléchargements "
            "YouTube vont échouer. `pip install -r requirements.txt` installe deno."
        )
    return runtimes or {"deno": {}}


def with_js_runtimes(opts: dict) -> dict:
    opts["js_runtimes"] = {name: dict(config) for name, config in js_runtimes().items()}
    return opts
