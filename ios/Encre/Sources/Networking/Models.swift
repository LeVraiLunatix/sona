import Foundation

// Miroir de `app/api/schemas.py` côté serveur Sona. `CodingKeys` explicites
// partout plutôt qu'un `keyDecodingStrategy(.convertFromSnakeCase)` global :
// Foundation convertit "cover_url" en "coverUrl", pas "coverURL" — silencieux
// avec un champ optionnel (juste `nil`), donc facile à rater sans ça.

struct Track: Codable, Identifiable, Hashable {
    var source: String
    var sourceId: String
    var title: String
    var artist: String
    var album: String?
    var year: String?
    var durationSeconds: Int?
    var coverURL: String?
    var artistSourceId: String?
    var albumSourceId: String?

    enum CodingKeys: String, CodingKey {
        case source, title, artist, album, year
        case sourceId = "source_id"
        case durationSeconds = "duration_seconds"
        case coverURL = "cover_url"
        case artistSourceId = "artist_source_id"
        case albumSourceId = "album_source_id"
    }

    var id: String { "\(source):\(sourceId)" }

    var durationLabel: String {
        guard let s = durationSeconds else { return "--:--" }
        return String(format: "%d:%02d", s / 60, s % 60)
    }
}

struct Album: Codable, Identifiable, Hashable {
    var source: String
    var sourceId: String
    var title: String
    var artist: String
    var artistSourceId: String?
    var year: String?
    var coverURL: String?
    var trackCount: Int?
    var durationSeconds: Int?
    var tracks: [Track]

    enum CodingKeys: String, CodingKey {
        case source, title, artist, year, tracks
        case sourceId = "source_id"
        case artistSourceId = "artist_source_id"
        case coverURL = "cover_url"
        case trackCount = "track_count"
        case durationSeconds = "duration_seconds"
    }

    var id: String { "\(source):\(sourceId)" }
}

struct Artist: Codable, Identifiable, Hashable {
    var source: String
    var sourceId: String
    var name: String
    var pictureURL: String?
    /// Nombre de fans Deezer — `nil` pour les autres sources.
    var fans: Int?

    enum CodingKeys: String, CodingKey {
        case source, name, fans
        case sourceId = "source_id"
        case pictureURL = "picture_url"
    }

    var id: String { "\(source):\(sourceId)" }
}

/// Radio thématique Deezer (`/browse/radios`) : une station sans fin, dont
/// `/radios/{id}/tracks` renvoie un nouveau tirage à chaque appel.
struct RadioStation: Codable, Identifiable, Hashable {
    var id: String
    var title: String
    var pictureURL: String?

    enum CodingKeys: String, CodingKey {
        case id, title
        case pictureURL = "picture_url"
    }
}

/// Paroles (`/lyrics`, source LRCLIB côté serveur). `time` en secondes
/// depuis le début quand `synced`, `nil` sinon.
struct Lyrics: Codable, Hashable {
    struct Line: Codable, Hashable {
        var time: Double?
        var text: String
    }

    var synced: Bool
    var instrumental: Bool
    var lines: [Line]
}

struct RadioGroup: Codable, Identifiable, Hashable {
    var title: String
    var radios: [RadioStation]

    var id: String { title }
}

struct SearchResponse: Codable {
    var queryId: String
    var provider: String?
    var total: Int
    var tracks: [Track]

    enum CodingKeys: String, CodingKey {
        case provider, total, tracks
        case queryId = "query_id"
    }
}

enum ResolvedKind: String, Codable {
    case track, album, artist, playlist
}

struct ResolvedLink: Codable {
    var kind: ResolvedKind
    var track: Track?
    var album: Album?
    var artist: Artist?
}

struct ArtistAlbums: Codable {
    var albums: [Album]
    var singles: [Album]
}

struct LibraryItem: Codable, Identifiable, Hashable {
    var kind: String
    var source: String
    var sourceId: String
    var title: String
    var subtitle: String?
    var coverURL: String?
    var addedAt: String

    enum CodingKeys: String, CodingKey {
        case kind, source, title, subtitle
        case sourceId = "source_id"
        case coverURL = "cover_url"
        case addedAt = "added_at"
    }

    var id: String { "\(kind):\(source):\(sourceId)" }
}

struct LibraryPage: Codable {
    var total: Int
    var items: [LibraryItem]
}

struct HistoryItem: Codable, Identifiable, Hashable {
    var source: String
    var sourceId: String
    var title: String
    var subtitle: String?
    var coverURL: String?
    var viewedAt: String

    enum CodingKeys: String, CodingKey {
        case source, title, subtitle
        case sourceId = "source_id"
        case coverURL = "cover_url"
        case viewedAt = "viewed_at"
    }

    var id: String { "\(source):\(sourceId):\(viewedAt)" }
}

struct HistoryPage: Codable {
    var total: Int
    var items: [HistoryItem]
}

struct UserSettingsDTO: Codable {
    var quality: String
    var format: String
    var autoplay: Bool
}
