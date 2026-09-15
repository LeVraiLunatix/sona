from __future__ import annotations

from math import ceil

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot import keyboards, navigation
from app.bot.callbacks import HistoryCB
from app.bot.deps import Deps
from app.bot.handlers.track import show_and_play_track
from app.bot.navigation import Screen
from app.bot.render import RenderTarget, show_text

router = Router(name="history")

PAGE_SIZE = keyboards.PAGE_SIZE


@navigation.register("history")
async def render_history(deps: Deps, target: RenderTarget, user_id: int, params: dict) -> RenderTarget:
    page = params.get("page", 1)
    offset = (page - 1) * PAGE_SIZE
    items, total = await deps.repo.history_list(user_id, offset=offset, limit=PAGE_SIZE)

    if total == 0:
        return await show_text(deps.bot, target, "Ton historique est vide.", keyboards.history_empty_keyboard())

    total_pages = max(1, ceil(total / PAGE_SIZE))
    page = max(1, min(page, total_pages))
    lines = []
    for it in items:
        artist_part = (it.subtitle or "").split(" • ")[0]
        lines.append(f"{artist_part} — {it.title}" if artist_part else it.title)
    text = "Récemment\n\n" + "\n".join(lines)
    markup = keyboards.history_keyboard(items, page, total_pages)
    return await show_text(deps.bot, target, text, markup)


@navigation.register("history_confirm_clear")
async def render_history_confirm(deps: Deps, target: RenderTarget, user_id: int, params: dict) -> RenderTarget:
    return await show_text(deps.bot, target, "Effacer tout l'historique ?", keyboards.history_clear_confirm_keyboard())


@router.message(Command("history"))
async def cmd_history(message: Message, deps: Deps) -> None:
    await navigation.goto(deps, message.from_user.id, message.chat.id, Screen("history"))


@router.callback_query(HistoryCB.filter(F.action == "menu"))
async def on_history_menu(callback: CallbackQuery, callback_data: HistoryCB, deps: Deps) -> None:
    await callback.answer()
    user_id = callback.from_user.id
    screen = Screen("history", {"page": callback_data.page})
    if navigation.current_screen(user_id).kind == "history":
        await navigation.replace_top(deps, user_id, screen)
    else:
        await navigation.goto(deps, user_id, callback.message.chat.id, screen)


@router.callback_query(HistoryCB.filter(F.action == "open"))
async def on_history_open(callback: CallbackQuery, callback_data: HistoryCB, deps: Deps) -> None:
    await callback.answer()
    await show_and_play_track(
        deps, callback.from_user.id, callback.message.chat.id, callback_data.source, callback_data.id
    )


@router.callback_query(HistoryCB.filter(F.action == "clear"))
async def on_history_clear(callback: CallbackQuery, deps: Deps) -> None:
    await callback.answer()
    await navigation.goto(deps, callback.from_user.id, callback.message.chat.id, Screen("history_confirm_clear"))


@router.callback_query(HistoryCB.filter(F.action == "clear_confirm"))
async def on_history_clear_confirm(callback: CallbackQuery, deps: Deps) -> None:
    user_id = callback.from_user.id
    await deps.repo.history_clear(user_id)
    await callback.answer("Historique effacé.")
    await navigation.replace_top(deps, user_id, Screen("history", {"page": 1}))


@router.callback_query(HistoryCB.filter(F.action == "clear_cancel"))
async def on_history_clear_cancel(callback: CallbackQuery, deps: Deps) -> None:
    await callback.answer()
    await navigation.back(deps, callback.from_user.id)
