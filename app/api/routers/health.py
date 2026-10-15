"""Santé de la lecture, côté admin (Réglages → Santé de la lecture) :
l'état, la version de yt-dlp et sa dernière mise à jour, la session
YouTube, et de quoi réparer sans SSH — renvoyer des cookies, lancer la
mise à jour de yt-dlp, faire un essai de lecture."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.api.auth import require_admin
from app.api.routers import stream
from app.api.state import ApiDeps
from app.config import BASE_DIR
from app.services import stream_health, youtube_session, ytdlp_updater
from app.services.resolver import ResolutionError, source_from_url

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["santé"])

MAX_COOKIES_BYTES = 512 * 1024


def cookies_path(deps: ApiDeps) -> Path:
    if deps.settings.youtube_cookies_file is not None:
        return deps.settings.youtube_cookies_file
    configured = os.getenv("YOUTUBE_COOKIES_FILE", "").strip()
    path = Path(configured) if configured else BASE_DIR / "data" / "cookies.txt"
    return path if path.is_absolute() else BASE_DIR / path


def validate_cookies(content: str) -> int:
    """Nombre de cookies YouTube/Google d'un fichier « cookies.txt » (format
    Netscape, celui de l'extension « Get cookies.txt LOCALLY »). Lève
    ValueError si le fichier n'en est pas un."""
    count = 0
    for raw in content.splitlines():
        line = raw.strip()
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_"):]
        elif not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != 7:
            raise ValueError("Ce n'est pas un fichier cookies.txt (format Netscape).")
        if "youtube.com" in fields[0] or "google.com" in fields[0]:
            count += 1
    if count == 0:
        raise ValueError("Aucun cookie YouTube dans ce fichier : exporte-le depuis un onglet youtube.com.")
    return count


def _ytdlp_version() -> str | None:
    try:
        import yt_dlp.version

        return yt_dlp.version.__version__
    except Exception:
        return None


@router.get("/streaming")
async def streaming_status(deps: ApiDeps = Depends(require_admin)) -> dict:
    path = cookies_path(deps)
    return {
        "health": stream_health.status(),
        "ytdlp": {"version": _ytdlp_version(), "last_update": ytdlp_updater.read_state()},
        "cookies": {
            "present": path.is_file(),
            "updated_at": path.stat().st_mtime if path.is_file() else None,
            "logged_in": youtube_session._last_known_logged_in,
        },
    }


class CookiesIn(BaseModel):
    content: str = Field(min_length=10, max_length=MAX_COOKIES_BYTES)


@router.post("/youtube-cookies")
async def upload_cookies(payload: CookiesIn, request: Request, deps: ApiDeps = Depends(require_admin)) -> dict:
    """Nouveaux cookies YouTube, envoyés depuis l'app ou le site : écrits sur
    le serveur (lisibles par Sona seul), puis vérifiés auprès de YouTube."""
    try:
        count = validate_cookies(payload.content)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    path = cookies_path(deps)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".cookies-", suffix=".txt")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(payload.content if payload.content.endswith("\n") else payload.content + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except OSError as exc:
        Path(tmp).unlink(missing_ok=True)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Écriture impossible : {exc}") from exc
    # Sona démarré sans cookies : les prochaines lectures s'en servent.
    shared = request.app.state.deps
    if shared.settings.youtube_cookies_file != path:
        shared.settings = dataclasses.replace(shared.settings, youtube_cookies_file=path)
    stream.forget_failures()
    logger.info("Cookies YouTube remplacés depuis l'app (%d cookies)", count)
    logged_in = await youtube_session.check_session(path, "cookies envoyés depuis l'app")
    message = {
        True: "Cookies installés : la session YouTube est connectée.",
        False: "Cookies installés, mais YouTube les voit déconnectés : réexporte-les (fenêtre privée, puis ferme-la).",
        None: "Cookies installés. Vérification auprès de YouTube impossible pour l'instant.",
    }[logged_in]
    return {"cookies": count, "logged_in": logged_in, "message": message}


@router.post("/streaming/selftest")
async def run_selftest(deps: ApiDeps = Depends(require_admin)) -> dict:
    """Essai de lecture d'une vidéo YouTube de référence."""
    ok, message = await asyncio.to_thread(ytdlp_updater.selftest)
    stream_health.record(ok, None if ok else stream_health.classify(message))
    return {"ok": ok, "message": message}


@router.post("/ytdlp/update", status_code=status.HTTP_202_ACCEPTED)
async def update_ytdlp(deps: ApiDeps = Depends(require_admin)) -> dict:
    """Mise à jour de yt-dlp tout de suite (sinon chaque nuit). Tourne à
    part : elle redémarre Sona si une nouvelle version arrive."""
    log = open(BASE_DIR / "data" / "ytdlp_update.log", "a")
    subprocess.Popen(
        [sys.executable, "-m", "app.services.ytdlp_updater"],
        cwd=BASE_DIR, stdout=log, stderr=log, start_new_session=True,
    )
    return {"started": True, "message": "Mise à jour lancée : Sona redémarre dans une minute si une nouvelle version arrive."}


@router.post("/diagnose/{source}/{source_id}")
async def diagnose_track(source: str, source_id: str, deps: ApiDeps = Depends(require_admin)) -> dict:
    """« Diagnostic de lecture » d'un titre : relance sa préparation (sans
    attendre la fin du délai après un échec) et rend le compte rendu — ce
    que YouTube et SoundCloud ont renvoyé, et pourquoi chaque source a été
    écartée. De quoi comprendre un titre qui ne se lance pas sans lire les
    journaux du serveur."""
    stream.forget_track_failures(source, source_id)
    try:
        await stream.ensure_file(deps, source, source_id, "best", "auto")
    except HTTPException:
        pass  # le compte rendu dit pourquoi
    report = stream.last_report(source, source_id)
    if report is None:
        return {"ready": True, "message": "Ce titre est déjà prêt sur le serveur : il se lance depuis le cache."}
    return {"ready": report["result"] == "ok", **report}


@router.post("/diagnose/{source}/{source_id}/unreject")
async def unreject_sources(source: str, source_id: str, deps: ApiDeps = Depends(require_admin)) -> dict:
    """Réautorise les sources écartées par « Mauvaise version ? » pour ce
    titre : quand la seule version disponible a été signalée, le titre ne
    se lance plus du tout. Elles repassent la vérification par empreinte."""
    count = await deps.repo.unreject_sources(source, source_id)
    stream.forget_track_failures(source, source_id)
    stream.forget_live_source(source, source_id)
    logger.info("%d source(s) réautorisée(s) pour %s:%s", count, source, source_id)
    return {"unrejected": count}


class UseSourceIn(BaseModel):
    url: str = Field(min_length=8, max_length=500)


@router.post("/diagnose/{source}/{source_id}/use-source")
async def use_source(
    source: str, source_id: str, payload: UseSourceIn, deps: ApiDeps = Depends(require_admin)
) -> dict:
    """Choisit à la main la source d'un titre qui n'a pas de bonne version : un
    lien YouTube ou SoundCloud collé depuis le diagnostic. Elle est essayée en
    premier à la prochaine lecture — et toujours comparée à l'extrait
    officiel : un audio qui n'est pas le bon enregistrement reste écarté."""
    try:
        video_id = await source_from_url(payload.url)
    except ResolutionError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    await deps.repo.unreject_source(source, source_id, video_id)
    await deps.repo.stream_source_set(source, source_id, video_id)
    stream.allow_source(source, source_id, video_id)
    logger.info("Source %s choisie à la main pour %s:%s", video_id, source, source_id)
    return {"video_id": video_id}
