from __future__ import annotations

import asyncio
import logging
import shutil
import time
from collections import defaultdict
from contextlib import aclosing
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, StreamingResponse
from starlette.background import BackgroundTask

from app.api.auth import require_token
from app.api.state import ApiDeps
from app.bot import lookup
from app.providers.base import TrackInfo
from app.db.repository import FORMAT_CHOICES, QUALITY_CHOICES
from app.services.audio_match import verify_recording
from app.services.downloader import DownloadError, cleanup_download, download_and_tag
from app.services.preview import complete_preview
from app.services import audio_analysis, live_stream, stream_health
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


def _download_failure(exc: DownloadError) -> str:
    """Message affiché dans l'app : la vraie cause, pas juste « impossible »
    — sans elle, impossible de savoir quoi réparer côté serveur."""
    if exc.bot_wall:
        return (
            "YouTube bloque le serveur (vérification anti-robot) : "
            "renouvelle le fichier de cookies YouTube du serveur."
        )
    cause = str(exc.__cause__ or exc).replace("ERROR: ", "").strip().splitlines()[0][:200]
    return f"Téléchargement audio impossible : {cause}"


async def _track_for(deps: ApiDeps, source: str, source_id: str) -> TrackInfo:
    """Fiche du titre chez sa source ; si elle ne le retrouve plus (titre
    retiré, autre pays…), celle enregistrée avec la playlist ou les écoutes."""
    try:
        return await lookup.get_track(deps, source, source_id)
    except lookup.ProviderErrors:
        known = await deps.repo.known_track(source, source_id)
        if known is None:
            raise
        logger.info("%s:%s introuvable chez la source : fiche enregistrée utilisée", source, source_id)
        return known


async def _resolve_and_download(deps: ApiDeps, source: str, source_id: str, quality: str, fmt: str) -> Path:
    """Reproduit `deliver_track_audio` du bot, sans Telegram : télécharge,
    vérifie l'audio contre l'extrait officiel, et rend un fichier persistant."""
    try:
        track = await _track_for(deps, source, source_id)
    except lookup.ProviderErrors as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Morceau introuvable : {exc}") from exc

    track = await complete_preview(deps.deezer, track)
    excluded = await deps.repo.rejected_sources(source, source_id)
    # Source déjà trouvée (lecture directe précédente) : essayée d'abord,
    # sans nouvelle recherche. Toujours vérifiée par empreinte ci-dessous.
    preferred = await deps.repo.stream_source_get(source, source_id)

    attempts = 0
    # YouTube en panne (cookies, yt-dlp dépassé…) : on ne s'acharne pas sur
    # ses autres vidéos, mais on essaie encore les autres sources
    # (SoundCloud) avant d'abandonner.
    youtube_failure: DownloadError | None = None
    try:
        async with aclosing(
            iter_audio_sources(track, deps.settings.youtube_cookies_file, excluded, preferred)
        ) as sources:
            async for source_candidate in sources:
                if youtube_failure is not None and source_candidate.platform == "youtube":
                    continue
                attempts += 1
                try:
                    path = await download_and_tag(
                        deps.settings, source_candidate.source_url, track, quality, fmt
                    )
                except DownloadError as exc:
                    if source_candidate.platform == "youtube":
                        youtube_failure = exc
                        stream_health.record(False, stream_health.classify(str(exc.__cause__ or exc), exc.bot_wall))
                        logger.info("YouTube indisponible pour %s — %s, essai des autres sources", track.artist, track.title)
                        continue
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
                    await deps.repo.stream_source_set(source, source_id, source_candidate.video_id)
                    stream_health.record(True)
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

    if youtube_failure is not None:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, _download_failure(youtube_failure)) from youtube_failure
    if attempts == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aucune source audio trouvée pour ce morceau.")
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Aucune version fidèle de ce morceau n'a été trouvée.")


# Échecs récents par morceau : l'app demande souvent le même titre deux fois
# de suite (préparation puis lecture, ou nouvel essai immédiat). Sans ce
# souvenir, chaque demande relançait des dizaines de secondes de
# téléchargements voués à échouer. Court, pour qu'un souci passager (YouTube
# qui bride) ne bloque pas le morceau longtemps.
FAILURE_TTL = 120.0
# Un seul téléchargement complet à la fois (yt-dlp + moteur JS + ffmpeg +
# empreinte) : sur une petite machine (1 Go), en lancer plusieurs en même
# temps — lecture, préparation du suivant, mise en cache en arrière-plan —
# saturait la mémoire au point de figer tout le serveur.
_download_slots = asyncio.Semaphore(1)
_failures: dict[tuple[str, str, str, str], tuple[float, int, str]] = {}


def forget_failures() -> None:
    """Oublie les échecs récents (cookies renouvelés : on réessaie tout de suite)."""
    _failures.clear()


def prune_cache(directory: Path, max_bytes: int, keep: Path | None = None) -> int:
    """Supprime les fichiers les moins récemment utilisés jusqu'à repasser
    sous `max_bytes`. Un fichier servi voit sa date d'accès rafraîchie (voir
    `_touch`) : ce sont donc bien les titres écoutés il y a le plus longtemps
    qui partent. Un fichier supprimé est simplement retéléchargé s'il est
    redemandé. Renvoie le nombre de fichiers supprimés."""
    if not directory.is_dir():
        return 0
    files = [p for p in directory.iterdir() if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    removed = 0
    for path in sorted(files, key=lambda p: p.stat().st_mtime):
        if total <= max_bytes:
            break
        if keep is not None and path == keep:
            continue
        size = path.stat().st_size
        try:
            path.unlink()
        except OSError:
            continue
        total -= size
        removed += 1
    if removed:
        logger.info("Cache audio : %d ancien(s) fichier(s) supprimé(s)", removed)
    return removed


def _touch(path: str) -> None:
    try:
        Path(path).touch()
    except OSError:
        pass


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
            async with _download_slots:
                dest = await _resolve_and_download(deps, source, source_id, quality, fmt)
            prune_cache(deps.settings.stream_cache_dir, deps.settings.stream_cache_max_mb * 1024 * 1024, keep=dest)
        except HTTPException as exc:
            _failures[key] = (time.monotonic(), exc.status_code, str(exc.detail))
            raise
        _failures.pop(key, None)
        # Analyse pour l'AutoMix, en arrière-plan (priorité basse).
        _spawn_analysis(deps, source, source_id, dest)

    return str(dest), _CONTENT_TYPES.get(dest.suffix.lower(), "application/octet-stream")


_analysis_tasks: set[asyncio.Task] = set()
_analysis_slots = asyncio.Semaphore(1)


def _spawn_analysis(deps: ApiDeps, source: str, source_id: str, path: Path) -> None:
    async def run() -> None:
        async with _analysis_slots:
            if await deps.repo.analysis_get(source, source_id):
                return
            result = await asyncio.to_thread(audio_analysis.analyze, path, deps.settings.ffmpeg_path)
        if result is not None:
            await deps.repo.analysis_set(
                source, source_id, result.loudness, result.start, result.mix_out, result.end, result.duration
            )

    task = asyncio.create_task(run())
    _analysis_tasks.add(task)
    task.add_done_callback(_analysis_tasks.discard)


@router.get("/analysis/{source}/{source_id}")
async def track_analysis(source: str, source_id: str, deps: ApiDeps = Depends(require_token)) -> dict:
    """Analyse audio d'un titre pour l'AutoMix (sonie, début, outro, fin),
    calculée à la mise en cache. 404 tant que le titre n'a pas été préparé."""
    found = await deps.repo.analysis_get(source, source_id)
    if found is None:
        cached = await deps.repo.stream_cache_get(source, source_id, "auto", "best")
        if cached is not None and Path(cached[0]).is_file():
            _spawn_analysis(deps, source, source_id, Path(cached[0]))
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Analyse pas encore prête.")
    return {
        "loudness": found["loudness"], "start": found["start"], "mix_out": found["mix_out"],
        "end": found["end_time"], "duration": found["duration"],
    }


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


_live = live_stream.LiveCache()
_warming: set[tuple[str, str, str, str]] = set()
_proxy_client: httpx.AsyncClient | None = None


def _client() -> httpx.AsyncClient:
    global _proxy_client
    if _proxy_client is None:
        _proxy_client = httpx.AsyncClient(timeout=httpx.Timeout(20.0, read=60.0), follow_redirects=True)
    return _proxy_client


class _LiveFailed(Exception):
    pass


async def _live_source(deps: ApiDeps, source: str, source_id: str, key: tuple) -> live_stream.LiveSource | None:
    known, cached = _live.get(key)
    if known:
        return cached
    async with _live.lock(key):
        known, cached = _live.get(key)
        if known:
            return cached
        try:
            track = await _track_for(deps, source, source_id)
            excluded = await deps.repo.rejected_sources(source, source_id)
            preferred = await deps.repo.stream_source_get(source, source_id)
            found = await live_stream.resolve(track, deps.settings.youtube_cookies_file, excluded, preferred)
            if found is not None and found.video_id:
                await deps.repo.stream_source_set(source, source_id, found.video_id)
        except Exception as exc:  # le chemin complet prend le relais, avec son propre message
            logger.info("Flux direct indisponible pour %s:%s : %s", source, source_id, exc)
            found = None
        _live.put(key, found)
        return found


def _warm(deps: ApiDeps, source: str, source_id: str, quality: str, fmt: str) -> None:
    """Télécharge et vérifie le fichier en arrière-plan pendant la lecture
    directe : les écoutes suivantes partent du cache."""
    key = _cache_key(source, source_id, fmt, quality)
    if key in _warming:
        return
    _warming.add(key)

    async def run() -> None:
        try:
            await ensure_file(deps, source, source_id, quality, fmt)
        except Exception as exc:
            logger.info("Mise en cache de %s:%s après lecture directe impossible : %s", source, source_id, exc)
        finally:
            _warming.discard(key)

    asyncio.create_task(run())


async def _proxy(request: Request, live: live_stream.LiveSource) -> StreamingResponse:
    # `identity` : les octets relayés doivent correspondre exactement aux
    # en-têtes Content-Length/Content-Range transmis à l'app.
    headers = {**live.headers, "Accept-Encoding": "identity"}
    if range_header := request.headers.get("range"):
        headers["Range"] = range_header
    client = _client()
    try:
        upstream = await client.send(client.build_request("GET", live.url, headers=headers), stream=True)
    except httpx.HTTPError as exc:
        raise _LiveFailed(str(exc)) from exc
    if upstream.status_code not in (200, 206):
        await upstream.aclose()
        raise _LiveFailed(f"HTTP {upstream.status_code}")
    out = {"Accept-Ranges": "bytes"}
    for name in ("content-length", "content-range"):
        if name in upstream.headers:
            out[name] = upstream.headers[name]
    return StreamingResponse(
        upstream.aiter_bytes(),
        status_code=upstream.status_code,
        headers=out,
        media_type=live.content_type,
        background=BackgroundTask(upstream.aclose),
    )


@router.get("/stream/{source}/{source_id}")
async def stream(
    request: Request,
    source: str,
    source_id: str,
    quality: str = Query("best"),
    format: str = Query("auto"),
    live: bool = Query(True, description="Relayer le flux YouTube tant que le fichier n'est pas prêt"),
    deps: ApiDeps = Depends(require_token),
):
    _check_params(quality, format)
    cached = await _cached_file(deps, source, source_id, format, quality)
    if cached is not None:
        _touch(cached[0])
        return FileResponse(cached[0], media_type=cached[1], filename=Path(cached[0]).name)

    # Pas encore en cache : lecture directe si possible (démarrage en
    # quelques secondes), fichier vérifié préparé en parallèle.
    key = _cache_key(source, source_id, format, quality)
    if live and format != "mp3":
        direct = await _live_source(deps, source, source_id, key)
        if direct is not None:
            _warm(deps, source, source_id, quality, format)
            try:
                response = await _proxy(request, direct)
                stream_health.record(True)
                return response
            except _LiveFailed as exc:
                logger.info("Relais direct de %s:%s interrompu (%s), repli sur le téléchargement", source, source_id, exc)
                _live.drop(key)

    file_path, content_type = await ensure_file(deps, source, source_id, quality, format)
    return FileResponse(file_path, media_type=content_type, filename=Path(file_path).name)


@router.post("/stream/{source}/{source_id}/wrong-version")
async def wrong_version(source: str, source_id: str, deps: ApiDeps = Depends(require_token)) -> dict:
    """« Mauvaise version ? » dans l'app (clip avec bruitages, live, autre
    enregistrement...) : la source servie pour ce morceau est écartée pour
    de bon, son fichier en cache supprimé, et la prochaine lecture en
    cherche une autre."""
    video_id = await deps.repo.stream_source_get(source, source_id)
    if video_id is not None:
        await deps.repo.reject_source(source, source_id, video_id)
    # Fichier mis en cache avant qu'on note les sources : pas d'identifiant à
    # écarter, mais le supprimer suffit souvent (le classement favorise
    # maintenant l'audio officiel).
    await deps.repo.analysis_delete(source, source_id)
    for path in await deps.repo.stream_cache_delete(source, source_id):
        try:
            Path(path).unlink(missing_ok=True)
        except OSError as exc:
            logger.info("Fichier %s impossible à supprimer : %s", path, exc)
    _live.drop_track(source, source_id)
    for key in [k for k in _failures if k[:2] == (source, source_id)]:
        del _failures[key]
    logger.info("Source %s écartée pour %s:%s (mauvaise version signalée)", video_id, source, source_id)
    return {"rejected": video_id}
