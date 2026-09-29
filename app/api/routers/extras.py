"""Petits plus de l'app : nouvelles sorties, « il y a un an », mode sport,
karaoké (instrumentale), moments sur la timeline, carte des écoutes, défis
et badges."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.auth import require_token
from app.api.schemas import Track
from app.api.state import ApiDeps
from app.providers.base import TrackInfo
from app.services import challenges, instrumental, listening_map, memories, releases, smart_playlists, sport

router = APIRouter(tags=["extras"])


@router.get("/smart")
async def smart_playlists_list(tz: str | None = Query(None), deps: ApiDeps = Depends(require_token)) -> list[dict]:
    """Playlists intelligentes non vides, avec quelques pochettes."""
    out = []
    for kind, (title, subtitle, icon) in smart_playlists.KINDS.items():
        tracks = await smart_playlists.build(deps.repo, deps.user_id, kind, tz)
        if tracks:
            covers = list(dict.fromkeys(t["cover_url"] for t in tracks if t["cover_url"]))[:4]
            out.append({"id": kind, "title": title, "subtitle": subtitle, "icon": icon,
                        "count": len(tracks), "covers": covers})
    return out


@router.get("/smart/{kind}", response_model=list[Track])
async def smart_playlist(kind: str, tz: str | None = Query(None), deps: ApiDeps = Depends(require_token)) -> list[Track]:
    if kind not in smart_playlists.KINDS:
        raise HTTPException(404, "Playlist intelligente inconnue.")
    return [Track(**t) for t in await smart_playlists.build(deps.repo, deps.user_id, kind, tz)]


@router.get("/releases")
async def new_releases(deps: ApiDeps = Depends(require_token)) -> list[dict]:
    """Sorties des 3 dernières semaines chez tes artistes les plus écoutés."""
    return await releases.recent_releases(deps, deps.user_id)


@router.get("/memories")
async def on_this_day(tz: str | None = Query(None), deps: ApiDeps = Depends(require_token)) -> list[dict]:
    return await memories.memories(deps.repo, deps.user_id, tz)


@router.get("/sport", response_model=list[Track])
async def sport_tracks(
    bpm: float = Query(..., ge=60, le=220, description="Cadence de course (pas par minute)"),
    exclude: str = Query(""),
    deps: ApiDeps = Depends(require_token),
) -> list[Track]:
    excluded = {x for x in exclude.split(",") if x}
    return [Track.from_info(t) for t in await sport.tracks_for_tempo(deps, deps.user_id, bpm, excluded)]


@router.get("/instrumental/{source}/{source_id}")
async def find_instrumental(
    source: str,
    source_id: str,
    title: str = Query(..., min_length=1),
    artist: str = Query(..., min_length=1),
    duration: int | None = Query(None, ge=1),
    deps: ApiDeps = Depends(require_token),
) -> dict:
    """Vidéo YouTube de l'instrumentale (à lire via /stream/youtube/<id>)."""
    track = TrackInfo(source, source_id, title, artist, None, None, duration, None)
    video_id = await instrumental.find(track, deps.settings.youtube_cookies_file)
    if video_id is None:
        raise HTTPException(404, "Pas d'instrumentale à la bonne durée pour ce titre.")
    return {"source": "youtube", "source_id": video_id}


# -- Moments -----------------------------------------------------------------


class MomentIn(BaseModel):
    position: float = Field(ge=0, le=7200)
    emoji: str = Field(min_length=1, max_length=8)
    text: str | None = Field(None, max_length=80)


async def _circle(deps: ApiDeps) -> dict[int, tuple[str, str | None]]:
    """Toi et tes amis (ceux qui partagent leur écoute) : nom et avatar."""
    people = {}
    for a in await deps.repo.list_accounts():
        if a.status == "approved" and (a.share_listening or a.user_id == deps.user_id):
            people[a.user_id] = (a.display_name or a.lastfm_username, a.avatar_url)
    people.setdefault(deps.user_id, ("Toi", None))
    return people


@router.get("/moments/{source}/{source_id}")
async def track_moments(source: str, source_id: str, deps: ApiDeps = Depends(require_token)) -> list[dict]:
    people = await _circle(deps)
    rows = await deps.repo.moments_for(source, source_id, list(people))
    return [
        {
            "id": r["id"], "position": r["position"], "emoji": r["emoji"], "text": r["text"],
            "name": people[r["user_id"]][0], "avatar_url": people[r["user_id"]][1],
            "is_me": r["user_id"] == deps.user_id,
        }
        for r in rows
    ]


@router.post("/moments/{source}/{source_id}")
async def add_moment(source: str, source_id: str, payload: MomentIn, deps: ApiDeps = Depends(require_token)) -> dict:
    text = (payload.text or "").strip() or None
    moment_id = await deps.repo.moment_add(deps.user_id, source, source_id, payload.position, payload.emoji, text)
    return {"id": moment_id}


@router.delete("/moments/{moment_id}")
async def delete_moment(moment_id: int, deps: ApiDeps = Depends(require_token)) -> dict:
    await deps.repo.moment_delete(deps.user_id, moment_id)
    return {"deleted": True}


# -- Carte, défis ------------------------------------------------------------


@router.get("/map")
async def listening_places(deps: ApiDeps = Depends(require_token)) -> list[dict]:
    return await listening_map.places(deps.repo, deps.user_id)


@router.get("/challenges")
async def weekly_challenges(tz: str | None = Query(None), deps: ApiDeps = Depends(require_token)) -> dict:
    return await challenges.compute(deps.repo, deps.user_id, tz)
