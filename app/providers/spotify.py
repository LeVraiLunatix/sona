from __future__ import annotations

import base64
import time

import httpx

from app.providers.base import AlbumInfo, ArtistInfo, TrackInfo

TOKEN_URL = "https://accounts.spotify.com/api/token"
API_BASE = "https://api.spotify.com/v1"
OEMBED_URL = "https://open.spotify.com/oembed"


class SpotifyError(Exception):
    pass


class SpotifyNotConfigured(SpotifyError):
    pass


def _year_from_date(date_str: str | None) -> str | None:
    if not date_str or len(date_str) < 4:
        return None
    return date_str[:4]


def _track_from_json(d: dict) -> TrackInfo:
    album = d.get("album") or {}
    artists = d.get("artists") or []
    images = album.get("images") or []
    cover = images[0]["url"] if images else None
    return TrackInfo(
        source="spotify",
        source_id=d["id"],
        title=d.get("name") or "Titre inconnu",
        artist=", ".join(a["name"] for a in artists) if artists else "Artiste inconnu",
        album=album.get("name"),
        year=_year_from_date(album.get("release_date")),
        duration_seconds=(d["duration_ms"] // 1000) if d.get("duration_ms") else None,
        cover_url=cover,
        artist_source_id=artists[0]["id"] if artists else None,
        album_source_id=album.get("id"),
        preview_url=d.get("preview_url") or None,
        # Deezer sait retrouver un enregistrement par son ISRC : c'est ce qui
        # rend un morceau Spotify vérifiable, Spotify ne servant plus
        # d'extrait sur une bonne partie de son catalogue.
        isrc=(d.get("external_ids") or {}).get("isrc") or None,
    )


def _album_from_json(d: dict, tracks: list[TrackInfo] | None = None) -> AlbumInfo:
    artists = d.get("artists") or []
    images = d.get("images") or []
    return AlbumInfo(
        source="spotify",
        source_id=d["id"],
        title=d.get("name") or "Album inconnu",
        artist=", ".join(a["name"] for a in artists) if artists else "Artiste inconnu",
        artist_source_id=artists[0]["id"] if artists else None,
        year=_year_from_date(d.get("release_date")),
        cover_url=images[0]["url"] if images else None,
        track_count=d.get("total_tracks"),
        duration_seconds=sum((t.duration_seconds or 0) for t in tracks) if tracks else None,
        tracks=tracks or [],
    )


class SpotifyClient:
    def __init__(
        self,
        client_id: str | None,
        client_secret: str | None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._client = client or httpx.AsyncClient(timeout=10)
        self._owns_client = client is None
        self._token: str | None = None
        self._token_expiry = 0.0

    @property
    def is_configured(self) -> bool:
        return bool(self._client_id and self._client_secret)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _ensure_token(self) -> str:
        if self._token and time.monotonic() < self._token_expiry:
            return self._token
        creds = f"{self._client_id}:{self._client_secret}".encode()
        auth = base64.b64encode(creds).decode()
        resp = await self._client.post(
            TOKEN_URL,
            data={"grant_type": "client_credentials"},
            headers={"Authorization": f"Basic {auth}"},
        )
        resp.raise_for_status()
        payload = resp.json()
        self._token = payload["access_token"]
        self._token_expiry = time.monotonic() + payload.get("expires_in", 3600) - 30
        return self._token

    async def _get(self, path: str, params: dict | None = None) -> dict:
        if not self.is_configured:
            raise SpotifyNotConfigured
        token = await self._ensure_token()
        try:
            resp = await self._client.get(
                f"{API_BASE}{path}",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise SpotifyError(str(exc)) from exc
        return resp.json()

    async def get_track(self, track_id: str) -> TrackInfo:
        if not self.is_configured:
            return await self._get_track_via_oembed(track_id)
        data = await self._get(f"/tracks/{track_id}")
        return _track_from_json(data)

    async def get_album(self, album_id: str) -> AlbumInfo:
        data = await self._get(f"/albums/{album_id}")
        tracks = []
        for t in (data.get("tracks") or {}).get("items", []):
            merged = dict(t)
            merged["album"] = data
            tracks.append(_track_from_json(merged))
        return _album_from_json(data, tracks)

    async def get_artist(self, artist_id: str) -> ArtistInfo:
        data = await self._get(f"/artists/{artist_id}")
        images = data.get("images") or []
        return ArtistInfo(
            source="spotify",
            source_id=data["id"],
            name=data.get("name") or "Artiste inconnu",
            picture_url=images[0]["url"] if images else None,
        )

    async def get_artist_top_tracks(self, artist_id: str, market: str = "FR") -> list[TrackInfo]:
        data = await self._get(f"/artists/{artist_id}/top-tracks", {"market": market})
        return [_track_from_json(t) for t in data.get("tracks", [])]

    async def get_artist_albums(self, artist_id: str) -> tuple[list[AlbumInfo], list[AlbumInfo]]:
        data = await self._get(
            f"/artists/{artist_id}/albums",
            {"include_groups": "album,single", "limit": 50},
        )
        albums: list[AlbumInfo] = []
        singles: list[AlbumInfo] = []
        for d in data.get("items", []):
            info = _album_from_json(d)
            if (d.get("album_group") or d.get("album_type")) == "album":
                albums.append(info)
            else:
                singles.append(info)
        return albums, singles

    async def _get_track_via_oembed(self, track_id: str) -> TrackInfo:
        url = f"https://open.spotify.com/track/{track_id}"
        try:
            resp = await self._client.get(OEMBED_URL, params={"url": url})
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise SpotifyError(str(exc)) from exc
        data = resp.json()
        title = data.get("title") or "Titre inconnu"
        return TrackInfo(
            source="spotify",
            source_id=track_id,
            title=title,
            artist="Artiste inconnu",
            album=None,
            year=None,
            duration_seconds=None,
            cover_url=data.get("thumbnail_url"),
        )
