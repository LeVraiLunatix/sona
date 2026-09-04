from __future__ import annotations

from aiogram import Dispatcher

from app.bot.handlers import album, artist, history, library, links, search, settings, start, track


def setup_routers(dp: Dispatcher) -> None:
    dp.include_router(start.router)
    dp.include_router(search.router)
    dp.include_router(track.router)
    dp.include_router(album.router)
    dp.include_router(artist.router)
    dp.include_router(library.router)
    dp.include_router(history.router)
    dp.include_router(settings.router)
    # links.router doit rester après les autres routers "commande explicite" :
    # il capte tout le texte libre restant (recherche directe / lien collé).
    dp.include_router(links.router)
