"""Petits plus de l'app : nouvelles sorties, « il y a un an », mode sport,
karaoké (instrumentale), moments sur la timeline, carte des écoutes, défis
et badges."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from app.api.auth import require_token
from app.api.schemas import Track
from app.api.state import ApiDeps
from app.bot import lookup
from app.providers.base import TrackInfo
from app.services import challenges, discover, dj_voice, query_cache, recognize, instrumental, listening_map, memories, releases, smart_playlists, sport
from app.services import stats as stats_service

router = APIRouter(tags=["extras"])

_synthesizers: dict[str, dj_voice.Synthesizer] = {}


@router.get("/dj/intro")
async def dj_intro(
    title: str = Query(..., min_length=1),
    artist: str = Query(..., min_length=1),
    prev_title: str | None = Query(None),
    prev_artist: str | None = Query(None),
    year: int | None = Query(None),
    voice: str = Query(dj_voice.DEFAULT_VOICE),
    tz: str | None = Query(None),
    deps: ApiDeps = Depends(require_token),
) -> dict:
    """Annonce du DJ vocal pour le titre qui démarre : le texte, et sa
    lecture en MP3 (base64) par une voix neuronale — `audio` vaut null si
    la voix est injoignable (l'app lit alors le texte elle-même)."""
    import base64
    import random
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    recent = await deps.repo.plays_between(
        deps.user_id, stats_service.to_utc_iso(now - timedelta(days=60)), None
    )
    first_seen = await deps.repo.plays_first_by_artist(deps.user_id)
    key_title, key_artist = title.casefold(), artist.casefold()
    ctx = dj_voice.Context(
        title=title, artist=artist, previous_title=prev_title, previous_artist=prev_artist,
        track_plays=sum(1 for p in recent if p.title.casefold() == key_title and p.artist.casefold() == key_artist),
        artist_plays=sum(1 for p in recent if p.artist.casefold() == key_artist),
        new_artist=key_artist not in first_seen,
        hour=now.astimezone(stats_service.resolve_tz(tz)).hour,
        year=year,
    )
    # Même annonce pour un même titre dans la journée : le cache de voix sert.
    rng = random.Random(f"{deps.user_id}|{key_title}|{key_artist}|{now.date()}|{prev_title}")
    text = dj_voice.script(ctx, rng)
    cache = deps.settings.database_path.parent / "dj_cache"
    synthesizer = _synthesizers.setdefault(str(cache), dj_voice.Synthesizer(cache))
    audio = await synthesizer.speak(text, voice)
    return {"text": text, "audio": base64.b64encode(audio).decode() if audio else None}


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
    out = await challenges.compute(deps.repo, deps.user_id, tz)
    out["friends"] = await challenges.friends_boards(deps.repo, deps.user_id, tz)
    return out


@router.get("/discover/radio/{source}/{artist_id}", response_model=list[Track])
async def discover_radio(source: str, artist_id: str, artist: str = Query(""),
                         deps: ApiDeps = Depends(require_token)) -> list[Track]:
    """« Si tu aimes ce titre » : des artistes proches, jamais écoutés."""
    try:
        tracks = await discover.unknown_artists_radio(deps, deps.user_id, source, artist_id, artist)
    except lookup.UnknownSourceError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except lookup.ProviderErrors as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return [Track.from_info(t) for t in tracks]


@router.get("/home/mood")
async def mood(tz: str | None = Query(None), lat: float | None = Query(None, ge=-90, le=90),
               lon: float | None = Query(None, ge=-180, le=180), deps: ApiDeps = Depends(require_token)) -> dict:
    """Mix « selon la météo » : l'humeur du moment (heure, jour, météo si la position est donnée)."""
    out = await discover.mood_mix(deps, tz, lat, lon)
    out["tracks"] = [Track.from_info(t).model_dump() for t in out["tracks"]]
    return out


@router.post("/recognize")
async def recognize_song(request: Request, deps: ApiDeps = Depends(require_token)) -> dict:
    """« Reconnaître un titre » : l'enregistrement (corps brut : WAV, M4A,
    WebM…) est identifié, puis retrouvé dans le catalogue de Sona."""
    audio = await request.body()
    if len(audio) > recognize.MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Enregistrement trop long.")
    if len(audio) < 2000:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Enregistrement vide.")
    try:
        wav = await recognize.to_wav(audio, deps.settings.ffmpeg_path)
        found = await recognize.identify(wav)
    except recognize.RecognizeError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    if found is None:
        return {"found": None, "track": None}
    from app.services.search import SearchError, search_tracks

    track = None
    try:
        tracks, _ = await search_tracks(deps, query_cache.CachedQuery(text=f"{found['title']} {found['artist']}"), index=0, limit=5)
        track = Track.from_info(tracks[0]).model_dump() if tracks else None
    except SearchError:
        pass
    return {"found": found, "track": track}
