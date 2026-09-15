"""Sauvegarde quotidienne de la base.

La base porte les accès, la bibliothèque, l'historique et le cache des
`file_id` Telegram : rien ne la sauvegardait.
"""

import asyncio
import logging
import os
import sqlite3
import stat
import time

import pytest

from app.services import backup

DAY = 24 * 3600


def make_database(path, rows=("Au DD", "Deux frères")):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE morceaux (titre TEXT)")
    conn.executemany("INSERT INTO morceaux VALUES (?)", [(r,) for r in rows])
    conn.commit()
    conn.close()
    return path


def titles(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return [row[0] for row in conn.execute("SELECT titre FROM morceaux ORDER BY titre")]
    finally:
        conn.close()


def fake_backups(backup_dir, count, newest_age_seconds=0.0):
    """Crée `count` sauvegardes factices espacées d'un jour, de la plus
    ancienne à la plus récente — cette dernière datée d'il y a
    `newest_age_seconds`."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    now = time.time()
    created = []
    for i in range(count):
        age = newest_age_seconds + (count - 1 - i) * DAY
        path = backup_dir / f"sona-{i:08d}-120000.db"
        path.write_bytes(b"")
        os.utime(path, (now - age, now - age))
        created.append(path)
    return created


def test_a_backup_is_a_readable_copy_of_the_base(tmp_path):
    db = make_database(tmp_path / "sona.db")
    destination = backup.create_backup(db, tmp_path / "backups")

    assert destination is not None
    assert titles(destination) == ["Au DD", "Deux frères"]


def test_a_backup_is_only_readable_by_sona(tmp_path):
    """Une sauvegarde contient tout ce que contient la base : accès compris."""
    db = make_database(tmp_path / "sona.db")
    destination = backup.create_backup(db, tmp_path / "backups")
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600


def test_writes_while_the_bot_runs_do_not_truncate_the_copy(tmp_path):
    """L'API `backup` de sqlite3 sait copier une base ouverte : un `cp` au
    même moment donnerait un fichier tronqué."""
    db = make_database(tmp_path / "sona.db")
    ouverte = sqlite3.connect(db)
    ouverte.execute("INSERT INTO morceaux VALUES ('Blanka')")
    ouverte.commit()
    try:
        destination = backup.create_backup(db, tmp_path / "backups")
    finally:
        ouverte.close()
    assert titles(destination) == ["Au DD", "Blanka", "Deux frères"]


def test_only_the_seven_most_recent_are_kept(tmp_path):
    backups = tmp_path / "backups"
    anciennes = fake_backups(backups, count=9)
    db = make_database(tmp_path / "sona.db")

    nouvelle = backup.create_backup(db, backups)

    restantes = backup.existing_backups(backups)
    assert len(restantes) == backup.KEEP
    assert nouvelle in restantes
    # Les plus anciennes partent en premier.
    assert anciennes[0] not in restantes and anciennes[1] not in restantes
    assert anciennes[-1] in restantes


def test_a_failed_backup_is_logged_and_never_raises(tmp_path, caplog):
    """Disque plein, dossier en lecture seule : un incident à signaler, pas de
    quoi arrêter le bot."""
    caplog.set_level(logging.WARNING, logger=backup.__name__)
    # Un dossier à la place du fichier de base : sqlite ne peut pas l'ouvrir.
    (tmp_path / "sona.db").mkdir()

    assert backup.create_backup(tmp_path / "sona.db", tmp_path / "backups") is None
    assert "Sauvegarde de la base impossible" in caplog.text


def test_each_backup_is_logged(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger=backup.__name__)
    db = make_database(tmp_path / "sona.db")
    backup.create_backup(db, tmp_path / "backups")
    assert "Base sauvegardée" in caplog.text


def test_two_backups_in_the_same_second_do_not_overwrite_each_other(tmp_path):
    db = make_database(tmp_path / "sona.db")
    backups = tmp_path / "backups"
    first = backup.create_backup(db, backups)
    second = backup.create_backup(db, backups)
    assert first != second
    assert len(backup.existing_backups(backups)) == 2


# -- Cadence ---------------------------------------------------------


def test_the_first_backup_does_not_wait(tmp_path):
    assert backup.seconds_until_due(tmp_path / "backups", DAY, now=time.time()) == 0


def test_a_backup_older_than_a_day_is_due_at_once(tmp_path):
    """Un bot resté éteint une semaine doit sauvegarder au démarrage."""
    backups = tmp_path / "backups"
    fake_backups(backups, count=1, newest_age_seconds=8 * DAY)
    assert backup.seconds_until_due(backups, DAY, now=time.time()) == 0


def test_a_recent_backup_pushes_the_next_one_to_tomorrow(tmp_path):
    backups = tmp_path / "backups"
    fake_backups(backups, count=1, newest_age_seconds=2 * 3600)
    delay = backup.seconds_until_due(backups, DAY, now=time.time())
    assert 21 * 3600 < delay <= 22 * 3600


def test_the_loop_saves_at_startup_then_waits(tmp_path):
    db = make_database(tmp_path / "sona.db")
    backups = tmp_path / "backups"

    async def scenario():
        # Intervalle d'un jour : la boucle ne doit sauvegarder qu'une fois,
        # tout de suite, puis attendre.
        task = asyncio.create_task(backup.run_backups(db, backups, interval=DAY))
        for _ in range(200):
            await asyncio.sleep(0.005)
            if backup.existing_backups(backups):
                break
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    faites = backup.existing_backups(backups)
    assert len(faites) == 1
    assert titles(faites[0]) == ["Au DD", "Deux frères"]


def test_the_loop_waits_when_a_backup_is_recent(tmp_path):
    db = make_database(tmp_path / "sona.db")
    backups = tmp_path / "backups"
    fake_backups(backups, count=1, newest_age_seconds=60)

    async def scenario():
        task = asyncio.create_task(backup.run_backups(db, backups, interval=DAY))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert len(backup.existing_backups(backups)) == 1


def test_the_backup_directory_is_configurable_and_ignored_by_git():
    from pathlib import Path

    gitignore = (Path(__file__).resolve().parent.parent / ".gitignore").read_text(encoding="utf-8")
    assert "data/backups/" in gitignore
    example = (Path(__file__).resolve().parent.parent / ".env.example").read_text(encoding="utf-8")
    assert "BACKUP_DIR" in example
