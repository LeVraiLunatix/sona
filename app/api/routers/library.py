from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.api.auth import require_token
from app.api.schemas import LibraryAddRequest, LibraryItemOut
from app.api.state import ApiDeps
from app.bot import lookup
from app.db.repository import VALID_KINDS
from app.providers.base import TrackInfo
from app.providers.lastfm_auth import LastfmAuthError
from app.services import playlist_import
from app.services.stats import to_utc_iso

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/library", tags=["library"])

_GETTERS = {
    "track": lookup.get_track,
    "album": lookup.get_album,
    "artist": lookup.get_artist,
}
_tasks: set[asyncio.Task] = set()


def _check_kind(kind: str) -> None:
    if kind not in VALID_KINDS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Type inconnu : {kind} (attendu : {VALID_KINDS})")


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def _lastfm_session(deps: ApiDeps) -> str | None:
    """Clé Last.fm du compte, si les titres aimés doivent y être reportés
    (même réglage que le scrobbling)."""
    account = deps.account
    if account and account.scrobble_to_lastfm and account.lastfm_session_key and deps.lastfm_auth:
        return account.lastfm_session_key
    return None


async def _sync_love(deps: ApiDeps, session_key: str, title: str, artist: str, loved: bool) -> None:
    try:
        if loved:
            await deps.lastfm_auth.love(session_key, title, artist)
        else:
            await deps.lastfm_auth.unlove(session_key, title, artist)
    except LastfmAuthError as exc:
        logger.info("♥ Last.fm impossible pour « %s » : %s", title, exc)


@router.get("/{kind}")
async def list_library(
    kind: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=500),
    deps: ApiDeps = Depends(require_token),
) -> dict:
    _check_kind(kind)
    items, total = await deps.repo.library_list(deps.user_id, kind, offset, limit)
    return {"total": total, "items": [LibraryItemOut.from_item(i) for i in items]}


@router.post("/{kind}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def add_to_library(kind: str, payload: LibraryAddRequest, deps: ApiDeps = Depends(require_token)) -> None:
    _check_kind(kind)
    try:
        obj = await _GETTERS[kind](deps, payload.source, payload.source_id)
    except lookup.ProviderErrors as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    added = await deps.repo.library_add(deps.user_id, kind, obj)
    session_key = _lastfm_session(deps)
    if added and kind == "track" and session_key:
        # Titre ajouté = titre aimé ♥ sur Last.fm (en arrière-plan).
        _spawn(_sync_love(deps, session_key, obj.title, obj.artist, loved=True))


@router.delete("/{kind}/{source}/{source_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def remove_from_library(
    kind: str, source: str, source_id: str, deps: ApiDeps = Depends(require_token)
) -> None:
    _check_kind(kind)
    item = await deps.repo.library_get(deps.user_id, kind, source, source_id)
    await deps.repo.library_remove(deps.user_id, kind, source, source_id)
    session_key = _lastfm_session(deps)
    if item and kind == "track" and session_key:
        # Le sous-titre d'un titre vaut « Artiste • Album ».
        artist = (item.subtitle or "").split(" • ", 1)[0].strip()
        if artist:
            _spawn(_sync_love(deps, session_key, item.title, artist, loved=False))


# -- Import des titres aimés sur Last.fm --------------------------------------


@dataclass(slots=True)
class LovedImport:
    running: bool = False
    total: int = 0
    done: int = 0
    added: int = 0
    missing: int = 0
    error: str | None = None


class LovedImportOut(BaseModel):
    running: bool
    total: int
    done: int
    added: int
    missing: int
    error: str | None


_loved_imports: dict[int, LovedImport] = {}


def _loved_out(state: LovedImport) -> LovedImportOut:
    return LovedImportOut(
        running=state.running, total=state.total, done=state.done, added=state.added,
        missing=state.missing, error=state.error,
    )


async def run_loved_import(deps: ApiDeps, user_id: int, username: str, state: LovedImport) -> None:
    """Ajoute à la bibliothèque les titres aimés sur Last.fm, retrouvés sur
    Deezer, en gardant leur date de ♥ (l'ordre de la bibliothèque suit)."""
    try:
        loved = await deps.lastfm_auth.loved_tracks(username)
        state.total = len(loved)
        wanted = [
            TrackInfo(source="lastfm", source_id="", title=t.title, artist=t.artist, album=None, year=None,
                      duration_seconds=None, cover_url=None)
            for t in loved
        ]
        throttle = playlist_import._Throttle(playlist_import.DEEZER_REQUESTS_PER_SECOND)
        semaphore = asyncio.Semaphore(playlist_import.MATCH_CONCURRENCY)

        async def one(index: int) -> None:
            track = wanted[index]
            async with semaphore:
                try:
                    if await deps.repo.library_has_title(user_id, track.title, track.artist):
                        match = None
                    else:
                        match = await playlist_import.match_on_deezer(deps.deezer, track, throttle)
                        if match is None:
                            state.missing += 1
                except Exception as exc:  # un titre raté ne doit pas arrêter l'import
                    logger.info("Titre aimé « %s » introuvable : %s", track.title, exc)
                    match = None
                    state.missing += 1
                if match is not None:
                    when = loved[index].loved_at
                    if await deps.repo.library_add(user_id, "track", match, to_utc_iso(when) if when else None):
                        state.added += 1
                state.done += 1

        await asyncio.gather(*(one(i) for i in range(len(wanted))))
    except LastfmAuthError as exc:
        state.error = str(exc)
    except Exception as exc:  # noqa: BLE001 — affiché dans l'app
        logger.exception("Import des titres aimés Last.fm échoué")
        state.error = f"Import impossible : {exc}"
    finally:
        state.running = False


@router.get("/lastfm-loved/import", response_model=LovedImportOut)
async def loved_import_status(deps: ApiDeps = Depends(require_token)) -> LovedImportOut:
    return _loved_out(_loved_imports.get(deps.user_id, LovedImport()))


@router.post("/lastfm-loved/import", response_model=LovedImportOut, status_code=status.HTTP_202_ACCEPTED)
async def start_loved_import(deps: ApiDeps = Depends(require_token)) -> LovedImportOut:
    username = deps.account.lastfm_username if deps.account else deps.settings.lastfm_user
    if not username or deps.lastfm_auth is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Aucun compte Last.fm relié.")
    current = _loved_imports.get(deps.user_id)
    if current and current.running:
        return _loved_out(current)
    state = LovedImport(running=True)
    _loved_imports[deps.user_id] = state
    _spawn(run_loved_import(deps, deps.user_id, username, state))
    return _loved_out(state)
