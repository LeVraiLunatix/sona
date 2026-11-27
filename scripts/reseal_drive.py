"""Chiffre les fichiers rangés sur Discord avant le chiffrement.

    python scripts/reseal_drive.py            # compte seulement, ne change rien
    python scripts/reseal_drive.py --apply    # renvoie chiffré, puis efface les messages en clair

Pour chaque fichier : nouvel envoi chiffré, relecture comparée à l'original, base mise à jour, et
seulement ensuite effacement des anciens messages. Relançable : ce qui est déjà chiffré est passé.
La base est copiée avant (`<base>.avant-chiffrement`).
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import load_settings  # noqa: E402
from app.services.discord_storage import MAGIC, Chunk, DiscordStorage, StorageError  # noqa: E402

# (table, colonne, le coffre ou « Mes fichiers » plutôt que les exclus)
COLUMNS = (
    ("exclusives", "chunks", False),
    ("exclusives", "cover_chunks", False),
    ("exclusive_versions", "chunks", False),
    ("audio_vault", "chunks", True),
    ("uploads", "chunks", True),
)


async def reseal(db: sqlite3.Connection, exclusives: DiscordStorage, vault: DiscordStorage, apply: bool) -> dict:
    done = {"clear": 0, "sealed": 0, "failed": 0, "left_on_discord": []}
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table, column, in_vault in COLUMNS:
        if table not in tables:
            continue
        storage = vault if in_vault else exclusives
        rows = db.execute(f"SELECT rowid, {column} FROM {table} WHERE {column} IS NOT NULL").fetchall()
        for rowid, raw in rows:
            old = [Chunk.from_json(c) for c in json.loads(raw)]
            new: list[Chunk] = []
            try:
                stored = [await storage.read_raw(c) for c in old]
                if all(data.startswith(MAGIC) for data in stored):
                    done["sealed"] += 1
                    continue
                if not apply:
                    done["clear"] += 1
                    continue
                plain = [await storage.read(c) for c in old]
                for chunk, data in zip(old, plain):
                    new.append(await storage.put_chunk(data, "morceau", chunk.index))
                    if await storage.read(new[-1]) != data:
                        raise StorageError("la relecture ne redonne pas l'original")
                changed = db.execute(
                    f"UPDATE {table} SET {column}=? WHERE rowid=? AND {column}=?",
                    (json.dumps([c.to_json() for c in new]), rowid, raw),
                ).rowcount
                db.commit()
                if not changed:  # remplacé ou supprimé pendant ce temps
                    raise StorageError("la ligne a changé pendant le renvoi")
            except StorageError as exc:
                done["failed"] += 1
                done["left_on_discord"] += await storage.delete(new)
                print(f"{table}.{column} ligne {rowid} : laissé tel quel ({exc})")
                continue
            done["clear"] += 1
            done["left_on_discord"] += await storage.delete(old)
            print(f"{table}.{column} ligne {rowid} : chiffré")
    return done


async def main(apply: bool) -> int:
    settings = load_settings()
    if settings.storage_key is None or not settings.exclusives_webhook and not settings.audio_vault_webhook:
        print("Il faut STORAGE_KEY et le webhook de stockage dans le .env.")
        return 1
    path = Path(settings.database_path)
    if not path.is_file():
        print(f"Base introuvable : {path}")
        return 1
    db = sqlite3.connect(path, timeout=30)
    if apply:
        copy = sqlite3.connect(f"{path}.avant-chiffrement")
        db.backup(copy)
        copy.close()
    exclusives = DiscordStorage(settings.exclusives_webhook, key=settings.storage_key)
    vault = DiscordStorage(settings.audio_vault_webhook or settings.exclusives_webhook, key=settings.storage_key)
    try:
        done = await reseal(db, exclusives, vault, apply)
    finally:
        await exclusives.aclose()
        await vault.aclose()
        db.close()
    print(f"{path} : {done['clear']} fichier(s) {'chiffré(s)' if apply else 'en clair'}, "
          f"{done['sealed']} déjà chiffré(s), {done['failed']} en échec.")
    if done["left_on_discord"]:
        print("Messages à effacer à la main dans le salon :", ", ".join(done["left_on_discord"]))
    return 1 if done["failed"] or done["left_on_discord"] else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main("--apply" in sys.argv[1:])))
