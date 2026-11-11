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


def track_dict(row: dict, cover_url: str, extras: list[dict] | None = None) -> dict:
    """Le titre au format de l'app. `artist_source_id` reste celui de la fiche de
    l'artiste (Deezer…) ; `artist_source` dit de quelle source il vient, puisque
    `source` vaut ici « exclusive »."""
    return {
        "source": SOURCE,
        "source_id": row["id"],
        "title": row["title"],
        "artist": row["artist"],
        "album": row.get("album"),
        "year": row["year"],
        "duration_seconds": row["duration_seconds"],
        "cover_url": cover_url,
        "artist_source": row["artist_source"],
        "artist_source_id": row["artist_source_id"],
        "tag": tag_label(row["kind"]),
        "persona": row.get("persona"),
        "track_number": row.get("track_number"),
        "exclusive": True,
        "artists": [],
        **_quality_fields(row, extras),
    }


def _quality_fields(row: dict, extras: list[dict] | None) -> dict:
    versions = versions_of(row, extras)
    best = pick_version(versions, "best")
    return {"quality": best["label"], "lossless": bool(best.get("lossless")), "versions": len(versions)}


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
    """Durée, qualité (codec, lossless, débit, fréquence, bits) et pochette intégrée du fichier."""
    duration = None
    quality: dict = {"codec": None, "lossless": 0, "bitrate": None, "sample_rate": None, "bit_depth": None}
    try:
        audio = MutagenFile(path)
        if audio is not None and audio.info is not None and getattr(audio.info, "length", None):
            duration = round(audio.info.length)
    except Exception as exc:  # noqa: BLE001 — un fichier sans tags reste utilisable
        logger.info("Exclu : durée illisible (%s)", exc)
    # Même lecture que la musique locale : codec, lossless ou non, 24 bits / 96 kHz…
    try:
        card = local_library.read_file(path.parent, path)
        if card:
            quality = {k: card.get(k) for k in quality}
    except Exception as exc:  # noqa: BLE001
        logger.info("Exclu : qualité illisible (%s)", exc)
    cover = None
    try:
        found = local_library.cover(path)
        cover = found
    except Exception:  # noqa: BLE001
        cover = None
    return {"duration": duration, "cover": cover, "quality": quality}


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
              year: str | None, kind: str, persona: str | None = None, album: str | None = None,
              album_kind: str | None = None, track_number: int | None = None, release_order: int | None = None) -> dict:
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
            **info["quality"],
            "filename": f"{artist} - {title}{suffix}", "size": size,
            "chunks": json.dumps([c.to_json() for c in chunks]),
            "cover_chunks": cover_chunks, "cover_mime": cover_mime,
            "persona": persona or None, "album": album or None,
            "album_kind": album_kind if album_kind in ("album", "ep", "single") else None,
            "track_number": track_number, "release_order": release_order,
        }
        await repo.exclusive_add(row)
    except Exception:
        await storage.delete(chunks)
        raise
    return row


async def add_version(storage: DiscordStorage, repo, exclusive_id: str, path: Path, size: int, filename: str,
                      content_type: str | None) -> dict:
    """Ajoute une autre version (ex. FLAC) à un exclu existant."""
    suffix = audio_suffix(filename, content_type)
    info = await asyncio.to_thread(probe, path)
    chunks = await storage.store(_file_parts(path), f"exclu{suffix}")
    row = {
        "id": uuid.uuid4().hex[:12], "exclusive_id": exclusive_id, **info["quality"],
        "mime": AUDIO_TYPES.get(suffix, "application/octet-stream"), "filename": f"version{suffix}", "size": size,
        "chunks": json.dumps([c.to_json() for c in chunks]),
    }
    try:
        await repo.exclusive_version_add(row)
    except Exception:
        await storage.delete(chunks)
        raise
    return row


MAIN = "main"


def versions_of(row: dict, extras: list[dict] | None) -> list[dict]:
    """Le fichier d'origine puis les versions ajoutées, chacune avec son libellé de qualité
    (« FLAC 24 bits / 96 kHz », « MP3 320 kbps »)."""
    main = {**row, "version_id": MAIN}
    found = [main] + [{**e, "version_id": e["id"]} for e in (extras or [])]
    for v in found:
        v["label"] = local_library.quality_label({**v, "codec": v.get("codec") or Path(v["filename"]).suffix.lstrip(".").upper() or "Audio"})
    return found


def _rank(v: dict) -> tuple:
    return (int(bool(v.get("lossless"))), (v.get("bit_depth") or 0) * (v.get("sample_rate") or 0), v.get("bitrate") or 0, v["size"])


def pick_version(versions: list[dict], quality: str, wanted: str | None = None) -> dict:
    """La version à lire : celle demandée, sinon selon la qualité choisie dans les réglages
    (lossless : la meilleure sans perte, à défaut la meilleure ; standard : la plus légère)."""
    if wanted:
        for v in versions:
            if v["version_id"] == wanted:
                return v
    if quality == "standard":
        return min(versions, key=lambda v: (_rank(v)[0], v["size"]))
    return max(versions, key=_rank)


def chunks_of(raw: str | None) -> list[Chunk]:
    return [Chunk.from_json(c) for c in json.loads(raw)] if raw else []


async def materialize(storage: DiscordStorage, cache_dir: Path, row: dict, version: dict | None = None) -> Path:
    """Fichier complet sur disque : rassemblé depuis Discord à la première lecture.
    `version` : une des versions de `versions_of` (sinon le fichier d'origine)."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    source = version or row
    extra = version is not None and version.get("version_id") != MAIN
    suffix = Path(source["filename"]).suffix
    name = f"{row['id']}_{version['version_id']}" if extra else row["id"]
    target = cache_dir / f"{name}{suffix}"
    if target.is_file():
        target.touch()
        return target
    lock = _locks.setdefault(name, asyncio.Lock())
    async with lock:
        if target.is_file():
            return target
        partial = target.with_suffix(target.suffix + ".part")
        try:
            with partial.open("wb") as out:
                for chunk in chunks_of(source["chunks"]):
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
    extras = (await repo.exclusive_versions(row["id"])).get(row["id"], [])
    await repo.exclusive_delete(row["id"])
    await storage.delete(chunks_of(row["chunks"]) + chunks_of(row.get("cover_chunks"))
                         + [c for e in extras for c in chunks_of(e["chunks"])])
    for leftover in cache_dir.glob(f"{row['id']}*"):
        leftover.unlink(missing_ok=True)
    _locks.pop(row["id"], None)


__all__ = ["StorageError"]


# -- Discographie d'un artiste à identités -------------------------------------

def _fold(text: str | None) -> str:
    import unicodedata

    decomposed = unicodedata.normalize("NFKD", (text or "").casefold())
    return "".join(ch for ch in decomposed if ch.isalnum() and not unicodedata.combining(ch))


def build_releases(personas: list[str], tracks: list[dict], rows: list[dict]) -> list[dict]:
    """Les sorties (albums et singles) d'un artiste à identités, dans l'ordre de la page :
    identité par identité (dans l'ordre donné), puis dans l'ordre des dossiers, chaque piste
    à sa place. Un titre n'apparaît qu'une fois par sortie. La pochette d'une sortie est la
    première pochette réelle de ses pistes (sinon la vignette neutre de la première)."""
    order = {_fold(name): i for i, name in enumerate(personas)}
    has_cover = {r["id"]: bool(r.get("cover_chunks")) for r in rows}
    by_id = {r["id"]: r for r in rows}
    groups: dict[tuple[str, str], list[dict]] = {}
    for track in tracks:
        row = by_id.get(track["source_id"])
        persona = (row or {}).get("persona")
        if not row or not persona or not row.get("album"):
            continue  # un exclu sans identité ni album n'appartient à aucune sortie
        groups.setdefault((persona, row["album"]), []).append(track)
    releases = []
    for (persona, album), items in groups.items():
        items.sort(key=lambda t: (t.get("track_number") or 10_000, _fold(t["title"])))
        seen: set[str] = set()
        unique = []
        for t in items:
            key = _fold(t["title"])
            if key in seen:
                continue
            seen.add(key)
            unique.append(t)
        first = by_id[unique[0]["source_id"]]
        cover = next((t["cover_url"] for t in unique if has_cover.get(t["source_id"])), unique[0]["cover_url"])
        kind = first.get("album_kind") or ("single" if len(unique) == 1 else "album")
        releases.append({
            "persona": persona, "album": album, "kind": kind, "order": first.get("release_order") or 0,
            "year": next((t["year"] for t in unique if t.get("year")), None),
            "track_count": len(unique), "duration_seconds": sum(t.get("duration_seconds") or 0 for t in unique),
            "cover_url": cover, "tracks": unique,
        })
    releases.sort(key=lambda r: (order.get(_fold(r["persona"]), 999), r["order"], _fold(r["album"])))
    return releases
