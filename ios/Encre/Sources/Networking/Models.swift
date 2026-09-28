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

// MARK: - Stats d'écoute (`/plays`, `/stats`)

/// Écoute terminée envoyée au serveur — aussi stockée telle quelle en
/// attente d'envoi quand le réseau manque (voir `Scrobbler`).
struct PlayPayload: Codable, Hashable {
    var title: String
    var artist: String
    var album: String?
    var source: String
    var sourceId: String
    var artistSourceId: String?
    var albumSourceId: String?
    var coverURL: String?
    var durationSeconds: Int?
    var listenedSeconds: Int
    var playedAt: String

    enum CodingKeys: String, CodingKey {
        case title, artist, album, source
        case sourceId = "source_id"
        case artistSourceId = "artist_source_id"
        case albumSourceId = "album_source_id"
        case coverURL = "cover_url"
        case durationSeconds = "duration_seconds"
        case listenedSeconds = "listened_seconds"
        case playedAt = "played_at"
    }
}

struct RecentPlay: Codable, Identifiable, Hashable {
    var playedAt: String
    var title: String
    var artist: String
    var album: String?
    var source: String?
    var sourceId: String?
    var artistSourceId: String?
    var albumSourceId: String?
    var coverURL: String?
    var durationSeconds: Int?
    var origin: String

    enum CodingKeys: String, CodingKey {
        case title, artist, album, source, origin
        case playedAt = "played_at"
        case sourceId = "source_id"
        case artistSourceId = "artist_source_id"
        case albumSourceId = "album_source_id"
        case coverURL = "cover_url"
        case durationSeconds = "duration_seconds"
    }

    var id: String { "\(playedAt)|\(title)|\(artist)" }
}

struct RankedStat: Codable, Identifiable, Hashable {
    var name: String
    var subtitle: String?
    var plays: Int
    var minutes: Int
    var coverURL: String?
    var source: String?
    var sourceId: String?

    enum CodingKeys: String, CodingKey {
        case name, subtitle, plays, minutes, source
        case coverURL = "cover_url"
        case sourceId = "source_id"
    }

    var id: String { "\(name)|\(subtitle ?? "")" }
}

struct StatBucket: Codable, Hashable {
    var label: String
    var plays: Int
    var minutes: Int
}

struct StatsReport: Codable, Hashable {
    var period: String
    var offset: Int
    var label: String
    var plays: Int
    var minutes: Int
    var artists: Int
    var tracks: Int
    var albums: Int
    var previousPlays: Int
    var topArtists: [RankedStat]
    var topTracks: [RankedStat]
    var topAlbums: [RankedStat]
    var timeline: [StatBucket]
    var hours: [Int]
    var weekdays: [Int]
    var discoveries: [RankedStat]
    var topHour: Int?
    var topWeekday: String?
    var streakDays: Int
    var firstPlay: String?

    enum CodingKeys: String, CodingKey {
        case period, offset, label, plays, minutes, artists, tracks, albums, timeline, hours, weekdays, discoveries
        case previousPlays = "previous_plays"
        case topArtists = "top_artists"
        case topTracks = "top_tracks"
        case topAlbums = "top_albums"
        case topHour = "top_hour"
        case topWeekday = "top_weekday"
        case streakDays = "streak_days"
        case firstPlay = "first_play"
    }
}

struct LastfmImportStatus: Codable, Hashable {
    var configured: Bool
    var running: Bool
    var page: Int
    var totalPages: Int
    var imported: Int
    var error: String?
    var finishedAt: String?

    enum CodingKeys: String, CodingKey {
        case configured, running, page, imported, error
        case totalPages = "total_pages"
        case finishedAt = "finished_at"
    }
}

// MARK: - Comptes (`/auth`, `/admin`)

struct AppAccount: Codable, Identifiable, Hashable {
    var id: Int?
    var username: String
    var displayName: String?
    var avatarURL: String?
    var status: String
    var isAdmin: Bool
    var scrobbleToLastfm: Bool
    var createdAt: String?

    enum CodingKeys: String, CodingKey {
        case id, username, status
        case displayName = "display_name"
        case avatarURL = "avatar_url"
        case isAdmin = "is_admin"
        case scrobbleToLastfm = "scrobble_to_lastfm"
        case createdAt = "created_at"
    }

    var name: String { displayName ?? username }
}

struct AuthConfig: Codable {
    var lastfmEnabled: Bool
    var authURL: String?
    var apiKey: String?

    enum CodingKeys: String, CodingKey {
        case lastfmEnabled = "lastfm_enabled"
        case authURL = "auth_url"
        case apiKey = "api_key"
    }
}

struct LoginResponse: Codable {
    var sessionToken: String
    var account: AppAccount

    enum CodingKeys: String, CodingKey {
        case account
        case sessionToken = "session_token"
    }
}
