from __future__ import annotations

import asyncio
import logging
import subprocess
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import httpx
from mutagen import File as MutagenFile

from app.providers.base import TrackInfo

logger = logging.getLogger(__name__)

# Écart d'empreinte (part des bits qui diffèrent) au-delà duquel l'audio
# téléchargé n'est pas l'enregistrement de l'extrait officiel. Mesures du
# 2026-09-15 sur le VPS : 0,04 à 0,11 pour le même enregistrement (titres
# officiels, repost fidèle) ; 0,21 à 0,32 pour une instru sur le même master,
# un remix ou un repost en 639 Hz ; 0,31 à 0,59 pour des reposts retouchés ;
# environ 0,46 entre deux morceaux sans rapport.
SAME_RECORDING_MAX_ERROR = 0.15
# Chromaprint produit environ 8 valeurs par seconde : en dessous de ~5 s,
# la comparaison ne prouve plus rien.
MIN_FINGERPRINT_LENGTH = 40
# Écart toléré entre la durée du fichier et celle du morceau : la même marge
# que pour un titre officiel dans le résolveur.
LENGTH_TOLERANCE = 15
LENGTH_TOLERANCE_RATIO = 0.08
PREVIEW_TIMEOUT = 15
FFMPEG_TIMEOUT = 120


@dataclass(frozen=True, slots=True)
class Verdict:
    """Résultat de la vérification d'un fichier.

    `error` : écart mesuré avec l'extrait officiel (1.0 si le fichier n'a pas
    la durée du morceau), ou None si la vérification n'a pas pu avoir lieu.
    `reason` explique un rejet qui ne vient pas de l'empreinte, ou pourquoi la
    vérification a été sautée.
    """

    error: float | None
    reason: str | None = None

    @property
    def rejected(self) -> bool:
        return self.error is not None and self.error > SAME_RECORDING_MAX_ERROR


def alignment_error(excerpt: list[int], full: list[int]) -> float:
    """Part minimale de bits différents entre l'extrait et le passage le plus
    ressemblant du morceau complet.

    L'extrait officiel est tiré d'un endroit inconnu du morceau : on le fait
    glisser sur toute la longueur plutôt que de comparer les débuts.
    """
    if len(full) < len(excerpt):
        excerpt, full = full, excerpt
    size = len(excerpt)
    if size == 0:
        raise ValueError("Empreinte vide.")
    fewest = size * 32
    for offset in range(len(full) - size + 1):
        differing = 0
        for a, b in zip(excerpt, full[offset : offset + size]):
            differing += (a ^ b).bit_count()
            if differing >= fewest:
                break
        fewest = min(fewest, differing)
    return fewest / (size * 32)


def length_matches(expected_seconds: int, actual_seconds: float) -> bool:
    allowed = max(LENGTH_TOLERANCE, expected_seconds * LENGTH_TOLERANCE_RATIO)
    return abs(actual_seconds - expected_seconds) <= allowed


@lru_cache(maxsize=4)
def chromaprint_available(ffmpeg_path: str) -> bool:
    """ffmpeg sait-il calculer une empreinte chromaprint ? C'est le cas des
    paquets Ubuntu/Debian ; certaines builds minimales ne l'embarquent pas."""
    try:
        result = subprocess.run(
            [ffmpeg_path, "-hide_banner", "-muxers"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        available = False
    else:
        available = "chromaprint" in result.stdout
    if not available:
        logger.warning(
            "ffmpeg (%s) sans chromaprint : l'audio ne sera pas comparé à l'extrait officiel", ffmpeg_path
        )
    return available


def fingerprint(ffmpeg_path: str, audio: Path) -> list[int]:
    """Empreinte chromaprint brute (entiers 32 bits) d'un fichier audio."""
    with tempfile.TemporaryDirectory(prefix="sona-fp-") as tmp:
        output = Path(tmp) / "fingerprint.raw"
        subprocess.run(
            [
                # `-nostdin` : sinon ffmpeg lit l'entrée standard et avale ce
                # qui s'y trouve (le reste d'un script lancé par `ssh … bash -s`).
                ffmpeg_path, "-nostdin", "-v", "error", "-y", "-i", str(audio), "-ac", "1",
                "-f", "chromaprint", "-fp_format", "raw", str(output),
            ],
            stdin=subprocess.DEVNULL,
            check=True,
            capture_output=True,
            timeout=FFMPEG_TIMEOUT,
        )
        raw = output.read_bytes()
    return [int.from_bytes(raw[i : i + 4], "little") for i in range(0, len(raw) - 3, 4)]


def _audio_length(audio: Path) -> float | None:
    try:
        parsed = MutagenFile(audio)
    except Exception:
        return None
    length = getattr(getattr(parsed, "info", None), "length", None)
    return float(length) if length else None


async def _fetch_preview(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=PREVIEW_TIMEOUT, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.content


async def verify_recording(track: TrackInfo, audio: Path, ffmpeg_path: str) -> Verdict:
    """Vérifie que l'audio téléchargé est bien le morceau demandé.

    Un titre et une durée identiques ne prouvent rien : les reposts retouchés
    pour échapper au Content ID, ou les instrus publiées sous le titre du
    morceau, passent tous les filtres du résolveur. On compare donc l'audio à
    l'extrait officiel. Sans extrait ou sans chromaprint, la comparaison est
    sautée et le choix du résolveur s'applique.
    """
    length = await asyncio.to_thread(_audio_length, audio)
    if track.duration_seconds and length and not length_matches(track.duration_seconds, length):
        # Typiquement l'extrait de 30 s d'un titre SoundCloud réservé aux
        # abonnés : il ressemble parfaitement à l'extrait officiel, mais ce
        # n'est pas le morceau entier.
        return Verdict(1.0, f"fichier de {length:.0f} s au lieu de {track.duration_seconds} s")
    if not track.preview_url:
        return Verdict(None, "pas d'extrait officiel")
    if not await asyncio.to_thread(chromaprint_available, ffmpeg_path):
        return Verdict(None, "ffmpeg sans chromaprint")
    try:
        content = await _fetch_preview(track.preview_url)
    except httpx.HTTPError as exc:
        return Verdict(None, f"extrait officiel inaccessible ({exc.__class__.__name__})")
    try:
        with tempfile.TemporaryDirectory(prefix="sona-preview-") as tmp:
            preview = Path(tmp) / "preview"
            preview.write_bytes(content)
            excerpt = await asyncio.to_thread(fingerprint, ffmpeg_path, preview)
        full = await asyncio.to_thread(fingerprint, ffmpeg_path, audio)
    except Exception as exc:  # une empreinte ratée ne doit pas priver l'utilisateur de son morceau
        logger.warning("Empreinte audio impossible pour %s: %s", audio.name, exc)
        return Verdict(None, "empreinte impossible")
    if min(len(excerpt), len(full)) < MIN_FINGERPRINT_LENGTH:
        return Verdict(None, "extrait trop court pour comparer")
    return Verdict(await asyncio.to_thread(alignment_error, excerpt, full))
