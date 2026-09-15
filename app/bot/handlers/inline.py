from __future__ import annotations

import logging

from aiogram import Router
from aiogram.types import (
    InlineQuery,
    InlineQueryResultArticle,
    InlineQueryResultCachedAudio,
    InlineQueryResultsButton,
    InputTextMessageContent,
)

from app.bot.deps import Deps
from app.providers.base import TrackInfo
from app.providers.link_detect import track_url
from app.services import query_cache
from app.services.search import SearchError, search_tracks

logger = logging.getLogger(__name__)

router = Router(name="inline")

# Telegram attend la réponse en quelques secondes et rappelle à chaque frappe :
# on reste sur une page courte, quitte à en charger d'autres au défilement.
INLINE_PAGE = 10
MIN_QUERY_LENGTH = 2
# Les résultats dépendent de l'utilisateur (son cache audio, ses réglages) :
# `is_personal` empêche Telegram de les servir à quelqu'un d'autre.
CACHE_SECONDS = 30

HINT_TYPE_SOMETHING = "Tape le nom d'un morceau ou d'un artiste"
HINT_NO_RESULT = "Aucun résultat — essaie une autre orthographe"
HINT_UNAVAILABLE = "Recherche indisponible pour le moment"


def _description(track: TrackInfo) -> str:
    parts = [track.artist]
    if track.album:
        parts.append(track.album)
    parts.append(track.duration_label)
    return " • ".join(parts)


async def _empty(query: InlineQuery, hint: str) -> None:
    """Panneau vide avec une explication : un panneau muet laisse croire que
    le bot ne répond pas."""
    await query.answer(
        [],
        cache_time=5,
        is_personal=True,
        button=InlineQueryResultsButton(text=hint, start_parameter="aide"),
    )


@router.inline_query()
async def on_inline_query(query: InlineQuery, deps: Deps) -> None:
    """Suggestions affichées au-dessus du champ de saisie pendant la frappe.

    Un morceau déjà présent dans le cache audio est proposé comme audio prêt à
    envoyer (un tap = le fichier arrive) ; les autres renvoient leur lien, que
    Sona redétecte aussitôt pour ouvrir l'écran Morceau.
    """
    text = (query.query or "").strip()
    if len(text) < MIN_QUERY_LENGTH:
        await _empty(query, HINT_TYPE_SOMETHING)
        return

    offset = int(query.offset) if (query.offset or "").isdigit() else 0
    cached = query_cache.CachedQuery(text=text)
    try:
        tracks, _total = await search_tracks(deps, cached, index=offset, limit=INLINE_PAGE)
    except SearchError:
        await _empty(query, HINT_UNAVAILABLE)
        return

    if not tracks:
        await _empty(query, HINT_NO_RESULT if offset == 0 else HINT_TYPE_SOMETHING)
        return

    settings = await deps.repo.get_settings(query.from_user.id)
    ready = await deps.repo.cache_get_many(
        [(t.source, t.source_id) for t in tracks], settings.format, settings.quality
    )

    results = []
    for track in tracks:
        file_id = ready.get((track.source, track.source_id))
        if file_id:
            results.append(
                InlineQueryResultCachedAudio(
                    id=f"a:{track.source}:{track.source_id}"[:64],
                    audio_file_id=file_id,
                )
            )
            continue
        url = track_url(track)
        if url is None:
            logger.debug("Pas d'URL pour %s:%s, résultat ignoré", track.source, track.source_id)
            continue
        results.append(
            InlineQueryResultArticle(
                id=f"t:{track.source}:{track.source_id}"[:64],
                title=track.title,
                description=_description(track),
                thumbnail_url=track.cover_url,
                input_message_content=InputTextMessageContent(
                    message_text=url, link_preview_options={"is_disabled": True}
                ),
            )
        )

    next_offset = str(offset + INLINE_PAGE) if len(tracks) == INLINE_PAGE else ""
    await query.answer(
        results, cache_time=CACHE_SECONDS, is_personal=True, next_offset=next_offset
    )
