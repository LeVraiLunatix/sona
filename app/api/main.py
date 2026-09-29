from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.gzip import GZipMiddleware

from app.api.routers import (
    accounts, browse, catalog, friends, history, home, library, lyrics, playlists, search, stats, stream,
    user_settings,
)
from app.api.state import ApiDeps
from app.config import load_settings
from app.db.database import Database
from app.db.repository import Repository
from app.logging_config import setup_logging
from app.providers.apple import AppleMusicClient
from app.providers.deezer import DeezerClient
from app.providers.lastfm_auth import LastfmAuthClient
from app.providers.lrclib import LrclibClient
from app.providers.spotify import SpotifyClient

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    settings = load_settings()
    if not settings.api_token:
        logger.warning(
            "API_TOKEN manquant dans .env : seules les connexions Last.fm de l'app sont acceptées."
        )

    db = Database(settings.database_path)
    await db.connect()
    deezer = DeezerClient()
    apple = AppleMusicClient()
    spotify = SpotifyClient(settings.spotify_client_id, settings.spotify_client_secret)
    lrclib = LrclibClient()
    lastfm_auth = (
        LastfmAuthClient(settings.lastfm_api_key, settings.lastfm_api_secret)
        if settings.lastfm_api_key and settings.lastfm_api_secret
        else None
    )

    # Un import de playlist coupé par un redémarrage ne reprendra pas.
    await Repository(db).playlists_fail_interrupted_imports()

    app.state.deps = ApiDeps(
        settings=settings,
        repo=Repository(db),
        deezer=deezer,
        apple=apple,
        spotify=spotify,
        lrclib=lrclib,
        lastfm_auth=lastfm_auth,
    )
    logger.info("API Sona démarrée (utilisateur API #%d)", settings.api_user_id)
    try:
        yield
    finally:
        await deezer.aclose()
        await apple.aclose()
        await spotify.aclose()
        await lrclib.aclose()
        if lastfm_auth is not None:
            await lastfm_auth.aclose()
        await db.close()


class GZipExceptStream:
    """Compression gzip des réponses JSON (listes de titres, mixes, stats :
    bien plus rapides en 4G/5G), jamais de l'audio : les requêtes `Range` du
    lecteur exigent les octets tels quels."""

    def __init__(self, app) -> None:
        self.app = app
        self.gzip = GZipMiddleware(app, minimum_size=1024)

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http" and not scope.get("path", "").startswith("/stream"):
            await self.gzip(scope, receive, send)
        else:
            await self.app(scope, receive, send)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Sona API",
        description="API privée servant de backend à l'app iOS de Sona.",
        lifespan=lifespan,
    )
    app.add_middleware(GZipExceptStream)
    app.include_router(accounts.router)
    app.include_router(search.router)
    app.include_router(catalog.router)
    app.include_router(stream.router)
    app.include_router(library.router)
    app.include_router(history.router)
    app.include_router(user_settings.router)
    app.include_router(browse.router)
    app.include_router(lyrics.router)
    app.include_router(stats.router)
    app.include_router(playlists.router)
    app.include_router(friends.router)
    app.include_router(home.router)

    @app.get("/health", tags=["health"])
    async def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
