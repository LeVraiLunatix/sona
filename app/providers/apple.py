from __future__ import annotations

import re

import httpx

from app.providers.base import AlbumInfo, ArtistInfo, TrackInfo

LOOKUP_URL = "https://itunes.apple.com/lookup"


class AppleMusicError(Exception):
    pass


def _upsize_artwork(url: str | None, size: int = 600) -> str | None:
    if not url:
        return None
    return re.sub(r"/\d+x\d+bb\.", f"/{size}x{size}bb.", url)


def _year_from_date(date_str: str | None) -> str | None:
    if not date_str or len(date_str) < 4:
        return None
    return date_str[:4]


def _track_from_json(d: dict) -> TrackInfo:
    return TrackInfo(
        source="apple",
        source_id=str(d["trackId"]),
        title=d.get("trackName") or "Titre inconnu",
        artist=d.get("artistName") or "Artiste inconnu",
        album=d.get("collectionName"),
        year=_year_from_date(d.get("releaseDate")),
        duration_seconds=(d["trackTimeMillis"] // 1000) if d.get("trackTimeMillis") else None,
        cover_url=_upsize_artwork(d.get("artworkUrl100")),
        artist_source_id=str(d["artistId"]) if d.get("artistId") else None,
        album_source_id=str(d["collectionId"]) if d.get("collectionId") else None,
    )


class AppleMusicClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(timeout=10)
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _lookup(self, params: dict) -> list[dict]:
        try:
            resp = await self._client.get(LOOKUP_URL, params=params)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise AppleMusicError(str(exc)) from exc
        return resp.json().get("results", [])

    async def get_track(self, track_id: str) -> TrackInfo:
        results = await self._lookup({"id": track_id, "entity": "song"})
        for r in results:
            if str(r.get("trackId")) == str(track_id):
                return _track_from_json(r)
        raise AppleMusicError("Morceau introuvable sur Apple Music.")

    async def get_album(self, album_id: str) -> AlbumInfo:
        results = await self._lookup({"id": album_id, "entity": "song"})
        if not results:
            raise AppleMusicError("Album introuvable sur Apple Music.")
        collection = next((r for r in results if r.get("wrapperType") == "collection"), None)
        songs = [r for r in results if r.get("wrapperType") == "track"]
        tracks = [_track_from_json(s) for s in songs]
        if collection:
            return AlbumInfo(
                source="apple",
                source_id=str(collection["collectionId"]),
                title=collection.get("collectionName") or "Album inconnu",
                artist=collection.get("artistName") or "Artiste inconnu",
                artist_source_id=str(collection["artistId"]) if collection.get("artistId") else None,
                year=_year_from_date(collection.get("releaseDate")),
                cover_url=_upsize_artwork(collection.get("artworkUrl100")),
                track_count=collection.get("trackCount"),
                duration_seconds=sum((t.duration_seconds or 0) for t in tracks) or None,
                tracks=tracks,
            )
        first = tracks[0]
        return AlbumInfo(
            source="apple",
            source_id=str(album_id),
            title=first.album or "Album inconnu",
            artist=first.artist,
            artist_source_id=first.artist_source_id,
            year=first.year,
            cover_url=first.cover_url,
            track_count=len(tracks),
            duration_seconds=sum((t.duration_seconds or 0) for t in tracks) or None,
            tracks=tracks,
        )

    async def get_artist(self, artist_id: str) -> ArtistInfo:
        results = await self._lookup({"id": artist_id, "entity": "song", "limit": 1})
        if not results:
            raise AppleMusicError("Artiste introuvable sur Apple Music.")
        artist = results[0]
        return ArtistInfo(
            source="apple",
            source_id=str(artist_id),
            name=artist.get("artistName") or "Artiste inconnu",
            picture_url=None,
        )

    async def get_artist_top_tracks(self, artist_id: str, limit: int = 25) -> list[TrackInfo]:
        results = await self._lookup({"id": artist_id, "entity": "song", "limit": limit})
        return [_track_from_json(r) for r in results if r.get("wrapperType") == "track"]

    async def get_artist_albums(self, artist_id: str) -> tuple[list[AlbumInfo], list[AlbumInfo]]:
        results = await self._lookup({"id": artist_id, "entity": "album", "limit": 100})
        albums: list[AlbumInfo] = []
        singles: list[AlbumInfo] = []
        for r in results:
            if r.get("wrapperType") != "collection":
                continue
            info = AlbumInfo(
                source="apple",
                source_id=str(r["collectionId"]),
                title=r.get("collectionName") or "Album inconnu",
                artist=r.get("artistName") or "Artiste inconnu",
                artist_source_id=str(artist_id),
                year=_year_from_date(r.get("releaseDate")),
                cover_url=_upsize_artwork(r.get("artworkUrl100")),
                track_count=r.get("trackCount"),
                duration_seconds=None,
            )
            track_count = r.get("trackCount") or 0
            if (r.get("collectionType") or "").lower() == "album" and track_count > 3:
                albums.append(info)
            else:
                singles.append(info)
        return albums, singles
