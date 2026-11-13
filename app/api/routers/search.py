from __future__ import annotations

import asyncio
import logging
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.api.auth import require_token
from app.api.schemas import Album, Artist, ResolvedLink, ResolveRequest, SearchResponse, Track
from app.api.state import ApiDeps
from app.bot import lookup
from app.providers.deezer import DeezerError
from app.providers.link_detect import resolve_link
from app.services import query_cache
from app.services.artist_search import rank_artists
from app.services.resolver import search_artists_youtube
from app.services.search import SearchError, _fold as fold, search_tracks, tidy_results

logger = logging.getLogger(__name__)
router = APIRouter(tags=["search"])


async def _without_archives(deps: ApiDeps, tracks: list) -> list:
    """Les artistes à identités (FEMTOGO…) ne sont qu'une archive : rien de leur côté Deezer dans la recherche."""
    ids, names = await deps.repo.archive_artists()
    if not ids and not names:
        return tracks
    folded = {fold(n) for n in names}
    return [
        t for t in tracks
        if t.source == "exclusive"
        or not ((t.source, t.artist_source_id or "") in ids
                or any(fold(part) in folded for part in (t.artist or "").split(",")))
    ]


def _require_text(q: str) -> str:
    text = q.strip()
    if not text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Paramètre `q` vide.")
    return text


# Les résultats de recherche Deezer n'ont pas les artistes en featuring : on
# les lit sur la fiche des premiers titres (en cache 6 h), au mieux et vite.
FEATS_LOOKUP_MAX = 12
FEATS_LOOKUP_BUDGET = 2.5


async def _add_feats(deps: ApiDeps, tracks: list) -> None:
    todo = [t for t in tracks if t.source == "deezer" and not t.artists][:FEATS_LOOKUP_MAX]
    if not todo:
        return
    gate = asyncio.Semaphore(4)

    async def one(track) -> None:
        async with gate:
            try:
                track.artists = (await lookup.get_track(deps, "deezer", track.source_id)).artists
            except Exception:  # noqa: BLE001 — au mieux : la recherche ne doit jamais échouer pour ça
                return

    tasks = [asyncio.create_task(one(t)) for t in todo]
    _, pending = await asyncio.wait(tasks, timeout=FEATS_LOOKUP_BUDGET)
    for task in pending:
        task.cancel()


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
    ids, names = await deps.repo.archive_artists()
    folded = {fold(n) for n in names}
    artists = [a for a in artists if (a.source, a.source_id) not in ids and fold(a.name) not in folded]
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
    _, names = await deps.repo.archive_artists()
    folded = {fold(n) for n in names}
    return [Album.from_info(a) for a in albums if fold(a.artist) not in folded]


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

    # Pas de ré-ordonnancement d'une page suivante : l'ordre de la source fait foi.
    tracks = tidy_results(cached.text, tracks) if offset == 0 else tidy_results("", tracks)
    tracks = await _without_archives(deps, tracks)
    await _add_feats(deps, tracks)
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


# -- Suggestions pendant la frappe ------------------------------------------

class Suggestion(BaseModel):
    kind: Literal["artist", "track"]
    text: str
    subtitle: str | None = None
    picture_url: str | None = None
    source: str
    source_id: str
    artist_source_id: str | None = None


SUGGEST_TTL = 60.0
SUGGEST_BUDGET = 2.0
_suggest_cache: dict[str, tuple[float, list[Suggestion]]] = {}


@router.get("/search/suggest", response_model=list[Suggestion])
async def suggest(
    q: str = Query(..., description="Début de saisie"),
    limit: int = Query(8, ge=1, le=12),
    deps: ApiDeps = Depends(require_token),
) -> list[Suggestion]:
    """Quelques artistes puis quelques titres pour la saisie en cours (liste
    sous la barre de recherche). Au mieux : lent ou en panne, la liste est
    simplement vide — la recherche, elle, ne dépend pas de ça. Gardé 1 min."""
    text = q.strip()
    if len(text) < 2:
        return []
    key = text.casefold()
    hit = _suggest_cache.get(key)
    if hit and time.monotonic() - hit[0] < SUGGEST_TTL:
        return hit[1][:limit]

    async def artists():
        return rank_artists(text, await deps.deezer.search_artists(text, limit=3))

    async def titles():
        found, _ = await deps.deezer.search_tracks(text, limit=6, order="RANKING")
        return tidy_results(text, found)

    try:
        got = await asyncio.wait_for(asyncio.gather(artists(), titles(), return_exceptions=True), SUGGEST_BUDGET)
    except asyncio.TimeoutError:
        return []
    found_artists = got[0] if isinstance(got[0], list) else []
    found_tracks = got[1] if isinstance(got[1], list) else []
    ids, names = await deps.repo.archive_artists()
    folded = {fold(n) for n in names}
    found_artists = [a for a in found_artists if (a.source, a.source_id) not in ids and fold(a.name) not in folded]
    found_tracks = await _without_archives(deps, found_tracks)
    out = [
        Suggestion(kind="artist", text=a.name, subtitle="Artiste", picture_url=a.picture_url, source=a.source, source_id=a.source_id)
        for a in found_artists
    ] + [
        Suggestion(
            kind="track", text=t.title, subtitle=t.artist, picture_url=t.cover_url, source=t.source,
            source_id=t.source_id, artist_source_id=getattr(t, "artist_source_id", None),
        )
        for t in found_tracks
    ]
    if out:
        if len(_suggest_cache) > 300:
            _suggest_cache.clear()
        _suggest_cache[key] = (time.monotonic(), out)
    return out[:limit]
