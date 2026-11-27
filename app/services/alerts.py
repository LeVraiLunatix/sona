"""Alertes aux administrateurs (panne de lecture, demande d'accès) sur un webhook Discord.

Au mieux : une alerte ratée ne bloque jamais rien. Sans webhook, elle est seulement écrite dans le journal.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


async def send(settings, text: str) -> None:
    url = settings.alerts_webhook
    if not url:
        logger.warning("Alerte non envoyée (ALERTS_DISCORD_WEBHOOK absent) : %s", text.splitlines()[0])
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # Jamais de mention : le texte peut contenir un nom choisi par quelqu'un.
            (await client.post(url, json={"content": text[:1900], "allowed_mentions": {"parse": []}})).raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("Alerte Discord impossible : %s", type(exc).__name__)
