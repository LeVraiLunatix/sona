from __future__ import annotations

from urllib.parse import quote

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot import keyboards, navigation
from app.bot.callbacks import AdminCB
from app.bot.deps import Deps
from app.bot.navigation import Screen
from app.bot.render import RenderTarget, show_text

router = Router(name="admin")


@navigation.register("admin_menu")
async def render_admin_menu(deps: Deps, target: RenderTarget, user_id: int, params: dict) -> RenderTarget:
    users = await deps.repo.list_allowed_users()
    lines = ["Gestion des accès", "", f"{len(users)} utilisateur(s) autorisé(s) :"]
    for u in users:
        label = u.display_name or str(u.user_id)
        lines.append(f"• {label}" + (" — admin" if u.is_admin else ""))
    text = "\n".join(lines)
    return await show_text(deps.bot, target, text, keyboards.admin_menu_keyboard())


@navigation.register("admin_invite")
async def render_admin_invite(deps: Deps, target: RenderTarget, user_id: int, params: dict) -> RenderTarget:
    token = params["token"]
    invite_link = f"https://t.me/{deps.bot_username}?start=invite_{token}"
    share_url = f"https://t.me/share/url?url={quote(invite_link, safe='')}"
    text = (
        "Invitation créée\n\n"
        "Partage ce lien avec la personne à ajouter. Il expire dans 24h et ne "
        "fonctionne qu'une fois.\n\n"
        f"{invite_link}"
    )
    return await show_text(deps.bot, target, text, keyboards.admin_invite_keyboard(share_url))


@navigation.register("admin_remove_list")
async def render_admin_remove_list(deps: Deps, target: RenderTarget, user_id: int, params: dict) -> RenderTarget:
    users = await deps.repo.list_allowed_users()
    text = "Retirer un accès\n\nChoisis un utilisateur à retirer (les admins ne peuvent pas être retirés ici)."
    return await show_text(deps.bot, target, text, keyboards.admin_remove_list_keyboard(users))


@router.callback_query(AdminCB.filter(F.action == "menu"))
async def on_admin_menu(callback: CallbackQuery, deps: Deps) -> None:
    if not await deps.repo.is_admin(callback.from_user.id):
        await callback.answer("Réservé aux administrateurs.", show_alert=True)
        return
    await callback.answer()
    await navigation.goto(deps, callback.from_user.id, callback.message.chat.id, Screen("admin_menu"))


@router.callback_query(AdminCB.filter(F.action == "invite"))
async def on_admin_invite(callback: CallbackQuery, deps: Deps) -> None:
    if not await deps.repo.is_admin(callback.from_user.id):
        await callback.answer("Réservé aux administrateurs.", show_alert=True)
        return
    await callback.answer()
    token = await deps.repo.create_invite(callback.from_user.id)
    await navigation.goto(
        deps, callback.from_user.id, callback.message.chat.id, Screen("admin_invite", {"token": token})
    )


@router.callback_query(AdminCB.filter(F.action == "remove_list"))
async def on_admin_remove_list(callback: CallbackQuery, deps: Deps) -> None:
    if not await deps.repo.is_admin(callback.from_user.id):
        await callback.answer("Réservé aux administrateurs.", show_alert=True)
        return
    await callback.answer()
    await navigation.goto(deps, callback.from_user.id, callback.message.chat.id, Screen("admin_remove_list"))


@router.callback_query(AdminCB.filter(F.action == "remove"))
async def on_admin_remove(callback: CallbackQuery, callback_data: AdminCB, deps: Deps) -> None:
    if not await deps.repo.is_admin(callback.from_user.id):
        await callback.answer("Réservé aux administrateurs.", show_alert=True)
        return
    await deps.repo.remove_allowed_user(int(callback_data.id))
    await callback.answer("Accès retiré.")
    await navigation.replace_top(deps, callback.from_user.id, Screen("admin_remove_list"))
