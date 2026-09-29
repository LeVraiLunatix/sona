"""Mise à jour automatique de yt-dlp, avec essai de lecture et retour arrière.

YouTube change régulièrement son lecteur ; yt-dlp suit en quelques heures ou
jours. Sans mise à jour, plus rien ne se lance. Chaque nuit (cron installé
par deploy/deploy.sh) :

1. on note la version installée et on vérifie qu'elle lit une vidéo test ;
2. on installe la dernière version de yt-dlp ;
3. si elle a changé, on refait l'essai : réussi → Sona redémarre dessus ;
   raté alors que l'ancienne marchait → retour à l'ancienne version.

Le résultat est gardé dans data/ytdlp_update.json (affiché dans l'app).

À la main : `.venv/bin/python -m app.services.ytdlp_updater`
Essai seul : `.venv/bin/python -m app.services.ytdlp_updater --selftest`
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[2]
STATE_FILE = BASE_DIR / "data" / "ytdlp_update.json"
# « Me at the zoo » : la toute première vidéo de YouTube, jamais retirée.
TEST_URL = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
PACKAGE = "yt-dlp[default,deno]"
SERVICES = ("sona-api", "sona")


def read_state() -> dict | None:
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return None


def _write_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def installed_version(python: str = sys.executable) -> str | None:
    """Version installée, lue dans un nouveau processus (celui-ci garde en
    mémoire l'ancienne version après une mise à jour)."""
    try:
        out = subprocess.run(
            [python, "-c", "import yt_dlp.version as v; print(v.__version__)"],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def selftest_in_process() -> tuple[bool, str]:
    """Essai : yt-dlp trouve-t-il un flux audio pour la vidéo test ?"""
    import yt_dlp

    from app.config import resolve_youtube_cookies_file
    from app.services.ytdlp_runtime import with_js_runtimes

    opts: dict = {"quiet": True, "no_warnings": True, "skip_download": True, "socket_timeout": 20}
    cookies = resolve_youtube_cookies_file()
    tmp: Path | None = None
    if cookies is not None:
        # yt-dlp réécrit son fichier de cookies : on lui en donne une copie.
        fd, name = tempfile.mkstemp(prefix="sona-selftest-", suffix=".txt")
        os.close(fd)
        tmp = Path(name)
        shutil.copyfile(cookies, tmp)
        opts["cookiefile"] = str(tmp)
    try:
        with yt_dlp.YoutubeDL(with_js_runtimes(opts)) as ydl:
            info = ydl.extract_info(TEST_URL, download=False)
    except Exception as exc:
        return False, str(exc).replace("ERROR: ", "").strip().splitlines()[0][:300]
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
    audio = [f for f in (info or {}).get("formats") or [] if f.get("acodec") not in (None, "none") and f.get("url")]
    if not audio:
        return False, "aucun format audio renvoyé"
    return True, f"{len(audio)} formats audio"


def selftest(python: str = sys.executable) -> tuple[bool, str]:
    """Essai dans un nouveau processus (avec la version installée sur disque)."""
    try:
        out = subprocess.run(
            [python, "-m", "app.services.ytdlp_updater", "--selftest", "--json"],
            capture_output=True, text=True, timeout=180, cwd=BASE_DIR,
        )
        result = json.loads(out.stdout.strip().splitlines()[-1])
        return bool(result["ok"]), str(result["message"])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError, KeyError) as exc:
        return False, f"essai impossible : {exc}"


def _pip(python: str, *args: str) -> bool:
    try:
        out = subprocess.run([python, "-m", "pip", "install", "--quiet", *args], capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.error("pip impossible : %s", exc)
        return False
    if out.returncode != 0:
        logger.error("pip a échoué : %s", out.stderr.strip()[-500:])
    return out.returncode == 0


def _restart_services() -> None:
    pm2 = shutil.which("pm2")
    if pm2 is None:
        logger.warning("pm2 introuvable : redémarre Sona à la main pour utiliser la nouvelle version.")
        return
    for name in SERVICES:
        subprocess.run([pm2, "restart", name, "--update-env"], capture_output=True, timeout=60)


def update(python: str = sys.executable, restart: bool = True, runner=None) -> dict:
    """Met yt-dlp à jour si besoin. `runner` : pour les tests (remplace
    pip / l'essai / le redémarrage)."""
    run = runner or {
        "version": lambda: installed_version(python),
        "selftest": lambda: selftest(python),
        "install": lambda spec: _pip(python, "--upgrade", spec),
        "restart": _restart_services,
    }
    before = run["version"]()
    worked_before, before_message = run["selftest"]()
    state = {"checked_at": time.time(), "previous": before, "version": before}
    if not run["install"](PACKAGE):
        state.update(result="error", message="Installation de la mise à jour impossible (voir les journaux).",
                     working=worked_before)
        _write_state(state)
        return state
    after = run["version"]()
    state["version"] = after
    if after == before:
        state.update(result="up_to_date", working=worked_before,
                     message="yt-dlp est à jour." if worked_before else f"yt-dlp est à jour, mais l'essai échoue : {before_message}")
        _write_state(state)
        return state
    works, message = run["selftest"]()
    if works or not worked_before:
        state.update(result="updated", working=works,
                     message=f"yt-dlp mis à jour ({before} → {after})." + ("" if works else f" L'essai échoue encore : {message}"))
        if restart:
            run["restart"]()
    else:
        # La nouvelle version casse ce qui marchait : retour à l'ancienne.
        run["install"](f"{PACKAGE}=={before}")
        state.update(result="rolled_back", version=before, working=True,
                     message=f"La version {after} ne lisait plus YouTube ({message}) : retour à {before}.")
    _write_state(state)
    return state


def ensure_cron() -> bool:
    """Installe la mise à jour nocturne (4 h 17) si elle manque — au
    démarrage de l'API, en plus de deploy/deploy.sh. True si ajoutée."""
    crontab = shutil.which("crontab")
    if crontab is None:
        return False
    try:
        current = subprocess.run([crontab, "-l"], capture_output=True, text=True, timeout=10).stdout
        if "app.services.ytdlp_updater" in current:
            return False
        path = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
        line = (f"17 4 * * * cd {BASE_DIR} && PATH={path} {sys.executable} -m app.services.ytdlp_updater "
                f">> data/ytdlp_update.log 2>&1")
        new = (current.rstrip("\n") + "\n" if current.strip() else "") + line + "\n"
        subprocess.run([crontab, "-"], input=new, text=True, capture_output=True, timeout=10, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("Mise à jour nocturne de yt-dlp non installée : %s", exc)
        return False
    logger.info("Mise à jour nocturne de yt-dlp installée (cron, 4 h 17)")
    return True


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if "--selftest" in argv:
        ok, message = selftest_in_process()
        if "--json" in argv:
            print(json.dumps({"ok": ok, "message": message}))
        else:
            print(("✅ " if ok else "❌ ") + message)
        return 0 if ok else 1
    state = update()
    print(state["message"])
    return 0 if state.get("working") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
