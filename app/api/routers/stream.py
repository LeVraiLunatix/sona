from __future__ import annotations

import asyncio
import logging
import shutil
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


@router.get("/stream/{source}/{source_id}")
async def stream(
    source: str,
    source_id: str,
    quality: str = Query("best"),
    format: str = Query("auto"),
    deps: ApiDeps = Depends(require_token),
) -> FileResponse:
    if quality not in QUALITY_CHOICES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Qualité inconnue : {quality}")
    if format not in FORMAT_CHOICES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Format inconnu : {format}")

    cached = await deps.repo.stream_cache_get(source, source_id, format, quality)
    if cached is not None:
        file_path, content_type = cached
        if Path(file_path).is_file():
            return FileResponse(file_path, media_type=content_type, filename=Path(file_path).name)
        logger.warning("Fichier en cache manquant sur disque, retéléchargement : %s", file_path)

    lock = _locks[_cache_key(source, source_id, format, quality)]
    async with lock:
        # Une requête concurrente a peut-être fini le téléchargement pendant
        # qu'on attendait le verrou.
        cached = await deps.repo.stream_cache_get(source, source_id, format, quality)
        if cached is not None and Path(cached[0]).is_file():
            file_path, content_type = cached
            return FileResponse(file_path, media_type=content_type, filename=Path(file_path).name)

        dest = await _resolve_and_download(deps, source, source_id, quality, format)

    content_type = _CONTENT_TYPES.get(dest.suffix.lower(), "application/octet-stream")
    return FileResponse(dest, media_type=content_type, filename=dest.name)
