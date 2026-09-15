from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.bot import access
from app.bot.deps import Deps

logger = logging.getLogger(__name__)

# Préfixe des callbacks ouverts aux utilisateurs pas encore autorisés
# (bouton « Demander l'accès », voir `app/bot/callbacks.py`).
_OPEN_CALLBACK_PREFIX = "access:"


class WhitelistMiddleware(BaseMiddleware):
    """Filtre d'accès : hors whitelist, l'événement ne va pas aux handlers.

    Les messages des utilisateurs non autorisés ne sont pas ignorés pour
    autant : ils sont confiés à `app.bot.access`, qui répond toujours quelque
    chose (accès accordé via invitation, raison précise du refus, ou demande
    d'accès transmise aux admins). Une invitation peut arriver sous plusieurs
    formes — `/start invite_xxx`, lien collé, jeton brut — et chacune doit
    fonctionner : c'est le seul chemin d'entrée d'un nouvel utilisateur.
    """

    def __init__(self, deps: Deps) -> None:
        self.deps = deps

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        if await self.deps.repo.is_allowed(user.id):
            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            if (event.data or "").startswith(_OPEN_CALLBACK_PREFIX):
                return await handler(event, data)
            logger.info("Callback refusé pour user_id=%s", user.id)
            await event.answer("Accès non autorisé.", show_alert=True)
            return None

        if isinstance(event, Message):
            logger.info("Message d'un utilisateur non autorisé: user_id=%s", user.id)
            await access.handle_denied_message(self.deps, event)
            return None

        return None
