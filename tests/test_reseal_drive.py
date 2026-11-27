"""Rechiffrement des anciens fichiers : rien n'est effacé avant que la copie chiffrée soit relue et notée."""

from __future__ import annotations

import asyncio
import json
import sqlite3

import httpx

from app.services.discord_storage import MAGIC, Chunk, DiscordStorage
from scripts.reseal_drive import reseal

WEBHOOK = "https://discord.test/api/webhooks/1/abc"
FAR = format(2**33, "x")  # lien qui n'expire pas pendant le test


def fake_discord(messages: dict[str, bytes], broken_upload: list[bool]):
    def url(message_id: str) -> str:
        return f"https://cdn.test/{message_id}?ex={FAR}"

    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[-1]
        if request.method == "DELETE":
            messages.pop(name)
            return httpx.Response(204)
        if request.method == "POST":
            if broken_upload[0]:
                return httpx.Response(403)
            body = request.content
            start = body.index(MAGIC)
            message_id = f"new{len(messages)}"
            messages[message_id] = body[start:body.rindex(b"\r\n--")]
            return httpx.Response(200, json={"id": message_id, "attachments": [{"id": "a", "url": url(message_id)}]})
        return httpx.Response(200, content=messages[name])

    storage = DiscordStorage(WEBHOOK, httpx.AsyncClient(transport=httpx.MockTransport(handler)), key=bytes(range(32)))
    return storage, url


def test_clear_files_are_resent_encrypted_then_the_old_messages_removed():
    messages = {"old0": b"musique", "old1": b"en clair"}
    broken = [True]
    storage, url = fake_discord(messages, broken)
    old = [Chunk(i, len(messages[f"old{i}"]), f"old{i}", "a", url(f"old{i}"), 2**33) for i in range(2)]
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE audio_vault (chunks TEXT)")
    db.execute("INSERT INTO audio_vault VALUES (?)", (json.dumps([c.to_json() for c in old]),))

    def stored() -> list[Chunk]:
        return [Chunk.from_json(c) for c in json.loads(db.execute("SELECT chunks FROM audio_vault").fetchone()[0])]

    async def run(apply: bool) -> dict:
        return await reseal(db, storage, storage, apply)

    assert asyncio.run(run(False))["clear"] == 1 and len(messages) == 2  # à blanc : rien ne bouge
    assert asyncio.run(run(True))["failed"] == 1  # envoi refusé : l'original reste
    assert set(messages) == {"old0", "old1"} and stored()[0].message_id == "old0"

    broken[0] = False
    assert asyncio.run(run(True)) == {"clear": 1, "sealed": 0, "failed": 0, "left_on_discord": []}
    assert not {"old0", "old1"} & set(messages) and all(data.startswith(MAGIC) for data in messages.values())

    async def read_all() -> bytes:
        return b"".join([await storage.read(c) for c in stored()])

    assert asyncio.run(read_all()) == b"musiqueen clair"
    assert asyncio.run(run(True)) == {"clear": 0, "sealed": 1, "failed": 0, "left_on_discord": []}
