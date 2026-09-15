from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from app.bot import access, keyboards, navigation
from app.bot.callbacks import AccessCB, NavCB
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
async def cmd_start(message: Message, deps: Deps) -> None:
    """Accueil d'un utilisateur déjà autorisé.

    Les utilisateurs non autorisés n'arrivent jamais ici : le filtre de
    whitelist les confie à `app.bot.access` (invitation, demande d'accès…).
    """
    await access.open_home(deps, message.from_user, message.chat.id)


@router.message(Command("help"))
async def cmd_help(message: Message, deps: Deps) -> None:
    await navigation.goto(deps, message.from_user.id, message.chat.id, Screen("home"), reset=True)


@router.message(Command("id"))
async def cmd_id(message: Message) -> None:
    """Affiche l'identifiant Telegram — le moyen le plus simple pour un admin
    d'ajouter quelqu'un sans passer par un lien d'invitation."""
    await message.answer(f"Ton identifiant Telegram : {message.from_user.id}")


@router.callback_query(AccessCB.filter(F.action == "request"))
async def on_access_request(callback: CallbackQuery, deps: Deps) -> None:
    """Bouton « Demander l'accès ».

    Accessible aux utilisateurs hors whitelist (le filtre laisse passer les
    callbacks `access:`) ; un utilisateur déjà autorisé qui reclique sur un
    vieux message est simplement ramené à l'accueil.
    """
    await callback.answer()
    if await deps.repo.is_allowed(callback.from_user.id):
        await access.open_home(deps, callback.from_user, callback.message.chat.id)
        return
    await access.submit_request(deps, callback.from_user, callback.message.chat.id)


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
