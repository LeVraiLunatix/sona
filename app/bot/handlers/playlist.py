"""Écran Playlist : même gabarit que l'album, espace d'identifiants à part.

Un lien de playlist Deezer était reconnu par `link_detect` mais refusé par
`links.py`, faute d'écran pour l'afficher. Il ne pouvait pas non plus passer
par l'écran Album : chez Deezer, les numéros de playlist et d'album vivent
dans deux espaces distincts — `/album/908622995` n'est pas
`/playlist/908622995`. D'où un écran, un callback (`PlaylistCB`) et un accès
(`lookup.get_playlist`) qui lui sont propres.
"""

from __future__ import annotations

import logging
from math import ceil

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot import errors, formatting, keyboards, lookup, navigation
from app.bot.callbacks import PlaylistCB
from app.bot.deps import Deps
from app.bot.handlers.track import play_all_tracks
from app.bot.navigation import Screen
from app.bot.render import RenderTarget, show_photo, show_text

logger = logging.getLogger(__name__)

router = Router(name="playlist")

PAGE_SIZE = keyboards.PAGE_SIZE


def _playlist_screen(callback_data: PlaylistCB) -> Screen:
    return Screen("playlist", {"source": callback_data.source, "id": callback_data.id})


@navigation.register("playlist")
async def render_playlist(deps: Deps, target: RenderTarget, user_id: int, params: dict) -> RenderTarget:
    source, source_id = params["source"], params["id"]
    page = params.get("page", 1)
    try:
        playlist = await lookup.get_playlist(deps, source, source_id)
    except lookup.ProviderErrors as exc:
        errors.log_and_hide(logger, "récupération playlist", exc)
        markup = keyboards.error_keyboard(PlaylistCB(action="view", source=source, id=source_id).pack())
        return await show_text(deps.bot, target, errors.GENERIC_FETCH_FAILED, markup)

    total_pages = max(1, ceil(len(playlist.tracks) / PAGE_SIZE)) if playlist.tracks else 1
    page = max(1, min(page, total_pages))
    start = (page - 1) * PAGE_SIZE
    page_tracks = playlist.tracks[start : start + PAGE_SIZE]

    meta = [
        formatting.tracks_label(playlist.track_count or len(playlist.tracks)),
        formatting.minutes_label(playlist.duration_seconds),
    ]
    header = [playlist.title, f"Playlist de {playlist.artist}", " • ".join(meta)]
    # L'artiste change d'un titre à l'autre : sans son nom, une playlist est
    # une liste de titres sans contexte.
    lines = [f"{start + i + 1}. {t.title} — {t.artist}" for i, t in enumerate(page_tracks)]
    text = "\n".join(header) + ("\n\n" + "\n".join(lines) if lines else "")
    markup = keyboards.playlist_keyboard(playlist, page, total_pages, page_tracks)

    if playlist.cover_url:
        return await show_photo(deps.bot, target, playlist.cover_url, text, markup)
    return await show_text(deps.bot, target, text, markup)


@router.callback_query(PlaylistCB.filter(F.action == "view"))
async def on_playlist_view(callback: CallbackQuery, callback_data: PlaylistCB, deps: Deps) -> None:
    await callback.answer()
    await navigation.goto(
        deps,
        callback.from_user.id,
        callback.message.chat.id,
        Screen("playlist", {"source": callback_data.source, "id": callback_data.id, "page": 1}),
    )


@router.callback_query(PlaylistCB.filter(F.action == "page"))
async def on_playlist_page(callback: CallbackQuery, callback_data: PlaylistCB, deps: Deps) -> None:
    await callback.answer()
    # Après un redémarrage, sans ça la page suivante partirait dans un nouveau message.
    navigation.adopt_message(callback.from_user.id, callback.message, _playlist_screen(callback_data))
    await navigation.replace_top(
        deps,
        callback.from_user.id,
        Screen(
            "playlist",
            {"source": callback_data.source, "id": callback_data.id, "page": callback_data.page},
        ),
    )


@router.callback_query(PlaylistCB.filter(F.action == "playall"))
async def on_playlist_playall(callback: CallbackQuery, callback_data: PlaylistCB, deps: Deps) -> None:
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    navigation.adopt_message(user_id, callback.message, _playlist_screen(callback_data))

    try:
        playlist = await lookup.get_playlist(deps, callback_data.source, callback_data.id)
    except lookup.ProviderErrors as exc:
        await callback.answer()
        errors.log_and_hide(logger, "playall (récupération playlist)", exc)
        await errors.show_error(deps, user_id, chat_id, errors.GENERIC_UNAVAILABLE, callback.data)
        return

    if not playlist.tracks:
        # Avant tout `answer()` : une requête callback déjà répondue ne peut
        # plus afficher d'alerte, et l'appui resterait sans explication.
        await callback.answer("Aucun morceau à écouter.", show_alert=True)
        return

    await callback.answer()
    await play_all_tracks(deps, user_id, chat_id, playlist.tracks)
