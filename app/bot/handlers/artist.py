from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot import errors, keyboards, lookup, navigation
from app.bot.callbacks import ArtistCB
from app.bot.deps import Deps
from app.bot.handlers.track import play_all_tracks
from app.bot.navigation import Screen
from app.bot.render import RenderTarget, show_photo, show_text

logger = logging.getLogger(__name__)

router = Router(name="artist")


@navigation.register("artist")
async def render_artist(deps: Deps, target: RenderTarget, user_id: int, params: dict) -> RenderTarget:
    source, source_id = params["source"], params["id"]
    try:
        artist = await lookup.get_artist(deps, source, source_id)
    except lookup.ProviderErrors as exc:
        errors.log_and_hide(logger, "récupération artiste", exc)
        markup = keyboards.error_keyboard(ArtistCB(action="view", source=source, id=source_id).pack())
        return await show_text(deps.bot, target, errors.GENERIC_FETCH_FAILED, markup)

    markup = keyboards.artist_keyboard(artist)
    if artist.picture_url:
        return await show_photo(deps.bot, target, artist.picture_url, artist.name, markup)
    return await show_text(deps.bot, target, artist.name, markup)


@navigation.register("artist_top")
async def render_artist_top(deps: Deps, target: RenderTarget, user_id: int, params: dict) -> RenderTarget:
    source, source_id = params["source"], params["id"]
    retry_cb = ArtistCB(action="top", source=source, id=source_id).pack()
    try:
        artist = await lookup.get_artist(deps, source, source_id)
        tracks = await lookup.get_artist_top_tracks(deps, source, source_id)
    except lookup.ProviderErrors as exc:
        errors.log_and_hide(logger, "titres populaires", exc)
        return await show_text(deps.bot, target, errors.GENERIC_FETCH_FAILED, keyboards.error_keyboard(retry_cb))

    if not tracks:
        text = f"Aucun titre populaire disponible pour {artist.name}."
    else:
        lines = [f"{i}. {t.title}" for i, t in enumerate(tracks, start=1)]
        text = f"Titres populaires — {artist.name}\n\n" + "\n".join(lines)
    markup = keyboards.artist_top_tracks_keyboard(artist, tracks)
    return await show_text(deps.bot, target, text, markup)


@navigation.register("artist_albums_list")
async def render_artist_albums_list(deps: Deps, target: RenderTarget, user_id: int, params: dict) -> RenderTarget:
    source, source_id, mode = params["source"], params["id"], params["mode"]
    action = "albums" if mode == "albums" else "singles"
    retry_cb = ArtistCB(action=action, source=source, id=source_id).pack()
    try:
        artist = await lookup.get_artist(deps, source, source_id)
        albums, singles = await lookup.get_artist_albums(deps, source, source_id)
    except lookup.ProviderErrors as exc:
        errors.log_and_hide(logger, f"artiste ({mode})", exc)
        return await show_text(deps.bot, target, errors.GENERIC_FETCH_FAILED, keyboards.error_keyboard(retry_cb))

    items = albums if mode == "albums" else singles
    label = "Albums" if mode == "albums" else "Singles & EP"
    noun = "album" if mode == "albums" else "single/EP"
    text = f"Aucun {noun} disponible pour {artist.name}." if not items else f"{label} — {artist.name}"
    markup = keyboards.album_list_keyboard(items)
    return await show_text(deps.bot, target, text, markup)


@router.callback_query(ArtistCB.filter(F.action == "view"))
async def on_artist_view(callback: CallbackQuery, callback_data: ArtistCB, deps: Deps) -> None:
    await callback.answer()
    await navigation.goto(
        deps,
        callback.from_user.id,
        callback.message.chat.id,
        Screen("artist", {"source": callback_data.source, "id": callback_data.id}),
    )


@router.callback_query(ArtistCB.filter(F.action == "top"))
async def on_artist_top(callback: CallbackQuery, callback_data: ArtistCB, deps: Deps) -> None:
    await callback.answer()
    await navigation.goto(
        deps,
        callback.from_user.id,
        callback.message.chat.id,
        Screen("artist_top", {"source": callback_data.source, "id": callback_data.id}),
    )


@router.callback_query(ArtistCB.filter(F.action == "playall"))
async def on_artist_playall(callback: CallbackQuery, callback_data: ArtistCB, deps: Deps) -> None:
    """Envoie tous les titres populaires de l'artiste, comme « Tout écouter »
    sur un album."""
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    source, source_id = callback_data.source, callback_data.id
    # Après un redémarrage, la navigation (en mémoire) ne connaît plus ce
    # message : sans ça, « Envoi 1/10… » n'aurait nulle part où s'afficher.
    navigation.adopt_message(user_id, callback.message, Screen("artist_top", {"source": source, "id": source_id}))

    try:
        tracks = await lookup.get_artist_top_tracks(deps, source, source_id)
    except lookup.ProviderErrors as exc:
        await callback.answer()
        errors.log_and_hide(logger, "playall (titres populaires)", exc)
        await errors.show_error(deps, user_id, chat_id, errors.GENERIC_UNAVAILABLE, callback.data)
        return

    if not tracks:
        # Avant tout `answer()` : une requête callback déjà répondue ne peut
        # plus afficher d'alerte, et l'appui resterait sans explication.
        await callback.answer("Aucun titre à écouter.", show_alert=True)
        return

    await callback.answer()
    await play_all_tracks(deps, user_id, chat_id, tracks)


@router.callback_query(ArtistCB.filter(F.action == "albums"))
async def on_artist_albums(callback: CallbackQuery, callback_data: ArtistCB, deps: Deps) -> None:
    await callback.answer()
    await navigation.goto(
        deps,
        callback.from_user.id,
        callback.message.chat.id,
        Screen("artist_albums_list", {"source": callback_data.source, "id": callback_data.id, "mode": "albums"}),
    )


@router.callback_query(ArtistCB.filter(F.action == "singles"))
async def on_artist_singles(callback: CallbackQuery, callback_data: ArtistCB, deps: Deps) -> None:
    await callback.answer()
    await navigation.goto(
        deps,
        callback.from_user.id,
        callback.message.chat.id,
        Screen("artist_albums_list", {"source": callback_data.source, "id": callback_data.id, "mode": "singles"}),
    )


@router.callback_query(ArtistCB.filter(F.action == "search"))
async def on_artist_search(callback: CallbackQuery, callback_data: ArtistCB, deps: Deps) -> None:
    await callback.answer()
    try:
        artist = await lookup.get_artist(deps, callback_data.source, callback_data.id)
    except lookup.ProviderErrors:
        await callback.answer("Recherche indisponible pour le moment.", show_alert=True)
        return
    await navigation.goto(
        deps,
        callback.from_user.id,
        callback.message.chat.id,
        Screen("search_prompt", {"scope_name": artist.name}),
    )
