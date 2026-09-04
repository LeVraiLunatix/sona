from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class TrackInfo:
    source: str  # "deezer" | "apple" | "spotify" | "youtube"
    source_id: str
    title: str
    artist: str
    album: str | None
    year: str | None
    duration_seconds: int | None
    cover_url: str | None
    artist_source_id: str | None = None
    album_source_id: str | None = None

    @property
    def uid(self) -> str:
        return f"{self.source}:{self.source_id}"

    @property
    def duration_label(self) -> str:
        if not self.duration_seconds:
            return "--:--"
        minutes, seconds = divmod(int(self.duration_seconds), 60)
        return f"{minutes}:{seconds:02d}"


@dataclass(slots=True)
class AlbumInfo:
    source: str
    source_id: str
    title: str
    artist: str
    artist_source_id: str | None
    year: str | None
    cover_url: str | None
    track_count: int | None
    duration_seconds: int | None
    tracks: list[TrackInfo] = field(default_factory=list)

    @property
    def uid(self) -> str:
        return f"{self.source}:{self.source_id}"


@dataclass(slots=True)
class ArtistInfo:
    source: str
    source_id: str
    name: str
    picture_url: str | None

    @property
    def uid(self) -> str:
        return f"{self.source}:{self.source_id}"


@dataclass(slots=True)
class SearchResults:
    query: str
    tracks: list[TrackInfo]
