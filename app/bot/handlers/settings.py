from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot import keyboards, navigation
from app.bot.callbacks import SettingsCB
from app.bot.deps import Deps
from app.bot.navigation import Screen
from app.bot.render import RenderTarget, show_text
from app.db.repository import FORMAT_CHOICES, QUALITY_CHOICES

router = Router(name="settings")


@navigation.register("settings_menu")
async def render_settings_menu(deps: Deps, target: RenderTarget, user_id: int, params: dict) -> RenderTarget:
    s = await deps.repo.get_settings(user_id)
    text = (
        "Paramètres\n\n"
        f"Qualité audio : {QUALITY_CHOICES[s.quality]}\n"
        f"Format : {FORMAT_CHOICES[s.format]}\n"
        f"Notifications : {'Activées' if s.notifications else 'Désactivées'}"
    )
    return await show_text(deps.bot, target, text, keyboards.settings_menu_keyboard())


@navigation.register("settings_quality")
async def render_settings_quality(deps: Deps, target: RenderTarget, user_id: int, params: dict) -> RenderTarget:
    s = await deps.repo.get_settings(user_id)
    return await show_text(deps.bot, target, "Qualité audio", keyboards.settings_quality_keyboard(s.quality))


@navigation.register("settings_format")
async def render_settings_format(deps: Deps, target: RenderTarget, user_id: int, params: dict) -> RenderTarget:
    s = await deps.repo.get_settings(user_id)
    return await show_text(deps.bot, target, "Format", keyboards.settings_format_keyboard(s.format))


@router.message(Command("settings"))
async def cmd_settings(message: Message, deps: Deps) -> None:
    await navigation.goto(deps, message.from_user.id, message.chat.id, Screen("settings_menu"))


@router.callback_query(SettingsCB.filter(F.action == "menu"))
async def on_settings_menu(callback: CallbackQuery, deps: Deps) -> None:
    await callback.answer()
    await navigation.goto(deps, callback.from_user.id, callback.message.chat.id, Screen("settings_menu"))


@router.callback_query(SettingsCB.filter(F.action == "quality"))
async def on_settings_quality(callback: CallbackQuery, deps: Deps) -> None:
    await callback.answer()
    await navigation.goto(deps, callback.from_user.id, callback.message.chat.id, Screen("settings_quality"))


@router.callback_query(SettingsCB.filter(F.action == "quality_set"))
async def on_settings_quality_set(callback: CallbackQuery, callback_data: SettingsCB, deps: Deps) -> None:
    user_id = callback.from_user.id
    await deps.repo.set_quality(user_id, callback_data.value)
    await callback.answer("Qualité mise à jour.")
    await navigation.rerender(deps, user_id)


@router.callback_query(SettingsCB.filter(F.action == "format"))
async def on_settings_format(callback: CallbackQuery, deps: Deps) -> None:
    await callback.answer()
    await navigation.goto(deps, callback.from_user.id, callback.message.chat.id, Screen("settings_format"))


@router.callback_query(SettingsCB.filter(F.action == "format_set"))
async def on_settings_format_set(callback: CallbackQuery, callback_data: SettingsCB, deps: Deps) -> None:
    user_id = callback.from_user.id
    await deps.repo.set_format(user_id, callback_data.value)
    await callback.answer("Format mis à jour.")
    await navigation.rerender(deps, user_id)


@router.callback_query(SettingsCB.filter(F.action == "notif_toggle"))
async def on_settings_notif_toggle(callback: CallbackQuery, deps: Deps) -> None:
    user_id = callback.from_user.id
    new_value = await deps.repo.toggle_notifications(user_id)
    await callback.answer("Notifications activées." if new_value else "Notifications désactivées.")
    await navigation.rerender(deps, user_id)
