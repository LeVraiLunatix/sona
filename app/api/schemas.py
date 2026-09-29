from __future__ import annotations

from pydantic import BaseModel, Field

from app.db.repository import HistoryItem, LibraryItem, Playlist, PlaylistEntry, UserSettings
from app.providers.base import AlbumInfo, ArtistInfo, TrackInfo


class Track(BaseModel):
    source: str
    source_id: str
    title: str
    artist: str
    # Facultatifs : l'app omet les champs vides quand elle renvoie un titre
    # (ajout à une playlist) — sans valeur par défaut, « Field required ».
    album: str | None = None
    year: str | None = None
    duration_seconds: int | None = None
    cover_url: str | None = None
    artist_source_id: str | None = None
    album_source_id: str | None = None

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

    def to_info(self) -> TrackInfo:
        return TrackInfo(
            source=self.source,
            source_id=self.source_id,
            title=self.title,
            artist=self.artist,
            album=self.album,
            year=self.year,
            duration_seconds=self.duration_seconds,
            cover_url=self.cover_url,
            artist_source_id=self.artist_source_id,
            album_source_id=self.album_source_id,
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


class PlaylistOut(BaseModel):
    id: int
    name: str
    description: str | None
    cover_url: str | None
    covers: list[str]
    origin: str | None
    track_count: int
    duration_seconds: int
    import_status: str
    import_total: int | None
    import_done: int
    import_missing: int
    import_error: str | None
    updated_at: str
    visibility: str = "private"
    # Faux pour une playlist d'un ami (partagée ou à plusieurs).
    is_owner: bool = True
    owner_name: str | None = None
    # Peut ajouter, retirer, déplacer des titres (propriétaire, ou playlist à plusieurs).
    can_edit: bool = True

    @classmethod
    def from_playlist(cls, p: Playlist, viewer_id: int | None = None, owner_name: str | None = None) -> "PlaylistOut":
        is_owner = viewer_id is None or p.user_id == viewer_id
        return cls(
            id=p.id, name=p.name, description=p.description, cover_url=p.cover_url, covers=p.covers,
            origin=p.origin, track_count=p.track_count, duration_seconds=p.duration_seconds,
            import_status=p.import_status, import_total=p.import_total, import_done=p.import_done,
            import_missing=p.import_missing, import_error=p.import_error, updated_at=p.updated_at,
            visibility=p.visibility, is_owner=is_owner, owner_name=None if is_owner else owner_name,
            can_edit=is_owner or p.visibility == "collaborative",
        )


class PlaylistEntryOut(BaseModel):
    entry_id: int
    track: Track

    @classmethod
    def from_entry(cls, e: PlaylistEntry) -> "PlaylistEntryOut":
        return cls(entry_id=e.entry_id, track=Track.from_info(e.track))


class PlaylistDetailOut(PlaylistOut):
    entries: list[PlaylistEntryOut] = []


class PlaylistCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    tracks: list[Track] = Field(default_factory=list, max_length=1000)


class PlaylistUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    visibility: str | None = None


class PlaylistAddTracks(BaseModel):
    tracks: list[Track] = Field(min_length=1, max_length=1000)


class PlaylistReorder(BaseModel):
    entry_ids: list[int]


class PlaylistImportRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
