"""Page publique « J'écoute » : un lien secret (à mettre sur un profil
Discord, Instagram…) qui montre en direct le titre en cours du compte, ou
sa dernière écoute. Activée et révoquée par le compte lui-même ; le lien ne
donne accès à rien d'autre."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

from app.api.auth import get_deps, require_token
from app.api.state import ApiDeps
from app.services import presence

router = APIRouter(tags=["page publique"])

PAGE = Path(__file__).resolve().parents[3] / "web" / "now.html"


@router.get("/me/public-link")
async def get_link(deps: ApiDeps = Depends(require_token)) -> dict:
    return {"token": await deps.repo.public_link(deps.user_id)}


@router.post("/me/public-link")
async def create_link(deps: ApiDeps = Depends(require_token)) -> dict:
    """Crée le lien (ou en change : l'ancien ne marche plus)."""
    token = secrets.token_urlsafe(12)
    await deps.repo.public_link_set(deps.user_id, token)
    return {"token": token}


@router.delete("/me/public-link", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_link(deps: ApiDeps = Depends(require_token)) -> None:
    await deps.repo.public_link_delete(deps.user_id)


async def _owner(deps: ApiDeps, token: str) -> int:
    user_id = await deps.repo.public_link_user(token) if 8 <= len(token) <= 64 else None
    if user_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ce lien n'existe pas (ou plus).")
    return user_id


@router.get("/p/{token}", include_in_schema=False)
async def page(token: str, deps: ApiDeps = Depends(get_deps)) -> FileResponse:
    await _owner(deps, token)
    return FileResponse(PAGE, media_type="text/html", headers={"Cache-Control": "no-cache", "X-Robots-Tag": "noindex"})


@router.get("/p/{token}/now")
async def now(token: str, deps: ApiDeps = Depends(get_deps)) -> dict:
    """Ce que montre la page : le titre en cours (et où il en est), sinon la dernière écoute."""
    user_id = await _owner(deps, token)
    account = await deps.repo.account_by_user_id(user_id)
    sharing = account is None or account.share_listening
    name = (account.display_name or account.lastfm_username) if account else "Sona"
    playing = None
    entry = presence.get(user_id) if sharing else None
    if entry is not None:
        t = entry.track
        playing = {
            "title": t.title, "artist": t.artist, "album": t.album, "cover_url": t.cover_url,
            "duration": t.duration_seconds,
            "position": round((datetime.now(timezone.utc) - entry.started_at).total_seconds(), 1),
        }
    last = None
    if playing is None and sharing:
        plays = await deps.repo.plays_recent(user_id, 1)
        if plays:
            p = plays[0]
            last = {"title": p.title, "artist": p.artist, "album": p.album, "cover_url": p.cover_url, "played_at": p.played_at}
    return {"name": name, "avatar_url": account.avatar_url if account else None, "playing": playing, "last": last}
