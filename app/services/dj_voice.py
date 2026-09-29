"""DJ vocal : les annonces entre deux titres, écrites ici à partir de ce que
Sona sait de tes écoutes (découverte, titre en boucle, artiste de retour…)
et lues par une voix neuronale Microsoft Edge (gratuite, sans clé), bien
plus naturelle que les voix de l'iPhone. Si la voix est injoignable, l'app
lit le même texte avec une voix de l'iPhone.
"""

from __future__ import annotations

import hashlib
import logging
import random
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

VOICES = {
    "remy": "fr-FR-RemyMultilingualNeural",
    "vivienne": "fr-FR-VivienneMultilingualNeural",
    "henri": "fr-FR-HenriNeural",
    "denise": "fr-FR-DeniseNeural",
}
DEFAULT_VOICE = "remy"
CACHE_LIMIT = 400


@dataclass
class Context:
    title: str
    artist: str
    previous_title: str | None = None
    previous_artist: str | None = None
    track_plays: int = 0          # écoutes de ce titre ces 60 derniers jours
    artist_plays: int = 0         # écoutes de l'artiste ces 60 derniers jours
    new_artist: bool = False      # jamais écouté avant
    hour: int = 12
    year: int | None = None


def _clean(text: str) -> str:
    """Titre lisible à voix haute : sans « (feat. …) », « - Remastered »…"""
    for cut in (" (feat", " (ft", " [feat", " - Remaster", " - Radio Edit", " (Remaster", " - Live"):
        index = text.lower().find(cut.lower())
        if index > 0:
            text = text[:index]
    return text.strip()


def script(ctx: Context, rng: random.Random) -> str:
    """Une ou deux phrases, comme à la radio, jamais les mêmes d'affilée."""
    title, artist = _clean(ctx.title), _clean(ctx.artist)
    prev_title = _clean(ctx.previous_title) if ctx.previous_title else None
    same_artist = bool(ctx.previous_artist) and ctx.previous_artist.casefold() == ctx.artist.casefold()

    if ctx.hour >= 23 or ctx.hour < 5:
        mood = rng.choice(["Pour la nuit…", "Il se fait tard.", "Musique de nuit."])
    elif ctx.hour < 10:
        mood = rng.choice(["Bien le bonjour.", "On se réveille en douceur.", "Pour bien démarrer la journée."])
    elif 17 <= ctx.hour < 20:
        mood = rng.choice(["Fin de journée.", "On lève le pied."])
    else:
        mood = ""

    if ctx.new_artist:
        options = [
            f"Une découverte pour toi : {artist}, avec {title}.",
            f"Tu ne connais peut-être pas encore {artist}… Écoute ça : {title}.",
            f"Nouveau venu dans ta playlist : {artist}. Le titre : {title}.",
        ]
    elif ctx.track_plays >= 8:
        options = [
            f"Celui-là, tu l'as écouté {ctx.track_plays} fois ces dernières semaines… {title}, de {artist}.",
            f"Ton titre du moment, visiblement : {title}, de {artist}.",
            f"On ne s'en lasse pas : {title}, de {artist}.",
        ]
    elif same_artist:
        options = [
            f"On reste avec {artist} : {title}.",
            f"Encore {artist}, avec {title}.",
            f"Toujours {artist}. Voici {title}.",
        ]
    elif ctx.artist_plays >= 15:
        options = [
            f"Un artiste que tu connais bien : {artist}, avec {title}.",
            f"Retour de {artist}, avec {title}.",
            f"{artist}, un habitué. Voici {title}.",
        ]
    else:
        options = [
            f"On enchaîne avec {title}, de {artist}.",
            f"Voici {artist}, avec {title}.",
            f"Place à {artist} : {title}.",
            f"Et maintenant, {title}, de {artist}.",
            f"Tu écoutes {title}, de {artist}.",
        ]
    line = rng.choice(options)
    if prev_title and not same_artist and rng.random() < 0.3:
        line = f"C'était {prev_title}. {line}"
    if ctx.year and ctx.year < datetime.now().year - 12 and rng.random() < 0.4:
        line += f" Un classique de {ctx.year}."
    if mood and rng.random() < 0.35:
        line = f"{mood} {line}"
    return line


class Synthesizer:
    """Voix neuronale Edge, avec cache sur disque (une même annonce n'est
    générée qu'une fois)."""

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir

    def _path(self, text: str, voice: str) -> Path:
        digest = hashlib.sha1(f"{voice}|{text}".encode()).hexdigest()[:20]
        return self.cache_dir / f"{digest}.mp3"

    async def speak(self, text: str, voice: str = DEFAULT_VOICE) -> bytes | None:
        voice_name = VOICES.get(voice, VOICES[DEFAULT_VOICE])
        path = self._path(text, voice_name)
        if path.exists():
            return path.read_bytes()
        try:
            import edge_tts
        except ImportError:
            logger.warning("DJ vocal : paquet edge-tts absent (pip install -r requirements.txt).")
            return None
        try:
            communicate = edge_tts.Communicate(text, voice_name, rate="+4%")
            chunks = []
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    chunks.append(chunk["data"])
            audio = b"".join(chunks)
        except Exception as exc:  # service externe : jamais bloquant
            logger.info("DJ vocal : voix neuronale indisponible (%s)", exc)
            return None
        if not audio:
            return None
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            path.write_bytes(audio)
            self._trim()
        except OSError:
            pass
        return audio

    def _trim(self) -> None:
        files = sorted(self.cache_dir.glob("*.mp3"), key=lambda p: p.stat().st_mtime)
        for old in files[:-CACHE_LIMIT]:
            old.unlink(missing_ok=True)
