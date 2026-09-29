"""Blind test (voir services/blindtest.py)."""

from __future__ import annotations

import secrets
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.auth import require_token
from app.api.state import ApiDeps
from app.services import blindtest

router = APIRouter(prefix="/blindtest", tags=["blind test"])



class ScoreIn(BaseModel):
    mode: str
    score: int = Field(ge=0, le=100_000)
    correct: int = Field(ge=0, le=100)
    total: int = Field(ge=1, le=100)


def _today() -> str:
    return date.today().isoformat()


async def _players(deps: ApiDeps, everyone: bool) -> list[int]:
    accounts = [a for a in await deps.repo.list_accounts() if a.status == "approved"]
    friends = [a.user_id for a in accounts if everyone or a.share_listening]
    return list(dict.fromkeys([deps.user_id, *friends]))


@router.get("/round")
async def get_round(
    mode: str = Query("solo", description="daily | solo | chart | artist | radio | playlist"),
    ref: str | None = Query(None, description="Artiste, radio ou playlist, selon le mode"),
    count: int = Query(blindtest.DEFAULT_QUESTIONS, ge=3, le=30),
    guess: str = Query("title", description="title | artist"),
    deps: ApiDeps = Depends(require_token),
) -> dict:
    if mode not in blindtest.MODES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Mode inconnu : {mode}")
    if guess not in blindtest.GUESSES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Question inconnue : {guess}")
    day = _today()
    if mode == "daily":
        # Toujours les mêmes règles pour le classement du jour.
        played = await deps.repo.blindtest_daily_played(deps.user_id, day)
        pool = await blindtest.pool_for_mode(deps, mode, await _players(deps, everyone=True), None)
        questions = await blindtest.build_round(deps, pool, f"daily-{day}")
        return {"mode": mode, "day": day, "guess": "title", "already_played": played, "questions": questions}
    if mode == "playlist" and ref:
        playlist = await deps.repo.playlist_by_id(int(ref)) if ref.isdigit() else None
        if playlist is None or (playlist.user_id != deps.user_id and playlist.visibility == "private"):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Playlist introuvable.")
    pool = await blindtest.pool_for_mode(deps, mode, await _players(deps, everyone=False), ref)
    questions = await blindtest.build_round(deps, pool, secrets.randbits(32), count, guess)
    return {"mode": mode, "day": day, "guess": guess, "already_played": False, "questions": questions}


@router.post("/score")
async def post_score(payload: ScoreIn, deps: ApiDeps = Depends(require_token)) -> dict:
    if payload.mode not in blindtest.MODES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Mode inconnu : {payload.mode}")
    day = _today()
    if payload.mode == "daily" and await deps.repo.blindtest_daily_played(deps.user_id, day):
        # Le défi du jour ne compte qu'une fois : la première partie.
        return {"saved": False}
    await deps.repo.blindtest_add_score(deps.user_id, payload.mode, day, payload.score, payload.correct, payload.total)
    return {"saved": True}


@router.get("/leaderboard")
async def leaderboard(mode: str = Query("daily"), deps: ApiDeps = Depends(require_token)) -> list[dict]:
    rows = await deps.repo.blindtest_leaderboard(mode, _today() if mode == "daily" else None)
    names = {
        a.user_id: (a.display_name or a.lastfm_username, a.avatar_url) for a in await deps.repo.list_accounts()
    }
    return [
        {
            "name": names.get(r["user_id"], ("Admin", None))[0],
            "avatar_url": names.get(r["user_id"], ("Admin", None))[1],
            "is_me": r["user_id"] == deps.user_id,
            "score": r["score"],
            "correct": r["correct"],
            "total": r["total"],
        }
        for r in rows
    ]
