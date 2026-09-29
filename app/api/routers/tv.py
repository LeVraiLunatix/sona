"""« Écouter sur la TV / PS5 » (voir services/tv_cast.py)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.auth import require_token
from app.api.schemas import Track
from app.api.state import ApiDeps
from app.providers.base import TrackInfo
from app.services import tv_cast

router = APIRouter(prefix="/tv", tags=["tv"])


class PairIn(BaseModel):
    code: str = Field(min_length=4, max_length=40)


class PlayIn(BaseModel):
    tracks: list[Track] = Field(min_length=1, max_length=200)


class ControlIn(BaseModel):
    action: str
    seconds: float | None = Field(None, ge=0)


def _info(track: Track) -> TrackInfo:
    return TrackInfo(
        track.source, track.source_id, track.title, track.artist, track.album, track.year,
        track.duration_seconds, track.cover_url, track.artist_source_id, track.album_source_id,
    )


@router.get("")
async def screens(deps: ApiDeps = Depends(require_token)) -> list[dict]:
    return await deps.repo.tv_screens(deps.user_id)


@router.post("/pair")
async def pair(payload: PairIn, deps: ApiDeps = Depends(require_token)) -> dict:
    try:
        screen = await tv_cast.pair(payload.code)
    except tv_cast.CastError as exc:
        raise HTTPException(400, str(exc)) from exc
    await deps.repo.tv_screen_add(deps.user_id, screen.screen_id, screen.name, screen.lounge_token)
    return {"screen_id": screen.screen_id, "name": screen.name}


@router.delete("/{screen_id}")
async def unpair(screen_id: str, deps: ApiDeps = Depends(require_token)) -> dict:
    await deps.repo.tv_screen_remove(deps.user_id, screen_id)
    return {"removed": True}


@router.post("/{screen_id}/play")
async def play(screen_id: str, payload: PlayIn, deps: ApiDeps = Depends(require_token)) -> dict:
    tracks = [_info(t) for t in payload.tracks]
    try:
        video_id = await tv_cast.play(deps.repo, deps.user_id, screen_id, tracks, deps.settings.youtube_cookies_file)
    except tv_cast.CastError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"video_id": video_id}


@router.post("/{screen_id}/control")
async def control(screen_id: str, payload: ControlIn, deps: ApiDeps = Depends(require_token)) -> dict:
    if payload.action == "seek" and payload.seconds is not None:
        command, parameters = "seekTo", {"newTime": int(payload.seconds)}
    elif payload.action in tv_cast.ACTIONS:
        command, parameters = tv_cast.ACTIONS[payload.action], None
    else:
        raise HTTPException(400, f"Action inconnue : {payload.action}")
    try:
        await tv_cast.send(deps.repo, deps.user_id, screen_id, command, parameters)
    except tv_cast.CastError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"ok": True}
