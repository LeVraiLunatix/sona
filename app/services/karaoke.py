"""Karaoké : file des séparations voix / instru, cache des pistes, état.

Chaque titre est séparé en deux passes (voir `separation.py`) : une passe
rapide, pour chanter au plus vite, puis une passe fine en arrière-plan qui
remplace les pistes rapides. Les deux pistes (voix, instru) sont gardées
dans `settings.karaoke_dir`. L'app les joue ensemble, parfaitement calées,
et ne règle que le volume de la voix.

Contraintes du serveur (2 cœurs ARM, qui servent aussi l'API et le bot) :

- une seule séparation à la fois, dans un sous-processus en priorité basse
  (`nice`), avec un délai maximum — l'API ne l'attend jamais ;
- ordre de passage : le titre en cours d'écoute, puis les suivants de la
  file (passes rapides), puis les passes fines, puis les titres préparés la
  nuit (un titre écouté maintenant passe même devant une passe fine ou une
  séparation de nuit déjà commencée) ;
- rien ne casse si la séparation est impossible (modèle pas téléchargeable,
  numpy / onnxruntime absents, titre trop long…) : l'état passe à « échec »
  et l'app garde l'ancien mode (instru YouTube ou voix baissée).
"""

from __future__ import annotations

import asyncio
import importlib.util
import itertools
import logging
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

import httpx

from app.config import BASE_DIR, Settings
from app.services import separation

logger = logging.getLogger(__name__)

STEMS = ("vocals", "instrumental")
# Deux passes (voir `separation.MODELS`) : « fast » d'abord, pour chanter
# vite, puis « hq », plus fine, qui remplace les pistes rapides.
QUALITIES = ("hq", "fast")  # de la meilleure à la moins bonne

# Priorités (plus petit = plus urgent).
NOW, UPCOMING, REFINE, NIGHT = 0, 1, 2, 3
# Au-delà, les demandes les moins urgentes sont oubliées : l'app redemande
# de toute façon les titres qu'elle s'apprête à jouer.
MAX_QUEUE = 30
# Un titre dont la séparation a échoué n'est retenté qu'après ce délai.
FAILURE_TTL = 3600.0
# Délai maximum d'une séparation (titre de 3 min, passe fine : 5 à 8 min).
TIMEOUT = 25 * 60


class SeparationError(Exception):
    """Séparation impossible : le message est montré dans l'app."""


@dataclass
class Job:
    source: str
    source_id: str
    quality: str
    priority: int
    order: int
    status: str = "queued"  # queued, running, failed
    progress: float = 0.0
    error: str | None = None
    failed_at: float = 0.0
    preempted: bool = False
    # Abandonnée (file vidée) : interrompue, et pas remise en file.
    cancelled: bool = False
    # Comptes qui l'attendent (vide : séparation de nuit). Sert à vider sa
    # propre file sans toucher à celle des autres.
    users: set[int] = field(default_factory=set)

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.source, self.source_id, self.quality)


_jobs: dict[tuple[str, str, str], Job] = {}
_order = itertools.count()
_wake: asyncio.Event | None = None
_worker: asyncio.Task | None = None
_running: Job | None = None
_process: asyncio.subprocess.Process | None = None
_nightly: asyncio.Task | None = None


def reset() -> None:
    """Remise à zéro (tests)."""
    global _wake, _worker, _running, _process, _nightly
    if _process is not None and _process.returncode is None:
        try:
            _process.kill()
        except ProcessLookupError:
            pass
    for task in (_worker, _nightly):
        if task is not None and not task.done():
            task.cancel()
    _jobs.clear()
    _wake = _worker = _running = _process = _nightly = None


def engine_available() -> bool:
    """numpy et onnxruntime installés : sinon, pas de séparation du tout."""
    return all(importlib.util.find_spec(name) is not None for name in ("numpy", "onnxruntime"))


# -- Pistes sur disque --------------------------------------------------------


def _safe(text: str) -> str:
    return "".join(ch for ch in text if ch.isalnum() or ch in "-_") or "track"


def stem_path(settings: Settings, source: str, source_id: str, stem: str, quality: str = "hq") -> Path:
    # Passe fine : noms d'origine (pistes déjà séparées avant les deux passes).
    tag = "" if quality == "hq" else f"_{quality}"
    return settings.karaoke_dir / f"{_safe(source)}_{_safe(source_id)}{tag}_{stem}.m4a"


def ready_quality(settings: Settings, source: str, source_id: str) -> str | None:
    """Meilleure qualité dont les deux pistes sont prêtes, ou None."""
    for quality in QUALITIES:
        if all(stem_path(settings, source, source_id, stem, quality).is_file() for stem in STEMS):
            return quality
    return None


def is_ready(settings: Settings, source: str, source_id: str) -> bool:
    return ready_quality(settings, source, source_id) is not None


def _delete(settings: Settings, source: str, source_id: str, quality: str) -> None:
    for stem in STEMS:
        stem_path(settings, source, source_id, stem, quality).unlink(missing_ok=True)


def forget(settings: Settings, source: str, source_id: str) -> None:
    """« Mauvaise version ? » : les pistes venaient du mauvais enregistrement."""
    for quality in QUALITIES:
        _delete(settings, source, source_id, quality)
        job = _jobs.get((source, source_id, quality))
        if job is not None and job.status != "running":
            _jobs.pop(job.key, None)


def _title_key(path: Path) -> str:
    """Titre auquel appartient une piste (ses deux qualités ensemble)."""
    base = path.stem.rsplit("_", 1)[0]
    for quality in QUALITIES:
        if base.endswith(f"_{quality}"):
            return base[: -len(quality) - 1]
    return base


def prune(settings: Settings, keep: tuple[str, str] | None = None) -> int:
    """Supprime les titres les moins récemment écoutés (toutes leurs pistes
    ensemble) jusqu'à repasser sous la taille max. Renvoie le nombre de
    titres supprimés."""
    directory = settings.karaoke_dir
    if not directory.is_dir():
        return 0
    groups: dict[str, list[Path]] = {}
    for path in directory.glob("*.m4a"):
        groups.setdefault(_title_key(path), []).append(path)
    kept = f"{_safe(keep[0])}_{_safe(keep[1])}" if keep else None
    total = sum(p.stat().st_size for paths in groups.values() for p in paths)
    limit = settings.karaoke_cache_max_mb * 1024 * 1024
    removed = 0
    for base, paths in sorted(groups.items(), key=lambda item: max(p.stat().st_mtime for p in item[1])):
        if total <= limit:
            break
        if base == kept:
            continue
        for path in paths:
            size = path.stat().st_size
            try:
                path.unlink()
            except OSError:
                continue
            total -= size
        removed += 1
    if removed:
        logger.info("Karaoké : %d ancien(s) titre(s) retiré(s) du cache", removed)
    return removed


def touch(path: Path) -> None:
    """Piste servie : elle compte comme récemment écoutée (voir `prune`)."""
    try:
        path.touch()
    except OSError:
        pass


# -- État ---------------------------------------------------------------------


def _job_state(job: Job) -> dict:
    out = {"status": job.status, "progress": round(job.progress, 3), "quality": job.quality}
    if job.status == "queued":
        out["ahead"] = sum(1 for other in _pending() if _rank(other) < _rank(job)) + (1 if _running else 0)
    if job.error:
        out["error"] = job.error
    return out


def status(settings: Settings, source: str, source_id: str) -> dict:
    """État d'un titre pour l'app : absent, en file, en cours, prêt, échec.
    Prêt en qualité rapide : `refining` dit où en est la passe fine."""
    quality = ready_quality(settings, source, source_id)
    if quality is not None:
        out = {"status": "ready", "progress": 1.0, "quality": quality}
        refine = _jobs.get((source, source_id, "hq"))
        if quality == "fast" and refine is not None and refine.status != "failed":
            out["refining"] = _job_state(refine)
        return out
    # Pas encore de pistes : la passe rapide si elle est demandée (c'est
    # elle qui arrivera en premier), sinon la passe fine (préparée la nuit).
    job = _jobs.get((source, source_id, "fast")) or _jobs.get((source, source_id, "hq"))
    if job is None:
        return {"status": "absent", "progress": 0.0, "available": engine_available()}
    return _job_state(job)


def _pending() -> list[Job]:
    return [job for job in _jobs.values() if job.status == "queued"]


def _rank(job: Job) -> tuple[int, int]:
    return (job.priority, job.order)


# -- Demandes -----------------------------------------------------------------


def request(deps, source: str, source_id: str, priority: int = NOW) -> dict:
    """Met un titre en file (ou le fait remonter si déjà demandé) et renvoie
    son état. Ne lance jamais le calcul dans la requête elle-même.

    Demandé pour être chanté : passe rapide d'abord, puis la passe fine si
    le titre est chanté maintenant (un titre seulement « à venir » n'a sa
    passe fine que s'il est chanté ensuite). Préparé la nuit : directement
    la passe fine."""
    settings = deps.settings
    user = deps.user_id if priority < NIGHT else None
    ready = ready_quality(settings, source, source_id)
    if ready == "hq":
        return status(settings, source, source_id)
    if ready == "fast":
        if priority == NOW or priority >= NIGHT:
            _ensure_job(source, source_id, "hq", max(priority, REFINE), user)
    elif priority >= NIGHT:
        _ensure_job(source, source_id, "hq", priority, user)
    else:
        _ensure_job(source, source_id, "fast", priority, user)
    # Un titre à écouter maintenant ne patiente pas derrière une passe fine
    # ou une séparation de nuit : elle est interrompue et reprendra après.
    if priority == NOW and _running is not None and _running.priority >= REFINE \
            and _running.key[:2] != (source, source_id):
        _preempt()
    _ensure_worker(deps)
    return status(settings, source, source_id)


def prepare_upcoming(deps, tracks: list[tuple[str, str]]) -> list[dict]:
    """Titres suivants de la file de l'app. Ceux demandés avant par ce
    compte et qui n'en font plus partie (titres passés, file changée) sont
    retirés : sans ça, la file du serveur grossissait à chaque titre."""
    wanted = set(tracks)
    for job in list(_jobs.values()):
        if job.status == "queued" and job.priority == UPCOMING and deps.user_id in job.users \
                and job.key[:2] not in wanted:
            job.users.discard(deps.user_id)
            if not job.users:
                _jobs.pop(job.key, None)
    return [
        {"source": source, "source_id": source_id, **request(deps, source, source_id, UPCOMING)}
        for source, source_id in tracks
    ]


def queue_info(deps) -> dict:
    """État de la file pour le menu karaoké : combien de séparations en
    attente, dont celles demandées par ce compte, et celle en cours."""
    pending = _pending()
    info = {
        "queued": len(pending),
        "mine": sum(1 for job in pending if deps.user_id in job.users),
        "running": None,
    }
    if _running is not None:
        info["running"] = {
            "source": _running.source, "source_id": _running.source_id, "quality": _running.quality,
            "progress": round(_running.progress, 3), "mine": deps.user_id in _running.users,
        }
    return info


def clear_queue(deps) -> int:
    """Vide la file : les séparations demandées par ce compte (toutes pour
    un administrateur), en attente, en cours ou en échec (elles pourront
    être redemandées aussitôt). Renvoie le nombre de séparations retirées."""
    removed = 0
    for job in list(_jobs.values()):
        mine = deps.user_id in job.users
        if not (deps.is_admin or mine):
            continue
        job.users.discard(deps.user_id)
        if job.users and not deps.is_admin:
            continue  # un autre compte l'attend encore
        if job is _running:
            job.cancelled = True
            _preempt()
        else:
            _jobs.pop(job.key, None)
        removed += 1
    if removed:
        logger.info("Karaoké : file vidée (%d séparation(s))", removed)
    return removed


def _ensure_job(source: str, source_id: str, quality: str, priority: int, user: int | None = None) -> None:
    key = (source, source_id, quality)
    job = _jobs.get(key)
    if job is not None and job.status == "failed":
        if time.monotonic() - job.failed_at < FAILURE_TTL:
            return
        job = None
    if job is None:
        job = Job(source, source_id, quality, priority, next(_order))
        _jobs[key] = job
        _trim_queue()
    elif priority < job.priority:
        job.priority = priority
        if job.status == "queued":
            job.order = next(_order)
    if user is not None:
        job.users.add(user)


def _trim_queue() -> None:
    pending = sorted(_pending(), key=_rank)
    for job in pending[MAX_QUEUE:]:
        _jobs.pop(job.key, None)


def _preempt() -> None:
    if _running is None:
        return
    _running.preempted = True
    if _process is not None and _process.returncode is None:
        try:
            _process.kill()
        except ProcessLookupError:
            pass


def _ensure_worker(deps) -> None:
    global _worker, _wake
    if _wake is None:
        _wake = asyncio.Event()
    _wake.set()
    if _worker is None or _worker.done():
        _worker = asyncio.create_task(_work(deps))


async def _work(deps) -> None:
    """Une séparation à la fois, la plus urgente d'abord."""
    global _running
    assert _wake is not None
    while True:
        pending = _pending()
        if not pending:
            _wake.clear()
            await _wake.wait()
            continue
        job = min(pending, key=_rank)
        job.status, job.progress, job.error, job.preempted = "running", 0.0, None, False
        _running = job
        try:
            await _process_job(deps, job)
        except asyncio.CancelledError:
            raise
        except _Preempted:
            if job.cancelled:
                _jobs.pop(job.key, None)
                continue
            logger.info("Karaoké : séparation de %s:%s reportée (titre plus urgent)", job.source, job.source_id)
            job.status, job.progress = "queued", 0.0
            job.order = next(_order)
            continue
        except SeparationError as exc:
            _fail(job, str(exc))
        except Exception as exc:  # jamais d'arrêt de la file sur une erreur imprévue
            logger.exception("Karaoké : erreur inattendue pour %s:%s", job.source, job.source_id)
            _fail(job, f"Séparation impossible : {exc}")
        else:
            _jobs.pop(job.key, None)
            if job.quality == "hq":
                # Passe fine prête : les pistes rapides ne servent plus.
                _delete(deps.settings, job.source, job.source_id, "fast")
            elif job.priority == NOW and not job.cancelled:
                # Titre chanté : la passe fine suit, quand la file des
                # titres à chanter est vide. (File vidée pendant le calcul,
                # ou titre seulement « à venir » : pas de passe fine.)
                _ensure_job(job.source, job.source_id, "hq", REFINE)
                refine = _jobs.get((job.source, job.source_id, "hq"))
                if refine is not None:
                    refine.users |= job.users
        finally:
            _running = None


def _fail(job: Job, message: str) -> None:
    logger.info("Karaoké : échec (%s) pour %s:%s — %s", job.quality, job.source, job.source_id, message)
    job.status, job.error, job.failed_at = "failed", message, time.monotonic()


class _Preempted(Exception):
    pass


async def _process_job(deps, job: Job) -> None:
    settings = deps.settings
    if not engine_available():
        raise SeparationError("Séparation indisponible sur le serveur (numpy / onnxruntime absents).")
    audio = await _source_audio(deps, job.source, job.source_id)
    model = await ensure_model(settings, job.quality)
    if job.preempted:
        raise _Preempted
    settings.karaoke_dir.mkdir(parents=True, exist_ok=True)
    vocals = stem_path(settings, job.source, job.source_id, "vocals", job.quality)
    instrumental = stem_path(settings, job.source, job.source_id, "instrumental", job.quality)
    started = time.monotonic()

    def on_progress(fraction: float) -> None:
        job.progress = max(0.0, min(1.0, fraction))

    try:
        await run_separation(settings, audio, model, vocals, instrumental, on_progress, quality=job.quality)
    except SeparationError:
        if job.preempted:
            raise _Preempted from None
        raise
    logger.info(
        "Karaoké : %s:%s séparé (%s) en %.0f s", job.source, job.source_id, job.quality, time.monotonic() - started
    )
    prune(settings, keep=job.key[:2])


async def _source_audio(deps, source: str, source_id: str) -> Path:
    """Le fichier du titre, depuis le cache de lecture — téléchargé et
    vérifié au besoin, exactement comme pour l'écouter."""
    from fastapi import HTTPException

    from app.api.routers.stream import ensure_file

    try:
        path, _ = await ensure_file(deps, source, source_id, "best", "auto")
    except HTTPException as exc:
        raise SeparationError(str(exc.detail)) from exc
    return Path(path)


# -- Modèle -------------------------------------------------------------------

_model_lock: asyncio.Lock | None = None


def model_spec(quality: str = separation.DEFAULT_MODEL) -> separation.ModelSpec:
    return separation.MODELS[quality]


async def ensure_model(settings: Settings, quality: str = separation.DEFAULT_MODEL) -> Path:
    """Le modèle sur disque, téléchargé la première fois (~60 Mo, depuis les
    publications officielles d'UVR). Taille vérifiée : un téléchargement
    coupé n'est jamais pris pour un modèle valide."""
    global _model_lock
    spec = model_spec(quality)
    path = settings.models_dir / spec.file
    if path.is_file() and path.stat().st_size == spec.size:
        return path
    if _model_lock is None:
        _model_lock = asyncio.Lock()
    async with _model_lock:
        if path.is_file() and path.stat().st_size == spec.size:
            return path
        settings.models_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".part")
        url = separation.MODEL_URL.format(file=spec.file)
        logger.info("Karaoké : téléchargement du modèle %s", spec.file)
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=120.0), follow_redirects=True) as client:
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    with tmp.open("wb") as out:
                        async for chunk in response.aiter_bytes(1 << 20):
                            out.write(chunk)
        except (httpx.HTTPError, OSError) as exc:
            tmp.unlink(missing_ok=True)
            raise SeparationError(f"Modèle de séparation impossible à télécharger : {exc}") from exc
        if tmp.stat().st_size != spec.size:
            tmp.unlink(missing_ok=True)
            raise SeparationError("Modèle de séparation incomplet : nouvel essai plus tard.")
        tmp.replace(path)
        return path


# -- Calcul (sous-processus) --------------------------------------------------


async def run_separation(
    settings: Settings,
    audio: Path,
    model: Path,
    vocals: Path,
    instrumental: Path,
    on_progress: Callable[[float], None],
    quality: str = separation.DEFAULT_MODEL,
) -> None:
    """Lance `python -m app.services.separation` en priorité basse et suit
    sa progression. Remplacé par un faux dans les tests."""
    global _process
    command = [
        sys.executable, "-m", "app.services.separation", str(audio), str(vocals), str(instrumental),
        "--model", str(model), "--spec", quality, "--ffmpeg", settings.ffmpeg_path, "--threads", str(settings.karaoke_threads),
    ]
    # `nice -n 19` : le calcul ne prend que le temps processeur que l'API et
    # le bot laissent libre.
    if nice := shutil.which("nice"):
        command = [nice, "-n", "19", *command]
    env = {**os.environ, "OMP_NUM_THREADS": str(settings.karaoke_threads)}
    process = await asyncio.create_subprocess_exec(
        *command, cwd=str(BASE_DIR), env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _process = process
    errors: list[str] = []

    async def read_progress() -> None:
        assert process.stdout is not None
        async for raw in process.stdout:
            line = raw.decode(errors="replace").strip()
            if line.startswith("progress "):
                try:
                    on_progress(float(line.split()[1]))
                except ValueError:
                    pass

    async def read_errors() -> None:
        assert process.stderr is not None
        async for raw in process.stderr:
            errors.append(raw.decode(errors="replace").rstrip())
            del errors[:-20]  # les dernières lignes suffisent (trace d'erreur)

    try:
        await asyncio.wait_for(asyncio.gather(read_progress(), read_errors(), process.wait()), TIMEOUT)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise SeparationError("Séparation trop longue, abandonnée.") from None
    except asyncio.CancelledError:
        if process.returncode is None:
            process.kill()
        raise
    finally:
        _process = None
    if process.returncode != 0:
        for path in (vocals, instrumental):
            path.unlink(missing_ok=True)
        # Le calcul signale ses erreurs connues par une ligne « erreur … » ;
        # sinon (plantage, mémoire), la dernière ligne de sa trace.
        cause = next((line[7:] for line in reversed(errors) if line.startswith("erreur ")), None) \
            or next((line for line in reversed(errors) if line.strip()), "") or f"code {process.returncode}"
        logger.info("Karaoké : sous-processus en échec — %s", "\n".join(errors[-5:]))
        raise SeparationError(f"Séparation impossible : {cause[:200]}")


# -- La nuit : les titres les plus écoutés ---------------------------------------

NIGHT_START, NIGHT_END = 2, 7  # heures du serveur
NIGHT_TRACKS = 10


async def run_nightly(deps, now: Callable[[], time.struct_time] = time.localtime,
                      sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
    """Chaque nuit, prépare les titres les plus écoutés ces 30 derniers jours
    (tous comptes confondus) qui ne le sont pas encore en passe fine (passe
    fine directement : rien ne presse). Ils passent après
    tout titre demandé par l'app, et sont interrompus si quelqu'un écoute."""
    last_night = None
    while True:
        moment = now()
        if NIGHT_START <= moment.tm_hour < NIGHT_END and last_night != moment.tm_yday:
            last_night = moment.tm_yday
            try:
                await queue_top_tracks(deps)
            except Exception as exc:
                logger.info("Karaoké : préparation de nuit impossible — %s", exc)
        await sleep(15 * 60)


async def queue_top_tracks(deps, limit: int = NIGHT_TRACKS) -> int:
    if not engine_available():
        return 0
    from datetime import datetime, timedelta, timezone

    from app.services.stats import to_utc_iso

    since = to_utc_iso(datetime.now(timezone.utc) - timedelta(days=30))
    queued = 0
    for source, source_id in await deps.repo.plays_top_tracks(since, limit * 3):
        if queued >= limit:
            break
        # Déjà en passe fine, ou déjà en file : rien à faire. Pistes rapides
        # seulement : la nuit est le bon moment pour la passe fine.
        if ready_quality(deps.settings, source, source_id) == "hq" or any(
            key[:2] == (source, source_id) for key in _jobs
        ):
            continue
        request(deps, source, source_id, NIGHT)
        queued += 1
    if queued:
        logger.info("Karaoké : %d titre(s) les plus écoutés en file pour la nuit", queued)
    return queued


def start_nightly(deps) -> asyncio.Task:
    global _nightly
    _nightly = asyncio.create_task(run_nightly(deps))
    return _nightly

