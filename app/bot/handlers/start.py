from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message

from app.bot import keyboards, navigation
from app.bot.callbacks import NavCB
from app.bot.deps import Deps
from app.bot.navigation import Screen
from app.bot.render import RenderTarget, show_text

router = Router(name="start")


@navigation.register("home")
async def render_home(deps: Deps, target: RenderTarget, user_id: int, params: dict) -> RenderTarget:
    text = "Bienvenue sur Sona\nTrouve et écoute facilement ta musique."
    return await show_text(deps.bot, target, text, keyboards.home_keyboard())


@navigation.register("link_help")
async def render_link_help(deps: Deps, target: RenderTarget, user_id: int, params: dict) -> RenderTarget:
    text = (
        "Colle un lien Deezer, Spotify, Apple Music ou YouTube directement dans "
        "la conversation.\n\nSona reconnaît automatiquement le morceau, l'album, "
        "l'artiste ou la playlist et l'affiche aussitôt — pas besoin de menu."
    )
    return await show_text(deps.bot, target, text, keyboards.link_help_keyboard())


@router.message(CommandStart())
async def cmd_start(message: Message, deps: Deps, command: CommandObject) -> None:
    user_id = message.from_user.id

    if not await deps.repo.is_allowed(user_id):
        token = None
        if command.args and command.args.startswith("invite_"):
            token = command.args[len("invite_") :]
        granted = bool(token) and await deps.repo.consume_invite(
            token, user_id, message.from_user.full_name
        )
        if not granted:
            await message.answer("Ce bot est privé et réservé à certains utilisateurs.")
            return

    await deps.repo.touch_display_name(user_id, message.from_user.full_name)
    await deps.repo.ensure_user(user_id)
    await navigation.goto(deps, user_id, message.chat.id, Screen("home"), reset=True)


@router.message(Command("help"))
async def cmd_help(message: Message, deps: Deps) -> None:
    await navigation.goto(deps, message.from_user.id, message.chat.id, Screen("home"), reset=True)


@router.callback_query(NavCB.filter(F.action == "home"))
async def on_home(callback: CallbackQuery, deps: Deps) -> None:
    await callback.answer()
    await navigation.goto(
        deps, callback.from_user.id, callback.message.chat.id, Screen("home"), reset=True
    )


@router.callback_query(NavCB.filter(F.action == "back"))
async def on_back(callback: CallbackQuery, deps: Deps) -> None:
    await callback.answer()
    await navigation.back(deps, callback.from_user.id)


@router.callback_query(NavCB.filter(F.action == "dismiss"))
async def on_dismiss(callback: CallbackQuery, deps: Deps) -> None:
    """Ferme un écran d'erreur affiché en place (restaure l'écran courant)."""
    await callback.answer()
    await navigation.rerender(deps, callback.from_user.id)


@router.callback_query(NavCB.filter(F.action == "link_help"))
async def on_link_help(callback: CallbackQuery, deps: Deps) -> None:
    await callback.answer()
    await navigation.goto(deps, callback.from_user.id, callback.message.chat.id, Screen("link_help"))


@router.callback_query(F.data == "noop")
async def on_noop(callback: CallbackQuery) -> None:
    await callback.answer()
