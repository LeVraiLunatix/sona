"""Moteur de stockage Discord : envoi, nouvel essai sur 429, rafraîchissement des liens."""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from app.services import discord_storage
from app.services.discord_storage import Chunk, DiscordStorage, StorageError, cdn_expiry

WEBHOOK = "https://discord.test/api/webhooks/1/abc"


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    async def no_sleep(_):
        return None

    monkeypatch.setattr(discord_storage.asyncio, "sleep", no_sleep)


def _storage(handler) -> DiscordStorage:
    return DiscordStorage(WEBHOOK, httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def _message(mid="10", att="20", ex="ffffffff") -> dict:
    return {"id": mid, "attachments": [{"id": att, "url": f"https://cdn.test/f?ex={ex}&is=1"}]}


def test_cdn_expiry_reads_the_hex_timestamp():
    assert cdn_expiry("https://cdn.test/f?ex=65f00000&is=1") == int("65f00000", 16)
    assert cdn_expiry("https://cdn.test/f") == 0.0
    assert cdn_expiry("https://cdn.test/f?ex=zz") == 0.0


def test_put_chunk_retries_after_429_then_succeeds():
    async def scenario():
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            if len(calls) == 1:
                return httpx.Response(429, json={"retry_after": 0.5})
            assert request.url.params["wait"] == "true"
            return httpx.Response(200, json=_message())

        chunk = await _storage(handler).put_chunk(b"abc", "x.part0", 0)
        assert len(calls) == 2
        assert (chunk.message_id, chunk.attachment_id, chunk.size) == ("10", "20", 3)

    asyncio.run(scenario())


def test_client_errors_are_not_retried():
    async def scenario():
        calls = []

        def handler(request):
            calls.append(1)
            return httpx.Response(404, json={"message": "Unknown Webhook"})

        with pytest.raises(StorageError):
            await _storage(handler).put_chunk(b"abc", "x", 0)
        assert len(calls) == 1

    asyncio.run(scenario())


def test_failed_store_removes_the_chunks_already_sent():
    async def scenario():
        sent, deleted = [], []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "DELETE":
                deleted.append(request.url.path.rsplit("/", 1)[-1])
                return httpx.Response(204)
            sent.append(1)
            return httpx.Response(200, json=_message(mid=str(len(sent)))) if len(sent) < 2 else httpx.Response(400, json={})

        async def parts():
            for piece in (b"a", b"b", b"c"):
                yield piece

        with pytest.raises(StorageError):
            await _storage(handler).store(parts(), "f.mp3")
        assert deleted == ["1"]

    asyncio.run(scenario())


def test_expired_link_is_refreshed_through_the_message():
    async def scenario():
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            if request.url.path.endswith("/messages/10"):
                return httpx.Response(200, json=_message(ex=format(int(time.time()) + 3600, "x")))
            return httpx.Response(200, content=b"DATA")

        chunk = Chunk(0, 4, "10", "20", "https://cdn.test/old?ex=1", expires_at=1.0)
        assert await _storage(handler).read(chunk) == b"DATA"
        assert any("/messages/10" in u for u in seen)
        assert chunk.expires_at > time.time()

    asyncio.run(scenario())


def test_fresh_link_is_used_without_asking_discord():
    async def scenario():
        def handler(request: httpx.Request) -> httpx.Response:
            assert "/messages/" not in request.url.path
            return httpx.Response(200, content=b"OK")

        chunk = Chunk(0, 2, "10", "20", "https://cdn.test/f", expires_at=time.time() + 3600)
        assert await _storage(handler).read(chunk) == b"OK"

    asyncio.run(scenario())


def test_disabled_storage_refuses_uploads():
    async def scenario():
        with pytest.raises(StorageError):
            await DiscordStorage(None).put_chunk(b"x", "f", 0)

    asyncio.run(scenario())
