from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from starlette.middleware.gzip import GZipMiddleware

from app.api.routers import (
    accounts, blindlive, blindtest, browse, connect, extras, catalog, concerts, friends, history, home, library, lyrics, party, playlists,
    search, stats, stream, tv, user_settings,
)
from app.api.state import ApiDeps
from app.config import load_settings
from app.services.backup import run_backups
from app.db.database import Database
from app.db.repository import Repository
from app.logging_config import setup_logging
from app.providers.apple import AppleMusicClient
from app.providers.deezer import DeezerClient
from app.providers.lastfm_auth import LastfmAuthClient
from app.providers.lrclib import LrclibClient
from app.providers.spotify import SpotifyClient

logger = logging.getLogger(__name__)


def _server_version() -> str:
    """Commit Git en cours (les 7 premiers caractères), ou « inconnue »."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short=7", "HEAD"], capture_output=True, text=True, timeout=5,
            cwd=Path(__file__).resolve().parents[2],
        )
        return out.stdout.strip() or "inconnue"
    except (OSError, subprocess.SubprocessError):
        return "inconnue"


SERVER_VERSION = _server_version()


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
    # Sans bot Telegram (c'est lui qui sauvegarde d'habitude), l'API prend
    # les sauvegardes quotidiennes en charge — jamais pendant les tests.
    backups = None
    if not settings.bot_token and "PYTEST_CURRENT_TEST" not in os.environ:
        backups = asyncio.create_task(run_backups(settings.database_path, settings.backup_dir))
    try:
        yield
    finally:
        if backups is not None:
            backups.cancel()
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
    # Sona web hébergé ailleurs (Vercel) : appels de l'API depuis une autre
    # adresse. Sans risque ici : l'authentification passe par un jeton
    # (en-tête Authorization), jamais par un cookie.
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
        expose_headers=["Content-Length", "Content-Range", "Accept-Ranges"],
    )
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
    app.include_router(party.router)
    app.include_router(blindlive.router)
    app.include_router(tv.router)
    app.include_router(connect.router)
    app.include_router(extras.router)
    app.include_router(blindtest.router)
    app.include_router(concerts.router)

    @app.get("/health", tags=["health"])
    async def health() -> dict:
        # `version` : commit déployé — l'app l'affiche dans ses réglages, pour
        # savoir d'un coup d'œil si le serveur est à jour.
        return {"status": "ok", "version": SERVER_VERSION}

    # Sona sur ordinateur (dossier `web/` du dépôt, le même que sur Vercel),
    # qui passe ensuite par la même API.
    web_dir = Path(__file__).resolve().parents[2] / "web"
    web_files = {"": ("index.html", "text/html"), "app.css": ("app.css", "text/css"),
                 "app.js": ("app.js", "application/javascript")}

    @app.get("/web", include_in_schema=False)
    async def web_root() -> RedirectResponse:
        return RedirectResponse("/web/")

    @app.get("/web/{name:path}", include_in_schema=False)
    async def web(name: str) -> FileResponse:
        file, media_type = web_files.get(name, web_files[""])
        return FileResponse(web_dir / file, media_type=media_type, headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
