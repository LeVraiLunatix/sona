from __future__ import annotations

import logging

from app.bot import keyboards, navigation
from app.bot.callbacks import NavCB
from app.bot.deps import Deps
from app.bot.render import RenderTarget, show_text, update_in_place

logger = logging.getLogger(__name__)

GENERIC_UNAVAILABLE = "Morceau indisponible pour le moment."
GENERIC_FETCH_FAILED = "Impossible de récupérer ce contenu."
LINK_UNRECOGNIZED = "Lien non reconnu ou contenu indisponible."

# Écoute : un message par cause réelle plutôt qu'un « indisponible » unique —
# l'utilisateur sait ainsi si ça vaut le coup de réessayer.
NO_SOURCE_FOUND = (
    "Aucune source audio trouvée pour ce morceau.\n"
    "Essaie un autre enregistrement (album, live, autre version)."
)
NO_FAITHFUL_SOURCE = (
    "Aucune version fidèle de ce morceau sur YouTube.\n"
    "Les vidéos trouvées sont des instrus, remixes ou reposts modifiés : "
    "Sona préfère ne rien envoyer plutôt qu'un autre enregistrement."
)
SOURCE_SEARCH_FAILED ="Recherche de la source impossible pour le moment. Réessaie dans un instant."
DOWNLOAD_FAILED = "Le téléchargement de ce morceau a échoué. Réessaie dans un instant."
SEND_FAILED = "L'envoi du fichier a échoué. Réessaie dans un instant."


async def show_error(
    deps: Deps, user_id: int, chat_id: int, text: str, retry_callback_data: str
) -> None:
    """Affiche un écran d'erreur en place, sans modifier la pile de navigation.

    '← Retour' sur cet écran restaure l'écran courant (voir NavCB action=dismiss)
    plutôt que de dépiler, puisque l'erreur n'est pas un nouvel écran empilé.
    Édite le message existant (texte ou légende) : une photo en cours n'est
    jamais supprimée pour un simple message d'erreur.
    """
    target = navigation.current_target(user_id) or RenderTarget(chat_id, None, False)
    markup = keyboards.error_keyboard(retry_callback_data, back_callback_data=NavCB(action="dismiss").pack())
    if target.message_id:
        new_target = await update_in_place(deps.bot, target, text, markup)
    else:
        new_target = await show_text(deps.bot, target, text, markup)
    navigation.set_target(user_id, new_target)


def log_and_hide(logger_: logging.Logger, action: str, exc: Exception) -> None:
    logger_.warning("Échec %s: %s", action, exc, exc_info=True)
