from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.db.repository import Repository

logger = logging.getLogger(__name__)


class WhitelistMiddleware(BaseMiddleware):
    """Bloque tout utilisateur absent de la table `allowed_users`.

    Exception : un message '/start' (avec ou sans lien d'invitation) passe
    toujours — c'est au handler /start de décider (invitation valide → accès
    accordé ; sinon → message "bot privé"), puisque c'est le seul point
    d'entrée par lequel un nouvel utilisateur peut être admis.
    """

    def __init__(self, repo: Repository) -> None:
        self.repo = repo

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        if await self.repo.is_allowed(user.id):
            return await handler(event, data)

        if isinstance(event, Message) and (event.text or "").startswith("/start"):
            return await handler(event, data)

        logger.info("Accès refusé pour user_id=%s", user.id)
        if isinstance(event, CallbackQuery):
            await event.answer("Accès non autorisé.", show_alert=True)
        elif isinstance(event, Message):
            await event.answer("Ce bot est privé et réservé à certains utilisateurs.")
        return None
