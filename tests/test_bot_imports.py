"""Import de playlists dans le bot : commande, rapport, corrections — faux
messages Telegram, vraie base SQLite, aucun appel réseau."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.bot.callbacks import ImportCB
from app.bot.handlers import imports
from app.db.database import Database
from app.db.repository import ImportItem, Repository
from app.providers.base import TrackInfo

USER = 4242


class FakeMessage:
    def __init__(self):
        self.answers: list[tuple[str, object]] = []
        self.edits: list[tuple[str, object]] = []
        self.chat = SimpleNamespace(id=USER)
        self.from_user = SimpleNamespace(id=USER)

    async def answer(self, text, reply_markup=None):
        self.answers.append((text, reply_markup))
        return self

    async def edit_text(self, text, reply_markup=None):
        self.edits.append((text, reply_markup))


class FakeCallback:
    def __init__(self, message):
        self.message = message
        self.from_user = SimpleNamespace(id=USER)
        self.alerts: list[str] = []

    async def answer(self, text=None, show_alert=False):
        if text:
            self.alerts.append(text)


def t(i, source="deezer", title=None):
    return TrackInfo(source, str(i), title or f"Titre {i}", "Artiste", None, None, 200, None)


@pytest.fixture
def deps(tmp_path: Path):
    db = Database(tmp_path / "bot.db")
    asyncio.run(db.connect())
    yield SimpleNamespace(repo=Repository(db))
    asyncio.run(db.close())


def _imported(deps) -> int:
    async def build():
        repo = deps.repo
        pid = await repo.playlist_create(USER, "Été", origin="spotify", origin_url="https://open.spotify.com/playlist/x")
        e1, e2 = await repo.playlist_add_tracks(pid, [t(1), t(2)])
        await repo.import_items_add(pid, [
            ImportItem(None, pid, 0, "spotify:a", t("a", "spotify"), "found", None, t(1), e1),
            ImportItem(None, pid, 1, "spotify:b", t("b", "spotify", "Titre B"), "uncertain", "Durée différente (6 s d'écart)", t(2), e2),
            ImportItem(None, pid, 2, "spotify:c", t("c", "spotify", "Titre C"), "missing", "Introuvable", None, None),
        ])
        await repo.playlist_update(pid, import_uncertain=1, import_missing=1)
        return pid

    return asyncio.run(build())


def test_bar():
    assert imports._bar(0, None) == "▱" * 12
    assert imports._bar(5, 10) == "▰" * 6 + "▱" * 6


def test_command_without_link_explains_usage(deps):
    message = FakeMessage()
    asyncio.run(imports.cmd_import(message, SimpleNamespace(args=None), deps))
    assert "/importer" in message.answers[0][0] and "SoundCloud" in message.answers[0][0]


def test_bad_link_is_explained(deps):
    message = FakeMessage()
    asyncio.run(imports.start(deps, message, USER, "https://example.com/rien"))
    assert message.answers[0][0].startswith("❌ Lien non reconnu")


def test_summary_and_report_then_fix(deps):
    pid = _imported(deps)
    message = FakeMessage()
    callback = FakeCallback(message)

    asyncio.run(imports.on_view(callback, ImportCB(action="view", pid=pid), deps))
    text, markup = message.edits[-1]
    assert "🎧 Été" in text and "⚠️ 1 à vérifier" in text and "❌ 1 introuvable" in text
    labels = [b.text for row in markup.inline_keyboard for b in row]
    assert "⚠️ À vérifier (1)" in labels and "🔄 Resynchroniser" in labels

    asyncio.run(imports.on_report(callback, ImportCB(action="report", pid=pid, status="uncertain"), deps))
    text, markup = message.edits[-1]
    assert "Titre B" in text and "6 s" in text
    accept = markup.inline_keyboard[0][0]
    assert accept.text == "✅ 1"

    asyncio.run(imports.on_fix(callback, ImportCB.unpack(accept.callback_data), deps))
    assert callback.alerts[-1] == "Validé"
    counts = asyncio.run(deps.repo.import_counts(pid))
    assert counts == {"found": 2, "missing": 1}
    # Plus rien à vérifier : retour au résumé.
    assert "🎧 Été" in message.edits[-1][0]


def test_list_of_imported_playlists(deps):
    _imported(deps)
    text, markup = asyncio.run(imports._list(deps, USER))
    assert text == "📚 Tes playlists importées"
    assert markup.inline_keyboard[0][0].text == "Été · 2 ⚠️"
    empty_text, empty_markup = asyncio.run(imports._list(deps, 1))
    assert empty_markup is None and "Aucune playlist" in empty_text


def test_callbacks_survive_the_round_trip_through_telegram():
    """Un champ vide revient à None une fois passé par Telegram."""
    packed = ImportCB(action="view", pid=3).pack()
    assert ImportCB.unpack(packed).pid == 3


def test_pending_link_expires(deps):
    callback = FakeCallback(FakeMessage())
    asyncio.run(imports.on_go(callback, deps))
    assert "expiré" in callback.alerts[-1]
