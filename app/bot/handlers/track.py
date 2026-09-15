from __future__ import annotations

import logging
from typing import Awaitable, Callable

from aiogram import F, Router
from aiogram.types import CallbackQuery, FSInputFile

from app.bot import errors, keyboards, lookup, navigation
from app.bot.callbacks import TrackCB
from app.bot.deps import Deps
from app.bot.navigation import Screen
from app.bot.render import RenderTarget, show_photo, show_text, update_in_place
from app.db.repository import UserSettings
from app.providers.base import TrackInfo
from app.services import antispam
from app.services.downloader import DownloadError, cleanup_download, download_and_tag
from app.services.resolver import ResolutionError, find_youtube_match

logger = logging.getLogger(__name__)

router = Router(name="track")

StatusCallback = Callable[[str], Awaitable[None]]


def _build_text(track: TrackInfo) -> str:
    lines = [track.title, track.artist]
    detail = track.album or ""
    if track.year:
        detail = f"{detail} • {track.year}" if detail else track.year
    if detail:
        lines.append(detail)
    lines.append(track.duration_label)
    return "\n".join(lines)


@navigation.register("track")
async def render_track(deps: Deps, target: RenderTarget, user_id: int, params: dict) -> RenderTarget:
    source, source_id = params["source"], params["id"]
    try:
        track = await lookup.get_track(deps, source, source_id)
    except lookup.ProviderErrors as exc:
        errors.log_and_hide(logger, "récupération morceau", exc)
        markup = keyboards.error_keyboard(TrackCB(action="view", source=source, id=source_id).pack())
        return await show_text(deps.bot, target, errors.GENERIC_FETCH_FAILED, markup)

    await deps.repo.history_add(user_id, track)
    in_library = await deps.repo.library_contains(user_id, "track", source, source_id)
    text = _build_text(track)
    markup = keyboards.track_keyboard(track, in_library)
    if track.cover_url:
        return await show_photo(deps.bot, target, track.cover_url, text, markup)
    return await show_text(deps.bot, target, text, markup)


@router.callback_query(TrackCB.filter(F.action == "view"))
async def on_track_view(callback: CallbackQuery, callback_data: TrackCB, deps: Deps) -> None:
    await callback.answer()
    await navigation.goto(
        deps,
        callback.from_user.id,
        callback.message.chat.id,
        Screen("track", {"source": callback_data.source, "id": callback_data.id}),
    )


@router.callback_query(TrackCB.filter(F.action.in_({"lib_add", "lib_del"})))
async def on_track_library_toggle(callback: CallbackQuery, callback_data: TrackCB, deps: Deps) -> None:
    user_id = callback.from_user.id
    if callback_data.action == "lib_add":
        try:
            track = await lookup.get_track(deps, callback_data.source, callback_data.id)
        except lookup.ProviderErrors:
            await callback.answer("Impossible d'ajouter ce morceau.", show_alert=True)
            return
        await deps.repo.library_add(user_id, "track", track)
        await callback.answer("Ajouté à la bibliothèque.")
    else:
        await deps.repo.library_remove(user_id, "track", callback_data.source, callback_data.id)
        await callback.answer("Retiré de la bibliothèque.")
    await navigation.rerender(deps, user_id)


async def _send_cached_audio(deps: Deps, chat_id: int, file_id: str, track: TrackInfo) -> None:
    await deps.bot.send_audio(
        chat_id,
        audio=file_id,
        title=track.title,
        performer=track.artist,
        duration=track.duration_seconds or 0,
    )


async def deliver_track_audio(
    deps: Deps,
    chat_id: int,
    track: TrackInfo,
    user_settings: UserSettings,
    status_cb: StatusCallback | None = None,
) -> str | None:
    """Envoie l'audio d'un morceau dans `chat_id` : cache, sinon résolution +
    téléchargement + envoi + mise en cache.

    Retourne None si l'envoi a réussi, sinon le message d'erreur à afficher.
    Distinguer les causes compte : « aucune source trouvée » invite à choisir
    une autre version, alors qu'un échec de téléchargement vaut la peine d'être
    réessayé tel quel.
    """
    cached_file_id = await deps.repo.cache_get(
        track.source, track.source_id, user_settings.format, user_settings.quality
    )
    if cached_file_id:
        try:
            await _send_cached_audio(deps, chat_id, cached_file_id, track)
            return None
        except Exception as exc:  # file_id périmé côté Telegram : on retélécharge
            errors.log_and_hide(logger, "envoi depuis cache", exc)

    if status_cb:
        await status_cb("Recherche de la source…" if track.source != "youtube" else "Préparation de l'audio…")
    try:
        match = await find_youtube_match(track, deps.settings.youtube_cookies_file)
    except ResolutionError as exc:
        errors.log_and_hide(logger, "résolution YouTube", exc)
        return errors.SOURCE_SEARCH_FAILED
    if match is None:
        logger.info("Aucune source YouTube pour %s — %s", track.artist, track.title)
        return errors.NO_SOURCE_FOUND
    video_id, _matched = match

    if status_cb:
        await status_cb("Préparation de l'audio…")
    try:
        path = await download_and_tag(
            deps.settings, video_id, track, user_settings.quality, user_settings.format
        )
    except DownloadError as exc:
        errors.log_and_hide(logger, "téléchargement audio", exc)
        return errors.DOWNLOAD_FAILED

    if status_cb:
        await status_cb("Envoi…")
    try:
        sent = await deps.bot.send_audio(
            chat_id,
            audio=FSInputFile(path, filename=f"{track.artist} - {track.title}{path.suffix}"),
            title=track.title,
            performer=track.artist,
            duration=track.duration_seconds or 0,
        )
    except Exception as exc:
        errors.log_and_hide(logger, "envoi audio", exc)
        return errors.SEND_FAILED
    finally:
        cleanup_download(path)

    if sent.audio:
        await deps.repo.cache_set(
            track.source,
            track.source_id,
            user_settings.format,
            user_settings.quality,
            sent.audio.file_id,
            sent.audio.file_unique_id,
        )
    return None


@router.callback_query(TrackCB.filter(F.action == "play"))
async def on_track_play(callback: CallbackQuery, callback_data: TrackCB, deps: Deps) -> None:
    await callback.answer()
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    source, source_id = callback_data.source, callback_data.id
    track_uid = f"{source}:{source_id}"
    retry_data = callback.data

    if not antispam.try_acquire(user_id, track_uid):
        await callback.answer("Préparation déjà en cours…", show_alert=False)
        return

    try:
        try:
            track = await lookup.get_track(deps, source, source_id)
        except lookup.ProviderErrors as exc:
            errors.log_and_hide(logger, "lecture (récupération morceau)", exc)
            await errors.show_error(deps, user_id, chat_id, errors.GENERIC_UNAVAILABLE, retry_data)
            return

        user_settings = await deps.repo.get_settings(user_id)

        # Fichier déjà en cache : envoi immédiat, sans le moindre message de
        # chargement (voir docs/UX_FLOW.md § 4bis).
        cached_file_id = await deps.repo.cache_get(
            source, source_id, user_settings.format, user_settings.quality
        )
        if cached_file_id:
            try:
                await _send_cached_audio(deps, chat_id, cached_file_id, track)
                return
            except Exception as exc:  # file_id périmé côté Telegram : flux normal ci-dessous
                errors.log_and_hide(logger, "envoi depuis cache", exc)

        async def status_cb(text: str) -> None:
            target = navigation.current_target(user_id)
            target = await update_in_place(deps.bot, target, text)
            navigation.set_target(user_id, target)

        await status_cb("Préparation du morceau…")
        failure = await deliver_track_audio(deps, chat_id, track, user_settings, status_cb)
        if failure:
            await errors.show_error(deps, user_id, chat_id, failure, retry_data)
            return

        await navigation.rerender(deps, user_id)
    except Exception as exc:
        # Sans ce filet, une exception imprévue laisse l'écran bloqué sur
        # « Préparation… » : côté utilisateur, le bouton n'a rien fait.
        errors.log_and_hide(logger, "lecture", exc)
        try:
            await errors.show_error(deps, user_id, chat_id, errors.GENERIC_UNAVAILABLE, retry_data)
        except Exception as report_exc:
            errors.log_and_hide(logger, "affichage de l'erreur de lecture", report_exc)
    finally:
        antispam.release(user_id, track_uid)
