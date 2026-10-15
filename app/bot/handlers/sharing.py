"""Liens de partage dans le bot (services/share.py) : « 🔗 Partager » sur
les fiches Titre et Album, « /partages » pour les retrouver et les révoquer,
et l'ouverture d'un lien reçu (`t.me/<bot>?start=s_<jeton>`, bouton
« Ouvrir dans Telegram » de la page publique).

Un lien n'ouvre rien de plus qu'une page d'extraits pour qui n'est pas
membre : le filtre de whitelist garde le bot fermé aux autres.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot import navigation
from app.bot.callbacks import ShareCB
from app.bot.deps import Deps
from app.bot.handlers.track import play_all_tracks
from app.bot.navigation import Screen
from app.services import share

logger = logging.getLogger(__name__)

router = Router(name="sharing")

PLAY_LIMIT = 30
NO_BASE_URL = (
    "Les liens de partage ne sont pas encore activés : il manque l'adresse publique "
    "du serveur (SHARE_BASE_URL dans le .env)."
)


def _link_markup(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🗑 Révoquer ce lien", callback_data=ShareCB(action="revoke", token=token).pack()),
    ]])


@router.callback_query(ShareCB.filter(F.action == "make"))
async def on_make(callback: CallbackQuery, callback_data: ShareCB, deps: Deps) -> None:
    if not deps.settings.share_base_url:
        await callback.answer(NO_BASE_URL, show_alert=True)
        return
    try:
        link = await share.create(deps, callback.from_user.id, callback_data.kind, callback_data.source, callback_data.id)
    except share.ShareError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer("Lien prêt")
    url = share.public_url(deps.settings, link.token)
    await callback.message.answer(
        f"🔗 {link.title}{f' — {link.subtitle}' if link.subtitle else ''}\n{url}\n\n"
        "Page publique : pochette et extraits de 30 s, jamais le titre complet. "
        "Les membres de Sona l'ouvrent dans l'app ou ici.",
        reply_markup=_link_markup(link.token),
        disable_web_page_preview=False,
    )


@router.message(Command("partages"))
async def cmd_shares(message: Message, deps: Deps) -> None:
    links = [link for link in await deps.repo.share_list(message.from_user.id) if link.active]
    if not links:
        await message.answer("Aucun lien de partage actif.\nUn titre ou un album se partage avec « 🔗 Partager » sur sa fiche.")
        return
    lines, rows = [], []
    for i, link in enumerate(links[:15], start=1):
        expiry = f" · expire le {link.expires_at[:10]}" if link.expires_at else ""
        lines.append(f"{i}. {link.title} ({share.KIND_LABELS[link.kind].lower()}) · {link.views} vue{'s' if link.views > 1 else ''}{expiry}")
        rows.append([InlineKeyboardButton(text=f"🗑 Révoquer {i}", callback_data=ShareCB(action="revoke", token=link.token).pack())])
    await message.answer("🔗 Tes liens de partage\n\n" + "\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(ShareCB.filter(F.action == "revoke"))
async def on_revoke(callback: CallbackQuery, callback_data: ShareCB, deps: Deps) -> None:
    if await deps.repo.share_revoke(callback.from_user.id, callback_data.token):
        share.reset()
        await callback.answer("Lien révoqué : la page n'existe plus.", show_alert=True)
    else:
        await callback.answer("Lien déjà révoqué.")


async def open_shared(deps: Deps, message: Message, token: str) -> None:
    """Lien de partage ouvert dans le bot par un membre."""
    link = await share.resolve(deps, token)
    user_id, chat_id = message.from_user.id, message.chat.id
    if link is None:
        await message.answer("Ce lien de partage n'existe plus (expiré ou révoqué).")
        return
    if link.kind == "track":
        navigation.detach(user_id, chat_id)
        await navigation.goto(deps, user_id, chat_id, Screen("track", {"source": link.source, "id": link.ref}), reset=True)
        return
    if link.kind == "album":
        navigation.detach(user_id, chat_id)
        await navigation.goto(deps, user_id, chat_id, Screen("album", {"source": link.source, "id": link.ref, "page": 1}), reset=True)
        return
    tracks = await share.tracks(deps, link)
    listing = "\n".join(f"{i}. {t.title} — {t.artist}" for i, t in enumerate(tracks[:10], start=1))
    more = f"\n… et {len(tracks) - 10} autres" if len(tracks) > 10 else ""
    await message.answer(
        f"🎧 Playlist partagée : {link.title}\n{link.subtitle or ''}\n\n{listing}{more}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="▶️ Écouter", callback_data=ShareCB(action="play", token=link.token).pack()),
        ]]),
    )


@router.callback_query(ShareCB.filter(F.action == "play"))
async def on_play(callback: CallbackQuery, callback_data: ShareCB, deps: Deps) -> None:
    link = await share.resolve(deps, callback_data.token)
    if link is None:
        await callback.answer("Ce lien n'existe plus.", show_alert=True)
        return
    tracks = (await share.tracks(deps, link))[:PLAY_LIMIT]
    await callback.answer(f"Envoi de {len(tracks)} titres")
    await play_all_tracks(deps, callback.from_user.id, callback.message.chat.id, tracks)
