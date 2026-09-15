from __future__ import annotations

import logging
from math import ceil

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot import errors, formatting, keyboards, lookup, navigation
from app.bot.callbacks import AlbumCB
from app.bot.deps import Deps
from app.bot.handlers.track import deliver_track_audio
from app.bot.navigation import Screen
from app.bot.render import RenderTarget, show_photo, show_text, update_in_place
from app.services import antispam

logger = logging.getLogger(__name__)

router = Router(name="album")

PAGE_SIZE = keyboards.PAGE_SIZE


@navigation.register("album")
async def render_album(deps: Deps, target: RenderTarget, user_id: int, params: dict) -> RenderTarget:
    source, source_id = params["source"], params["id"]
    page = params.get("page", 1)
    try:
        album = await lookup.get_album(deps, source, source_id)
    except lookup.ProviderErrors as exc:
        errors.log_and_hide(logger, "récupération album", exc)
        markup = keyboards.error_keyboard(AlbumCB(action="view", source=source, id=source_id).pack())
        return await show_text(deps.bot, target, errors.GENERIC_FETCH_FAILED, markup)

    in_library = await deps.repo.library_contains(user_id, "album", source, source_id)
    total_pages = max(1, ceil(len(album.tracks) / PAGE_SIZE)) if album.tracks else 1
    page = max(1, min(page, total_pages))
    start = (page - 1) * PAGE_SIZE
    page_tracks = album.tracks[start : start + PAGE_SIZE]

    meta = []
    if album.year:
        meta.append(album.year)
    meta.append(formatting.tracks_label(album.track_count or len(album.tracks)))
    meta.append(formatting.minutes_label(album.duration_seconds))
    header = [album.title, album.artist, " • ".join(meta)]
    lines = [f"{start + i + 1}. {t.title}" for i, t in enumerate(page_tracks)]
    text = "\n".join(header) + ("\n\n" + "\n".join(lines) if lines else "")
    markup = keyboards.album_keyboard(album, in_library, page, total_pages, page_tracks)

    if album.cover_url:
        return await show_photo(deps.bot, target, album.cover_url, text, markup)
    return await show_text(deps.bot, target, text, markup)


@router.callback_query(AlbumCB.filter(F.action == "view"))
async def on_album_view(callback: CallbackQuery, callback_data: AlbumCB, deps: Deps) -> None:
    await callback.answer()
    await navigation.goto(
        deps,
        callback.from_user.id,
        callback.message.chat.id,
        Screen("album", {"source": callback_data.source, "id": callback_data.id, "page": 1}),
    )


@router.callback_query(AlbumCB.filter(F.action == "page"))
async def on_album_page(callback: CallbackQuery, callback_data: AlbumCB, deps: Deps) -> None:
    await callback.answer()
    await navigation.replace_top(
        deps,
        callback.from_user.id,
        Screen("album", {"source": callback_data.source, "id": callback_data.id, "page": callback_data.page}),
    )


@router.callback_query(AlbumCB.filter(F.action.in_({"lib_add", "lib_del"})))
async def on_album_library_toggle(callback: CallbackQuery, callback_data: AlbumCB, deps: Deps) -> None:
    user_id = callback.from_user.id
    if callback_data.action == "lib_add":
        try:
            album = await lookup.get_album(deps, callback_data.source, callback_data.id)
        except lookup.ProviderErrors:
            await callback.answer("Impossible d'ajouter cet album.", show_alert=True)
            return
        await deps.repo.library_add(user_id, "album", album)
        await callback.answer("Ajouté à la bibliothèque.")
    else:
        await deps.repo.library_remove(user_id, "album", callback_data.source, callback_data.id)
        await callback.answer("Retiré de la bibliothèque.")
    await navigation.rerender(deps, user_id)


@router.callback_query(AlbumCB.filter(F.action == "playall"))
async def on_album_playall(callback: CallbackQuery, callback_data: AlbumCB, deps: Deps) -> None:
    await callback.answer()
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id

    try:
        album = await lookup.get_album(deps, callback_data.source, callback_data.id)
    except lookup.ProviderErrors as exc:
        errors.log_and_hide(logger, "playall (récupération album)", exc)
        await errors.show_error(deps, user_id, chat_id, errors.GENERIC_UNAVAILABLE, callback.data)
        return

    tracks = album.tracks
    if not tracks:
        await callback.answer("Aucun morceau à écouter.", show_alert=True)
        return

    user_settings = await deps.repo.get_settings(user_id)
    total = len(tracks)
    failed = 0
    for i, track in enumerate(tracks, start=1):
        track_uid = f"{track.source}:{track.source_id}"
        if not antispam.try_acquire(user_id, track_uid):
            continue
        try:
            target = navigation.current_target(user_id)
            target = await update_in_place(deps.bot, target, f"Envoi {i}/{total}…")
            navigation.set_target(user_id, target)
            if await deliver_track_audio(deps, chat_id, track, user_settings):
                failed += 1
        except Exception as exc:
            failed += 1
            errors.log_and_hide(logger, "playall (envoi morceau)", exc)
        finally:
            antispam.release(user_id, track_uid)

    await navigation.rerender(deps, user_id)
    if failed:
        # Message à part plutôt qu'une réponse au callback : « Tout écouter »
        # dure parfois plusieurs minutes, et la requête callback est alors
        # expirée côté Telegram. Sans ce mot, l'utilisateur doit compter
        # lui-même les morceaux reçus.
        await deps.bot.send_message(
            chat_id, f"{failed} morceau(x) sur {total} n'ont pas pu être envoyés."
        )
