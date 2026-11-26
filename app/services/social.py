"""Qui voit quoi : le cercle d'une personne, calculé par le service de comptes (jamais recodé ici).

Plus de « tous les comptes sont amis » : on est ami seulement après une demande acceptée, et chaque information
(présence, historique, statistiques, playlists) suit le réglage de la personne, les blocages et son état de
compte. Sans service de comptes, ou pour un ancien compte pas encore rattaché, le cercle est vide.
"""

from __future__ import annotations

import logging

from app.api.state import ApiDeps
from app.db.repository import Account
from app.services.sona_accounts import Relation

logger = logging.getLogger(__name__)

PERMISSIONS = ("presence", "history", "stats", "playlists", "profile")


async def circle(deps: ApiDeps, permission: str = "profile") -> list[tuple[Account, Relation]]:
    """Amis acceptés, visibles, et pour lesquels `permission` est accordée à l'appelant."""
    if permission not in PERMISSIONS:
        raise ValueError(permission)
    me = deps.account
    if deps.accounts is None or me is None or not me.supabase_uid:
        return []
    try:
        uids = await deps.accounts.friend_ids(me.supabase_uid)
        relations = await deps.accounts.relations(me.supabase_uid, uids)
    except Exception as exc:  # service injoignable : on ne montre RIEN plutôt que trop
        logger.warning("Cercle d'amis indisponible : %s", exc)
        return []
    allowed = [u for u in uids if (r := relations.get(u)) and r.friend and not r.blocked and r.visible and getattr(r, permission)]
    accounts = {a.supabase_uid: a for a in await deps.repo.accounts_for_uids(allowed)}
    return [(accounts[u], relations[u]) for u in allowed if u in accounts and accounts[u].user_id != deps.user_id]


async def friend_accounts(deps: ApiDeps, permission: str = "profile") -> list[Account]:
    return [a for a, _ in await circle(deps, permission)]
