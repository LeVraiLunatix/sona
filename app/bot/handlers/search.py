from __future__ import annotations

from math import ceil

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from app.bot import formatting, keyboards, navigation
from app.bot.callbacks import SearchCB
from app.bot.deps import Deps
from app.bot.errors import GENERIC_FETCH_FAILED
from app.bot.navigation import Screen
from app.bot.render import RenderTarget, show_text
from app.services import query_cache
from app.services.search import SearchError, search_tracks

router = Router(name="search")

PAGE_SIZE = keyboards.PAGE_SIZE
MAX_PAGES = 20
SUGGESTION_COUNT = 5

SEARCH_HINT = (
    "Que veux-tu écouter ?\n\n"
    "Envoie un titre, un artiste, ou les deux — par exemple « daft punk "
    "instant crush ». Tu peux aussi utiliser /search directement."
)


@navigation.register("search_prompt")
async def render_search_prompt(deps: Deps, target: RenderTarget, user_id: int, params: dict) -> RenderTarget:
    scope_name = params.get("scope_name")
    if scope_name:
        text = f"Rechercher chez {scope_name}\n\nEnvoie un titre ou un mot-clé."
        return await show_text(deps.bot, target, text, keyboards.search_prompt_keyboard([]))

    # Menu d'entrée : les derniers morceaux consultés sont proposés en un clic,
    # pour que l'écran de recherche ne soit pas une page vide.
    suggestions, _ = await deps.repo.history_list(user_id, limit=SUGGESTION_COUNT)
    text = SEARCH_HINT
    if suggestions:
        text += "\n\nReprendre une écoute récente :"
    return await show_text(deps.bot, target, text, keyboards.search_prompt_keyboard(suggestions))


@navigation.register("search_results")
async def render_search_results(deps: Deps, target: RenderTarget, user_id: int, params: dict) -> RenderTarget:
    qid = params["qid"]
    page = params.get("page", 1)
    cached = query_cache.get(qid)
    if cached is None:
        text = "Cette recherche a expiré. Lance une nouvelle recherche."
        return await show_text(deps.bot, target, text, keyboards.no_results_keyboard())

    index = (page - 1) * PAGE_SIZE
    try:
        tracks, total = await search_tracks(deps, cached, index=index, limit=PAGE_SIZE)
    except SearchError:
        return await show_text(
            deps.bot,
            target,
            GENERIC_FETCH_FAILED,
            keyboards.error_keyboard(SearchCB(action="page", qid=qid, page=page).pack()),
        )

    if not tracks:
        text = f"Aucun résultat pour « {cached.text} »"
        return await show_text(deps.bot, target, text, keyboards.no_results_keyboard())

    total_pages = min(MAX_PAGES, max(1, ceil(total / PAGE_SIZE))) if total else page
    lines = [formatting.result_line(i + 1, t) for i, t in enumerate(tracks)]
    text = f"Résultats pour « {cached.text} »\n\n" + "\n".join(lines)
    markup = keyboards.search_results_keyboard(qid, page, total_pages, tracks)
    return await show_text(deps.bot, target, text, markup)


async def start_search(
    deps: Deps,
    user_id: int,
    chat_id: int,
    query_text: str,
    artist_scope_name: str | None = None,
) -> None:
    cached = query_cache.CachedQuery(text=query_text, artist_scope_name=artist_scope_name)
    qid = query_cache.put(cached)
    screen = Screen("search_results", {"qid": qid, "page": 1})
    current = navigation.current_screen(user_id)
    if current.kind in ("search_prompt", "search_results"):
        await navigation.replace_top(deps, user_id, screen)
    else:
        await navigation.goto(deps, user_id, chat_id, screen)


@router.message(Command("search"))
async def cmd_search(message: Message, deps: Deps, command: CommandObject) -> None:
    """`/search` ouvre l'écran de recherche ; `/search <requête>` affiche
    directement le menu des morceaux trouvés."""
    query = (command.args or "").strip()
    if query:
        await start_search(deps, message.from_user.id, message.chat.id, query)
        return
    await navigation.goto(deps, message.from_user.id, message.chat.id, Screen("search_prompt"))


@router.callback_query(SearchCB.filter(F.action == "prompt"))
async def on_search_prompt(callback: CallbackQuery, deps: Deps) -> None:
    await callback.answer()
    await navigation.goto(deps, callback.from_user.id, callback.message.chat.id, Screen("search_prompt"))


@router.callback_query(SearchCB.filter(F.action == "page"))
async def on_search_page(callback: CallbackQuery, callback_data: SearchCB, deps: Deps) -> None:
    await callback.answer()
    await navigation.replace_top(
        deps,
        callback.from_user.id,
        Screen("search_results", {"qid": callback_data.qid, "page": callback_data.page}),
    )
