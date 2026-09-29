from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.auth import require_token
from app.api.state import ApiDeps
from app.db.repository import Play
from app.providers.lastfm import ImportStatus, LastfmClient, import_history
from app.providers.base import TrackInfo
from app.providers.lastfm_auth import LastfmAuthError
from app.services import presence
from app.services import recap as recap_service
from app.services import stats as stats_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["stats"])

# Import Last.fm en cours ou terminé, par espace de données (un par compte) :
# l'app suit sa progression pendant qu'il avance.
_import_statuses: dict[int, ImportStatus] = {}
_import_tasks: set[asyncio.Task] = set()


class PlayIn(BaseModel):
    title: str = Field(min_length=1)
    artist: str = Field(min_length=1)
    album: str | None = None
    source: str | None = None
    source_id: str | None = None
    artist_source_id: str | None = None
    album_source_id: str | None = None
    cover_url: str | None = None
    duration_seconds: int | None = Field(default=None, ge=0)
    listened_seconds: int | None = Field(default=None, ge=0)
    played_at: datetime | None = Field(default=None, description="Début de l'écoute ; maintenant par défaut")


class NowPlayingIn(BaseModel):
    title: str = Field(min_length=1)
    artist: str = Field(min_length=1)
    album: str | None = None
    duration_seconds: int | None = Field(default=None, ge=0)
    # De quoi relancer le même titre depuis l'onglet Amis.
    source: str | None = None
    source_id: str | None = None
    cover_url: str | None = None
    artist_source_id: str | None = None
    album_source_id: str | None = None
    position_seconds: float | None = Field(default=None, ge=0)


class PlaysIn(BaseModel):
    plays: list[PlayIn]


class PlayOut(BaseModel):
    played_at: str
    title: str
    artist: str
    album: str | None
    source: str | None
    source_id: str | None
    artist_source_id: str | None
    album_source_id: str | None
    cover_url: str | None
    duration_seconds: int | None
    origin: str


class RankedOut(BaseModel):
    name: str
    subtitle: str | None
    plays: int
    minutes: int
    cover_url: str | None
    source: str | None
    source_id: str | None


class BucketOut(BaseModel):
    label: str
    plays: int
    minutes: int


class StatsOut(BaseModel):
    period: str
    offset: int
    label: str
    start: str | None
    end: str | None
    plays: int
    minutes: int
    artists: int
    tracks: int
    albums: int
    previous_plays: int
    top_artists: list[RankedOut]
    top_tracks: list[RankedOut]
    top_albums: list[RankedOut]
    timeline: list[BucketOut]
    hours: list[int]
    weekdays: list[int]
    discoveries: list[RankedOut]
    top_hour: int | None
    top_weekday: str | None
    streak_days: int
    first_play: str | None


class ImportStatusOut(BaseModel):
    configured: bool
    running: bool
    page: int
    total_pages: int
    imported: int
    error: str | None
    finished_at: str | None


def _to_play(p: PlayIn) -> Play:
    played_at = p.played_at or datetime.now(timezone.utc)
    return Play(
        played_at=stats_service.to_utc_iso(played_at),
        title=p.title.strip(), artist=p.artist.strip(), album=(p.album or "").strip() or None,
        source=p.source, source_id=p.source_id, artist_source_id=p.artist_source_id,
        album_source_id=p.album_source_id, cover_url=p.cover_url,
        duration_seconds=p.duration_seconds, listened_seconds=p.listened_seconds, origin="sona",
    )


@router.post("/plays", status_code=status.HTTP_201_CREATED)
async def add_plays(payload: PlaysIn, deps: ApiDeps = Depends(require_token)) -> dict:
    """Écoutes terminées, envoyées par lot : l'app garde celles qu'elle n'a
    pas pu envoyer (hors connexion) et les renvoie plus tard — les doublons
    sont ignorés."""
    added = await deps.repo.plays_add(deps.user_id, [_to_play(p) for p in payload.plays])
    account = deps.account
    if (
        added and account is not None and account.scrobble_to_lastfm
        and account.lastfm_session_key and deps.lastfm_auth is not None
    ):
        # Aussi sur le profil Last.fm (et donc Sonar) : en arrière-plan, un
        # Last.fm lent ou en panne ne doit pas retarder l'app.
        task = asyncio.create_task(_scrobble(deps, account.lastfm_session_key, added))
        _import_tasks.add(task)
        task.add_done_callback(_import_tasks.discard)
    return {"added": len(added)}


@router.post("/plays/now", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def now_playing(payload: NowPlayingIn, deps: ApiDeps = Depends(require_token)) -> None:
    """Titre qui vient de démarrer dans l'app : affiché « en train
    d'écouter » sur le profil Last.fm du compte, en direct (en arrière-plan :
    Last.fm lent ou en panne ne retarde pas la lecture), et pour les amis
    dans l'app."""
    account = deps.account
    if account is None or account.share_listening:
        presence.set_playing(
            deps.user_id,
            TrackInfo(
                source=payload.source or "", source_id=payload.source_id or "",
                title=payload.title.strip(), artist=payload.artist.strip(), album=payload.album, year=None,
                duration_seconds=payload.duration_seconds, cover_url=payload.cover_url,
                artist_source_id=payload.artist_source_id, album_source_id=payload.album_source_id,
            ),
            payload.position_seconds or 0,
        )
    if not (account and account.scrobble_to_lastfm and account.lastfm_session_key and deps.lastfm_auth):
        return
    task = asyncio.create_task(_now_playing(deps, account.lastfm_session_key, payload))
    _import_tasks.add(task)
    task.add_done_callback(_import_tasks.discard)


@router.delete("/plays/now", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def stop_playing(deps: ApiDeps = Depends(require_token)) -> None:
    """Pause ou arrêt dans l'app : plus « en train d'écouter » pour les amis."""
    presence.clear(deps.user_id)


@dataclass
class LastfmSync:
    """Derniers échanges avec Last.fm pour un compte : l'onglet Stats les
    montre, pour vérifier que le scrobbling marche vraiment."""

    now_playing_at: str | None = None
    now_playing_title: str | None = None
    scrobbled_at: str | None = None
    scrobbled_count: int = 0
    last_title: str | None = None
    error: str | None = None
    error_at: str | None = None


_lastfm_sync: dict[int, LastfmSync] = {}


def _now_iso() -> str:
    return stats_service.to_utc_iso(datetime.now(timezone.utc))


async def _now_playing(deps: ApiDeps, session_key: str, payload: NowPlayingIn) -> None:
    sync = _lastfm_sync.setdefault(deps.user_id, LastfmSync())
    try:
        await deps.lastfm_auth.update_now_playing(
            session_key, payload.title.strip(), payload.artist.strip(), payload.album, payload.duration_seconds
        )
        sync.now_playing_at, sync.now_playing_title = _now_iso(), payload.title.strip()
    except LastfmAuthError as exc:
        logger.info("« En train d'écouter » Last.fm impossible : %s", exc)
        sync.error, sync.error_at = str(exc), _now_iso()


async def _scrobble(deps: ApiDeps, session_key: str, plays: list[Play]) -> None:
    sync = _lastfm_sync.setdefault(deps.user_id, LastfmSync())
    try:
        await deps.lastfm_auth.scrobble(session_key, plays)
        sync.scrobbled_at = _now_iso()
        sync.scrobbled_count += len(plays)
        sync.last_title = plays[-1].title if plays else None
        sync.error = None
    except LastfmAuthError as exc:
        logger.info("Scrobbling Last.fm impossible : %s", exc)
        sync.error, sync.error_at = str(exc), _now_iso()


class LastfmSyncOut(BaseModel):
    connected: bool
    enabled: bool
    username: str | None
    now_playing_at: str | None
    now_playing_title: str | None
    scrobbled_at: str | None
    scrobbled_count: int
    last_title: str | None
    error: str | None
    error_at: str | None


class LiveOut(BaseModel):
    """En direct : ce que le serveur sait de l'écoute en cours et du jour."""

    now_playing: dict | None
    today_plays: int
    today_minutes: int
    recent: list[PlayOut]
    lastfm: LastfmSyncOut


@router.get("/stats/live", response_model=LiveOut)
async def live(
    tz: str | None = Query(None, description="Fuseau IANA de l'appareil"),
    deps: ApiDeps = Depends(require_token),
) -> LiveOut:
    zone = stats_service.resolve_tz(tz)
    now = datetime.now(timezone.utc).astimezone(zone)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today = await deps.repo.plays_between(deps.user_id, stats_service.to_utc_iso(start), None)
    recent = await deps.repo.plays_recent(deps.user_id, 8)
    playing = presence.get(deps.user_id)
    account = deps.account
    sync = _lastfm_sync.get(deps.user_id, LastfmSync())
    return LiveOut(
        now_playing={
            "title": playing.track.title, "artist": playing.track.artist,
            "cover_url": playing.track.cover_url,
            "started_at": stats_service.to_utc_iso(playing.started_at),
        } if playing else None,
        today_plays=len(today),
        today_minutes=sum(stats_service.seconds_of(p) for p in today) // 60,
        recent=[PlayOut(**{k: v for k, v in asdict(p).items() if k != "listened_seconds"}) for p in recent],
        lastfm=LastfmSyncOut(
            connected=bool(account and account.lastfm_session_key),
            enabled=bool(account and account.scrobble_to_lastfm and deps.lastfm_auth),
            username=account.lastfm_username if account else None,
            **asdict(sync),
        ),
    )


@router.get("/plays/recent", response_model=list[PlayOut])
async def recent_plays(
    limit: int = Query(50, ge=1, le=200), deps: ApiDeps = Depends(require_token)
) -> list[PlayOut]:
    plays = await deps.repo.plays_recent(deps.user_id, limit)
    return [PlayOut(**{k: v for k, v in asdict(p).items() if k != "listened_seconds"}) for p in plays]


@router.get("/stats", response_model=StatsOut)
async def get_stats(
    period: str = Query("week", description="day | week | month | year | all"),
    offset: int = Query(0, le=0, ge=-600, description="0 = période en cours, -1 = précédente…"),
    tz: str | None = Query(None, description="Fuseau IANA de l'appareil (ex. Europe/Paris)"),
    deps: ApiDeps = Depends(require_token),
) -> StatsOut:
    if period not in stats_service.PERIODS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Période inconnue : {period}")
    report = await stats_service.compute(deps.repo, deps.user_id, period, offset, tz)
    return StatsOut(**asdict(report))


@router.get("/stats/recap")
async def get_recap(
    period: str = Query("month", description="week | month | year"),
    offset: int = Query(0, le=0, ge=-600),
    tz: str | None = Query(None),
    deps: ApiDeps = Depends(require_token),
) -> dict:
    """Récap en story (voir services/recap.py)."""
    if period not in ("week", "month", "year"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Période inconnue : {period}")
    if offset >= 0:
        # Comme un vrai Wrapped : le récap d'une période sort quand elle est finie.
        raise HTTPException(status.HTTP_409_CONFLICT, recap_service.available_message(period))
    recap = await recap_service.compute(deps, deps.user_id, period, offset, tz)
    for key in ("top_artists", "top_tracks", "top_albums", "discoveries"):
        recap[key] = [asdict(item) for item in recap[key]]
    return recap


def _lastfm_username(deps: ApiDeps) -> str | None:
    """Historique importé : celui du compte Last.fm connecté, sinon (ancien
    jeton unique) celui de LASTFM_USER."""
    return deps.account.lastfm_username if deps.account else deps.settings.lastfm_user


def _status_out(deps: ApiDeps) -> ImportStatusOut:
    current = _import_statuses.get(deps.user_id) or ImportStatus()
    return ImportStatusOut(
        configured=bool(deps.settings.lastfm_api_key and _lastfm_username(deps)),
        **asdict(current),
    )


@router.get("/stats/import/lastfm", response_model=ImportStatusOut)
async def lastfm_import_status(deps: ApiDeps = Depends(require_token)) -> ImportStatusOut:
    return _status_out(deps)


@router.post("/stats/import/lastfm", response_model=ImportStatusOut, status_code=status.HTTP_202_ACCEPTED)
async def start_lastfm_import(deps: ApiDeps = Depends(require_token)) -> ImportStatusOut:
    """Lance (en tâche de fond) l'import de l'historique Last.fm du compte :
    tout la première fois, puis seulement les nouveautés."""
    username = _lastfm_username(deps)
    if not (deps.settings.lastfm_api_key and username):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Import Last.fm non configuré : renseigne LASTFM_API_KEY (et LASTFM_USER) dans le .env du serveur.",
        )
    current = _import_statuses.setdefault(deps.user_id, ImportStatus())
    if not current.running:
        client = LastfmClient(deps.settings.lastfm_api_key)
        current.running = True
        user_id = deps.user_id

        async def run() -> None:
            try:
                await import_history(client, deps.repo, user_id, username, current)
            finally:
                await client.aclose()

        task = asyncio.create_task(run())
        _import_tasks.add(task)
        task.add_done_callback(_import_tasks.discard)
    return _status_out(deps)
