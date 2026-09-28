from __future__ import annotations

from pydantic import BaseModel

from app.db.repository import HistoryItem, LibraryItem, UserSettings
from app.providers.base import AlbumInfo, ArtistInfo, TrackInfo


class Track(BaseModel):
    source: str
    source_id: str
    title: str
    artist: str
    album: str | None
    year: str | None
    duration_seconds: int | None
    cover_url: str | None
    artist_source_id: str | None
    album_source_id: str | None

    @classmethod
    def from_info(cls, t: TrackInfo) -> "Track":
        return cls(
            source=t.source,
            source_id=t.source_id,
            title=t.title,
            artist=t.artist,
            album=t.album,
            year=t.year,
            duration_seconds=t.duration_seconds,
            cover_url=t.cover_url,
            artist_source_id=t.artist_source_id,
            album_source_id=t.album_source_id,
        )


class Album(BaseModel):
    source: str
    source_id: str
    title: str
    artist: str
    artist_source_id: str | None
    year: str | None
    cover_url: str | None
    track_count: int | None
    duration_seconds: int | None
    tracks: list[Track] = []

    @classmethod
    def from_info(cls, a: AlbumInfo) -> "Album":
        return cls(
            source=a.source,
            source_id=a.source_id,
            title=a.title,
            artist=a.artist,
            artist_source_id=a.artist_source_id,
            year=a.year,
            cover_url=a.cover_url,
            track_count=a.track_count,
            duration_seconds=a.duration_seconds,
            tracks=[Track.from_info(t) for t in a.tracks],
        )


class Artist(BaseModel):
    source: str
    source_id: str
    name: str
    picture_url: str | None
    fans: int | None = None

    @classmethod
    def from_info(cls, a: ArtistInfo) -> "Artist":
        return cls(
            source=a.source, source_id=a.source_id, name=a.name, picture_url=a.picture_url, fans=a.fans,
        )


class RadioStation(BaseModel):
    id: str
    title: str
    picture_url: str | None


class RadioGroup(BaseModel):
    title: str
    radios: list[RadioStation]


class LyricsLineOut(BaseModel):
    time: float | None
    text: str


class LyricsOut(BaseModel):
    synced: bool
    instrumental: bool
    lines: list[LyricsLineOut]


class SearchResponse(BaseModel):
    query_id: str
    provider: str | None
    total: int
    tracks: list[Track]


class ResolvedLink(BaseModel):
    kind: str  # "track" | "album" | "artist" | "playlist"
    track: Track | None = None
    album: Album | None = None
    artist: Artist | None = None


class ResolveRequest(BaseModel):
    text: str


class LibraryItemOut(BaseModel):
    kind: str
    source: str
    source_id: str
    title: str
    subtitle: str | None
    cover_url: str | None
    added_at: str

    @classmethod
    def from_item(cls, i: LibraryItem) -> "LibraryItemOut":
        return cls(
            kind=i.kind, source=i.source, source_id=i.source_id, title=i.title,
            subtitle=i.subtitle, cover_url=i.cover_url, added_at=i.added_at,
        )


class LibraryAddRequest(BaseModel):
    source: str
    source_id: str


class HistoryItemOut(BaseModel):
    source: str
    source_id: str
    title: str
    subtitle: str | None
    cover_url: str | None
    viewed_at: str

    @classmethod
    def from_item(cls, i: HistoryItem) -> "HistoryItemOut":
        return cls(
            source=i.source, source_id=i.source_id, title=i.title,
            subtitle=i.subtitle, cover_url=i.cover_url, viewed_at=i.viewed_at,
        )


class UserSettingsOut(BaseModel):
    quality: str
    format: str
    autoplay: bool

    @classmethod
    def from_settings(cls, s: UserSettings) -> "UserSettingsOut":
        return cls(quality=s.quality, format=s.format, autoplay=s.autoplay)


class UserSettingsUpdate(BaseModel):
    quality: str | None = None
    format: str | None = None
    autoplay: bool | None = None
