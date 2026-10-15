"""Import de playlists dans le bot : « /importer <lien> » (Deezer, Spotify,
Apple Music, YouTube / YouTube Music, SoundCloud — playlists et likes), ou
un lien de playlist collé que le bot ne sait pas afficher.

Le message d'import se met à jour tout seul (barre d'avancement), puis
devient le rapport : trouvés, à vérifier, introuvables. Chaque titre à
vérifier se valide ou se retire d'un bouton ; « Resynchroniser » récupère
les titres ajoutés depuis à la playlist d'origine. « /playlists » liste les
playlists importées.

Mêmes playlists et même service que l'app (services/playlist_import.py),
dans l'espace de données du compte Telegram.
"""

from __future__ import annotations

import asyncio
import logging
import time

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.callbacks import ImportCB
from app.bot.deps import Deps
from app.bot.handlers.track import play_all_tracks
from app.db.repository import Playlist
from app.services import playlist_import

logger = logging.getLogger(__name__)

router = Router(name="imports")

# Titres du rapport par page (un message Telegram reste lisible).
REPORT_PAGE = 5
# « Écouter » envoie les premiers titres : au-delà, mieux vaut l'app.
PLAY_LIMIT = 30
# Suivi d'un import : un pas toutes les 2,5 s (limite d'édition de Telegram),
# abandonné au bout de 20 min.
WATCH_EVERY = 2.5
WATCH_FOR = 20 * 60

# Lien de playlist collé, en attente du bouton « Importer » (par compte).
_pending: dict[int, str] = {}
_watchers: set[asyncio.Task] = set()

STATUS_LABELS = {"uncertain": "À vérifier", "missing": "Introuvables", "found": "Trouvés"}


def _bar(done: int, total: int | None, width: int = 12) -> str:
    if not total:
        return "▱" * width
    filled = round(width * min(done, total) / total)
    return "▰" * filled + "▱" * (width - filled)


def _summary(playlist: Playlist, counts: dict[str, int]) -> str:
    found, uncertain, missing = (counts.get(k, 0) for k in ("found", "uncertain", "missing"))
    lines = [f"🎧 {playlist.name}", f"{playlist.track_count} titres dans Sona"]
    parts = [f"✅ {found} trouvé{'s' if found > 1 else ''}"]
    if uncertain:
        parts.append(f"⚠️ {uncertain} à vérifier")
    if missing:
        parts.append(f"❌ {missing} introuvable{'s' if missing > 1 else ''}")
    lines.append(" · ".join(parts))
    if playlist.import_added:
        lines.append(f"➕ {playlist.import_added} nouveau{'x' if playlist.import_added > 1 else ''} titre{'s' if playlist.import_added > 1 else ''} à la dernière resynchro")
    if playlist.import_error:
        lines.append(f"ℹ️ {playlist.import_error}")
    return "\n".join(lines)


def _report_keyboard(playlist: Playlist, counts: dict[str, int]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="▶️ Écouter", callback_data=ImportCB(action="play", pid=playlist.id).pack())]]
    filters = [
        InlineKeyboardButton(
            text=f"{'⚠️' if key == 'uncertain' else '❌'} {STATUS_LABELS[key]} ({counts[key]})",
            callback_data=ImportCB(action="report", pid=playlist.id, status=key).pack(),
        )
        for key in ("uncertain", "missing") if counts.get(key)
    ]
    if filters:
        rows.append(filters)
    if playlist.origin_url:
        rows.append([InlineKeyboardButton(text="🔄 Resynchroniser", callback_data=ImportCB(action="sync", pid=playlist.id).pack())])
    rows.append([InlineKeyboardButton(text="📚 Mes playlists", callback_data=ImportCB(action="list").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _edit(message: Message, text: str, markup: InlineKeyboardMarkup | None) -> None:
    try:
        await message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as exc:
        if "not modified" not in str(exc):
            raise


async def _show_summary(deps: Deps, message: Message, user_id: int, playlist_id: int) -> None:
    playlist = await deps.repo.playlist_get(user_id, playlist_id)
    if playlist is None:
        await _edit(message, "Cette playlist n'existe plus.", None)
        return
    if playlist.import_status == "failed":
        await _edit(message, f"❌ Import impossible : {playlist.import_error or 'erreur inconnue'}", None)
        return
    counts = await deps.repo.import_counts(playlist_id)
    await _edit(message, _summary(playlist, counts), _report_keyboard(playlist, counts))


async def _watch(deps: Deps, message: Message, user_id: int, playlist_id: int) -> None:
    """Fait avancer la barre du message jusqu'à la fin de l'import."""
    deadline = time.monotonic() + WATCH_FOR
    shown = ""
    while time.monotonic() < deadline:
        playlist = await deps.repo.playlist_get(user_id, playlist_id)
        if playlist is None:
            return
        if playlist.import_status != "importing":
            await _show_summary(deps, message, user_id, playlist_id)
            return
        if playlist.import_total:
            text = (
                f"📥 Import en cours… {playlist.name if playlist.name != 'Import en cours…' else ''}\n"
                f"{_bar(playlist.import_done, playlist.import_total)} {playlist.import_done}/{playlist.import_total}\n"
                "Chaque titre est rapproché du catalogue (titre, artiste, version, durée)."
            )
        else:
            text = "📥 Lecture de la playlist…"
        if text != shown:
            try:
                await _edit(message, text, None)
            except Exception as exc:  # noqa: BLE001 — le suivi n'est qu'un confort
                logger.debug("Suivi d'import : %s", exc)
            shown = text
        await asyncio.sleep(WATCH_EVERY)


def _follow(deps: Deps, message: Message, user_id: int, playlist_id: int) -> None:
    task = asyncio.create_task(_watch(deps, message, user_id, playlist_id))
    _watchers.add(task)
    task.add_done_callback(_watchers.discard)


async def start(deps: Deps, message: Message, user_id: int, text: str) -> None:
    """Lance l'import d'un lien et suit son avancement dans un message."""
    try:
        playlist_id = await playlist_import.start_import(deps, user_id, text)
    except playlist_import.PlaylistImportError as exc:
        await message.answer(f"❌ {exc}")
        return
    status = await message.answer("📥 Lecture de la playlist…")
    _follow(deps, status, user_id, playlist_id)


def offer(user_id: int, url: str, source_label: str) -> tuple[str, InlineKeyboardMarkup]:
    """Lien de playlist que le bot n'affiche pas : on propose l'import."""
    _pending[user_id] = url
    text = (
        f"Playlist {source_label} détectée.\n"
        "Je peux l'importer dans tes playlists Sona : chaque titre est retrouvé au "
        "catalogue, avec un rapport de ce qui est sûr, à vérifier ou introuvable."
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📥 Importer", callback_data=ImportCB(action="go").pack()),
    ]])
    return text, markup


@router.message(Command("importer", "import"))
async def cmd_import(message: Message, command: CommandObject, deps: Deps) -> None:
    if not (command.args or "").strip():
        await message.answer(
            "Colle le lien d'une playlist après la commande :\n"
            "/importer https://open.spotify.com/playlist/…\n\n"
            "Deezer, Spotify, Apple Music, YouTube, YouTube Music et SoundCloud "
            "(playlists et likes publics)."
        )
        return
    await start(deps, message, message.from_user.id, command.args)


@router.message(Command("playlists"))
async def cmd_playlists(message: Message, deps: Deps) -> None:
    text, markup = await _list(deps, message.from_user.id)
    await message.answer(text, reply_markup=markup)


async def _list(deps: Deps, user_id: int) -> tuple[str, InlineKeyboardMarkup | None]:
    playlists = [p for p in await deps.repo.playlist_list(user_id) if p.origin]
    if not playlists:
        return ("Aucune playlist importée pour l'instant.\nColle un lien de playlist, ou /importer <lien>.", None)
    rows = []
    for p in playlists[:20]:
        flag = " ⚠️" if p.import_uncertain else ""
        rows.append([InlineKeyboardButton(
            text=f"{p.name} · {p.track_count}{flag}", callback_data=ImportCB(action="view", pid=p.id).pack(),
        )])
    return "📚 Tes playlists importées", InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(ImportCB.filter(F.action == "go"))
async def on_go(callback: CallbackQuery, deps: Deps) -> None:
    url = _pending.pop(callback.from_user.id, None)
    if url is None:
        await callback.answer("Lien expiré : colle-le de nouveau.", show_alert=True)
        return
    await callback.answer()
    try:
        playlist_id = await playlist_import.start_import(deps, callback.from_user.id, url)
    except playlist_import.PlaylistImportError as exc:
        await _edit(callback.message, f"❌ {exc}", None)
        return
    await _edit(callback.message, "📥 Lecture de la playlist…", None)
    _follow(deps, callback.message, callback.from_user.id, playlist_id)


@router.callback_query(ImportCB.filter(F.action == "list"))
async def on_list(callback: CallbackQuery, deps: Deps) -> None:
    await callback.answer()
    text, markup = await _list(deps, callback.from_user.id)
    await _edit(callback.message, text, markup)


@router.callback_query(ImportCB.filter(F.action == "view"))
async def on_view(callback: CallbackQuery, callback_data: ImportCB, deps: Deps) -> None:
    await callback.answer()
    playlist = await deps.repo.playlist_get(callback.from_user.id, callback_data.pid)
    if playlist is not None and playlist.import_status == "importing":
        _follow(deps, callback.message, callback.from_user.id, playlist.id)
        return
    await _show_summary(deps, callback.message, callback.from_user.id, callback_data.pid)


@router.callback_query(ImportCB.filter(F.action == "sync"))
async def on_sync(callback: CallbackQuery, callback_data: ImportCB, deps: Deps) -> None:
    user_id = callback.from_user.id
    playlist = await deps.repo.playlist_get(user_id, callback_data.pid)
    if playlist is None:
        await callback.answer("Playlist introuvable.", show_alert=True)
        return
    try:
        await playlist_import.start_reimport(deps, playlist)
    except playlist_import.PlaylistImportError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer("Resynchronisation lancée")
    await _edit(callback.message, "🔄 Resynchronisation…", None)
    _follow(deps, callback.message, user_id, playlist.id)


@router.callback_query(ImportCB.filter(F.action == "play"))
async def on_play(callback: CallbackQuery, callback_data: ImportCB, deps: Deps) -> None:
    user_id = callback.from_user.id
    if await deps.repo.playlist_get(user_id, callback_data.pid) is None:
        await callback.answer("Playlist introuvable.", show_alert=True)
        return
    entries = await deps.repo.playlist_tracks(callback_data.pid)
    tracks = [e.track for e in entries][:PLAY_LIMIT]
    await callback.answer(
        f"Envoi des {len(tracks)} premiers titres" if len(entries) > PLAY_LIMIT else "Envoi des titres"
    )
    await play_all_tracks(deps, user_id, callback.message.chat.id, tracks)


def _item_line(index: int, item) -> str:
    original = item.original
    line = f"{index}. {original.title} — {original.artist}"
    if item.matched is not None and (item.matched.title, item.matched.artist) != (original.title, original.artist):
        line += f"\n    → {item.matched.title} — {item.matched.artist}"
    if item.reason:
        line += f"\n    {item.reason}"
    return line


async def _render_report(deps: Deps, callback: CallbackQuery, pid: int, status: str, page: int) -> None:
    user_id = callback.from_user.id
    playlist = await deps.repo.playlist_get(user_id, pid)
    if playlist is None:
        await _edit(callback.message, "Cette playlist n'existe plus.", None)
        return
    items = await deps.repo.import_items(pid, status)
    if not items:
        await _show_summary(deps, callback.message, user_id, pid)
        return
    pages = max(1, -(-len(items) // REPORT_PAGE))
    page = max(1, min(page, pages))
    shown = items[(page - 1) * REPORT_PAGE: page * REPORT_PAGE]
    start = (page - 1) * REPORT_PAGE
    header = f"{'⚠️' if status == 'uncertain' else '❌'} {STATUS_LABELS[status]} — {playlist.name} ({len(items)})"
    body = "\n\n".join(_item_line(start + i + 1, item) for i, item in enumerate(shown))
    hint = (
        "\n\n✅ = c'est le bon titre · 🗑 = le retirer. Pour en choisir un autre "
        "(recherche ou lien YouTube / SoundCloud), passe par l'app."
    )
    rows = []
    for i, item in enumerate(shown):
        number = start + i + 1
        buttons = []
        if item.matched is not None:
            buttons.append(InlineKeyboardButton(
                text=f"✅ {number}", callback_data=ImportCB(action="accept", pid=pid, item=item.id, status=status, page=page).pack(),
            ))
            buttons.append(InlineKeyboardButton(
                text=f"🗑 {number}", callback_data=ImportCB(action="remove", pid=pid, item=item.id, status=status, page=page).pack(),
            ))
        if buttons:
            rows.append(buttons)
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="‹", callback_data=ImportCB(action="report", pid=pid, status=status, page=page - 1).pack()))
    if pages > 1:
        nav.append(InlineKeyboardButton(text=f"{page}/{pages}", callback_data=ImportCB(action="report", pid=pid, status=status, page=page).pack()))
    if page < pages:
        nav.append(InlineKeyboardButton(text="›", callback_data=ImportCB(action="report", pid=pid, status=status, page=page + 1).pack()))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="← Retour", callback_data=ImportCB(action="view", pid=pid).pack())])
    text = f"{header}\n\n{body}{hint if status == 'uncertain' else ''}"
    await _edit(callback.message, text[:4000], InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(ImportCB.filter(F.action == "report"))
async def on_report(callback: CallbackQuery, callback_data: ImportCB, deps: Deps) -> None:
    await callback.answer()
    await _render_report(deps, callback, callback_data.pid, callback_data.status or "uncertain", callback_data.page)


@router.callback_query(ImportCB.filter(F.action.in_({"accept", "remove"})))
async def on_fix(callback: CallbackQuery, callback_data: ImportCB, deps: Deps) -> None:
    playlist = await deps.repo.playlist_get(callback.from_user.id, callback_data.pid)
    if playlist is None:
        await callback.answer("Playlist introuvable.", show_alert=True)
        return
    try:
        await playlist_import.fix_item(deps, playlist, callback_data.item, callback_data.action)
    except playlist_import.PlaylistImportError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer("Validé" if callback_data.action == "accept" else "Retiré de la playlist")
    await _render_report(deps, callback, callback_data.pid, callback_data.status or "uncertain", callback_data.page)
