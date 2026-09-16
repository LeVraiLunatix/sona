"""Annonce envoyée à tous les utilisateurs, depuis le bot (réservé aux admins).

Prévenir tout le monde d'une coupure ou d'une nouveauté demandait jusqu'ici
d'écrire à chacun à la main. Le parcours est : bouton « Envoyer une annonce »
→ écran de saisie → aperçu → envoi → bilan.

La saisie passe par un écran dédié : c'est `handlers/links.py` qui capte le
texte libre (recherche ou lien collé), et il délègue ici quand l'écran courant
attend une annonce — sans quoi le texte partirait en recherche.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.bot import broadcast, keyboards, navigation
from app.bot.callbacks import AdminCB
from app.bot.deps import Deps
from app.bot.handlers.admin import require_admin
from app.bot.navigation import Screen
from app.bot.render import RenderTarget, show_text

logger = logging.getLogger(__name__)

router = Router(name="announce")

PROMPT_TEXT = (
    "Envoyer une annonce\n\n"
    "Écris ici le message à envoyer. Il partira à tous les utilisateurs "
    "autorisés qui ont gardé leurs notifications.\n\n"
    "Tu pourras le relire avant l'envoi."
)
# La pile de navigation vit en mémoire : un redémarrage entre l'aperçu et
# l'appui sur « Envoyer » perd le brouillon. Mieux vaut le dire que d'envoyer
# un message vide à tout le monde.
DRAFT_LOST = "Annonce perdue (bot redémarré). Recommence depuis « Envoyer une annonce »."


@navigation.register("announce_prompt")
async def render_announce_prompt(deps: Deps, target: RenderTarget, user_id: int, params: dict) -> RenderTarget:
    return await show_text(deps.bot, target, PROMPT_TEXT, keyboards.admin_announce_prompt_keyboard())


@navigation.register("announce_preview")
async def render_announce_preview(deps: Deps, target: RenderTarget, user_id: int, params: dict) -> RenderTarget:
    text = f"Aperçu de l'annonce\n\n{params['text']}\n\nEnvoyer à tout le monde ?"
    return await show_text(deps.bot, target, text, keyboards.admin_announce_preview_keyboard())


def _report_text(report: broadcast.BroadcastReport) -> str:
    lines = ["Annonce envoyée", "", f"{report.delivered} envoyée(s)"]
    if report.muted:
        lines.append(f"{report.muted} sans notifications")
    if report.failed:
        lines.append(f"{report.failed} échec(s) — bot bloqué ou conversation jamais ouverte")
    return "\n".join(lines)


async def capture_draft(deps: Deps, message: Message) -> bool:
    """Prend le texte en charge quand l'écran courant attend une annonce.

    Retourne True quand le message a été traité : l'appelant
    (`handlers/links.py`) n'a alors rien à en faire. Un lien collé dans une
    annonce reste du texte, donc cette prise en charge passe avant la
    détection de lien.
    """
    user_id = message.from_user.id
    if navigation.current_screen(user_id).kind != "announce_prompt":
        return False
    if not await deps.repo.is_admin(user_id):
        # Écran ouvert avant un retrait d'accès : on laisse le texte repartir
        # en recherche plutôt que d'ouvrir la diffusion à quelqu'un d'autre.
        return False
    text = (message.text or "").strip()
    if not text:
        return False
    await navigation.replace_top(deps, user_id, Screen("announce_preview", {"text": text}))
    return True


@router.callback_query(AdminCB.filter(F.action == "announce"))
async def on_announce(callback: CallbackQuery, deps: Deps) -> None:
    if not await require_admin(callback, deps):
        return
    await callback.answer()
    await navigation.goto(deps, callback.from_user.id, callback.message.chat.id, Screen("announce_prompt"))


@router.callback_query(AdminCB.filter(F.action == "announce_cancel"))
async def on_announce_cancel(callback: CallbackQuery, deps: Deps) -> None:
    if not await require_admin(callback, deps):
        return
    await callback.answer("Annonce annulée.")
    await navigation.replace_top(deps, callback.from_user.id, Screen("admin_menu"))


@router.callback_query(AdminCB.filter(F.action == "announce_send"))
async def on_announce_send(callback: CallbackQuery, deps: Deps) -> None:
    if not await require_admin(callback, deps):
        return
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    screen = navigation.current_screen(user_id)
    text = screen.params.get("text") if screen.kind == "announce_preview" else None
    if not text:
        await callback.answer(DRAFT_LOST, show_alert=True)
        return

    await callback.answer("Envoi en cours…")
    await navigation.show_status(deps, user_id, "Envoi de l'annonce…")
    report = await broadcast.announce(deps, text)
    logger.info("Annonce de l'admin %s : %s", user_id, report)

    # L'annonce est partie en messages neufs : l'écran suivi est remonté loin
    # au-dessus. Le bilan part donc lui aussi en message, là où l'admin
    # regarde, et l'écran revient à la gestion des accès.
    await navigation.replace_top(deps, user_id, Screen("admin_menu"))
    await broadcast.send_to(deps, chat_id, _report_text(report))
