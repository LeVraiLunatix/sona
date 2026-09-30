"""Karaoké : demandes de séparation voix / instru, état, et les deux pistes.

Les pistes sont servies sous /stream/… : le lecteur web (balise <audio>,
jeton dans l'adresse) peut les lire comme n'importe quel flux audio."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.api.auth import require_token
from app.api.state import ApiDeps
from app.services import karaoke

router = APIRouter(tags=["karaoke"])


class TrackRef(BaseModel):
    source: str = Field(min_length=1, max_length=32)
    source_id: str = Field(min_length=1, max_length=128)


class PrepareIn(BaseModel):
    # Les titres suivants de la file : 2 ou 3 suffisent, la file serveur
    # est partagée entre tous les comptes.
    tracks: list[TrackRef] = Field(default_factory=list, max_length=5)


@router.post("/karaoke/prepare")
async def prepare_upcoming(payload: PrepareIn, deps: ApiDeps = Depends(require_token)) -> list[dict]:
    """Titres à venir quand le mode chant est actif : séparés à l'avance,
    après le titre en cours d'écoute."""
    return [
        {"source": t.source, "source_id": t.source_id,
         **karaoke.request(deps, t.source, t.source_id, karaoke.UPCOMING)}
        for t in payload.tracks
    ]


@router.post("/karaoke/{source}/{source_id}")
async def request_separation(source: str, source_id: str, deps: ApiDeps = Depends(require_token)) -> dict:
    """Titre écouté maintenant en mode chant : en tête de file. Répond tout
    de suite avec l'état ; l'app interroge ensuite `GET` jusqu'à « ready »."""
    return karaoke.request(deps, source, source_id, karaoke.NOW)


@router.get("/karaoke/{source}/{source_id}")
async def separation_status(source: str, source_id: str, deps: ApiDeps = Depends(require_token)) -> dict:
    return karaoke.status(deps.settings, source, source_id)


@router.get("/stream/{source}/{source_id}/karaoke/{stem}")
async def stem_audio(
    source: str,
    source_id: str,
    stem: str,
    quality: str | None = Query(None, description="fast ou hq ; par défaut la meilleure prête"),
    deps: ApiDeps = Depends(require_token),
):
    """Piste voix ou instru (m4a), avec support `Range` comme les autres flux.
    L'app demande les deux pistes dans la même qualité (celle annoncée par
    l'état) : une voix fine sur une instru rapide ne redonnerait pas le
    titre exact."""
    if stem not in karaoke.STEMS or (quality is not None and quality not in karaoke.QUALITIES):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Piste inconnue.")
    quality = quality or karaoke.ready_quality(deps.settings, source, source_id)
    path = karaoke.stem_path(deps.settings, source, source_id, stem, quality) if quality else None
    if path is None or not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Séparation pas encore prête.")
    karaoke.touch(path)
    return FileResponse(path, media_type="audio/mp4", filename=path.name, headers={"X-Karaoke-Quality": quality})
