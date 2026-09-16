"""Annonce envoyée à tous les utilisateurs depuis le bot (admins).

Prévenir tout le monde d'une coupure demandait d'écrire à chacun à la main.
"""

import asyncio
from types import SimpleNamespace

import pytest

from app.bot import broadcast, keyboards, navigation
from app.bot.callbacks import AdminCB
from app.bot.handlers import announce, links
from app.db.repository import AllowedUser, UserSettings

ADMIN = 1
AUTRES = (2, 3)


def allowed(user_id, is_admin=False):
    return AllowedUser(user_id, f"Utilisateur {user_id}", is_admin, "2026-01-01T00:00:00+00:00")


def fake_deps(users=(ADMIN, *AUTRES), muted=(), blocked=(), admins=(ADMIN,)):
    """Deps réduit à ce dont l'annonce se sert."""
    sent = []

    async def send_message(chat_id, text, **_kwargs):
        if chat_id in blocked:
            raise RuntimeError("bot was blocked by the user")
        sent.append((chat_id, text))

    async def list_allowed_users():
        return [allowed(uid, uid in admins) for uid in users]

    async def get_settings(user_id):
        return UserSettings("best", "auto", notifications=user_id not in muted, autoplay=True)

    async def is_admin(user_id):
        return user_id in admins

    deps = SimpleNamespace(
        bot=SimpleNamespace(send_message=send_message),
        repo=SimpleNamespace(
            list_allowed_users=list_allowed_users, get_settings=get_settings, is_admin=is_admin
        ),
    )
    return deps, sent


def fake_callback(user_id=ADMIN):
    answers = []

    async def answer(text=None, show_alert=False):
        answers.append((text, show_alert))

    callback = SimpleNamespace(
        answer=answer,
        data="admin:announce_send:",
        from_user=SimpleNamespace(id=user_id),
        message=SimpleNamespace(chat=SimpleNamespace(id=user_id), photo=None),
    )
    return callback, answers


@pytest.fixture(autouse=True)
def quiet_navigation(monkeypatch):
    """La navigation vit en mémoire : chaque test repart d'une pile neuve et
    n'essaie jamais d'écrire dans une vraie conversation."""
    monkeypatch.setattr(navigation, "_states", {})
    ecrans = []

    async def goto(deps, user_id, chat_id, screen, **_kwargs):
        navigation.state_for(user_id).stack.append(screen)
        ecrans.append(screen)

    async def replace_top(deps, user_id, screen):
        navigation.state_for(user_id).stack[-1] = screen
        ecrans.append(screen)

    async def show_status(deps, user_id, text):
        ecrans.append(text)

    monkeypatch.setattr(navigation, "goto", goto)
    monkeypatch.setattr(navigation, "replace_top", replace_top)
    monkeypatch.setattr(navigation, "show_status", show_status)
    return ecrans


# -- Diffusion ---------------------------------------------------------


def test_the_announcement_reaches_every_notified_user():
    deps, sent = fake_deps()
    report = asyncio.run(broadcast.announce(deps, "Coupure ce soir", pause=0))

    assert [chat_id for chat_id, _ in sent] == [ADMIN, 2, 3]
    assert all(text == "Coupure ce soir" for _, text in sent)
    assert (report.delivered, report.muted, report.failed) == (3, 0, 0)


def test_users_without_notifications_are_left_alone_and_counted():
    """Couper ses notifications, c'est aussi couper les annonces — et ce n'est
    pas un échec."""
    deps, sent = fake_deps(muted={2})
    report = asyncio.run(broadcast.announce(deps, "Coupure ce soir", pause=0))

    assert [chat_id for chat_id, _ in sent] == [ADMIN, 3]
    assert (report.delivered, report.muted, report.failed) == (2, 1, 0)


def test_a_blocked_user_does_not_stop_the_broadcast():
    deps, sent = fake_deps(blocked={2})
    report = asyncio.run(broadcast.announce(deps, "Coupure ce soir", pause=0))

    assert [chat_id for chat_id, _ in sent] == [ADMIN, 3]
    assert (report.delivered, report.muted, report.failed) == (2, 0, 1)


def test_sending_waits_a_little_between_two_users(monkeypatch):
    """Sans pause, une annonce à toute la liste finit en « Too Many Requests »."""
    pauses = []

    async def fake_sleep(seconds):
        pauses.append(seconds)

    monkeypatch.setattr(broadcast.asyncio, "sleep", fake_sleep)
    deps, _sent = fake_deps()
    asyncio.run(broadcast.announce(deps, "Coupure ce soir"))

    assert pauses == [broadcast.ANNOUNCE_PAUSE_SECONDS] * 3
    assert broadcast.ANNOUNCE_PAUSE_SECONDS > 0


# -- Parcours dans le bot ---------------------------------------------


def test_the_access_screen_offers_the_button():
    markup = keyboards.admin_menu_keyboard()
    boutons = [b for row in markup.inline_keyboard for b in row]
    bouton = [b for b in boutons if b.text == "Envoyer une annonce"]
    assert len(bouton) == 1
    assert bouton[0].callback_data == AdminCB(action="announce").pack()


def test_only_an_admin_opens_the_announcement_screen(quiet_navigation):
    deps, _sent = fake_deps()
    callback, answers = fake_callback(user_id=2)

    asyncio.run(announce.on_announce(callback, deps))

    assert answers == [("Réservé aux administrateurs.", True)]
    assert quiet_navigation == []


def test_the_typed_text_becomes_a_preview(quiet_navigation):
    deps, _sent = fake_deps()
    navigation.state_for(ADMIN).stack.append(navigation.Screen("announce_prompt"))
    message = SimpleNamespace(
        text="  Coupure ce soir  ", from_user=SimpleNamespace(id=ADMIN), chat=SimpleNamespace(id=ADMIN)
    )

    assert asyncio.run(announce.capture_draft(deps, message)) is True
    assert quiet_navigation[-1].kind == "announce_preview"
    assert quiet_navigation[-1].params == {"text": "Coupure ce soir"}


def test_a_pasted_link_inside_an_announcement_stays_text(monkeypatch, quiet_navigation):
    """Sans ça, coller un lien Deezer dans une annonce ouvrirait le morceau."""
    deps, _sent = fake_deps()
    navigation.state_for(ADMIN).stack.append(navigation.Screen("announce_prompt"))
    recherches = []

    async def start_search(*args, **kwargs):
        recherches.append(args)

    async def resolve_link(_text):
        raise AssertionError("la détection de lien ne doit pas être atteinte")

    monkeypatch.setattr(links, "start_search", start_search)
    monkeypatch.setattr(links, "resolve_link", resolve_link)
    message = SimpleNamespace(
        text="Nouveau : https://www.deezer.com/track/783257002",
        from_user=SimpleNamespace(id=ADMIN),
        chat=SimpleNamespace(id=ADMIN),
    )

    asyncio.run(links.on_text(message, deps))

    assert recherches == []
    assert quiet_navigation[-1].params["text"] == "Nouveau : https://www.deezer.com/track/783257002"


def test_text_typed_elsewhere_is_not_captured(quiet_navigation):
    """Hors de l'écran de saisie, le texte libre reste une recherche."""
    deps, _sent = fake_deps()
    message = SimpleNamespace(text="pnl au dd", from_user=SimpleNamespace(id=ADMIN), chat=SimpleNamespace(id=ADMIN))

    assert asyncio.run(announce.capture_draft(deps, message)) is False
    assert quiet_navigation == []


def test_a_non_admin_on_the_screen_is_not_captured(quiet_navigation):
    """Accès retiré entre l'ouverture de l'écran et la frappe."""
    deps, _sent = fake_deps()
    navigation.state_for(2).stack.append(navigation.Screen("announce_prompt"))
    message = SimpleNamespace(text="coucou", from_user=SimpleNamespace(id=2), chat=SimpleNamespace(id=2))

    assert asyncio.run(announce.capture_draft(deps, message)) is False


def test_sending_from_the_preview_delivers_and_reports(quiet_navigation):
    deps, sent = fake_deps(muted={3})
    navigation.state_for(ADMIN).stack.append(
        navigation.Screen("announce_preview", {"text": "Coupure ce soir"})
    )
    callback, answers = fake_callback()

    asyncio.run(announce.on_announce_send(callback, deps))

    annonces = [(chat_id, text) for chat_id, text in sent if text == "Coupure ce soir"]
    assert [chat_id for chat_id, _ in annonces] == [ADMIN, 2]
    bilan = sent[-1][1]
    assert "2 envoyée(s)" in bilan
    assert "1 sans notifications" in bilan
    assert answers == [("Envoi en cours…", False)]
    # L'écran revient à la gestion des accès : l'aperçu n'a plus de sens.
    assert quiet_navigation[-1].kind == "admin_menu"


def test_failures_appear_in_the_report(quiet_navigation):
    deps, sent = fake_deps(blocked={2})
    navigation.state_for(ADMIN).stack.append(
        navigation.Screen("announce_preview", {"text": "Coupure ce soir"})
    )
    callback, _answers = fake_callback()

    asyncio.run(announce.on_announce_send(callback, deps))

    assert "1 échec(s)" in sent[-1][1]


def test_a_lost_draft_is_said_instead_of_sending_nothing(quiet_navigation):
    """Redémarrage entre l'aperçu et l'envoi : la pile repart de l'accueil."""
    deps, sent = fake_deps()
    callback, answers = fake_callback()

    asyncio.run(announce.on_announce_send(callback, deps))

    assert sent == []
    assert answers == [(announce.DRAFT_LOST, True)]


def test_only_an_admin_can_send(quiet_navigation):
    deps, sent = fake_deps()
    navigation.state_for(2).stack.append(
        navigation.Screen("announce_preview", {"text": "Coupure ce soir"})
    )
    callback, answers = fake_callback(user_id=2)

    asyncio.run(announce.on_announce_send(callback, deps))

    assert sent == []
    assert answers == [("Réservé aux administrateurs.", True)]


def test_cancelling_goes_back_to_the_access_screen(quiet_navigation):
    deps, sent = fake_deps()
    navigation.state_for(ADMIN).stack.append(
        navigation.Screen("announce_preview", {"text": "Coupure ce soir"})
    )
    callback, answers = fake_callback()

    asyncio.run(announce.on_announce_cancel(callback, deps))

    assert sent == []
    assert answers == [("Annonce annulée.", False)]
    assert quiet_navigation[-1].kind == "admin_menu"
