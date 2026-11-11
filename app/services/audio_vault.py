"""Coffre audio Drivecord : le cache de second niveau des morceaux préparés.

Le cache du serveur (`data/stream_cache`, plafonné) efface les titres écoutés
il y a le plus longtemps. Redemandé, un titre effacé repassait par la recherche
de sa source et un nouveau téléchargement : plusieurs secondes, et dépendant
de YouTube. Avec le coffre, chaque titre préparé est aussi envoyé (découpé en
morceaux, comme dans Drivecord) dans un salon Discord par webhook, et
retrouvé là quand le disque ne l'a plus : quelques centaines de millisecondes,
et sans YouTube.

Tout est « au mieux » : le coffre n'est jamais obligatoire. Désactivé, en panne,
ou sans copie, on retombe sur le téléchargement habituel.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from collections.abc import AsyncIterator, Callable
from pathlib import Path

from app.services.discord_storage import CHUNK_SIZE, Chunk, StorageError

logger = logging.getLogger(__name__)

# Au-delà, ce n'est plus un morceau (une émission, un mix de plusieurs heures) : on ne le garde pas.
MAX_FILE_BYTES = 80 * 1024 * 1024
# Temps laissé à Discord pour rendre un morceau avant de retomber sur le téléchargement :
# la lecture d'un titre ne doit pas attendre les réessais de la couche de stockage.
RESTORE_TIMEOUT = 25.0
# Copie introuvable (message supprimé du salon) deux fois de suite : on l'oublie.
MAX_STRIKES = 2

# Rattrapage des titres déjà présents sur le disque : un petit lot, puis une pause
# (le serveur sert l'app et Discord limite le débit d'un webhook) ; une fois à
# jour, on ne revérifie qu'une fois par heure.
BACKFILL_DELAY = 120.0
BACKFILL_BATCH = 4
BACKFILL_PAUSE = 60.0
BACKFILL_IDLE = 3600.0

_upload_slot = asyncio.Semaphore(1)
# Titres du disque qu'on ne peut pas mettre de côté (fichier disparu, vide, trop gros) :
# inutile de les reproposer à chaque lot.
_skipped: set[tuple[str, str, str, str]] = set()
_tasks: set[asyncio.Task] = set()
_pending: set[tuple[str, str, str, str]] = set()
_strikes: dict[tuple[str, str, str, str], int] = defaultdict(int)


def enabled(deps) -> bool:
    storage = getattr(deps, "vault_storage", None)
    return bool(storage is not None and storage.enabled and deps.settings.audio_vault)


async def has(deps, source: str, source_id: str, fmt: str, quality: str) -> bool:
    return enabled(deps) and await deps.repo.vault_get(source, source_id, fmt, quality) is not None


async def _parts(path: Path) -> AsyncIterator[bytes]:
    with path.open("rb") as handle:
        while True:
            part = await asyncio.to_thread(handle.read, CHUNK_SIZE)
            if not part:
                return
            yield part


async def upload(deps, source: str, source_id: str, fmt: str, quality: str, path: Path, content_type: str) -> bool:
    """Envoie le fichier dans le salon et note où il est. False : rien envoyé
    (déjà là, vide, ou trop gros)."""
    if await deps.repo.vault_get(source, source_id, fmt, quality) is not None:
        return False
    try:
        size = (await asyncio.to_thread(path.stat)).st_size
    except OSError:
        return False
    if size <= 0 or size > MAX_FILE_BYTES:
        return False
    chunks = await deps.vault_storage.store(_parts(path), path.name)
    await deps.repo.vault_set(
        source, source_id, fmt, quality, path.name, size,
        json.dumps([chunk.to_json() for chunk in chunks]), content_type,
    )
    logger.info("Coffre Drivecord : %s:%s mis de côté (%d Ko, %d morceau(x))", source, source_id, size // 1024, len(chunks))
    return True


def spawn_upload(deps, source: str, source_id: str, fmt: str, quality: str, path: Path, content_type: str) -> None:
    """Envoi en arrière-plan, un à la fois : la lecture n'attend jamais le coffre."""
    if not enabled(deps):
        return
    key = (source, source_id, fmt, quality)
    if key in _pending:
        return
    _pending.add(key)

    async def run() -> None:
        try:
            async with _upload_slot:
                await upload(deps, source, source_id, fmt, quality, path, content_type)
        except Exception as exc:  # noqa: BLE001 — le coffre ne doit jamais faire échouer une lecture
            logger.warning("Coffre Drivecord : envoi de %s:%s impossible : %s", source, source_id, exc)
        finally:
            _pending.discard(key)

    task = asyncio.create_task(run())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def backfill_once(deps, batch: int = BACKFILL_BATCH) -> int:
    """Envoie au plus `batch` titres du cache disque qui ne sont pas encore dans le
    coffre (les plus récents d'abord). Renvoie le nombre de titres envoyés."""
    if not enabled(deps) or not deps.settings.audio_vault_backfill:
        return 0
    rows = await deps.repo.vault_missing(batch + len(_skipped))
    sent = 0
    for row in rows:
        if sent >= batch:
            break
        key = (row["source"], row["source_id"], row["format"], row["quality"])
        if key in _skipped or key in _pending:
            continue
        path = Path(row["file_path"])
        _pending.add(key)
        try:
            async with _upload_slot:
                if await upload(deps, *key, path, row["content_type"]):
                    sent += 1
                else:
                    _skipped.add(key)
        except Exception as exc:  # noqa: BLE001 — Discord en panne : on réessaiera au prochain lot
            logger.warning("Coffre Drivecord : rattrapage de %s:%s impossible : %s", key[0], key[1], exc)
            break
        finally:
            _pending.discard(key)
    if sent:
        logger.info("Coffre Drivecord : rattrapage, %d titre(s) de plus mis de côté", sent)
    return sent


async def backfill_loop(deps) -> None:
    """Tâche de fond : met peu à peu de côté les titres déjà présents sur le disque."""
    await asyncio.sleep(BACKFILL_DELAY)
    while True:
        try:
            sent = await backfill_once(deps)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — une tâche de fond ne doit pas s'arrêter pour une erreur
            logger.exception("Coffre Drivecord : rattrapage interrompu")
            sent = 0
        await asyncio.sleep(BACKFILL_PAUSE if sent else BACKFILL_IDLE)


async def restore(
    deps, source: str, source_id: str, fmt: str, quality: str, make_path: Callable[[str], Path],
) -> tuple[Path, str] | None:
    """Rassemble le titre depuis Drivecord sur le disque. `make_path(suffixe)`
    donne où l'écrire. None : pas de copie, ou elle n'a pas pu être lue (le
    téléchargement habituel prend alors le relais)."""
    if not enabled(deps):
        return None
    row = await deps.repo.vault_get(source, source_id, fmt, quality)
    if row is None:
        return None
    key = (source, source_id, fmt, quality)
    target = make_path(Path(row["filename"]).suffix)
    partial = target.with_suffix(target.suffix + ".part")
    try:
        chunks = [Chunk.from_json(c) for c in json.loads(row["chunks"])]
        target.parent.mkdir(parents=True, exist_ok=True)

        async def gather() -> None:
            with partial.open("wb") as out:
                for chunk in chunks:
                    await asyncio.to_thread(out.write, await deps.vault_storage.read(chunk))

        await asyncio.wait_for(gather(), RESTORE_TIMEOUT)
        if partial.stat().st_size != row["size"]:
            raise StorageError("taille différente de l'original")
        partial.replace(target)
    except (StorageError, OSError, ValueError, asyncio.TimeoutError) as exc:
        partial.unlink(missing_ok=True)
        _strikes[key] += 1
        logger.info("Coffre Drivecord : %s:%s illisible (%s), essai %d", source, source_id, exc or type(exc).__name__, _strikes[key])
        if _strikes[key] >= MAX_STRIKES:
            _strikes.pop(key, None)
            await forget(deps, source, source_id)
        return None
    _strikes.pop(key, None)
    logger.info("Coffre Drivecord : %s:%s retrouvé, sans passer par YouTube", source, source_id)
    return target, row["content_type"]


async def forget(deps, source: str, source_id: str) -> None:
    """Oublie les copies d'un titre (mauvaise version signalée, copie perdue) et efface leurs messages."""
    rows = await deps.repo.vault_delete(source, source_id)
    storage = getattr(deps, "vault_storage", None)
    if storage is None or not storage.enabled:
        return
    for row in rows:
        try:
            await storage.delete([Chunk.from_json(c) for c in json.loads(row["chunks"])])
        except Exception as exc:  # noqa: BLE001 — au mieux
            logger.info("Coffre Drivecord : effacement des messages de %s:%s impossible : %s", source, source_id, exc)
