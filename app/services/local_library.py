"""Musique locale : le vrai lossless.

YouTube et SoundCloud ne fournissent jamais de lossless. Ce service indexe un
dossier de fichiers que tu possèdes (FLAC, ALAC, WAV, AIFF, WavPack…, mais
aussi MP3/AAC/Opus/OGG) et les sert tels quels : aucun réencodage, donc aucune
perte. Les tags sont lus avec mutagen ; la pochette intégrée (ou `cover.jpg`
à côté du fichier) est servie à part.

Quand le réglage de qualité est « Lossless », un titre demandé depuis une
autre source est remplacé par ton fichier s'il existe (ISRC, sinon
« artiste titre » normalisé).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import unicodedata
from pathlib import Path

from mutagen import File as MutagenFile
from mutagen.flac import FLAC, Picture
from mutagen.id3 import ID3
from mutagen.mp4 import MP4

logger = logging.getLogger(__name__)

# extension -> (nom du codec, sans perte ?)
FORMATS: dict[str, tuple[str, bool]] = {
    ".flac": ("FLAC", True),
    ".alac": ("ALAC", True),
    ".wav": ("WAV", True),
    ".aif": ("AIFF", True),
    ".aiff": ("AIFF", True),
    ".wv": ("WavPack", True),
    ".ape": ("APE", True),
    ".m4a": ("AAC", False),  # ALAC ou AAC : tranché à la lecture des infos
    ".mp3": ("MP3", False),
    ".ogg": ("Vorbis", False),
    ".opus": ("Opus", False),
}
MEDIA_TYPES = {
    ".flac": "audio/flac", ".alac": "audio/mp4", ".wav": "audio/wav", ".aif": "audio/aiff", ".aiff": "audio/aiff",
    ".wv": "audio/x-wavpack", ".ape": "audio/x-ape", ".m4a": "audio/mp4", ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg", ".opus": "audio/ogg",
}
COVER_NAMES = ("cover", "folder", "front", "album")
COVER_SUFFIXES = (".jpg", ".jpeg", ".png")


def track_id(rel_path: str) -> str:
    return hashlib.sha1(rel_path.encode("utf-8")).hexdigest()[:16]


def normalize(artist: str, title: str) -> str:
    """« Artiste titre » sans accents, casse, ponctuation ni mentions entre
    parenthèses (feat., remaster…) : la clé de rapprochement entre sources."""
    def clean(text: str) -> str:
        text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
        text = re.sub(r"[\(\[][^\)\]]*[\)\]]", " ", text.casefold())
        text = re.sub(r"\b(feat|ft|featuring)\b.*$", " ", text)
        return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())

    return f"{clean(artist)} {clean(title)}".strip()


def _first(tags, *keys: str) -> str | None:
    for key in keys:
        value = tags.get(key) if tags is not None else None
        if value:
            item = value[0] if isinstance(value, (list, tuple)) else value
            text = str(item).strip()
            if text:
                return text
    return None


def _number(text: str | None) -> int | None:
    match = re.match(r"\s*(\d+)", text or "")
    return int(match.group(1)) if match else None


def read_file(root: Path, path: Path) -> dict | None:
    """Fiche d'un fichier audio ; None s'il est illisible."""
    suffix = path.suffix.lower()
    if suffix not in FORMATS:
        return None
    try:
        audio = MutagenFile(path, easy=suffix not in (".m4a",))
        stat = path.stat()
    except Exception as exc:  # noqa: BLE001 — un fichier abîmé ne doit pas bloquer l'analyse du dossier
        logger.info("Fichier audio illisible %s : %s", path, exc)
        return None
    if audio is None or audio.info is None:
        return None
    codec, lossless = FORMATS[suffix]
    info = audio.info
    tags = audio.tags
    if suffix == ".m4a":
        # ALAC ou AAC : les deux vivent dans un .m4a.
        is_alac = getattr(info, "codec", "") in ("alac", "ALAC")
        codec, lossless = ("ALAC", True) if is_alac else ("AAC", False)
        title = _first(tags, "\xa9nam")
        artist = _first(tags, "\xa9ART", "aART")
        album = _first(tags, "\xa9alb")
        year = (_first(tags, "\xa9day") or "")[:4] or None
        track = _number(str(tags["trkn"][0][0])) if tags and tags.get("trkn") else None
        disc = _number(str(tags["disk"][0][0])) if tags and tags.get("disk") else None
        isrc = _first(tags, "----:com.apple.iTunes:ISRC")
    else:
        title = _first(tags, "title")
        artist = _first(tags, "artist", "albumartist")
        album = _first(tags, "album")
        year = (_first(tags, "date", "originaldate") or "")[:4] or None
        track = _number(_first(tags, "tracknumber"))
        disc = _number(_first(tags, "discnumber"))
        isrc = _first(tags, "isrc")
    rel = path.relative_to(root).as_posix()
    title = title or path.stem
    artist = artist or path.parent.parent.name or "Artiste inconnu"
    bitrate = getattr(info, "bitrate", None)
    return {
        "id": track_id(rel), "path": rel, "title": title, "artist": artist, "album": album or path.parent.name,
        "year": year, "duration_seconds": int(info.length) if getattr(info, "length", None) else None,
        "track_number": track, "disc_number": disc, "codec": codec, "lossless": int(lossless),
        "bitrate": int(bitrate) if bitrate else None, "sample_rate": getattr(info, "sample_rate", None),
        "bit_depth": getattr(info, "bits_per_sample", None) or None,
        "size": stat.st_size, "mtime": stat.st_mtime, "norm": normalize(artist, title),
        "isrc": isrc.upper().replace("-", "") if isrc else None,
    }


def _walk(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in FORMATS and not p.name.startswith(".")]


async def scan(repo, root: Path) -> dict:
    """Indexe `root` : ne relit que les fichiers nouveaux ou modifiés,
    oublie ceux qui ont disparu. Renvoie un compte rendu."""
    files = await asyncio.to_thread(_walk, root)
    known = await repo.local_known()
    seen = {p.relative_to(root).as_posix() for p in files}
    todo = []
    for p in files:
        rel = p.relative_to(root).as_posix()
        stat = p.stat()
        if known.get(rel) != (stat.st_size, stat.st_mtime):
            todo.append(p)

    def read_all() -> list[dict]:
        return [row for p in todo if (row := read_file(root, p)) is not None]

    rows = await asyncio.to_thread(read_all)
    if rows:
        await repo.local_upsert(rows)
    gone = [p for p in known if p not in seen]
    if gone:
        await repo.local_delete_paths(gone)
    return {"found": len(files), "added_or_updated": len(rows), "removed": len(gone), "unreadable": len(todo) - len(rows)}


def resolve_path(root: Path, row: dict) -> Path | None:
    """Chemin réel d'une fiche, jamais en dehors du dossier de musique."""
    path = (root / row["path"]).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return None
    return path if path.is_file() else None


def media_type(row: dict) -> str:
    return MEDIA_TYPES.get(Path(row["path"]).suffix.lower(), "application/octet-stream")


def cover(path: Path) -> tuple[bytes, str] | None:
    """Pochette : image intégrée au fichier, sinon cover.jpg / folder.png du dossier."""
    try:
        suffix = path.suffix.lower()
        if suffix == ".flac":
            pics: list[Picture] = FLAC(path).pictures
            if pics:
                return pics[0].data, pics[0].mime or "image/jpeg"
        elif suffix == ".mp3":
            for frame in ID3(path).getall("APIC"):
                return frame.data, frame.mime or "image/jpeg"
        elif suffix == ".m4a":
            covr = (MP4(path).tags or {}).get("covr")
            if covr:
                return bytes(covr[0]), "image/png" if getattr(covr[0], "imageformat", 13) == 14 else "image/jpeg"
    except Exception as exc:  # noqa: BLE001
        logger.info("Pochette intégrée illisible %s : %s", path, exc)
    for name in COVER_NAMES:
        for ext in COVER_SUFFIXES:
            candidate = path.parent / f"{name}{ext}"
            if candidate.is_file():
                return candidate.read_bytes(), "image/png" if ext == ".png" else "image/jpeg"
    return None


def quality_label(row: dict) -> str:
    """« FLAC 24 bits / 96 kHz », « MP3 320 kbps »… tel que stocké dans le fichier."""
    parts = [row["codec"]]
    if row.get("lossless"):
        if row.get("bit_depth") and row.get("sample_rate"):
            khz = row["sample_rate"] / 1000
            parts.append(f"{row['bit_depth']} bits / {khz:g} kHz")
    elif row.get("bitrate"):
        parts.append(f"{round(row['bitrate'] / 1000)} kbps")
    return " ".join(parts)
