"""Lecture immédiate d'un morceau pas encore téléchargé.

Le chemin complet (recherche → téléchargement → vérification par empreinte
→ cache) prend facilement 10 à 20 s : trop pour une app de streaming. Ici,
on retrouve seulement l'adresse du flux audio YouTube de la meilleure source
(quelques secondes) et le serveur le relaie tel quel à l'app, requêtes
`Range` comprises — la lecture démarre tout de suite. Le chemin complet
tourne en parallèle : les écoutes suivantes sont servies depuis le fichier
vérifié. Seul le m4a (AAC) est relayé : c'est ce que lit `AVPlayer`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import aclosing
from dataclasses import dataclass
from pathlib import Path

import yt_dlp

from app.logging_config import ytdlp_logger
from app.providers.base import TrackInfo
from app.services.resolver import iter_audio_sources
from app.services.ytdlp_runtime import with_js_runtimes

logger = logging.getLogger(__name__)

# Les adresses de flux YouTube restent valables ~6 h ; on les garde bien moins.
URL_TTL = 20 * 60
# Pas de flux direct trouvé : on ne réessaie pas à chaque requête `Range`.
MISS_TTL = 120
_CLIENT_ATTEMPTS: tuple[list[str] | None, ...] = (None, ["tv"], ["web_safari", "mweb"])
# Une seule extraction à la fois : chacune lance un moteur JavaScript
# (Deno/Node, plusieurs dizaines de Mo), à ne pas multiplier sur une petite
# machine.
_extract_slots = asyncio.Semaphore(1)


@dataclass(slots=True)
class LiveSource:
    url: str
    headers: dict[str, str]
    content_type: str = "audio/mp4"
    # Source retenue (vidéo YouTube) : pour « Mauvaise version ? ».
    video_id: str | None = None


def _extract_sync(source_url: str, cookies_file: Path | None) -> LiveSource | None:
    last_error: Exception | None = None
    for clients in _CLIENT_ATTEMPTS:
        opts = {
            "quiet": True,
            "logger": ytdlp_logger,
            "skip_download": True,
            "noplaylist": True,
            "format": "bestaudio[ext=m4a]/bestaudio[acodec^=mp4a]",
            "socket_timeout": 15,
        }
        if cookies_file is not None:
            opts["cookiefile"] = str(cookies_file)
        if clients:
            opts["extractor_args"] = {"youtube": {"player_client": clients}}
        try:
            with yt_dlp.YoutubeDL(with_js_runtimes(opts)) as ydl:
                info = ydl.extract_info(source_url, download=False)
        except Exception as exc:
            last_error = exc
            continue
        url = (info or {}).get("url")
        if url and (info.get("ext") in ("m4a", "mp4") or str(info.get("acodec", "")).startswith("mp4a")):
            headers = {k: v for k, v in (info.get("http_headers") or {}).items() if k.lower() != "accept-encoding"}
            return LiveSource(url=url, headers=headers)
    if last_error is not None:
        logger.info("Pas de flux direct pour %s : %s", source_url, last_error)
    return None


async def resolve(
    track: TrackInfo, cookies_file: Path | None, excluded: frozenset[str] | set[str] = frozenset()
) -> LiveSource | None:
    """Flux direct de la source la plus probable (la même que le chemin
    complet essaie en premier), ou None pour se rabattre sur le chemin
    complet."""
    async with aclosing(iter_audio_sources(track, cookies_file, excluded)) as sources:
        async for candidate in sources:
            if candidate.platform != "youtube":
                return None
            async with _extract_slots:
                found = await asyncio.to_thread(_extract_sync, candidate.source_url, cookies_file)
            if found is not None:
                found.video_id = candidate.video_id
            return found
    return None


class LiveCache:
    """Adresses de flux direct par morceau, pour que les nombreuses requêtes
    `Range` d'une même lecture ne relancent pas la résolution."""

    def __init__(self) -> None:
        self._entries: dict[tuple, tuple[float, LiveSource | None]] = {}
        self._locks: dict[tuple, asyncio.Lock] = {}

    def get(self, key: tuple) -> tuple[bool, LiveSource | None]:
        entry = self._entries.get(key)
        if entry is None or entry[0] < time.monotonic():
            return False, None
        return True, entry[1]

    def put(self, key: tuple, source: LiveSource | None) -> None:
        ttl = URL_TTL if source else MISS_TTL
        self._entries[key] = (time.monotonic() + ttl, source)

    def drop(self, key: tuple) -> None:
        self._entries.pop(key, None)

    def lock(self, key: tuple) -> asyncio.Lock:
        return self._locks.setdefault(key, asyncio.Lock())

    def clear(self) -> None:
        self._entries.clear()

    def drop_track(self, source: str, source_id: str) -> None:
        """Toutes les entrées d'un morceau (tous formats et qualités)."""
        for key in [k for k in self._entries if k[:2] == (source, source_id)]:
            del self._entries[key]
