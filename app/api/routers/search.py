from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.auth import require_token
from app.api.schemas import Album, Artist, ResolvedLink, ResolveRequest, SearchResponse, Track
from app.api.state import ApiDeps
from app.bot import lookup
from app.providers.deezer import DeezerError
from app.providers.link_detect import resolve_link
from app.services import query_cache
from app.services.artist_search import rank_artists
from app.services.resolver import search_artists_youtube
from app.services.search import SearchError, search_tracks

logger = logging.getLogger(__name__)
router = APIRouter(tags=["search"])


def _require_text(q: str) -> str:
    text = q.strip()
    if not text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Paramètre `q` vide.")
    return text


@router.get("/search/artists", response_model=list[Artist])
async def search_artists(
    q: str = Query(..., description="Nom d'artiste, même approximatif"),
    limit: int = Query(10, ge=1, le=50),
    deps: ApiDeps = Depends(require_token),
) -> list[Artist]:
    text = _require_text(q)
    try:
        artists = await deps.deezer.search_artists(text, limit=limit)
    except DeezerError as exc:
        logger.warning("Recherche d'artistes Deezer indisponible pour %r: %s", text, exc)
        artists = []
    if not artists:
        artists = await search_artists_youtube(text, limit=limit)
    return [Artist.from_info(a) for a in rank_artists(text, artists)]


@router.get("/search/albums", response_model=list[Album])
async def search_albums(
    q: str = Query(...),
    limit: int = Query(10, ge=1, le=50),
    deps: ApiDeps = Depends(require_token),
) -> list[Album]:
    text = _require_text(q)
    try:
        albums = await deps.deezer.search_albums(text, limit=limit)
    except DeezerError as exc:
        logger.warning("Recherche d'albums Deezer indisponible pour %r: %s", text, exc)
        albums = []
    return [Album.from_info(a) for a in albums]


@router.get("/search", response_model=SearchResponse)
async def search(
    q: str | None = Query(None, description="Texte recherché (requis sans query_id)"),
    query_id: str | None = Query(None, description="Identifiant renvoyé par une recherche précédente, pour paginer"),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=50),
    deps: ApiDeps = Depends(require_token),
) -> SearchResponse:
    if query_id:
        cached = query_cache.get(query_id)
        if cached is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Recherche expirée, relance-la avec `q`.")
    elif q and q.strip():
        cached = query_cache.CachedQuery(text=q.strip())
        query_id = query_cache.put(cached)
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Paramètre `q` ou `query_id` requis.")

    try:
        tracks, total = await search_tracks(deps, cached, index=offset, limit=limit)
    except SearchError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    return SearchResponse(
        query_id=query_id,
        provider=cached.provider,
        total=total,
        tracks=[Track.from_info(t) for t in tracks],
    )


@router.post("/resolve", response_model=ResolvedLink)
async def resolve(payload: ResolveRequest, deps: ApiDeps = Depends(require_token)) -> ResolvedLink:
    """Résout un lien Deezer/Spotify/Apple Music/YouTube collé dans l'app
    (équivalent de coller un lien dans la conversation Telegram)."""
    detected = await resolve_link(payload.text)
    if detected is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Aucun lien reconnu dans ce texte.")

    try:
        if detected.kind == "track":
            track = await lookup.get_track(deps, detected.source, detected.ref)
            return ResolvedLink(kind="track", track=Track.from_info(track))
        if detected.kind == "album":
            album = await lookup.get_album(deps, detected.source, detected.ref)
            return ResolvedLink(kind="album", album=Album.from_info(album))
        if detected.kind == "playlist":
            playlist = await lookup.get_playlist(deps, detected.source, detected.ref)
            return ResolvedLink(kind="playlist", album=Album.from_info(playlist))
        if detected.kind == "artist":
            artist = await lookup.get_artist(deps, detected.source, detected.ref)
            return ResolvedLink(kind="artist", artist=Artist.from_info(artist))
    except lookup.UnknownSourceError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Type de contenu non supporté pour {detected.source}.") from exc
    except lookup.ProviderErrors as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    raise HTTPException(status.HTTP_400_BAD_REQUEST, "Lien non supporté.")
