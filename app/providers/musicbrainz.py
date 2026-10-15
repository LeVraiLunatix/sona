"""Crédits d'un enregistrement via MusicBrainz (https://musicbrainz.org) :
compositeurs, auteurs, producteurs, ingénieurs… Base ouverte, sans clé,
retrouvée par le code ISRC du titre.

MusicBrainz impose un User-Agent qui identifie l'application et au plus une
requête par seconde : les appels sont espacés ici, et les réponses gardées
en mémoire (y compris « rien trouvé »)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict

import httpx

logger = logging.getLogger(__name__)

API_BASE = "https://musicbrainz.org/ws/2"
USER_AGENT = "Sona/1.0 (bot musical prive; https://github.com/LeVraiLunatix/sona)"
MIN_INTERVAL = 1.1
CACHE_SIZE = 512

# Type de relation MusicBrainz → intitulé affiché, dans l'ordre d'affichage.
# Le même intitulé regroupe plusieurs types (« writer » = auteur-compositeur).
ROLE_LABELS: dict[str, str] = {
    "composer": "Compositeur",
    "writer": "Auteur-compositeur",
    "lyricist": "Parolier",
    "librettist": "Parolier",
    "arranger": "Arrangeur",
    "orchestrator": "Orchestrateur",
    "producer": "Producteur",
    "co-producer": "Co-producteur",
    "executive producer": "Producteur exécutif",
    "mix": "Mixage",
    "mixer": "Mixage",
    "recording": "Enregistrement",
    "engineer": "Ingénieur du son",
    "sound": "Ingénieur du son",
    "mastering": "Mastering",
    "remixer": "Remix",
    "vocal": "Chant",
    "instrument": "Instruments",
    "performer": "Interprète",
    "programming": "Programmation",
    "dj-mix": "Mix DJ",
}
# Relations de l'œuvre (la chanson), par opposition à celles de
# l'enregistrement : écrites, pas jouées.
WORK_ROLES = ("composer", "writer", "lyricist", "librettist", "arranger", "orchestrator")
# Instruments et chant : trop nombreux et peu parlants hors d'un livret.
SKIPPED_ROLES = ("instrument", "vocal", "performer")


class MusicBrainzError(Exception):
    pass


def parse_credits(recording: dict) -> list[dict]:
    """Enregistrement MusicBrainz (`inc=artist-rels+work-rels+work-level-rels`)
    → `[{"role": "Producteur", "names": ["A", "B"]}, …]`, sans doublon."""
    found: dict[str, list[str]] = {}

    def add(rel: dict) -> None:
        kind = str(rel.get("type") or "").lower()
        label = ROLE_LABELS.get(kind)
        artist = rel.get("artist") or {}
        name = (artist.get("name") or "").strip()
        if not label or kind in SKIPPED_ROLES or not name:
            return
        names = found.setdefault(label, [])
        if name not in names:
            names.append(name)

    for rel in recording.get("relations") or []:
        if rel.get("target-type") == "artist" or "artist" in rel:
            add(rel)
        work = rel.get("work")
        if isinstance(work, dict):
            for inner in work.get("relations") or []:
                if str(inner.get("type") or "").lower() in WORK_ROLES:
                    add(inner)

    order = list(dict.fromkeys(ROLE_LABELS.values()))
    return [{"role": role, "names": found[role]} for role in order if role in found]


class MusicBrainzClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(
            base_url=API_BASE, timeout=10.0,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        self._cache: OrderedDict[str, list[dict]] = OrderedDict()
        self._lock = asyncio.Lock()
        self._last_call = 0.0

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict) -> dict | None:
        async with self._lock:
            wait = self._last_call + MIN_INTERVAL - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                response = await self._client.get(path, params={**params, "fmt": "json"})
            except httpx.HTTPError as exc:
                raise MusicBrainzError(f"MusicBrainz injoignable : {exc}") from exc
            finally:
                self._last_call = time.monotonic()
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise MusicBrainzError(f"MusicBrainz a répondu {response.status_code}")
        data = response.json()
        return data if isinstance(data, dict) else None

    async def credits_by_isrc(self, isrc: str) -> list[dict]:
        """Crédits du titre portant ce code ISRC ; liste vide si inconnu."""
        key = isrc.strip().upper()
        if not key:
            return []
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]

        found = await self._get(f"/isrc/{key}", {"inc": "recordings"})
        recordings = (found or {}).get("recordings") or []
        credits: list[dict] = []
        if recordings and recordings[0].get("id"):
            detail = await self._get(
                f"/recording/{recordings[0]['id']}",
                {"inc": "artist-rels+work-rels+work-level-rels"},
            )
            credits = parse_credits(detail or {})

        self._cache[key] = credits
        if len(self._cache) > CACHE_SIZE:
            self._cache.popitem(last=False)
        return credits
