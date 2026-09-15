from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import Message

from app.bot import errors, keyboards, navigation
from app.bot.deps import Deps
from app.bot.handlers.search import start_search
from app.bot.navigation import Screen
from app.bot.render import RenderTarget, show_text
from app.providers.link_detect import DetectedLink, resolve_link

logger = logging.getLogger(__name__)

router = Router(name="links")

# Playlists Deezer/Spotify/Apple non prises en charge (pas d'endpoint dédié
# implémenté côté provider) : seul le morceau/album/artiste est résolu pour
# ces sources. YouTube n'a pas d'"album" à proprement parler : une playlist
# YouTube est donc affichée avec le même gabarit que l'écran Album.
_SUPPORTED_KINDS = {
    "deezer": {"track", "album", "artist"},
    "spotify": {"track", "album", "artist"},
    "apple": {"track", "album", "artist"},
    "youtube": {"track", "playlist"},
}
_KIND_TO_SCREEN = {"track": "track", "album": "album", "artist": "artist", "playlist": "album"}


@navigation.register("link_loading")
async def render_link_loading(deps: Deps, target: RenderTarget, user_id: int, params: dict) -> RenderTarget:
    return await show_text(deps.bot, target, "Analyse du lien…", None)


async def _handle_detected_link(deps: Deps, message: Message, detected: DetectedLink) -> None:
    user_id = message.from_user.id
    chat_id = message.chat.id

    await navigation.goto(deps, user_id, chat_id, Screen("link_loading"))

    allowed_kinds = _SUPPORTED_KINDS.get(detected.source, set())
    if detected.kind not in allowed_kinds:
        target = navigation.current_target(user_id)
        new_target = await show_text(deps.bot, target, errors.LINK_UNRECOGNIZED, keyboards.no_results_keyboard())
        navigation.set_target(user_id, new_target)
        return

    screen_kind = _KIND_TO_SCREEN[detected.kind]
    params: dict = {"source": detected.source, "id": detected.ref}
    if screen_kind == "album":
        params["page"] = 1
    await navigation.replace_top(deps, user_id, Screen(screen_kind, params))


@router.message(F.text)
async def on_text(message: Message, deps: Deps) -> None:
    text = (message.text or "").strip()
    if not text:
        return
    if text.startswith("/"):
        # Commande inconnue : les commandes gérées ont été captées par les
        # routers précédents. On renvoie vers ce qui existe plutôt que de
        # laisser le message sans réponse.
        await message.answer(
            "Commande inconnue. Utilise /search pour chercher un morceau, "
            "/start pour revenir à l'accueil."
        )
        return

    try:
        detected = await resolve_link(text)
    except Exception as exc:  # résolution de lien court en panne, DNS…
        logger.warning("Détection de lien impossible pour %r: %s", text, exc)
        detected = None

    if detected:
        await _handle_detected_link(deps, message, detected)
        return

    user_id = message.from_user.id
    screen = navigation.current_screen(user_id)
    scope_name = screen.params.get("scope_name") if screen.kind == "search_prompt" else None
    await start_search(deps, user_id, message.chat.id, text, artist_scope_name=scope_name)
