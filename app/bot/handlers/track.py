from __future__ import annotations

import logging
from contextlib import aclosing
from pathlib import Path
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
from app.services.audio_match import Verdict, verify_recording
from app.services.downloader import DownloadError, cleanup_download, download_and_tag
from app.services.resolver import ResolutionError, iter_audio_sources

logger = logging.getLogger(__name__)

router = Router(name="track")

StatusCallback = Callable[[str], Awaitable[None]]

# Sources téléchargées et comparées à l'extrait officiel avant d'abandonner.
# L'ordre (titre officiel YouTube Music, publications de l'artiste sur
# SoundCloud, puis reposts) met les meilleures chances en tête ; au-delà,
# chaque essai coûte un téléchargement complet pour peu d'espoir.
MAX_SOURCE_ATTEMPTS = 4


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
    téléchargement + vérification + envoi + mise en cache.

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

    attempts = 0
    try:
        async with aclosing(iter_audio_sources(track, deps.settings.youtube_cookies_file)) as sources:
            async for source in sources:
                attempts += 1
                if status_cb:
                    await status_cb("Préparation de l'audio…" if attempts == 1 else "Recherche d'une version fidèle…")
                try:
                    path = await download_and_tag(
                        deps.settings, source.source_url, track, user_settings.quality, user_settings.format
                    )
                except DownloadError as exc:
                    if source.platform == "youtube":
                        errors.log_and_hide(logger, "téléchargement audio", exc)
                        return errors.DOWNLOAD_FAILED
                    # Hors YouTube, l'échec vise ce titre-là (protégé par DRM,
                    # retiré…) : la source suivante peut très bien passer.
                    logger.info("Source %s inutilisable : %s", source.video_id, exc.__cause__ or exc)
                    if attempts >= MAX_SOURCE_ATTEMPTS:
                        break
                    continue

                verdict = await verify_recording(track, path, deps.settings.ffmpeg_path)
                if not verdict.rejected:
                    _log_verdict(source.video_id, verdict)
                    return await _send_downloaded_audio(deps, chat_id, track, user_settings, path, status_cb)

                logger.info(
                    "Audio %s écarté pour %s — %s : %s",
                    source.video_id, track.artist, track.title,
                    verdict.reason or f"écart d'empreinte {verdict.error:.3f} avec l'extrait officiel",
                )
                cleanup_download(path)
                if attempts >= MAX_SOURCE_ATTEMPTS:
                    break
    except ResolutionError as exc:
        errors.log_and_hide(logger, "résolution YouTube", exc)
        return errors.SOURCE_SEARCH_FAILED

    if attempts == 0:
        logger.info("Aucune source YouTube pour %s — %s", track.artist, track.title)
        return errors.NO_SOURCE_FOUND
    logger.info("Aucune version fidèle sur YouTube pour %s — %s (%d essai(s))", track.artist, track.title, attempts)
    return errors.NO_FAITHFUL_SOURCE


def _log_verdict(video_id: str, verdict: Verdict) -> None:
    if verdict.error is None:
        logger.info("Audio %s envoyé sans vérification : %s", video_id, verdict.reason)
    else:
        logger.info("Audio %s vérifié : écart d'empreinte %.3f", video_id, verdict.error)


async def _send_downloaded_audio(
    deps: Deps,
    chat_id: int,
    track: TrackInfo,
    user_settings: UserSettings,
    path: Path,
    status_cb: StatusCallback | None,
) -> str | None:
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
