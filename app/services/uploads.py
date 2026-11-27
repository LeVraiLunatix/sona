"""Fichiers audio envoyés par les gens : vérifiés, puis réécrits au propre avant d'être gardés.

Rien de ce que dit l'envoi (nom, type annoncé) n'est cru :
1. le format est reconnu aux premiers octets, et seuls quelques formats audio passent ;
2. ffmpeg n'ouvre QUE ce format, sans accès au réseau, et ne reprend que la piste audio : images,
   métadonnées, pistes annexes et octets ajoutés à la fin disparaissent ;
3. le résultat est entièrement décodé : un fichier qui ne contient pas de son est refusé.
Le nom sur le disque est tiré au hasard : rien de choisi par la personne n'y entre.
"""

from __future__ import annotations

import asyncio
import re
import secrets
import unicodedata
from dataclasses import dataclass
from pathlib import Path

MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_FILES = 500
MIN_SECONDS, MAX_SECONDS = 1, 2 * 3600
TIMEOUT = 300

# format reconnu -> (lecteur ffmpeg, extension gardée, codage, écrivain ffmpeg, type servi)
FORMATS = {
    "mp3": ("mp3", ".mp3", ["-c:a", "copy"], "mp3", "audio/mpeg"),
    "m4a": ("mov", ".m4a", ["-c:a", "copy"], "mp4", "audio/mp4"),
    "flac": ("flac", ".flac", ["-c:a", "copy"], "flac", "audio/flac"),
    "wav": ("wav", ".flac", ["-c:a", "flac"], "flac", "audio/flac"),
    "ogg": ("ogg", ".m4a", ["-c:a", "aac", "-b:a", "256k"], "mp4", "audio/mp4"),
}

_one_at_a_time = asyncio.Semaphore(1)


class UploadError(Exception):
    """Refus à montrer à la personne."""


@dataclass(frozen=True, slots=True)
class Cleaned:
    path: Path
    mime: str
    duration: int
    size: int


def sniff(head: bytes) -> str | None:
    if head.startswith(b"ID3") or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE6 in (0xE2, 0xE4, 0xE6)):
        return "mp3"
    if head[4:8] == b"ftyp":
        return "m4a"
    if head.startswith(b"fLaC"):
        return "flac"
    if head.startswith(b"RIFF") and head[8:12] == b"WAVE":
        return "wav"
    if head.startswith(b"OggS"):
        return "ogg"
    return None


def clean_text(value: object, limit: int = 200) -> str:
    """Texte d'un tag ou d'un nom de fichier : sans caractères de contrôle ni invisibles, borné."""
    text = "".join(ch for ch in str(value or "") if unicodedata.category(ch)[0] != "C")
    return " ".join(text.split())[:limit]


def describe(source: Path, filename: str) -> tuple[str, str, str | None]:
    """(titre, artiste, album) : les tags du fichier, sinon « Artiste - Titre » d'après son nom."""
    tags: dict = {}
    try:
        import mutagen

        found = mutagen.File(source, easy=True)
        tags = dict(found.tags or {}) if found is not None else {}
    except Exception:  # noqa: BLE001 — tags illisibles ou piégés : le nom du fichier suffit
        tags = {}

    def tag(name: str) -> str:
        value = tags.get(name)
        return clean_text(value[0] if isinstance(value, list) and value else value)

    stem = clean_text(Path(filename.replace("\\", "/")).stem)
    by_name = stem.split(" - ", 1)
    title = tag("title") or (by_name[-1] if by_name[-1] else "Sans titre")
    artist = tag("artist") or (by_name[0] if len(by_name) == 2 else "Artiste inconnu")
    return title, artist, tag("album") or None


async def _ffmpeg(ffmpeg: str, *args: str) -> tuple[int, str]:
    process = await asyncio.create_subprocess_exec(
        ffmpeg, "-nostdin", "-hide_banner", "-protocol_whitelist", "file", *args,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, err = await asyncio.wait_for(process.communicate(), TIMEOUT)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise UploadError("Fichier trop long à vérifier.") from None
    return process.returncode, err.decode("utf-8", "replace")


async def clean(source: Path, folder: Path, ffmpeg: str) -> Cleaned:
    """Vérifie `source` et écrit sa version propre dans `folder`. Lève UploadError."""
    with source.open("rb") as handle:
        kind = sniff(handle.read(16))
    if kind is None:
        raise UploadError("Format non accepté : envoie un MP3, M4A, FLAC, WAV ou OGG.")
    demuxer, suffix, codec, muxer, mime = FORMATS[kind]
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{secrets.token_hex(16)}{suffix}"
    async with _one_at_a_time:
        try:
            code, _ = await _ffmpeg(
                ffmpeg, "-f", demuxer, "-i", str(source), "-t", str(MAX_SECONDS + 1),
                "-map", "0:a:0", "-vn", "-sn", "-dn", "-map_metadata", "-1", "-map_chapters", "-1",
                *codec, "-f", muxer, str(out),
            )
            if code != 0 or not out.is_file():
                raise UploadError("Ce fichier n'est pas un audio lisible.")
            # Décodage complet : la durée annoncée par le fichier peut mentir, le son décodé non.
            code, log = await _ffmpeg(ffmpeg, "-i", str(out), "-map", "0:a:0", "-f", "null", "-")
            times = re.findall(r"time=(\d+):(\d\d):(\d\d(?:\.\d+)?)", log)
            seconds = int(times[-1][0]) * 3600 + int(times[-1][1]) * 60 + float(times[-1][2]) if times else 0
            if code != 0 or seconds < MIN_SECONDS:
                raise UploadError("Ce fichier n'est pas un audio lisible.")
            if seconds > MAX_SECONDS:
                raise UploadError("Fichier de plus de 2 heures.")
        except BaseException:
            out.unlink(missing_ok=True)
            raise
    return Cleaned(out, mime, round(seconds), out.stat().st_size)
