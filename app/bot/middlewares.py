from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.config import Settings

logger = logging.getLogger(__name__)


class WhitelistMiddleware(BaseMiddleware):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is not None and not self.settings.is_allowed(user.id):
            logger.info("Accès refusé pour user_id=%s", user.id)
            if isinstance(event, CallbackQuery):
                await event.answer("Accès non autorisé.", show_alert=True)
            elif isinstance(event, Message):
                await event.answer("Ce bot est privé et réservé à certains utilisateurs.")
            return None
        return await handler(event, data)
