from __future__ import annotations

import logging

from aiogram.types import Message, User

from app.bot import keyboards, navigation
from app.bot.deps import Deps
from app.bot.navigation import Screen
from app.db.repository import InviteResult
from app.services.invites import extract_invite_token

logger = logging.getLogger(__name__)

PRIVATE_BOT = "Sona est un bot privé."
INVITE_MESSAGES = {
    InviteResult.UNKNOWN: (
        "Ce lien d'invitation n'est pas reconnu.\n\n"
        "Demande à la personne qui t'a invité de t'en générer un nouveau."
    ),
    InviteResult.EXPIRED: (
        "Ce lien d'invitation a expiré.\n\n"
        "Demande à la personne qui t'a invité de t'en générer un nouveau."
    ),
    InviteResult.EXHAUSTED: (
        "Ce lien d'invitation a déjà été utilisé.\n\n"
        "Demande à la personne qui t'a invité de t'en générer un nouveau."
    ),
    InviteResult.REVOKED: (
        "Ce lien d'invitation a été annulé.\n\n"
        "Demande à la personne qui t'a invité de t'en générer un nouveau."
    ),
}


def describe(user: User) -> str:
    parts = [user.full_name or str(user.id)]
    if user.username:
        parts.append(f"@{user.username}")
    parts.append(f"id {user.id}")
    return " · ".join(parts)


async def _send(deps: Deps, chat_id: int, text: str, markup=None) -> None:
    try:
        await deps.bot.send_message(chat_id, text, reply_markup=markup)
    except Exception as exc:  # destinataire ayant bloqué le bot, chat inconnu…
        logger.warning("Message à %s non délivré: %s", chat_id, exc)


async def open_home(deps: Deps, user: User, chat_id: int) -> None:
    """Amène un utilisateur autorisé sur l'écran d'accueil."""
    await deps.repo.ensure_user(user.id)
    await deps.repo.touch_display_name(user.id, user.full_name)
    await navigation.goto(deps, user.id, chat_id, Screen("home"), reset=True)


async def notify_admins_of_request(deps: Deps, user: User) -> None:
    admins = await deps.repo.list_admins()
    if not admins:
        logger.warning("Demande d'accès de %s sans aucun admin à prévenir", user.id)
        return
    text = f"Demande d'accès\n\n{describe(user)}"
    markup = keyboards.admin_request_notice_keyboard(user.id)
    for admin_id in admins:
        if admin_id == user.id:
            continue
        await _send(deps, admin_id, text, markup)


async def submit_request(deps: Deps, user: User, chat_id: int) -> None:
    """Enregistre une demande d'accès et prévient les admins."""
    is_new = await deps.repo.record_access_request(user.id, user.full_name, user.username)
    if is_new:
        await notify_admins_of_request(deps, user)
        await _send(
            deps,
            chat_id,
            "Demande envoyée.\n\nTu recevras un message ici dès qu'un "
            "administrateur l'aura validée.",
        )
    else:
        await _send(
            deps,
            chat_id,
            "Ta demande est déjà en attente. Tu recevras un message ici dès "
            "qu'un administrateur l'aura validée.",
        )


async def approve_request(deps: Deps, admin_id: int, user_id: int) -> bool:
    """Autorise un utilisateur et le prévient. Retourne False s'il l'était déjà."""
    if await deps.repo.is_allowed(user_id):
        await deps.repo.resolve_access_request(user_id, "approved", admin_id)
        return False
    request = await deps.repo.get_access_request(user_id)
    display_name = request.display_name if request else None
    await deps.repo.add_allowed_user(user_id, added_by=admin_id, display_name=display_name)
    await deps.repo.resolve_access_request(user_id, "approved", admin_id)
    await deps.repo.ensure_user(user_id)
    await _send(deps, user_id, "Accès accordé ! Bienvenue sur Sona.")
    # En conversation privée, chat_id == user_id : on peut lui ouvrir
    # directement l'écran d'accueil sans attendre qu'il tape /start.
    try:
        await navigation.goto(deps, user_id, user_id, Screen("home"), reset=True)
    except Exception as exc:
        logger.warning("Accueil non affiché à %s après validation: %s", user_id, exc)
    return True


async def deny_request(deps: Deps, admin_id: int, user_id: int) -> None:
    await deps.repo.resolve_access_request(user_id, "denied", admin_id)


async def _try_invite(deps: Deps, message: Message, token: str) -> bool:
    """Tente d'accorder l'accès via un jeton. Retourne True si c'est traité
    (accès accordé ou refus expliqué) — l'appelant n'a alors rien à ajouter."""
    user = message.from_user
    result, inviter_id = await deps.repo.consume_invite(token, user.id, user.full_name)

    if result is InviteResult.OK:
        logger.info("Accès accordé à %s via invitation de %s", user.id, inviter_id)
        await deps.repo.resolve_access_request(user.id, "approved", inviter_id or 0)
        await open_home(deps, user, message.chat.id)
        if inviter_id:
            await _send(deps, inviter_id, f"Invitation utilisée par {describe(user)}.")
        return True

    if result is InviteResult.ALREADY_ALLOWED:
        await open_home(deps, user, message.chat.id)
        return True

    await _send(
        deps,
        message.chat.id,
        INVITE_MESSAGES[result],
        keyboards.access_request_keyboard(),
    )
    return True


async def handle_denied_message(deps: Deps, message: Message) -> None:
    """Seul point d'entrée des messages d'un utilisateur non autorisé.

    Répond toujours quelque chose : un silence ici donne l'impression que le
    bot est hors service (symptôme « /start ne fait rien »).
    """
    user = message.from_user
    text = (message.text or "").strip()

    if text.startswith("/id"):
        await _send(deps, message.chat.id, f"Ton identifiant Telegram : {user.id}")
        return

    token = extract_invite_token(text)
    if token and await _try_invite(deps, message, token):
        return

    if text.startswith("/start"):
        await submit_request(deps, user, message.chat.id)
        return

    await _send(
        deps,
        message.chat.id,
        f"{PRIVATE_BOT}\n\nSi tu as reçu un lien d'invitation, ouvre-le ou "
        "colle-le ici. Sinon, tu peux demander l'accès à un administrateur.",
        keyboards.access_request_keyboard(),
    )
