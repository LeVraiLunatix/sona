"""Stockage « Drivecord » : des fichiers découpés en morceaux de 9,5 Mio,
envoyés dans un salon Discord par webhook.

Même principe que le moteur de Drivecord (et de prod-syn-site), sans
chiffrement : ces fichiers ne servent qu'à Sona. Chaque morceau est une pièce
jointe d'un message ; on garde son `messageId` / `attachmentId` et la dernière
URL CDN connue. Ces URLs sont signées et expirent (~24 h) : au moment de
relire, on redemande le message au webhook pour en obtenir une fraîche.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import asdict, dataclass
from urllib.parse import parse_qs, urlparse

import httpx

logger = logging.getLogger(__name__)

# 10 Mio = limite d'une pièce jointe (serveur sans boost) ; marge pour le multipart.
CHUNK_SIZE = int(9.5 * 1024 * 1024)
RETRIES = 8
BASE_DELAY = 0.5
MAX_DELAY = 30.0


class StorageError(Exception):
    pass


class PermanentError(StorageError):
    """Erreur 4xx : réessayer ne servirait à rien."""


@dataclass
class Chunk:
    index: int
    size: int
    message_id: str
    attachment_id: str
    url: str
    expires_at: float = 0.0  # secondes Unix ; 0 = inconnu

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict) -> "Chunk":
        return cls(**data)


def cdn_expiry(url: str) -> float:
    """Expiration d'une URL CDN Discord (paramètre `ex`, secondes en hexadécimal)."""
    try:
        value = parse_qs(urlparse(url).query).get("ex", [""])[0]
        return float(int(value, 16)) if value else 0.0
    except ValueError:
        return 0.0


class RetryAfter(Exception):
    def __init__(self, delay: float) -> None:
        self.delay = delay


def _raise_for(response: httpx.Response) -> None:
    if response.status_code == 429:
        try:
            delay = float(response.json().get("retry_after", 1))
        except (ValueError, KeyError):
            delay = 1.0
        raise RetryAfter(delay)
    if response.status_code >= 500:
        raise StorageError(f"Discord {response.status_code}")
    if response.status_code >= 400:
        raise PermanentError(f"Discord {response.status_code} : {response.text[:200]}")


class DiscordStorage:
    def __init__(self, webhook: str | None, client: httpx.AsyncClient | None = None) -> None:
        self._webhook = (webhook or "").strip()
        self._client = client
        # Un seul webhook : le cadencer évite surtout de déclencher des 429.
        self._lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self._webhook)

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0), follow_redirects=True)
        return self._client

    async def _retry(self, call):
        last: Exception | None = None
        for attempt in range(RETRIES):
            try:
                return await call()
            except RetryAfter as exc:
                last = StorageError("Discord limite le débit (429)")
                await asyncio.sleep(exc.delay + 0.1)
            except PermanentError:
                raise
            except (StorageError, httpx.TransportError) as exc:
                last = exc
                await asyncio.sleep(min(BASE_DELAY * 2**attempt, MAX_DELAY))
        raise StorageError(str(last) if last else "Échec du stockage")

    async def put_chunk(self, data: bytes, filename: str, index: int) -> Chunk:
        if not self.enabled:
            raise StorageError("Stockage Discord non configuré (DISCORD_STORAGE_WEBHOOK).")

        async def call() -> Chunk:
            response = await self._http().post(
                self._webhook, params={"wait": "true"},
                files={"files[0]": (filename, data, "application/octet-stream")},
            )
            _raise_for(response)
            message = response.json()
            attachments = message.get("attachments") or []
            if not attachments:
                raise StorageError("Morceau envoyé mais aucune pièce jointe renvoyée.")
            att = attachments[0]
            return Chunk(index, len(data), str(message["id"]), str(att["id"]), att["url"], cdn_expiry(att["url"]))

        async with self._lock:
            return await self._retry(call)

    async def store(self, parts: AsyncIterator[bytes], filename: str) -> list[Chunk]:
        """Envoie un flux d'octets (déjà découpé en morceaux ≤ CHUNK_SIZE)."""
        chunks: list[Chunk] = []
        try:
            # aclosing : en cas d'échec, le fichier source est refermé tout de suite.
            async with aclosing(parts) as source:
                async for part in source:
                    name = f"{filename}.part{len(chunks)}"
                    chunks.append(await self.put_chunk(part, name, len(chunks)))
        except Exception:
            await self.delete(chunks)  # pas de morceaux orphelins dans le salon
            raise
        return chunks

    async def fresh_url(self, chunk: Chunk) -> str:
        """URL CDN utilisable maintenant (rafraîchie si elle expire dans moins d'une minute)."""
        if chunk.expires_at and chunk.expires_at - time.time() > 60:
            return chunk.url

        async def call() -> str:
            response = await self._http().get(f"{self._webhook}/messages/{chunk.message_id}")
            _raise_for(response)
            for att in response.json().get("attachments", []):
                if str(att["id"]) == chunk.attachment_id:
                    chunk.url, chunk.expires_at = att["url"], cdn_expiry(att["url"])
                    return chunk.url
            raise StorageError("Pièce jointe introuvable dans le salon Discord.")

        async with self._lock:
            return await self._retry(call)

    async def read(self, chunk: Chunk) -> bytes:
        async def call() -> bytes:
            url = await self.fresh_url(chunk)
            response = await self._http().get(url)
            if response.status_code in (403, 404):
                chunk.expires_at = 0.0  # lien périmé : le prochain essai en redemande un
                raise StorageError(f"Discord {response.status_code}")
            _raise_for(response)
            return response.content

        return await self._retry(call)

    async def delete(self, chunks: list[Chunk]) -> None:
        """Efface les messages (au mieux : un échec n'empêche pas le reste)."""
        for chunk in chunks:
            try:
                async with self._lock:
                    response = await self._http().delete(f"{self._webhook}/messages/{chunk.message_id}")
                if response.status_code not in (200, 204, 404):
                    logger.info("Suppression du message Discord %s : %s", chunk.message_id, response.status_code)
            except httpx.HTTPError as exc:
                logger.info("Suppression du message Discord %s impossible : %s", chunk.message_id, exc)

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
