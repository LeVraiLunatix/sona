from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.auth import require_token
from app.api.state import ApiDeps
from app.db.repository import Play
from app.providers.lastfm import ImportStatus, LastfmClient, import_history
from app.services import stats as stats_service

router = APIRouter(tags=["stats"])

# Un seul import Last.fm à la fois (usage personnel) : son état vit ici,
# consulté par l'app pendant qu'il avance.
_import_status = ImportStatus()
_import_task: asyncio.Task | None = None


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
    return {"added": added}


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


def _status_out(deps: ApiDeps) -> ImportStatusOut:
    return ImportStatusOut(
        configured=bool(deps.settings.lastfm_api_key and deps.settings.lastfm_user),
        **asdict(_import_status),
    )


@router.get("/stats/import/lastfm", response_model=ImportStatusOut)
async def lastfm_import_status(deps: ApiDeps = Depends(require_token)) -> ImportStatusOut:
    return _status_out(deps)


@router.post("/stats/import/lastfm", response_model=ImportStatusOut, status_code=status.HTTP_202_ACCEPTED)
async def start_lastfm_import(deps: ApiDeps = Depends(require_token)) -> ImportStatusOut:
    """Lance (en tâche de fond) l'import de l'historique Last.fm de
    `LASTFM_USER` : tout la première fois, puis seulement les nouveautés."""
    global _import_task
    if not (deps.settings.lastfm_api_key and deps.settings.lastfm_user):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Import Last.fm non configuré : renseigne LASTFM_API_KEY et LASTFM_USER dans le .env du serveur.",
        )
    if not _import_status.running:
        client = LastfmClient(deps.settings.lastfm_api_key)
        _import_status.running = True

        async def run() -> None:
            try:
                await import_history(client, deps.repo, deps.user_id, deps.settings.lastfm_user, _import_status)
            finally:
                await client.aclose()

        _import_task = asyncio.create_task(run())
    return _status_out(deps)
