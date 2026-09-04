from __future__ import annotations

from math import ceil

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot import keyboards, navigation
from app.bot.callbacks import LibraryCB
from app.bot.deps import Deps
from app.bot.navigation import Screen
from app.bot.render import RenderTarget, show_text

router = Router(name="library")

PAGE_SIZE = keyboards.PAGE_SIZE

_KIND_LABELS = {"track": "morceaux", "album": "albums", "artist": "artistes"}
_KIND_TITLES = {"track": "Morceaux", "album": "Albums", "artist": "Artistes"}


@navigation.register("library_menu")
async def render_library_menu(deps: Deps, target: RenderTarget, user_id: int, params: dict) -> RenderTarget:
    return await show_text(deps.bot, target, "Ma bibliothèque", keyboards.library_menu_keyboard())


@navigation.register("library_tab")
async def render_library_tab(deps: Deps, target: RenderTarget, user_id: int, params: dict) -> RenderTarget:
    kind = params["kind"]
    page = params.get("page", 1)
    offset = (page - 1) * PAGE_SIZE
    items, total = await deps.repo.library_list(user_id, kind, offset=offset, limit=PAGE_SIZE)

    if total == 0:
        text = f"Ta bibliothèque de {_KIND_LABELS[kind]} est vide."
        return await show_text(deps.bot, target, text, keyboards.library_empty_keyboard())

    total_pages = max(1, ceil(total / PAGE_SIZE))
    page = max(1, min(page, total_pages))
    text = f"Ma bibliothèque — {_KIND_TITLES[kind]}"
    markup = keyboards.library_list_keyboard(kind, items, page, total_pages)
    return await show_text(deps.bot, target, text, markup)


@router.message(Command("library"))
async def cmd_library(message: Message, deps: Deps) -> None:
    await navigation.goto(deps, message.from_user.id, message.chat.id, Screen("library_menu"))


@router.callback_query(LibraryCB.filter(F.action == "menu"))
async def on_library_menu(callback: CallbackQuery, deps: Deps) -> None:
    await callback.answer()
    await navigation.goto(deps, callback.from_user.id, callback.message.chat.id, Screen("library_menu"))


@router.callback_query(LibraryCB.filter(F.action == "tab"))
async def on_library_tab(callback: CallbackQuery, callback_data: LibraryCB, deps: Deps) -> None:
    await callback.answer()
    user_id = callback.from_user.id
    screen = Screen("library_tab", {"kind": callback_data.kind, "page": callback_data.page})
    if navigation.current_screen(user_id).kind == "library_tab":
        await navigation.replace_top(deps, user_id, screen)
    else:
        await navigation.goto(deps, user_id, callback.message.chat.id, screen)


@router.callback_query(LibraryCB.filter(F.action == "remove"))
async def on_library_remove(callback: CallbackQuery, callback_data: LibraryCB, deps: Deps) -> None:
    user_id = callback.from_user.id
    await deps.repo.library_remove(user_id, callback_data.kind, callback_data.source, callback_data.id)
    await callback.answer("Retiré de la bibliothèque.")
    await navigation.replace_top(
        deps, user_id, Screen("library_tab", {"kind": callback_data.kind, "page": callback_data.page})
    )
