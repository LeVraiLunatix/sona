"""Messages envoyés en dehors de la navigation (alertes techniques, annonces).

Ces messages ne sont pas des écrans : ils partent dans un nouveau message et
ne touchent pas à la pile de navigation, donc ils n'écrasent pas ce que la
personne est en train de faire.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from app.bot.deps import Deps

logger = logging.getLogger(__name__)

# Petite pause entre deux envois : Telegram limite le débit d'un bot, et une
# annonce à toute la liste d'un coup se solderait par des « Too Many Requests ».
ANNOUNCE_PAUSE_SECONDS = 0.05


@dataclass(slots=True)
class BroadcastReport:
    """Bilan d'une annonce : trois cas bien distincts.

    Un utilisateur qui n'a rien reçu parce qu'il a coupé ses notifications
    n'est pas un échec — le dire évite de croire à une panne.
    """

    delivered: int = 0
    muted: int = 0
    failed: int = 0

    @property
    def total(self) -> int:
        return self.delivered + self.muted + self.failed


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


async def announce(deps: Deps, text: str, pause: float = ANNOUNCE_PAUSE_SECONDS) -> BroadcastReport:
    """Envoie une annonce à chaque utilisateur autorisé qui a gardé ses
    notifications, et retourne le bilan.

    L'envoi continue quoi qu'il arrive : un destinataire qui a bloqué le bot
    ferait autrement taire l'annonce pour tous ceux qui viennent après lui.
    """
    report = BroadcastReport()
    for user in await deps.repo.list_allowed_users():
        settings = await deps.repo.get_settings(user.user_id)
        if not settings.notifications:
            report.muted += 1
            continue
        if await send_to(deps, user.user_id, text):
            report.delivered += 1
        else:
            report.failed += 1
        if pause:
            await asyncio.sleep(pause)
    logger.info(
        "Annonce diffusée : %d envoyée(s), %d sans notifications, %d échec(s)",
        report.delivered, report.muted, report.failed,
    )
    return report
