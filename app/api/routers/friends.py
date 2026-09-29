"""Onglet Amis : ce qu'écoutent les autres comptes de l'app en ce moment,
leurs dernières écoutes, leurs goûts comparés aux siens et leurs playlists
partagées.

« Amis » = tous les comptes acceptés qui partagent leur écoute (réglage
`share_listening`) : l'app est privée, chaque compte a été validé par un
admin — pas besoin de demandes d'ami en plus.
"""

from __future__ import annotations

import math
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.auth import require_token
from app.api.schemas import PlaylistOut, Track
from app.api.state import ApiDeps
from app.db.repository import Account, Play
from app.services import presence
from app.services import stats as stats_service

router = APIRouter(prefix="/friends", tags=["amis"])

TASTE_WINDOW_DAYS = 90
MIN_PLAYS_FOR_TASTE = 10


class NowPlayingOut(BaseModel):
    track: Track
    started_at: str


class FriendPlayOut(BaseModel):
    played_at: str
    title: str
    artist: str
    album: str | None
    cover_url: str | None
    source: str | None
    source_id: str | None
    artist_source_id: str | None
    album_source_id: str | None
    duration_seconds: int | None

    @classmethod
    def from_play(cls, p: Play) -> "FriendPlayOut":
        return cls(
            played_at=p.played_at, title=p.title, artist=p.artist, album=p.album, cover_url=p.cover_url,
            source=p.source, source_id=p.source_id, artist_source_id=p.artist_source_id,
            album_source_id=p.album_source_id, duration_seconds=p.duration_seconds,
        )


class FriendRankedOut(BaseModel):
    name: str
    subtitle: str | None
    plays: int
    cover_url: str | None
    source: str | None
    source_id: str | None


class FriendOut(BaseModel):
    account_id: int
    username: str
    display_name: str | None
    avatar_url: str | None
    now_playing: NowPlayingOut | None
    last_play: FriendPlayOut | None
    # Affinité musicale en % (artistes écoutés ces 90 derniers jours), ou
    # None si l'un des deux n'a pas encore assez écouté.
    compatibility: int | None


class FriendProfileOut(FriendOut):
    shared_artists: list[str]
    top_artists: list[FriendRankedOut]
    top_tracks: list[FriendRankedOut]
    recent: list[FriendPlayOut]
    playlists: list[PlaylistOut]


def _taste(plays: list[Play]) -> Counter:
    return Counter(p.artist.casefold() for p in plays)


def compatibility(mine: Counter, theirs: Counter) -> int | None:
    """Similarité cosinus des écoutes par artiste, en pourcentage."""
    if sum(mine.values()) < MIN_PLAYS_FOR_TASTE or sum(theirs.values()) < MIN_PLAYS_FOR_TASTE:
        return None
    dot = sum(count * theirs[artist] for artist, count in mine.items())
    norm = math.sqrt(sum(c * c for c in mine.values())) * math.sqrt(sum(c * c for c in theirs.values()))
    return round(100 * dot / norm) if norm else None


async def _recent_plays(deps: ApiDeps, user_id: int, days: int) -> list[Play]:
    start = stats_service.to_utc_iso(datetime.now(timezone.utc) - timedelta(days=days))
    return await deps.repo.plays_between(user_id, start, None)


# Goûts (écoutes par artiste sur 90 jours) gardés 10 min : l'onglet Amis se
# rafraîchit toutes les 15 s, et relire des milliers d'écoutes à chaque fois
# ralentissait tout le serveur.
TASTE_CACHE_SECONDS = 600
_tastes: dict[int, tuple[float, Counter]] = {}


async def _taste_of(deps: ApiDeps, user_id: int) -> Counter:
    now = time.monotonic()
    hit = _tastes.get(user_id)
    if hit is not None and hit[0] > now:
        return hit[1]
    taste = _taste(await _recent_plays(deps, user_id, TASTE_WINDOW_DAYS))
    _tastes[user_id] = (now + TASTE_CACHE_SECONDS, taste)
    return taste


async def _friends(deps: ApiDeps) -> list[Account]:
    return [
        a for a in await deps.repo.list_accounts()
        if a.status == "approved" and a.share_listening and a.user_id != deps.user_id
    ]


async def _friend_out(deps: ApiDeps, friend: Account, my_taste: Counter, cls=FriendOut, **extra):
    playing = presence.get(friend.user_id)
    last = await deps.repo.plays_recent(friend.user_id, 1)
    theirs = extra.pop("_their_plays", None)
    their_taste = _taste(theirs) if theirs is not None else await _taste_of(deps, friend.user_id)
    return cls(
        account_id=friend.id,
        username=friend.lastfm_username,
        display_name=friend.display_name,
        avatar_url=friend.avatar_url,
        now_playing=NowPlayingOut(
            track=Track.from_info(playing.track), started_at=stats_service.to_utc_iso(playing.started_at)
        ) if playing else None,
        last_play=FriendPlayOut.from_play(last[0]) if last else None,
        compatibility=compatibility(my_taste, their_taste),
        **extra,
    )


@router.get("", response_model=list[FriendOut])
async def list_friends(deps: ApiDeps = Depends(require_token)) -> list[FriendOut]:
    my_taste = await _taste_of(deps, deps.user_id)
    friends = [await _friend_out(deps, f, my_taste) for f in await _friends(deps)]
    # En train d'écouter d'abord, puis par écoute la plus récente (tris
    # stables : le second garde l'ordre du premier à égalité).
    friends.sort(key=lambda f: f.last_play.played_at if f.last_play else "", reverse=True)
    friends.sort(key=lambda f: f.now_playing is None)
    return friends


@router.get("/{account_id}", response_model=FriendProfileOut)
async def friend_profile(account_id: int, deps: ApiDeps = Depends(require_token)) -> FriendProfileOut:
    friend = next((f for f in await _friends(deps) if f.id == account_id), None)
    if friend is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profil introuvable ou privé.")
    my_plays = await _recent_plays(deps, deps.user_id, TASTE_WINDOW_DAYS)
    their_plays = await _recent_plays(deps, friend.user_id, TASTE_WINDOW_DAYS)
    my_top = {a.name.casefold() for a in stats_service.top_artists(my_plays, limit=50)}
    shared = [a.name for a in stats_service.top_artists(their_plays, limit=50) if a.name.casefold() in my_top][:12]
    month = await _recent_plays(deps, friend.user_id, 30)

    def ranked(items):
        return [
            FriendRankedOut(
                name=i.name, subtitle=i.subtitle, plays=i.plays, cover_url=i.cover_url,
                source=i.source, source_id=i.source_id,
            )
            for i in items
        ]

    playlists = await deps.repo.playlists_shared_by(friend.user_id)
    owner = friend.display_name or friend.lastfm_username
    return await _friend_out(
        deps, friend, _taste(my_plays), FriendProfileOut,
        _their_plays=their_plays,
        shared_artists=shared,
        top_artists=ranked(stats_service.top_artists(month, limit=10)),
        top_tracks=ranked(stats_service.top_tracks(month, limit=10)),
        recent=[FriendPlayOut.from_play(p) for p in await deps.repo.plays_recent(friend.user_id, 20)],
        playlists=[PlaylistOut.from_playlist(p, deps.user_id, owner) for p in playlists],
    )
