"""Exclus : titres inédits que l'admin ajoute lui-même.

Le fichier audio est découpé et stocké sur Discord (services/discord_storage.py,
même principe que Drivecord). Pour le lire, on rassemble les morceaux une
fois dans un cache disque (`data/exclusives/`), puis on le sert comme n'importe
quel fichier local — d'où le support des Range (avance rapide) sans effort.
"""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import os
import tempfile
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

from mutagen import File as MutagenFile

from app.services import local_library
from app.services.discord_storage import CHUNK_SIZE, Chunk, DiscordStorage, StorageError

logger = logging.getLogger(__name__)

SOURCE = "exclusive"
KINDS = {"exclu": "Exclu", "inedit": "Inédit"}
AUDIO_TYPES = {suffix: media for suffix, media in local_library.MEDIA_TYPES.items()}
MAX_AUDIO_BYTES = 300 * 1024 * 1024
MAX_COVER_BYTES = 8 * 1024 * 1024
_locks: dict[str, asyncio.Lock] = {}


def tag_label(kind: str) -> str:
    return KINDS.get(kind, KINDS["exclu"])


def track_dict(row: dict, cover_url: str) -> dict:
    """Le titre au format de l'app. `artist_source_id` reste celui de la fiche de
    l'artiste (Deezer…) ; `artist_source` dit de quelle source il vient, puisque
    `source` vaut ici « exclusive »."""
    return {
        "source": SOURCE,
        "source_id": row["id"],
        "title": row["title"],
        "artist": row["artist"],
        "album": None,
        "year": row["year"],
        "duration_seconds": row["duration_seconds"],
        "cover_url": cover_url,
        "artist_source": row["artist_source"],
        "artist_source_id": row["artist_source_id"],
        "tag": tag_label(row["kind"]),
        "exclusive": True,
        "artists": [],
    }


def clean_year(value: str | None) -> str | None:
    text = (value or "").strip()
    return text if len(text) == 4 and text.isdigit() else None


def audio_suffix(filename: str, content_type: str | None) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix in AUDIO_TYPES:
        return suffix
    guess = mimetypes.guess_extension((content_type or "").split(";")[0].strip()) or ""
    return guess if guess in AUDIO_TYPES else ""


async def spool(stream: AsyncIterator[bytes], suffix: str, limit: int) -> tuple[Path, int]:
    """Copie le corps de la requête dans un fichier temporaire (pas en mémoire)."""
    fd, name = tempfile.mkstemp(suffix=suffix, prefix="sona-exclu-")
    size = 0
    try:
        with os.fdopen(fd, "wb") as out:
            async for part in stream:
                size += len(part)
                if size > limit:
                    raise ValueError("Fichier trop gros.")
                await asyncio.to_thread(out.write, part)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise
    return Path(name), size


def probe(path: Path) -> dict:
    """Durée et pochette intégrée du fichier."""
    duration = None
    try:
        audio = MutagenFile(path)
        if audio is not None and audio.info is not None and getattr(audio.info, "length", None):
            duration = round(audio.info.length)
    except Exception as exc:  # noqa: BLE001 — un fichier sans tags reste utilisable
        logger.info("Exclu : durée illisible (%s)", exc)
    cover = None
    try:
        found = local_library.cover(path)
        cover = found
    except Exception:  # noqa: BLE001
        cover = None
    return {"duration": duration, "cover": cover}


async def _file_parts(path: Path) -> AsyncIterator[bytes]:
    with path.open("rb") as handle:
        while True:
            part = await asyncio.to_thread(handle.read, CHUNK_SIZE)
            if not part:
                return
            yield part


async def _bytes_parts(data: bytes) -> AsyncIterator[bytes]:
    for start in range(0, len(data), CHUNK_SIZE):
        yield data[start:start + CHUNK_SIZE]


async def store_cover(storage: DiscordStorage, data: bytes, mime: str) -> tuple[str, str]:
    chunks = await storage.store(_bytes_parts(data), "cover")
    return json.dumps([c.to_json() for c in chunks]), mime


async def add(storage: DiscordStorage, repo, path: Path, size: int, filename: str, content_type: str | None,
              *, title: str, artist: str, artist_source: str | None, artist_source_id: str | None,
              year: str | None, kind: str) -> dict:
    """Range un fichier déjà reçu sur disque : Discord, puis la base."""
    suffix = audio_suffix(filename, content_type)
    info = await asyncio.to_thread(probe, path)
    chunks = await storage.store(_file_parts(path), f"exclu{suffix}")
    cover_chunks = cover_mime = None
    try:
        if info["cover"]:
            cover_chunks, cover_mime = await store_cover(storage, info["cover"][0], info["cover"][1])
        row = {
            "id": uuid.uuid4().hex[:16], "title": title, "artist": artist,
            "artist_source": artist_source if artist_source_id else None, "artist_source_id": artist_source_id or None,
            "year": clean_year(year), "kind": kind if kind in KINDS else "exclu",
            "duration_seconds": info["duration"], "mime": AUDIO_TYPES.get(suffix, "application/octet-stream"),
            "filename": f"{artist} - {title}{suffix}", "size": size,
            "chunks": json.dumps([c.to_json() for c in chunks]),
            "cover_chunks": cover_chunks, "cover_mime": cover_mime,
        }
        await repo.exclusive_add(row)
    except Exception:
        await storage.delete(chunks)
        raise
    return row


def chunks_of(raw: str | None) -> list[Chunk]:
    return [Chunk.from_json(c) for c in json.loads(raw)] if raw else []


async def materialize(storage: DiscordStorage, cache_dir: Path, row: dict) -> Path:
    """Fichier complet sur disque : rassemblé depuis Discord à la première lecture."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(row["filename"]).suffix
    target = cache_dir / f"{row['id']}{suffix}"
    if target.is_file():
        target.touch()
        return target
    lock = _locks.setdefault(row["id"], asyncio.Lock())
    async with lock:
        if target.is_file():
            return target
        partial = target.with_suffix(target.suffix + ".part")
        try:
            with partial.open("wb") as out:
                for chunk in chunks_of(row["chunks"]):
                    await asyncio.to_thread(out.write, await storage.read(chunk))
            partial.replace(target)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
    return target


async def read_cover(storage: DiscordStorage, row: dict) -> tuple[bytes, str] | None:
    chunks = chunks_of(row.get("cover_chunks"))
    if not chunks:
        return None
    data = b"".join([await storage.read(c) for c in chunks])
    return data, row.get("cover_mime") or "image/jpeg"


async def remove(storage: DiscordStorage, repo, cache_dir: Path, row: dict) -> None:
    await repo.exclusive_delete(row["id"])
    await storage.delete(chunks_of(row["chunks"]) + chunks_of(row.get("cover_chunks")))
    for leftover in cache_dir.glob(f"{row['id']}*"):
        leftover.unlink(missing_ok=True)
    _locks.pop(row["id"], None)


__all__ = ["StorageError"]
