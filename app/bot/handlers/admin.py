from __future__ import annotations

import logging
from urllib.parse import quote

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from app.bot import access, keyboards, navigation
from app.bot.callbacks import AdminCB
from app.bot.deps import Deps
from app.bot.navigation import Screen
from app.bot.render import RenderTarget, show_text
from app.db.repository import INVITE_TTL_HOURS
from app.services.invites import build_invite_link

logger = logging.getLogger(__name__)

router = Router(name="admin")

MULTI_INVITE_USES = 10
_INVITE_TTL_DAYS = INVITE_TTL_HOURS // 24
NOT_ADMIN = "Réservé aux administrateurs."


def _invite_text(invite_link: str, max_uses: int) -> str:
    portee = (
        "Il fonctionne une seule fois"
        if max_uses == 1
        else f"Il fonctionne pour {max_uses} personnes"
    )
    return (
        "Invitation créée\n\n"
        f"Partage ce lien avec la personne à ajouter. {portee} et expire dans "
        f"{_INVITE_TTL_DAYS} jours.\n\n"
        f"{invite_link}\n\n"
        "Si l'ouverture du lien ne déclenche rien chez la personne invitée "
        "(conversation déjà existante avec Sona), elle peut simplement coller "
        "ce lien dans la conversation : Sona le reconnaîtra."
    )


@navigation.register("admin_menu")
async def render_admin_menu(deps: Deps, target: RenderTarget, user_id: int, params: dict) -> RenderTarget:
    users = await deps.repo.list_allowed_users()
    pending = await deps.repo.list_access_requests()
    lines = ["Gestion des accès", "", f"{len(users)} utilisateur(s) autorisé(s) :"]
    for u in users:
        label = u.display_name or str(u.user_id)
        lines.append(f"• {label}" + (" — admin" if u.is_admin else ""))
    if pending:
        lines += ["", f"{len(pending)} demande(s) d'accès en attente."]
    text = "\n".join(lines)
    return await show_text(deps.bot, target, text, keyboards.admin_menu_keyboard(len(pending)))


@navigation.register("admin_invite")
async def render_admin_invite(deps: Deps, target: RenderTarget, user_id: int, params: dict) -> RenderTarget:
    token = params["token"]
    max_uses = params.get("max_uses", 1)
    invite_link = build_invite_link(deps.bot_username, token)
    share_url = f"https://t.me/share/url?url={quote(invite_link, safe='')}"
    text = _invite_text(invite_link, max_uses)
    return await show_text(deps.bot, target, text, keyboards.admin_invite_keyboard(share_url, token))


@navigation.register("admin_remove_list")
async def render_admin_remove_list(deps: Deps, target: RenderTarget, user_id: int, params: dict) -> RenderTarget:
    users = await deps.repo.list_allowed_users()
    text = "Retirer un accès\n\nChoisis un utilisateur à retirer (les admins ne peuvent pas être retirés ici)."
    return await show_text(deps.bot, target, text, keyboards.admin_remove_list_keyboard(users))


@navigation.register("admin_requests")
async def render_admin_requests(deps: Deps, target: RenderTarget, user_id: int, params: dict) -> RenderTarget:
    requests = await deps.repo.list_access_requests()
    if not requests:
        text = "Demandes d'accès\n\nAucune demande en attente."
        return await show_text(deps.bot, target, text, keyboards.admin_requests_keyboard([]))
    lines = ["Demandes d'accès", ""]
    for req in requests:
        label = req.display_name or str(req.user_id)
        username = f" (@{req.username})" if req.username else ""
        lines.append(f"• {label}{username} — id {req.user_id}")
    return await show_text(deps.bot, target, "\n".join(lines), keyboards.admin_requests_keyboard(requests))


async def _require_admin(callback: CallbackQuery, deps: Deps) -> bool:
    if await deps.repo.is_admin(callback.from_user.id):
        return True
    await callback.answer(NOT_ADMIN, show_alert=True)
    return False


async def _open_invite_screen(callback: CallbackQuery, deps: Deps, max_uses: int) -> None:
    token = await deps.repo.create_invite(callback.from_user.id, max_uses=max_uses)
    await navigation.goto(
        deps,
        callback.from_user.id,
        callback.message.chat.id,
        Screen("admin_invite", {"token": token, "max_uses": max_uses}),
    )


@router.callback_query(AdminCB.filter(F.action == "menu"))
async def on_admin_menu(callback: CallbackQuery, deps: Deps) -> None:
    if not await _require_admin(callback, deps):
        return
    await callback.answer()
    await navigation.goto(deps, callback.from_user.id, callback.message.chat.id, Screen("admin_menu"))


@router.callback_query(AdminCB.filter(F.action == "invite"))
async def on_admin_invite(callback: CallbackQuery, deps: Deps) -> None:
    if not await _require_admin(callback, deps):
        return
    await callback.answer()
    await _open_invite_screen(callback, deps, max_uses=1)


@router.callback_query(AdminCB.filter(F.action == "invite_multi"))
async def on_admin_invite_multi(callback: CallbackQuery, deps: Deps) -> None:
    if not await _require_admin(callback, deps):
        return
    await callback.answer()
    await _open_invite_screen(callback, deps, max_uses=MULTI_INVITE_USES)


@router.callback_query(AdminCB.filter(F.action == "revoke"))
async def on_admin_revoke_invite(callback: CallbackQuery, callback_data: AdminCB, deps: Deps) -> None:
    """Annule un lien d'invitation partagé par erreur : il est refusé ensuite
    avec un message explicite plutôt qu'un silence."""
    if not await _require_admin(callback, deps):
        return
    await deps.repo.revoke_invite(callback_data.id)
    await callback.answer("Lien annulé.")
    await navigation.replace_top(deps, callback.from_user.id, Screen("admin_menu"))


@router.callback_query(AdminCB.filter(F.action == "remove_list"))
async def on_admin_remove_list(callback: CallbackQuery, deps: Deps) -> None:
    if not await _require_admin(callback, deps):
        return
    await callback.answer()
    await navigation.goto(deps, callback.from_user.id, callback.message.chat.id, Screen("admin_remove_list"))


@router.callback_query(AdminCB.filter(F.action == "remove"))
async def on_admin_remove(callback: CallbackQuery, callback_data: AdminCB, deps: Deps) -> None:
    if not await _require_admin(callback, deps):
        return
    await deps.repo.remove_allowed_user(int(callback_data.id))
    await callback.answer("Accès retiré.")
    await navigation.replace_top(deps, callback.from_user.id, Screen("admin_remove_list"))


@router.callback_query(AdminCB.filter(F.action == "requests"))
async def on_admin_requests(callback: CallbackQuery, deps: Deps) -> None:
    if not await _require_admin(callback, deps):
        return
    await callback.answer()
    await navigation.goto(deps, callback.from_user.id, callback.message.chat.id, Screen("admin_requests"))


@router.callback_query(AdminCB.filter(F.action.in_({"approve", "deny"})))
async def on_admin_resolve_request(callback: CallbackQuery, callback_data: AdminCB, deps: Deps) -> None:
    """Valide/refuse une demande d'accès.

    Déclenché soit depuis l'écran « Demandes d'accès », soit depuis la
    notification reçue en message direct — dans ce second cas il n'y a pas
    d'écran à rafraîchir, on se contente de neutraliser les boutons.
    """
    if not await _require_admin(callback, deps):
        return
    target_id = int(callback_data.id)

    if callback_data.action == "approve":
        granted = await access.approve_request(deps, callback.from_user.id, target_id)
        await callback.answer("Accès accordé." if granted else "Déjà autorisé.")
        verdict = "autorisé"
    else:
        await access.deny_request(deps, callback.from_user.id, target_id)
        await callback.answer("Demande refusée.")
        verdict = "refusé"

    if navigation.current_screen(callback.from_user.id).kind == "admin_requests":
        await navigation.replace_top(deps, callback.from_user.id, Screen("admin_requests"))
        return

    try:
        await callback.message.edit_text(f"{callback.message.text}\n\n→ {verdict}")
    except Exception as exc:
        logger.debug("Notification de demande non mise à jour: %s", exc)


@router.message(Command("invite"))
async def cmd_invite(message: Message, deps: Deps) -> None:
    if not await deps.repo.is_admin(message.from_user.id):
        await message.answer(NOT_ADMIN)
        return
    token = await deps.repo.create_invite(message.from_user.id, max_uses=1)
    await message.answer(_invite_text(build_invite_link(deps.bot_username, token), 1))


@router.message(Command("allow"))
async def cmd_allow(message: Message, deps: Deps, command: CommandObject) -> None:
    """Ajoute un utilisateur par son identifiant numérique.

    Filet de sécurité quand le lien d'invitation ne passe pas : l'invité
    récupère son id avec /id et l'admin l'ajoute à la main."""
    if not await deps.repo.is_admin(message.from_user.id):
        await message.answer(NOT_ADMIN)
        return
    raw = (command.args or "").strip()
    if not raw.lstrip("-").isdigit():
        await message.answer("Utilisation : /allow <identifiant Telegram>\n(l'invité l'obtient avec /id)")
        return
    target_id = int(raw)
    if await deps.repo.is_allowed(target_id):
        await message.answer("Cet utilisateur a déjà accès.")
        return
    await access.approve_request(deps, message.from_user.id, target_id)
    await message.answer(f"Accès accordé à {target_id}.")
