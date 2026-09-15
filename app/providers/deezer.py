from __future__ import annotations

import logging

import httpx

from app.providers.base import AlbumInfo, ArtistInfo, TrackInfo

logger = logging.getLogger(__name__)

API_BASE = "https://api.deezer.com"


class DeezerError(Exception):
    pass


def _year_from_date(date_str: str | None) -> str | None:
    if not date_str or len(date_str) < 4:
        return None
    return date_str[:4]


def _largest_image(d: dict, prefix: str) -> str | None:
    """Plus grande version disponible (`_xl` = 1000 px). La 250 px (`_medium`)
    était pixelisée une fois affichée en grand dans Telegram."""
    return d.get(f"{prefix}_xl") or d.get(f"{prefix}_big") or d.get(f"{prefix}_medium")


def _track_from_json(d: dict) -> TrackInfo:
    album = d.get("album") or {}
    artist = d.get("artist") or {}
    return TrackInfo(
        source="deezer",
        source_id=str(d["id"]),
        title=d.get("title") or d.get("title_short") or "Titre inconnu",
        artist=artist.get("name") or "Artiste inconnu",
        album=album.get("title"),
        year=_year_from_date(album.get("release_date") or d.get("release_date")),
        duration_seconds=d.get("duration"),
        cover_url=_largest_image(album, "cover"),
        artist_source_id=str(artist["id"]) if artist.get("id") else None,
        album_source_id=str(album["id"]) if album.get("id") else None,
        preview_url=d.get("preview") or None,
    )


def _album_from_json(d: dict, tracks: list[TrackInfo] | None = None) -> AlbumInfo:
    artist = d.get("artist") or {}
    return AlbumInfo(
        source="deezer",
        source_id=str(d["id"]),
        title=d.get("title") or "Album inconnu",
        artist=artist.get("name") or "Artiste inconnu",
        artist_source_id=str(artist["id"]) if artist.get("id") else None,
        year=_year_from_date(d.get("release_date")),
        cover_url=_largest_image(d, "cover"),
        track_count=d.get("nb_tracks"),
        duration_seconds=d.get("duration"),
        tracks=tracks or [],
    )


def _artist_from_json(d: dict) -> ArtistInfo:
    return ArtistInfo(
        source="deezer",
        source_id=str(d["id"]),
        name=d.get("name") or "Artiste inconnu",
        picture_url=_largest_image(d, "picture"),
    )


class DeezerClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(timeout=10)
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _get(self, path: str, params: dict | None = None) -> dict:
        try:
            resp = await self._client.get(f"{API_BASE}{path}", params=params)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise DeezerError(str(exc)) from exc
        data = resp.json()
        if isinstance(data, dict) and data.get("error"):
            raise DeezerError(str(data["error"]))
        return data

    async def search_tracks(
        self, query: str, index: int = 0, limit: int = 25
    ) -> tuple[list[TrackInfo], int]:
        data = await self._get(
            "/search/track", {"q": query, "index": index, "limit": limit}
        )
        items = [_track_from_json(d) for d in data.get("data", [])]
        total = data.get("total", len(items))
        return items, total

    async def search_tracks_by_artist(
        self, artist_name: str, query: str, index: int = 0, limit: int = 25
    ) -> tuple[list[TrackInfo], int]:
        full_query = f'artist:"{artist_name}" {query}'.strip()
        return await self.search_tracks(full_query, index=index, limit=limit)

    async def get_track(self, track_id: str) -> TrackInfo:
        data = await self._get(f"/track/{track_id}")
        return _track_from_json(data)

    async def get_album(self, album_id: str) -> AlbumInfo:
        data = await self._get(f"/album/{album_id}")
        tracks = []
        for t in (data.get("tracks") or {}).get("data", []):
            # Les morceaux imbriqués dans /album/<id> n'ont pas d'objet album complet.
            merged = dict(t)
            merged["album"] = {
                "id": data.get("id"),
                "title": data.get("title"),
                "cover_medium": data.get("cover_medium"),
                "cover_big": data.get("cover_big"),
                "cover_xl": data.get("cover_xl"),
                "release_date": data.get("release_date"),
            }
            tracks.append(_track_from_json(merged))
        return _album_from_json(data, tracks)

    async def get_artist(self, artist_id: str) -> ArtistInfo:
        data = await self._get(f"/artist/{artist_id}")
        return _artist_from_json(data)

    async def get_artist_top_tracks(
        self, artist_id: str, limit: int = 25
    ) -> list[TrackInfo]:
        data = await self._get(f"/artist/{artist_id}/top", {"limit": limit})
        return [_track_from_json(d) for d in data.get("data", [])]

    async def get_artist_albums(
        self, artist_id: str
    ) -> tuple[list[AlbumInfo], list[AlbumInfo]]:
        """Retourne (albums, singles_et_eps)."""
        data = await self._get(f"/artist/{artist_id}/albums", {"limit": 100})
        albums: list[AlbumInfo] = []
        singles: list[AlbumInfo] = []
        for d in data.get("data", []):
            info = _album_from_json(d)
            if (d.get("record_type") or "").lower() == "album":
                albums.append(info)
            else:
                singles.append(info)
        return albums, singles

    async def get_track_by_isrc_hint(self, title: str, artist: str) -> TrackInfo | None:
        items, _ = await self.search_tracks(f'"{title}" "{artist}"', limit=1)
        return items[0] if items else None
