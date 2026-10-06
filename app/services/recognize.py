"""« Reconnaître un titre » : quelques secondes enregistrées par l'app
(micro de l'iPhone ou du PC), identifiées par le service de Shazam
(bibliothèque `shazamio`, sans clé) puis retrouvées dans le catalogue de
Sona. Fait côté serveur : ShazamKit, sur l'iPhone, exige un compte
développeur Apple que l'installation re-signée n'a pas."""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

# 3 Mo : ~12 s de WAV 16 kHz, largement assez pour un extrait compressé.
MAX_BYTES = 3 * 1024 * 1024


class RecognizeError(Exception):
    """Reconnaissance impossible (service absent ou injoignable)."""


async def to_wav(audio: bytes, ffmpeg_path: str) -> bytes:
    """N'importe quel enregistrement (WAV, M4A, WebM/Opus…) → WAV mono 16 kHz, 12 s au plus.
    Par fichiers temporaires : le M4A ne se lit pas d'un flux, et un WAV
    écrit dans un flux n'a pas de longueur valide."""
    with tempfile.TemporaryDirectory(prefix="sona-ecoute-") as tmp:
        src, dst = Path(tmp) / "extrait", Path(tmp) / "extrait.wav"
        src.write_bytes(audio)
        proc = await asyncio.create_subprocess_exec(
            ffmpeg_path, "-nostdin", "-v", "error", "-y", "-i", str(src), "-t", "12", "-ac", "1", "-ar", "16000", str(dst),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(proc.wait(), timeout=30)
        except asyncio.TimeoutError as exc:
            proc.kill()
            raise RecognizeError("Enregistrement illisible.") from exc
        if proc.returncode != 0 or not dst.exists() or dst.stat().st_size < 1000:
            raise RecognizeError("Enregistrement illisible.")
        return dst.read_bytes()


def parse(result: dict) -> dict | None:
    """Le titre reconnu (réponse de Shazam), ou None."""
    track = (result or {}).get("track") or {}
    title, artist = track.get("title"), track.get("subtitle")
    if not title or not artist:
        return None
    album = None
    for section in track.get("sections") or []:
        for meta in section.get("metadata") or []:
            if meta.get("title") in ("Album", "Albums") and meta.get("text"):
                album = meta["text"]
    return {"title": title, "artist": artist, "album": album, "cover_url": (track.get("images") or {}).get("coverart")}


async def identify(wav: bytes) -> dict | None:
    try:
        from shazamio import Shazam
    except ImportError as exc:  # dépendance absente sur ce serveur
        raise RecognizeError("La reconnaissance n'est pas installée sur le serveur (pip install shazamio).") from exc
    try:
        result = await asyncio.wait_for(Shazam().recognize(wav), timeout=25)
    except Exception as exc:  # noqa: BLE001 — réseau, service changé, réponse inattendue
        log.warning("Reconnaissance Shazam impossible : %s", exc)
        raise RecognizeError("Le service de reconnaissance ne répond pas. Réessaie dans un instant.") from exc
    return parse(result)
