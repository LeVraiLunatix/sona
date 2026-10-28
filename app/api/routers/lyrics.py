from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.auth import require_token
from app.api.schemas import LyricsLineOut, LyricsOut, LyricsWordOut
from app.api.state import ApiDeps
from app.providers.lrclib import LyricsError
from app.services.lyrics import LyricsResult, detect_language

logger = logging.getLogger(__name__)
router = APIRouter(tags=["lyrics"])


@router.get("/lyrics", response_model=LyricsOut)
async def get_lyrics(
    title: str = Query(..., min_length=1),
    artist: str = Query(..., min_length=1),
    album: str | None = Query(None),
    duration: int | None = Query(None, ge=1, description="Durée du morceau en secondes"),
    refresh: bool = Query(False, description="Ignorer le cache (« paroles fausses ? chercher encore »)"),
    deps: ApiDeps = Depends(require_token),
) -> LyricsOut:
    """Paroles d'un morceau d'après ses métadonnées (l'app les a déjà sous
    la main) plutôt que par source/identifiant : marche aussi pour les
    morceaux YouTube, sans refaire un appel au fournisseur d'origine.

    Les meilleures disponibles (voir services/lyrics.py) : mot par mot,
    sinon ligne par ligne, sinon le texte brut."""
    title, artist = title.strip(), artist.strip()
    try:
        if deps.lyrics is not None:
            result = await deps.lyrics.get(title, artist, album, duration, refresh=refresh)
        else:
            found = await deps.lrclib.get_lyrics(title, artist, album, duration)
            result = LyricsResult(found, "lrclib", detect_language(found)) if found else None
    except LyricsError as exc:
        logger.warning("Paroles indisponibles pour %r - %r : %s", artist, title, exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pas de paroles connues pour ce morceau.")
    lyrics = result.lyrics
    return LyricsOut(
        synced=lyrics.synced,
        instrumental=lyrics.instrumental,
        sync=result.sync,
        approximate=lyrics.approximate,
        source=result.source,
        language=result.language,
        lines=[
            LyricsLineOut(
                time=line.time, text=line.text, end=line.end,
                words=[LyricsWordOut(time=w.time, text=w.text, end=w.end) for w in line.words] if line.words else None,
            )
            for line in lyrics.lines
        ],
    )
