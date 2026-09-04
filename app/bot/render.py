from __future__ import annotations

from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, InputMediaPhoto


@dataclass(slots=True)
class RenderTarget:
    chat_id: int
    message_id: int | None
    is_photo: bool


async def show_text(
    bot: Bot, target: RenderTarget, text: str, markup: InlineKeyboardMarkup | None
) -> RenderTarget:
    if target.message_id and not target.is_photo:
        try:
            await bot.edit_message_text(
                text,
                chat_id=target.chat_id,
                message_id=target.message_id,
                reply_markup=markup,
            )
            return target
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc):
                return target
            # Message introuvable / trop vieux : on retombe sur un nouvel envoi.

    if target.message_id:
        try:
            await bot.delete_message(target.chat_id, target.message_id)
        except TelegramBadRequest:
            pass

    msg = await bot.send_message(target.chat_id, text, reply_markup=markup)
    return RenderTarget(target.chat_id, msg.message_id, is_photo=False)


async def update_in_place(
    bot: Bot, target: RenderTarget, text: str, markup: InlineKeyboardMarkup | None = None
) -> RenderTarget:
    """Édite le texte ou la légende du message courant sans changer son type.

    À utiliser pour les états transitoires (chargement, erreur en place) où
    l'on ne veut ni supprimer une photo existante ni changer la pile de nav.
    """
    try:
        if target.is_photo:
            await bot.edit_message_caption(
                chat_id=target.chat_id,
                message_id=target.message_id,
                caption=text,
                reply_markup=markup,
            )
        else:
            await bot.edit_message_text(
                text,
                chat_id=target.chat_id,
                message_id=target.message_id,
                reply_markup=markup,
            )
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            raise
    return target


async def show_photo(
    bot: Bot,
    target: RenderTarget,
    photo: str,
    caption: str,
    markup: InlineKeyboardMarkup | None,
) -> RenderTarget:
    if target.message_id and target.is_photo:
        try:
            media = InputMediaPhoto(media=photo, caption=caption)
            await bot.edit_message_media(
                media=media,
                chat_id=target.chat_id,
                message_id=target.message_id,
                reply_markup=markup,
            )
            return target
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc):
                return target

    if target.message_id:
        try:
            await bot.delete_message(target.chat_id, target.message_id)
        except TelegramBadRequest:
            pass

    msg = await bot.send_photo(target.chat_id, photo=photo, caption=caption, reply_markup=markup)
    return RenderTarget(target.chat_id, msg.message_id, is_photo=True)
