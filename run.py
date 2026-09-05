from __future__ import annotations

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher

from app.bot.deps import Deps
from app.bot.handlers import setup_routers
from app.bot.middlewares import WhitelistMiddleware
from app.config import load_settings
from app.db.database import Database
from app.db.repository import Repository
from app.logging_config import setup_logging
from app.providers.apple import AppleMusicClient
from app.providers.deezer import DeezerClient
from app.providers.spotify import SpotifyClient

logger = logging.getLogger(__name__)


def _clear_node_ipc_env() -> None:
    """Retire les variables d'IPC Node héritées du superviseur de process.

    PM2 lance Sona comme un process enfant de Node et expose NODE_CHANNEL_FD
    dans l'environnement. Deno — utilisé par yt-dlp pour résoudre les
    challenges JS de YouTube — est compatible Node : il hérite de la variable,
    tente d'ouvrir ce canal IPC qui ne lui appartient pas et sort en erreur
    ("fd is not from BiPipe"). Résultat : plus aucun format audio n'est
    déchiffrable et tous les morceaux paraissent indisponibles.

    Python n'utilise pas ce canal ; on le masque donc aux process enfants.
    """
    for var in ("NODE_CHANNEL_FD", "NODE_CHANNEL_SERIALIZATION_MODE"):
        if os.environ.pop(var, None) is not None:
            logger.info("Variable d'IPC Node %s retirée de l'environnement", var)


async def main() -> None:
    setup_logging()
    _clear_node_ipc_env()
    settings = load_settings()

    if not settings.is_private_mode:
        logger.warning(
            "ALLOWED_USER_IDS est vide : personne ne pourra utiliser Sona. "
            "Renseigne ton user_id Telegram dans .env."
        )

    db = Database(settings.database_path)
    await db.connect()
    repo = Repository(db)
    await repo.bootstrap_admins(list(settings.allowed_user_ids))

    bot = Bot(token=settings.bot_token)
    me = await bot.get_me()
    dp = Dispatcher()

    deezer = DeezerClient()
    apple = AppleMusicClient()
    spotify = SpotifyClient(settings.spotify_client_id, settings.spotify_client_secret)

    deps = Deps(
        bot=bot,
        bot_username=me.username,
        settings=settings,
        repo=repo,
        deezer=deezer,
        apple=apple,
        spotify=spotify,
    )
    dp["deps"] = deps

    dp.message.outer_middleware(WhitelistMiddleware(repo))
    dp.callback_query.outer_middleware(WhitelistMiddleware(repo))

    setup_routers(dp)

    allowed_count = len(await repo.list_allowed_users())
    logger.info("Sona démarre (bot privé, %d utilisateur(s) autorisé(s))", allowed_count)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await deezer.aclose()
        await apple.aclose()
        await spotify.aclose()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
