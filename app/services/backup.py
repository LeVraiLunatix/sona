"""Sauvegarde quotidienne de la base.

`data/sona.db` contient les accès, la bibliothèque, l'historique et le cache
des `file_id` Telegram : la perdre, c'est refaire toutes les invitations et
retélécharger tous les morceaux déjà envoyés. Rien ne la sauvegardait.

La copie passe par l'API `backup` de sqlite3, qui sait copier une base
ouverte : un simple `cp` pendant une écriture donnerait un fichier tronqué.
"""

from __future__ import annotations

import asyncio
import gzip
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Une sauvegarde par jour : au pire, on perd les écoutes de la journée.
INTERVAL_SECONDS = 24 * 60 * 60
# Une semaine d'historique : de quoi remonter avant une bêtise repérée le
# lendemain, sans laisser grossir le disque du VPS indéfiniment.
KEEP = 7
_PREFIX = "sona-"
_SUFFIX = ".db"


def _backup_name(moment: datetime) -> str:
    return f"{_PREFIX}{moment.strftime('%Y%m%d-%H%M%S')}{_SUFFIX}"


def existing_backups(backup_dir: Path) -> list[Path]:
    """Sauvegardes présentes, de la plus ancienne à la plus récente."""
    if not backup_dir.is_dir():
        return []
    files = [p for p in backup_dir.glob(f"{_PREFIX}*{_SUFFIX}") if p.is_file()]
    return sorted(files, key=lambda p: p.stat().st_mtime)


def seconds_until_due(backup_dir: Path, interval: float, now: float) -> float:
    """Temps à attendre avant la prochaine sauvegarde.

    0 quand il n'y en a aucune, ou que la dernière date de plus de `interval` :
    au démarrage, un bot resté éteint une semaine doit sauvegarder tout de
    suite, pas dans 24 h.
    """
    backups = existing_backups(backup_dir)
    if not backups:
        return 0.0
    return max(0.0, backups[-1].stat().st_mtime + interval - now)


def _copy_database(db_path: Path, destination: Path) -> None:
    source = sqlite3.connect(db_path)
    try:
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()


def prune(backup_dir: Path, keep: int = KEEP) -> list[Path]:
    """Supprime les sauvegardes les plus anciennes. Retourne celles effacées."""
    backups = existing_backups(backup_dir)
    removed = []
    for path in backups[: max(0, len(backups) - keep)]:
        try:
            path.unlink()
            removed.append(path)
        except OSError as exc:
            logger.warning("Ancienne sauvegarde %s non supprimée : %s", path.name, exc)
    return removed


def create_backup(db_path: Path, backup_dir: Path) -> Path | None:
    """Copie la base dans `backup_dir` et fait le ménage. None si ça échoue.

    Ne lève jamais : une sauvegarde ratée (disque plein, dossier en lecture
    seule) est un incident à signaler dans les logs, pas de quoi arrêter le
    bot.
    """
    try:
        # 0700 : les sauvegardes contiennent tout ce que contient la base.
        backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        destination = backup_dir / _backup_name(datetime.now(timezone.utc))
        # Deux sauvegardes dans la même seconde (démarrages rapprochés) ne
        # doivent pas s'écraser l'une l'autre.
        index = 1
        while destination.exists():
            destination = destination.with_name(f"{destination.stem}-{index}{_SUFFIX}")
            index += 1
        _copy_database(db_path, destination)
        os.chmod(destination, 0o600)
    except Exception as exc:
        logger.warning("Sauvegarde de la base impossible : %s", exc)
        return None

    removed = prune(backup_dir)
    logger.info(
        "Base sauvegardée dans %s (%s Ko)%s",
        destination,
        destination.stat().st_size // 1024,
        f", {len(removed)} ancienne(s) supprimée(s)" if removed else "",
    )
    return destination


# Copie hors du serveur : URL d'écriture (« pre-authenticated request ») d'un
# bucket Oracle Object Storage, finissant par « /o/ » (voir
# docs/MIGRATION_ORACLE.md). Si le serveur meurt, les données survivent.
UPLOAD_URL_ENV = "BACKUP_UPLOAD_URL"


def upload_backup(path: Path, url: str | None = None, client=None) -> bool:
    """Envoie la sauvegarde (compressée) vers le stockage distant. Ne lève
    jamais : un envoi raté est signalé dans les logs, la copie locale reste."""
    url = (url if url is not None else os.getenv(UPLOAD_URL_ENV, "")).strip()
    if not url:
        return False
    import httpx

    target = url.rstrip("/") + "/" + path.name + ".gz"
    try:
        body = gzip.compress(path.read_bytes())
        http = client or httpx.Client(timeout=120)
        try:
            response = http.put(target, content=body, headers={"Content-Type": "application/gzip"})
        finally:
            if client is None:
                http.close()
        response.raise_for_status()
    except Exception as exc:
        logger.warning("Envoi de la sauvegarde hors du serveur impossible : %s", exc)
        return False
    logger.info("Sauvegarde envoyée hors du serveur (%s Ko)", len(body) // 1024)
    return True


async def run_backups(db_path: Path, backup_dir: Path, interval: float = INTERVAL_SECONDS) -> None:
    """Boucle de sauvegarde, à lancer en tâche de fond au démarrage.

    Sauvegarde dès maintenant si la dernière date de plus de `interval`, puis
    une fois par `interval`. Une sauvegarde ratée n'interrompt pas la boucle :
    la suivante aura lieu à l'heure prévue — sans quoi un dossier
    inaccessible ferait tourner la boucle en continu.
    """
    while True:
        delay = seconds_until_due(backup_dir, interval, time.time())
        if delay > 0:
            await asyncio.sleep(delay)
            continue
        created = await asyncio.to_thread(create_backup, db_path, backup_dir)
        if created is not None:
            await asyncio.to_thread(upload_backup, created)
        await asyncio.sleep(interval)
