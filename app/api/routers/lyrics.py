from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.auth import require_token
from app.api.schemas import LyricsLineOut, LyricsOut
from app.api.state import ApiDeps
from app.providers.lrclib import LyricsError

logger = logging.getLogger(__name__)
router = APIRouter(tags=["lyrics"])


@router.get("/lyrics", response_model=LyricsOut)
async def get_lyrics(
    title: str = Query(..., min_length=1),
    artist: str = Query(..., min_length=1),
    album: str | None = Query(None),
    duration: int | None = Query(None, ge=1, description="Durée du morceau en secondes"),
    deps: ApiDeps = Depends(require_token),
) -> LyricsOut:
    """Paroles d'un morceau d'après ses métadonnées (l'app les a déjà sous
    la main) plutôt que par source/identifiant : marche aussi pour les
    morceaux YouTube, sans refaire un appel au fournisseur d'origine."""
    try:
        lyrics = await deps.lrclib.get_lyrics(title.strip(), artist.strip(), album, duration)
    except LyricsError as exc:
        logger.warning("Paroles indisponibles pour %r - %r : %s", artist, title, exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    if lyrics is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pas de paroles connues pour ce morceau.")
    return LyricsOut(
        synced=lyrics.synced,
        instrumental=lyrics.instrumental,
        lines=[LyricsLineOut(time=line.time, text=line.text) for line in lyrics.lines],
    )
