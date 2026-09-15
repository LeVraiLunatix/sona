"""Messages envoyés en dehors de la navigation (alertes techniques, annonces).

Ces messages ne sont pas des écrans : ils partent dans un nouveau message et
ne touchent pas à la pile de navigation, donc ils n'écrasent pas ce que la
personne est en train de faire.
"""

from __future__ import annotations

import logging

from app.bot.deps import Deps

logger = logging.getLogger(__name__)


async def send_to(deps: Deps, chat_id: int, text: str) -> bool:
    """Envoie un message. Retourne False s'il n'est pas passé.

    Un destinataire qui a bloqué le bot, ou qui n'a jamais ouvert de
    conversation, fait lever aiogram : c'est attendu, et ça ne doit jamais
    interrompre une diffusion en cours.
    """
    try:
        await deps.bot.send_message(chat_id, text)
        return True
    except Exception as exc:
        logger.warning("Message à %s non délivré: %s", chat_id, exc)
        return False


async def notify_admins(deps: Deps, text: str) -> int:
    """Prévient chaque administrateur. Retourne le nombre d'envois réussis."""
    admins = await deps.repo.list_admins()
    if not admins:
        logger.warning("Aucun administrateur à prévenir : %s", text.splitlines()[0])
        return 0
    delivered = 0
    for admin_id in admins:
        if await send_to(deps, admin_id, text):
            delivered += 1
    return delivered
