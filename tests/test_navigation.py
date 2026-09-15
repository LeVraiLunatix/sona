import asyncio
from types import SimpleNamespace

from aiogram.types import Chat, InaccessibleMessage, Message, PhotoSize

from app.bot import navigation
from app.bot.navigation import Screen
from app.bot.render import RenderTarget

CHAT = Chat(id=7, type="private")


def track_card(message_id=42):
    """Écran Morceau tel qu'il reste dans la conversation : une photo légendée."""
    return Message(
        message_id=message_id,
        date=0,
        chat=CHAT,
        caption="Hasta la vista\nPNL",
        photo=[PhotoSize(file_id="f", file_unique_id="u", width=1000, height=1000)],
    )


def restarted_bot(monkeypatch):
    """Comme juste après un redémarrage : plus aucune navigation en mémoire."""
    monkeypatch.setattr(navigation, "_states", {})


class FakeBot:
    def __init__(self):
        self.calls = []

    async def edit_message_caption(self, **kwargs):
        self.calls.append(("caption", kwargs))

    async def edit_message_text(self, text, **kwargs):
        self.calls.append(("text", text, kwargs))


def test_button_of_a_message_from_before_a_restart_is_adopted(monkeypatch):
    restarted_bot(monkeypatch)
    screen = Screen("track", {"source": "deezer", "id": "783257002"})
    assert navigation.adopt_message(7, track_card(), screen) == RenderTarget(7, 42, is_photo=True)
    assert navigation.state_for(7).stack == [Screen("home"), screen]


def test_known_navigation_is_left_alone(monkeypatch):
    restarted_bot(monkeypatch)
    navigation.set_target(7, RenderTarget(7, 10, is_photo=False))
    assert navigation.adopt_message(7, track_card(), Screen("track")) == RenderTarget(7, 10, is_photo=False)
    assert navigation.state_for(7).stack == [Screen("home")]


def test_inaccessible_message_is_not_adopted(monkeypatch):
    restarted_bot(monkeypatch)
    assert navigation.adopt_message(7, InaccessibleMessage(chat=CHAT, message_id=5), Screen("track")) is None
    assert navigation.adopt_message(7, None) is None


def test_status_without_a_known_screen_does_not_crash(monkeypatch):
    """Le bug d'origine : `'NoneType' object has no attribute 'is_photo'`."""
    restarted_bot(monkeypatch)
    bot = FakeBot()
    asyncio.run(navigation.show_status(SimpleNamespace(bot=bot), 7, "Préparation du morceau…"))
    assert bot.calls == []


def test_status_replaces_the_caption_of_the_adopted_track_card(monkeypatch):
    restarted_bot(monkeypatch)
    navigation.adopt_message(7, track_card(), Screen("track"))
    bot = FakeBot()
    asyncio.run(navigation.show_status(SimpleNamespace(bot=bot), 7, "Préparation du morceau…"))
    assert bot.calls == [
        ("caption", {"chat_id": 7, "message_id": 42, "caption": "Préparation du morceau…", "reply_markup": None})
    ]


def test_rerender_after_a_restart_gets_a_usable_target(monkeypatch):
    """Retour, réglages… : sans message suivi, l'écran part dans un nouveau
    message au lieu de planter dans le renderer."""
    restarted_bot(monkeypatch)
    received = []

    async def renderer(deps, target, user_id, params):
        received.append(target)
        return RenderTarget(user_id, 99, is_photo=False)

    monkeypatch.setitem(navigation._renderers, "home", renderer)
    asyncio.run(navigation.rerender(SimpleNamespace(bot=FakeBot()), 7))
    assert received == [RenderTarget(7, None, is_photo=False)]
    assert navigation.current_target(7) == RenderTarget(7, 99, is_photo=False)
