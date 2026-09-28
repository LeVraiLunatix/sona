from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routers import browse, catalog, history, library, lyrics, search, stats, stream, user_settings
from app.api.state import ApiDeps
from app.config import load_settings
from app.db.database import Database
from app.db.repository import Repository
from app.logging_config import setup_logging
from app.providers.apple import AppleMusicClient
from app.providers.deezer import DeezerClient
from app.providers.lrclib import LrclibClient
from app.providers.spotify import SpotifyClient

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    settings = load_settings()
    if not settings.api_token:
        logger.warning(
            "API_TOKEN manquant dans .env : toutes les requêtes seront refusées (503)."
        )

    db = Database(settings.database_path)
    await db.connect()
    deezer = DeezerClient()
    apple = AppleMusicClient()
    spotify = SpotifyClient(settings.spotify_client_id, settings.spotify_client_secret)
    lrclib = LrclibClient()

    app.state.deps = ApiDeps(
        settings=settings,
        repo=Repository(db),
        deezer=deezer,
        apple=apple,
        spotify=spotify,
        lrclib=lrclib,
    )
    logger.info("API Sona démarrée (utilisateur API #%d)", settings.api_user_id)
    try:
        yield
    finally:
        await deezer.aclose()
        await apple.aclose()
        await spotify.aclose()
        await lrclib.aclose()
        await db.close()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Sona API",
        description="API privée servant de backend à l'app iOS de Sona.",
        lifespan=lifespan,
    )
    app.include_router(search.router)
    app.include_router(catalog.router)
    app.include_router(stream.router)
    app.include_router(library.router)
    app.include_router(history.router)
    app.include_router(user_settings.router)
    app.include_router(browse.router)
    app.include_router(lyrics.router)
    app.include_router(stats.router)

    @app.get("/health", tags=["health"])
    async def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
