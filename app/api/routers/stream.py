from __future__ import annotations

import asyncio
import logging
import shutil
import time
from collections import defaultdict
from contextlib import aclosing
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse

from app.api.auth import require_token
from app.api.state import ApiDeps
from app.bot import lookup
from app.db.repository import FORMAT_CHOICES, QUALITY_CHOICES
from app.services.audio_match import verify_recording
from app.services.downloader import DownloadError, cleanup_download, download_and_tag
from app.services.preview import complete_preview
from app.services.resolver import ResolutionError, iter_audio_sources

logger = logging.getLogger(__name__)
router = APIRouter(tags=["stream"])

# Mêmes bornes que le bot (app/bot/handlers/track.py) : au-delà, chaque
# téléchargement supplémentaire coûte plus qu'il n'a de chances d'aboutir.
MAX_SOURCE_ATTEMPTS = 4

_CONTENT_TYPES = {".mp3": "audio/mpeg", ".m4a": "audio/mp4"}

# Un verrou par (source, source_id, format, quality) : deux requêtes pour le
# même morceau ne doivent pas déclencher deux téléchargements en parallèle.
_locks: dict[tuple[str, str, str, str], asyncio.Lock] = defaultdict(asyncio.Lock)


def _cache_key(source: str, source_id: str, fmt: str, quality: str) -> tuple[str, str, str, str]:
    return (source, source_id, fmt, quality)


def _persistent_path(deps: ApiDeps, source: str, source_id: str, fmt: str, quality: str, suffix: str) -> Path:
    safe_id = "".join(ch for ch in source_id if ch.isalnum() or ch in "-_") or "track"
    return deps.settings.stream_cache_dir / f"{source}_{safe_id}_{quality}_{fmt}{suffix}"


async def _resolve_and_download(deps: ApiDeps, source: str, source_id: str, quality: str, fmt: str) -> Path:
    """Reproduit `deliver_track_audio` du bot, sans Telegram : télécharge,
    vérifie l'audio contre l'extrait officiel, et rend un fichier persistant."""
    try:
        track = await lookup.get_track(deps, source, source_id)
    except lookup.ProviderErrors as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Morceau introuvable : {exc}") from exc

    track = await complete_preview(deps.deezer, track)

    attempts = 0
    try:
        async with aclosing(iter_audio_sources(track, deps.settings.youtube_cookies_file)) as sources:
            async for source_candidate in sources:
                attempts += 1
                try:
                    path = await download_and_tag(
                        deps.settings, source_candidate.source_url, track, quality, fmt
                    )
                except DownloadError as exc:
                    if source_candidate.platform == "youtube":
                        raise HTTPException(
                            status.HTTP_502_BAD_GATEWAY, "Téléchargement audio impossible."
                        ) from exc
                    logger.info("Source %s inutilisable : %s", source_candidate.video_id, exc.__cause__ or exc)
                    if attempts >= MAX_SOURCE_ATTEMPTS:
                        break
                    continue

                verdict = await verify_recording(track, path, deps.settings.ffmpeg_path)
                if not verdict.rejected:
                    dest = _persistent_path(deps, source, source_id, fmt, quality, path.suffix)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(path), dest)
                    cleanup_download(path)  # nettoie le dossier de travail temporaire restant
                    content_type = _CONTENT_TYPES.get(dest.suffix.lower(), "application/octet-stream")
                    await deps.repo.stream_cache_set(source, source_id, fmt, quality, str(dest), content_type)
                    return dest

                logger.info(
                    "Audio %s écarté pour %s — %s : %s",
                    source_candidate.video_id, track.artist, track.title,
                    verdict.reason or f"écart d'empreinte {verdict.error:.3f}",
                )
                cleanup_download(path)
                if attempts >= MAX_SOURCE_ATTEMPTS:
                    break
    except ResolutionError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Résolution de la source audio impossible.") from exc

    if attempts == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aucune source audio trouvée pour ce morceau.")
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Aucune version fidèle de ce morceau n'a été trouvée.")


# Échecs récents par morceau : l'app demande souvent le même titre deux fois
# de suite (préparation puis lecture, ou nouvel essai immédiat). Sans ce
# souvenir, chaque demande relançait des dizaines de secondes de
# téléchargements voués à échouer. Court, pour qu'un souci passager (YouTube
# qui bride) ne bloque pas le morceau longtemps.
FAILURE_TTL = 120.0
_failures: dict[tuple[str, str, str, str], tuple[float, int, str]] = {}


def _check_params(quality: str, fmt: str) -> None:
    if quality not in QUALITY_CHOICES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Qualité inconnue : {quality}")
    if fmt not in FORMAT_CHOICES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Format inconnu : {fmt}")


async def _cached_file(deps: ApiDeps, source: str, source_id: str, fmt: str, quality: str) -> tuple[str, str] | None:
    cached = await deps.repo.stream_cache_get(source, source_id, fmt, quality)
    if cached is not None and Path(cached[0]).is_file():
        return cached
    if cached is not None:
        logger.warning("Fichier en cache manquant sur disque, retéléchargement : %s", cached[0])
    return None


async def ensure_file(deps: ApiDeps, source: str, source_id: str, quality: str, fmt: str) -> tuple[str, str]:
    """Chemin et type du fichier audio prêt à servir : depuis le cache, ou
    après téléchargement + vérification (un seul à la fois par morceau)."""
    cached = await _cached_file(deps, source, source_id, fmt, quality)
    if cached is not None:
        return cached

    key = _cache_key(source, source_id, fmt, quality)
    failure = _failures.get(key)
    if failure is not None and time.monotonic() - failure[0] < FAILURE_TTL:
        raise HTTPException(failure[1], failure[2])

    async with _locks[key]:
        # Une requête concurrente a peut-être fini (ou échoué) pendant
        # qu'on attendait le verrou.
        cached = await _cached_file(deps, source, source_id, fmt, quality)
        if cached is not None:
            return cached
        failure = _failures.get(key)
        if failure is not None and time.monotonic() - failure[0] < FAILURE_TTL:
            raise HTTPException(failure[1], failure[2])
        try:
            dest = await _resolve_and_download(deps, source, source_id, quality, fmt)
        except HTTPException as exc:
            _failures[key] = (time.monotonic(), exc.status_code, str(exc.detail))
            raise
        _failures.pop(key, None)

    return str(dest), _CONTENT_TYPES.get(dest.suffix.lower(), "application/octet-stream")


@router.post("/stream/{source}/{source_id}/prepare")
async def prepare(
    source: str,
    source_id: str,
    quality: str = Query("best"),
    format: str = Query("auto"),
    deps: ApiDeps = Depends(require_token),
) -> dict:
    """Télécharge et vérifie le morceau sans l'envoyer. L'app l'appelle avant
    de lancer la lecture (le lecteur audio d'iOS abandonne sur une réponse
    trop lente et ne montre alors qu'un « resource unavailable » sans la
    vraie cause), et pour le morceau suivant pendant l'écoute du courant —
    l'enchaînement est alors instantané."""
    _check_params(quality, format)
    await ensure_file(deps, source, source_id, quality, format)
    return {"ready": True}


@router.get("/stream/{source}/{source_id}")
async def stream(
    source: str,
    source_id: str,
    quality: str = Query("best"),
    format: str = Query("auto"),
    deps: ApiDeps = Depends(require_token),
) -> FileResponse:
    _check_params(quality, format)
    file_path, content_type = await ensure_file(deps, source, source_id, quality, format)
    return FileResponse(file_path, media_type=content_type, filename=Path(file_path).name)
