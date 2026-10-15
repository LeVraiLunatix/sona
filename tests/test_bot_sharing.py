"""Liens de partage dans le bot : « 🔗 Partager », « /partages »,
révocation et ouverture d'un lien reçu — faux messages Telegram, vraie base."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.bot import lookup, navigation
from app.bot.callbacks import ShareCB
from app.bot.handlers import sharing
from app.db.database import Database
from app.db.repository import Repository
from app.providers.base import TrackInfo

USER = 777
TRACK = TrackInfo("deezer", "42", "Titre", "Artiste", "Album", None, 200, "https://img/42.jpg")


class FakeMessage:
    def __init__(self):
        self.sent: list[tuple[str, object]] = []
        self.chat = SimpleNamespace(id=USER)
        self.from_user = SimpleNamespace(id=USER)

    async def answer(self, text, reply_markup=None, **kwargs):
        self.sent.append((text, reply_markup))


class FakeCallback:
    def __init__(self):
        self.message = FakeMessage()
        self.from_user = SimpleNamespace(id=USER)
        self.alerts: list[str] = []

    async def answer(self, text=None, show_alert=False):
        if text:
            self.alerts.append(text)


@pytest.fixture
def deps(tmp_path: Path, monkeypatch):
    async def get_track(deps, source, source_id):
        return TRACK

    monkeypatch.setattr(lookup, "get_track", get_track)
    db = Database(tmp_path / "bot.db")
    asyncio.run(db.connect())
    yield SimpleNamespace(repo=Repository(db), settings=SimpleNamespace(share_base_url="https://sona.exemple.fr", bot_token=None))
    asyncio.run(db.close())


def test_share_button_then_list_and_revoke(deps):
    callback = FakeCallback()
    asyncio.run(sharing.on_make(callback, ShareCB(action="make", kind="track", source="deezer", id="42"), deps))
    text, markup = callback.message.sent[0]
    assert "https://sona.exemple.fr/s/" in text and "extraits de 30 s" in text
    token = ShareCB.unpack(markup.inline_keyboard[0][0].callback_data).token

    message = FakeMessage()
    asyncio.run(sharing.cmd_shares(message, deps))
    assert "1. Titre (titre) · 0 vue" in message.sent[0][0]

    asyncio.run(sharing.on_revoke(callback, ShareCB(action="revoke", token=token), deps))
    assert "révoqué" in callback.alerts[-1]
    message = FakeMessage()
    asyncio.run(sharing.cmd_shares(message, deps))
    assert message.sent[0][0].startswith("Aucun lien")


def test_share_needs_a_public_address(deps):
    deps.settings.share_base_url = None
    callback = FakeCallback()
    asyncio.run(sharing.on_make(callback, ShareCB(action="make", kind="track", source="deezer", id="42"), deps))
    assert "SHARE_BASE_URL" in callback.alerts[-1] and not callback.message.sent


def test_opening_a_shared_track(deps, monkeypatch):
    callback = FakeCallback()
    asyncio.run(sharing.on_make(callback, ShareCB(action="make", kind="track", source="deezer", id="42"), deps))
    token = ShareCB.unpack(callback.message.sent[0][1].inline_keyboard[0][0].callback_data).token

    screens = []

    async def goto(deps_, user_id, chat_id, screen, reset=False):
        screens.append(screen)

    monkeypatch.setattr(navigation, "goto", goto)
    monkeypatch.setattr(navigation, "detach", lambda user_id, chat_id: None)
    asyncio.run(sharing.open_shared(deps, FakeMessage(), token))
    assert (screens[0].kind, screens[0].params) == ("track", {"source": "deezer", "id": "42"})

    gone = FakeMessage()
    asyncio.run(sharing.open_shared(deps, gone, "jeton-inconnu-assez-long"))
    assert "n'existe plus" in gone.sent[0][0]
