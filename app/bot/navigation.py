from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from aiogram.types import Message

from app.bot import keyboards
from app.bot.callbacks import NavCB
from app.bot.deps import Deps
from app.bot.render import RenderTarget, show_text, update_in_place

logger = logging.getLogger(__name__)

RendererFn = Callable[[Deps, RenderTarget | None, int, dict[str, Any]], Awaitable[RenderTarget]]


@dataclass(slots=True)
class Screen:
    kind: str
    params: dict[str, Any] = field(default_factory=dict)


class NavigationState:
    __slots__ = ("stack", "message")

    def __init__(self) -> None:
        self.stack: list[Screen] = [Screen("home")]
        self.message: RenderTarget | None = None


_states: dict[int, NavigationState] = {}
_renderers: dict[str, RendererFn] = {}


def register(kind: str) -> Callable[[RendererFn], RendererFn]:
    def deco(fn: RendererFn) -> RendererFn:
        _renderers[kind] = fn
        return fn

    return deco


def state_for(user_id: int) -> NavigationState:
    return _states.setdefault(user_id, NavigationState())


def current_target(user_id: int) -> RenderTarget | None:
    return state_for(user_id).message


def set_target(user_id: int, target: RenderTarget) -> None:
    state_for(user_id).message = target


def adopt_message(user_id: int, message: object, screen: Screen | None = None) -> RenderTarget | None:
    """Rattache la navigation au message dont l'utilisateur vient d'appuyer un bouton.

    La pile de navigation vit en mémoire : après un redémarrage du bot elle
    repart de zéro, alors que les anciens messages et leurs boutons restent
    dans la conversation. Sans cible connue, « Écouter » plantait au premier
    appui (`'NoneType' object has no attribute 'is_photo'`). Si rien n'est
    suivi, on adopte donc ce message, et l'écran qu'il affiche quand
    l'appelant le connaît, pour que la suite le redessine au lieu de l'accueil.
    Un message devenu inaccessible (trop ancien) n'est pas adopté.
    Retourne la cible courante.
    """
    state = state_for(user_id)
    if state.message is None and isinstance(message, Message):
        state.message = RenderTarget(message.chat.id, message.message_id, is_photo=bool(message.photo))
        if screen is not None and len(state.stack) == 1 and state.stack[0].kind == "home":
            state.stack.append(screen)
    return state.message


async def show_status(deps: Deps, user_id: int, text: str) -> None:
    """Affiche un état d'attente (« Préparation… », « Envoi 3/12… ») à la
    place de l'écran courant.

    Sans écran connu, rien : mieux vaut pas de message d'attente qu'une
    exception qui fait échouer toute l'action.
    """
    target = current_target(user_id)
    if target is None or target.message_id is None:
        return
    set_target(user_id, await update_in_place(deps.bot, target, text))


def current_screen(user_id: int) -> Screen:
    return state_for(user_id).stack[-1]


async def _render_current(deps: Deps, user_id: int) -> None:
    state = state_for(user_id)
    screen = state.stack[-1]
    renderer = _renderers.get(screen.kind)
    if renderer is None:
        # Écran inconnu (pile héritée d'une version antérieure du bot) : on
        # repart de l'accueil plutôt que de lever une KeyError silencieuse.
        logger.warning("Écran inconnu %r, retour à l'accueil", screen.kind)
        state.stack = [Screen("home")]
        screen = state.stack[-1]
        renderer = _renderers.get("home")
        if renderer is None:  # aucun écran enregistré : les handlers n'ont pas été importés
            logger.error("Aucun renderer d'accueil enregistré")
            return
    if state.message is None:
        # Aucun message suivi (bot redémarré depuis l'affichage de l'écran) :
        # l'écran part dans un nouveau message. Sona ne fonctionne qu'en
        # conversation privée, donc chat_id == user_id.
        state.message = RenderTarget(user_id, None, False)
    try:
        state.message = await renderer(deps, state.message, user_id, screen.params)
    except Exception:
        # Filet de sécurité : un renderer ne doit jamais laisser fuiter une
        # trace technique vers l'utilisateur (voir docs/UX_FLOW.md § Erreurs).
        # Les erreurs "attendues" (source indisponible, etc.) sont déjà
        # gérées à l'intérieur de chaque renderer ; ceci ne couvre que les
        # imprévus (bug, API tierce en panne...).
        logger.exception("Erreur inattendue au rendu de l'écran %r", screen.kind)

        text = "Impossible d'afficher cet écran pour le moment."
        markup = keyboards.error_keyboard(NavCB(action="dismiss").pack())
        # Sona ne fonctionne qu'en conversation privée : à défaut de cible
        # connue, chat_id == user_id.
        target = state.message or RenderTarget(user_id, None, False)
        try:
            if target.message_id:
                state.message = await update_in_place(deps.bot, target, text, markup)
            else:
                state.message = await show_text(deps.bot, target, text, markup)
        except Exception:
            # Dernier filet : sans ça l'utilisateur ne voit *rien* se passer
            # (symptôme « le bot ne répond pas ») et le log est le seul indice.
            logger.exception("Message d'erreur non délivré à user_id=%s", user_id)


async def goto(
    deps: Deps, user_id: int, chat_id: int, screen: Screen, *, reset: bool = False
) -> None:
    state = state_for(user_id)
    if state.message is None or state.message.chat_id != chat_id:
        state.message = RenderTarget(chat_id, None, False)
    if reset:
        state.stack = [screen] if screen.kind == "home" else [Screen("home"), screen]
    else:
        state.stack.append(screen)
    await _render_current(deps, user_id)


async def back(deps: Deps, user_id: int) -> None:
    state = state_for(user_id)
    if len(state.stack) > 1:
        state.stack.pop()
    await _render_current(deps, user_id)


async def replace_top(deps: Deps, user_id: int, screen: Screen) -> None:
    """Remplace l'écran courant sans empiler (pagination sur place)."""
    state = state_for(user_id)
    if state.stack:
        state.stack[-1] = screen
    else:
        state.stack = [screen]
    await _render_current(deps, user_id)


async def rerender(deps: Deps, user_id: int) -> None:
    """Redessine l'écran courant sans changer la pile."""
    await _render_current(deps, user_id)
