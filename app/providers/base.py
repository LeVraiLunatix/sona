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
    # Extrait officiel de 30 s (Deezer, Apple…) : sert à vérifier que l'audio
    # trouvé sur YouTube est bien le même enregistrement.
    preview_url: str | None = None
    # Code ISRC : identifiant international de l'enregistrement, le même d'une
    # plateforme à l'autre. Permet de retrouver le morceau exact sur Deezer
    # quand la source ne fournit pas d'extrait (voir services/preview.py).
    isrc: str | None = None
    # Tempo (Deezer, fiche complète seulement) : pour l'AutoMix.
    bpm: float | None = None

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
    # Date de sortie complète (AAAA-MM-JJ), quand la source la donne.
    release_date: str | None = None
    record_type: str | None = None

    @property
    def uid(self) -> str:
        return f"{self.source}:{self.source_id}"


@dataclass(slots=True)
class ArtistInfo:
    source: str
    source_id: str
    name: str
    picture_url: str | None
    # Nombre de fans (Deezer `nb_fan`) : départage les homonymes (deux
    # « Ziak » chez Deezer, l'un à 600 000 fans, l'autre à 248).
    fans: int | None = None

    @property
    def uid(self) -> str:
        return f"{self.source}:{self.source_id}"


@dataclass(slots=True)
class RadioInfo:
    """Station thématique Deezer (« Rap français », « Années 80 »…)."""

    source_id: str
    title: str
    picture_url: str | None


@dataclass(slots=True)
class SearchResults:
    query: str
    tracks: list[TrackInfo]


@dataclass(slots=True)
class ExternalPlaylist:
    """Playlist lue sur une autre plateforme, à importer dans l'app."""

    name: str
    description: str | None
    cover_url: str | None
    tracks: list[TrackInfo] = field(default_factory=list)
    # Avertissement à montrer dans l'app (import partiel, par exemple).
    note: str | None = None
