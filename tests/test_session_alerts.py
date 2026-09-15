"""Alerte aux administrateurs quand les cookies YouTube expirent.

Jusqu'ici, une session Google morte ne laissait qu'un avertissement dans les
logs du VPS : côté Telegram, tous les morceaux devenaient « indisponibles »
sans que personne sache pourquoi.
"""

import asyncio
import inspect
import logging
from types import SimpleNamespace

import pytest

from app.bot import broadcast
from app.services import youtube_session

HOUR = 3600


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    """L'état de session vit dans le module : chaque test repart de zéro."""
    monkeypatch.setattr(youtube_session, "_last_known_logged_in", None)
    monkeypatch.setattr(youtube_session, "_last_alert_at", None)
    monkeypatch.setattr(youtube_session, "_last_check_at", None)
    monkeypatch.setattr(youtube_session, "_notifier", None)


def fake_deps(admins, blocked=()):
    """Deps réduit à ce dont la diffusion se sert : le bot et la base."""
    sent = []

    async def send_message(chat_id, text, **_kwargs):
        if chat_id in blocked:
            raise RuntimeError("bot was blocked by the user")
        sent.append((chat_id, text))

    async def list_admins():
        return list(admins)

    deps = SimpleNamespace(
        bot=SimpleNamespace(send_message=send_message),
        repo=SimpleNamespace(list_admins=list_admins),
    )
    return deps, sent


# -- Décision : qui prévenir, et quand -------------------------------


def test_a_dead_session_is_announced_once():
    first = youtube_session.session_alert(False, now=0.0)
    again = youtube_session.session_alert(False, now=60.0)

    assert first is not None and "Cookies YouTube expirés" in first
    assert again is None


def test_the_alert_says_what_to_do_and_never_carries_a_cookie():
    message = youtube_session.session_lost_message()
    assert "navigation privée" in message
    assert "Get cookies.txt LOCALLY" in message
    assert "ce site uniquement" in message
    assert "ne la rouvre jamais" in message
    assert "sur le serveur" in message
    # Le message parle du fichier, jamais de son contenu.
    for marqueur in ("LOGIN_INFO", "SAPISID", "__Secure", "Netscape HTTP Cookie File"):
        assert marqueur not in message


def test_a_reminder_comes_back_after_twelve_hours():
    youtube_session.session_alert(False, now=0.0)

    assert youtube_session.session_alert(False, now=11 * HOUR) is None
    rappel = youtube_session.session_alert(False, now=12 * HOUR)
    assert rappel is not None and "toujours expirés" in rappel
    assert youtube_session.session_alert(False, now=12 * HOUR + 60) is None


def test_the_return_to_normal_is_announced():
    youtube_session.session_alert(False, now=0.0)
    assert youtube_session.session_alert(True, now=HOUR) == youtube_session.SESSION_BACK_MESSAGE


def test_a_healthy_session_says_nothing_at_startup():
    """Une session valide est la normale : personne ne veut un message à
    chaque redémarrage du bot."""
    assert youtube_session.session_alert(True, now=0.0) is None
    assert youtube_session.session_alert(True, now=HOUR) is None


def test_a_new_fall_is_announced_as_a_first_one():
    youtube_session.session_alert(False, now=0.0)
    youtube_session.session_alert(True, now=HOUR)
    rechute = youtube_session.session_alert(False, now=2 * HOUR)
    assert rechute is not None and "toujours" not in rechute


def test_an_undetermined_check_wakes_nobody():
    """Page de consentement, réseau en panne : ça ne prouve pas que la session
    est morte, et ça ne doit pas effacer l'état connu."""
    youtube_session.session_alert(False, now=0.0)
    assert youtube_session.session_alert(None, now=HOUR) is None
    assert youtube_session.session_alert(False, now=2 * HOUR) is None


# -- Envoi effectif ---------------------------------------------------


def test_the_check_sends_the_alert_to_every_admin(monkeypatch, tmp_path):
    monkeypatch.setattr(youtube_session, "report_session", lambda path, reason: False)
    deps, sent = fake_deps(admins=[1, 2])
    youtube_session.register_notifier(lambda text: broadcast.notify_admins(deps, text))

    verdict = asyncio.run(youtube_session.check_session(tmp_path / "cookies.txt", "démarrage"))

    assert verdict is False
    assert [chat_id for chat_id, _ in sent] == [1, 2]
    assert all("Cookies YouTube expirés" in text for _, text in sent)


def test_nothing_is_sent_while_the_session_holds(monkeypatch, tmp_path):
    monkeypatch.setattr(youtube_session, "report_session", lambda path, reason: True)
    deps, sent = fake_deps(admins=[1])
    youtube_session.register_notifier(lambda text: broadcast.notify_admins(deps, text))

    asyncio.run(youtube_session.check_session(tmp_path / "cookies.txt", "démarrage"))

    assert sent == []


def test_an_admin_blocking_the_bot_does_not_silence_the_others():
    deps, sent = fake_deps(admins=[1, 2, 3], blocked={2})
    delivered = asyncio.run(broadcast.notify_admins(deps, "coucou"))
    assert delivered == 2
    assert [chat_id for chat_id, _ in sent] == [1, 3]


def test_a_failed_notification_never_breaks_the_check(monkeypatch, tmp_path, caplog):
    """La vérification tourne en tâche de fond : une exception y passerait
    inaperçue et emporterait la tâche avec elle."""
    monkeypatch.setattr(youtube_session, "report_session", lambda path, reason: False)

    async def broken(_text):
        raise RuntimeError("Telegram indisponible")

    youtube_session.register_notifier(broken)
    caplog.set_level(logging.WARNING, logger=youtube_session.__name__)

    assert asyncio.run(youtube_session.check_session(tmp_path / "cookies.txt", "démarrage")) is False
    assert "non envoyée" in caplog.text


def test_the_notifier_is_registered_at_startup():
    """Le branchement se fait dans run.py : sans lui, l'alerte n'arrive nulle part."""
    import run

    source = inspect.getsource(run.main)
    assert "register_notifier" in source
    assert "notify_admins" in source
