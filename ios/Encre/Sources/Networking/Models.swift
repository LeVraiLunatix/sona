import Foundation

// Miroir de `app/api/schemas.py` côté serveur Sona. `CodingKeys` explicites
// partout plutôt qu'un `keyDecodingStrategy(.convertFromSnakeCase)` global :
// Foundation convertit "cover_url" en "coverUrl", pas "coverURL" — silencieux
// avec un champ optionnel (juste `nil`), donc facile à rater sans ça.

/// État de la séparation voix / instru d'un titre sur le serveur :
/// `absent`, `queued`, `running`, `ready` ou `failed`.
struct KaraokeStatus: Decodable {
    var status: String
    var progress: Double?
    /// Séparations à faire avant celle-ci (en file).
    var ahead: Int?
    var error: String?
    /// Prêt : `fast` (passe rapide) ou `hq` (passe fine, définitive).
    var quality: String?
    /// Prêt en passe rapide : où en est la passe fine.
    var refining: Refining?

    struct Refining: Decodable {
        var status: String
        var progress: Double?
    }
}

/// File des séparations du serveur : en attente (au total et demandées
/// par ce compte) et celle en cours.
struct KaraokeQueue: Decodable {
    var queued: Int
    var mine: Int
    var running: Running?
    /// Réponse à « Vider la file » : séparations retirées.
    var removed: Int?

    struct Running: Decodable {
        var sourceId: String
        var quality: String
        var progress: Double
        var mine: Bool

        enum CodingKeys: String, CodingKey {
            case quality, progress, mine
            case sourceId = "source_id"
        }
    }
}

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
    /// Tempo (Deezer, fiche complète) : sert à l'AutoMix.
    var bpm: Double? = nil

    enum CodingKeys: String, CodingKey {
        case source, title, artist, album, year, bpm
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
    struct Word: Codable, Hashable {
        var time: Double
        var text: String
    }

    struct Line: Codable, Hashable {
        var time: Double?
        var text: String
        /// Mot par mot quand la source le donne (sinon estimé par l'app).
        var words: [Word]?
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
    /// Fiche complète d'un titre, quand le serveur l'a : rien à redemander.
    var track: Track?

    enum CodingKeys: String, CodingKey {
        case kind, source, title, subtitle, track
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
    /// Lieu approximatif (carte des écoutes), arrondi à ~1 km.
    var lat: Double? = nil
    var lon: Double? = nil

    enum CodingKeys: String, CodingKey {
        case title, artist, album, source, lat, lon
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
    /// Photo de l'artiste, vérifiée par son nom côté serveur.
    var pictureURL: String?

    enum CodingKeys: String, CodingKey {
        case name, subtitle, plays, minutes, source
        case coverURL = "cover_url"
        case sourceId = "source_id"
        case pictureURL = "picture_url"
    }

    var id: String { "\(name)|\(subtitle ?? "")" }
}

/// Récap en story (serveur : `app/services/recap.py`).
struct Recap: Codable, Hashable {
    struct Personality: Codable, Hashable {
        var title: String
        var emoji: String
        var description: String
        var traits: [String: Double]
    }

    struct Day: Codable, Hashable {
        var label: String
        var minutes: Int
    }

    struct Rank: Codable, Hashable {
        var rank: Int
        var total: Int
    }

    var period: String
    var offset: Int
    var label: String
    var plays: Int
    var minutes: Int
    var previousMinutes: Int
    var artists: Int
    var tracks: Int
    var topArtists: [RankedStat]
    var topTracks: [RankedStat]
    var topAlbums: [RankedStat]
    var discoveries: [RankedStat]
    var discoveredCount: Int
    var topHour: Int?
    var topWeekday: String?
    var streakDays: Int
    var biggestDay: Day?
    var firstTrack: Track?
    var favouriteTrack: Track?
    var personality: Personality?
    var friendsRank: Rank?

    enum CodingKeys: String, CodingKey {
        case period, offset, label, plays, minutes, artists, tracks, discoveries, personality
        case previousMinutes = "previous_minutes"
        case topArtists = "top_artists"
        case topTracks = "top_tracks"
        case topAlbums = "top_albums"
        case discoveredCount = "discovered_count"
        case topHour = "top_hour"
        case topWeekday = "top_weekday"
        case streakDays = "streak_days"
        case biggestDay = "biggest_day"
        case firstTrack = "first_track"
        case favouriteTrack = "favourite_track"
        case friendsRank = "friends_rank"
    }
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
    var shareListening: Bool?

    enum CodingKeys: String, CodingKey {
        case id, username, status
        case displayName = "display_name"
        case avatarURL = "avatar_url"
        case isAdmin = "is_admin"
        case scrobbleToLastfm = "scrobble_to_lastfm"
        case createdAt = "created_at"
        case shareListening = "share_listening"
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

// MARK: - Playlists de l'app

/// Playlist de l'utilisateur (créée dans l'app ou importée). `entries`
/// n'est rempli que par la fiche détaillée.
struct UserPlaylist: Codable, Identifiable, Hashable {
    var id: Int
    var name: String
    var description: String?
    var coverURL: String?
    var covers: [String]
    var origin: String?
    var trackCount: Int
    var durationSeconds: Int
    var importStatus: String
    var importTotal: Int?
    var importDone: Int
    var importMissing: Int
    var importError: String?
    var updatedAt: String
    var entries: [PlaylistEntry]?
    /// private / friends (visible des amis) / collaborative (modifiable par eux).
    var visibility: String?
    var isOwner: Bool?
    var ownerName: String?
    var canEdit: Bool?

    enum CodingKeys: String, CodingKey {
        case id, name, description, covers, origin, entries, visibility
        case isOwner = "is_owner"
        case ownerName = "owner_name"
        case canEdit = "can_edit"
        case coverURL = "cover_url"
        case trackCount = "track_count"
        case durationSeconds = "duration_seconds"
        case importStatus = "import_status"
        case importTotal = "import_total"
        case importDone = "import_done"
        case importMissing = "import_missing"
        case importError = "import_error"
        case updatedAt = "updated_at"
    }

    var isImporting: Bool { importStatus == "importing" }
    var mine: Bool { isOwner ?? true }
    var editable: Bool { canEdit ?? true }
    var visibilityLabel: String {
        switch visibility {
        case "friends": "Visible par tes amis"
        case "collaborative": "À plusieurs"
        default: "Privée"
        }
    }
    var importFailed: Bool { importStatus == "failed" }
    var tracks: [Track] { (entries ?? []).map(\.track) }

    /// « Spotify », « Apple Music », « Deezer » — d'où vient la playlist.
    var originLabel: String? {
        switch origin {
        case "spotify": "Spotify"
        case "apple": "Apple Music"
        case "deezer": "Deezer"
        default: nil
        }
    }
}

struct PlaylistEntry: Codable, Identifiable, Hashable {
    var entryId: Int
    var track: Track

    enum CodingKeys: String, CodingKey {
        case track
        case entryId = "entry_id"
    }

    var id: Int { entryId }
}

// MARK: - Accueil

/// Mix « Faits pour toi » (Mix du jour, Découvertes, En boucle).
struct Mix: Codable, Identifiable, Hashable {
    var id: String
    var title: String
    var subtitle: String
    var covers: [String]
    var tracks: [Track]
}

// MARK: - Amis

struct FriendNowPlaying: Codable, Hashable {
    var track: Track
    var startedAt: String

    enum CodingKeys: String, CodingKey {
        case track
        case startedAt = "started_at"
    }
}

struct FriendPlay: Codable, Hashable, Identifiable {
    var playedAt: String
    var title: String
    var artist: String
    var album: String?
    var coverURL: String?
    var source: String?
    var sourceId: String?
    var artistSourceId: String?
    var albumSourceId: String?
    var durationSeconds: Int?

    enum CodingKeys: String, CodingKey {
        case title, artist, album, source
        case playedAt = "played_at"
        case coverURL = "cover_url"
        case sourceId = "source_id"
        case artistSourceId = "artist_source_id"
        case albumSourceId = "album_source_id"
        case durationSeconds = "duration_seconds"
    }

    var id: String { "\(playedAt)|\(title)" }

    /// Relisible si la source est connue (écoutes faites dans l'app).
    var track: Track? {
        guard let source, let sourceId, !source.isEmpty else { return nil }
        return Track(
            source: source, sourceId: sourceId, title: title, artist: artist, album: album, year: nil,
            durationSeconds: durationSeconds, coverURL: coverURL,
            artistSourceId: artistSourceId, albumSourceId: albumSourceId
        )
    }
}

struct FriendRanked: Codable, Hashable, Identifiable {
    var name: String
    var subtitle: String?
    var plays: Int
    var coverURL: String?
    var source: String?
    var sourceId: String?

    enum CodingKeys: String, CodingKey {
        case name, subtitle, plays, source
        case coverURL = "cover_url"
        case sourceId = "source_id"
    }

    var id: String { "\(name)|\(subtitle ?? "")" }
}

struct Friend: Codable, Hashable, Identifiable {
    var accountId: Int
    var username: String
    var displayName: String?
    var avatarURL: String?
    var nowPlaying: FriendNowPlaying?
    var lastPlay: FriendPlay?
    var compatibility: Int?
    // Profil détaillé seulement :
    var sharedArtists: [String]?
    var topArtists: [FriendRanked]?
    var topTracks: [FriendRanked]?
    var recent: [FriendPlay]?
    var playlists: [UserPlaylist]?

    enum CodingKeys: String, CodingKey {
        case username, compatibility, recent, playlists
        case accountId = "account_id"
        case displayName = "display_name"
        case avatarURL = "avatar_url"
        case nowPlaying = "now_playing"
        case lastPlay = "last_play"
        case sharedArtists = "shared_artists"
        case topArtists = "top_artists"
        case topTracks = "top_tracks"
    }

    var id: Int { accountId }
    var name: String { displayName ?? username }
}

struct LovedImportStatus: Codable, Equatable {
    var running: Bool
    var total: Int
    var done: Int
    var added: Int
    var missing: Int
    var error: String?
}

// MARK: - Stats en direct

struct LiveNowPlaying: Codable, Hashable {
    var title: String
    var artist: String
    var coverURL: String?
    var startedAt: String

    enum CodingKeys: String, CodingKey {
        case title, artist
        case coverURL = "cover_url"
        case startedAt = "started_at"
    }
}

struct LastfmSync: Codable, Hashable {
    var connected: Bool
    var enabled: Bool
    var username: String?
    var nowPlayingAt: String?
    var nowPlayingTitle: String?
    var scrobbledAt: String?
    var scrobbledCount: Int
    var lastTitle: String?
    var error: String?
    var errorAt: String?

    enum CodingKeys: String, CodingKey {
        case connected, enabled, username, error
        case nowPlayingAt = "now_playing_at"
        case nowPlayingTitle = "now_playing_title"
        case scrobbledAt = "scrobbled_at"
        case scrobbledCount = "scrobbled_count"
        case lastTitle = "last_title"
        case errorAt = "error_at"
    }
}

struct LiveStats: Codable, Hashable {
    var nowPlaying: LiveNowPlaying?
    var todayPlays: Int
    var todayMinutes: Int
    var recent: [RecentPlay]
    var lastfm: LastfmSync

    enum CodingKeys: String, CodingKey {
        case recent, lastfm
        case nowPlaying = "now_playing"
        case todayPlays = "today_plays"
        case todayMinutes = "today_minutes"
    }
}

struct ServerHealth: Codable {
    var status: String
    var version: String?
}

/// Titre lu dans la bibliothèque Musique de l'iPhone, envoyé pour import.
struct DeviceTrack: Codable {
    var title: String
    var artist: String
    var album: String?
    var durationSeconds: Int?
    var appleId: String?

    enum CodingKeys: String, CodingKey {
        case title, artist, album
        case durationSeconds = "duration_seconds"
        case appleId = "apple_id"
    }
}


// MARK: - Écoute ensemble

struct PartyMember: Codable, Hashable {
    var name: String
    var avatarURL: String?
    var isHost: Bool

    enum CodingKeys: String, CodingKey {
        case name
        case avatarURL = "avatar_url"
        case isHost = "is_host"
    }
}

struct PartyQueueItem: Codable, Hashable, Identifiable {
    var id: Int
    var track: Track
    var by: String
    var votes: Int?
    var voted: Bool?
}

struct PartyReaction: Codable, Hashable, Identifiable {
    var id: Int
    var emoji: String
    var by: String
    var age: Double
}

struct PartyState: Codable, Equatable {
    var code: String
    var isHost: Bool
    var hostName: String?
    var members: [PartyMember]
    var track: Track?
    var paused: Bool
    var position: Double
    var serverTime: Double
    var queue: [PartyQueueItem]
    var reactions: [PartyReaction]
    var version: Int

    enum CodingKeys: String, CodingKey {
        case code, members, track, paused, position, queue, reactions, version
        case isHost = "is_host"
        case hostName = "host_name"
        case serverTime = "server_time"
    }
}

struct PartySummary: Codable, Hashable, Identifiable {
    var code: String
    var hostName: String?
    var hostAvatarURL: String?
    var members: Int
    var track: Track?
    var joined: Bool

    enum CodingKeys: String, CodingKey {
        case code, members, track, joined
        case hostName = "host_name"
        case hostAvatarURL = "host_avatar_url"
    }

    var id: String { code }
}

// MARK: - Blind test

struct BlindChoice: Codable, Hashable {
    var title: String
    var artist: String
}

struct BlindQuestion: Codable, Hashable {
    var previewURL: String
    var coverURL: String?
    var answer: Int
    var choices: [BlindChoice]
    var track: Track
    /// « Complète les paroles » : `kind == "lyrics"`, extrait du titre
    /// complet de `clipStart` à `lineTime`, puis la fin de la ligne à trouver.
    var kind: String?
    var before: [String]?
    var prompt: String?
    var clipStart: Double?
    var lineTime: Double?
    var revealEnd: Double?

    var isLyrics: Bool { kind == "lyrics" }

    enum CodingKeys: String, CodingKey {
        case answer, choices, track, kind, before, prompt
        case previewURL = "preview_url"
        case coverURL = "cover_url"
        case clipStart = "clip_start"
        case lineTime = "line_time"
        case revealEnd = "reveal_end"
    }
}

struct BlindRound: Codable {
    var mode: String
    var day: String
    var guess: String?
    var alreadyPlayed: Bool
    var questions: [BlindQuestion]

    enum CodingKeys: String, CodingKey {
        case mode, day, guess, questions
        case alreadyPlayed = "already_played"
    }
}

struct BlindScore: Codable, Hashable, Identifiable {
    var name: String
    var avatarURL: String?
    var isMe: Bool
    var score: Int
    var correct: Int
    var total: Int

    enum CodingKeys: String, CodingKey {
        case name, score, correct, total
        case avatarURL = "avatar_url"
        case isMe = "is_me"
    }

    var id: String { "\(name)|\(score)" }
}

// MARK: - Extras (sorties, souvenirs, moments, carte, défis)

struct Release: Codable, Hashable, Identifiable {
    var source: String
    var sourceId: String
    var title: String
    var artist: String
    var artistSourceId: String?
    var coverURL: String?
    var releaseDate: String
    var kind: String
    var trackCount: Int?

    enum CodingKeys: String, CodingKey {
        case source, title, artist, kind
        case sourceId = "source_id"
        case artistSourceId = "artist_source_id"
        case coverURL = "cover_url"
        case releaseDate = "release_date"
        case trackCount = "track_count"
    }

    var id: String { "\(source):\(sourceId)" }

    /// « il y a 3 jours », « aujourd'hui »…
    var ageLabel: String {
        guard let date = ISO8601DateFormatter.day.date(from: releaseDate) else { return releaseDate }
        let days = Calendar.current.dateComponents([.day], from: date, to: Date()).day ?? 0
        switch days {
        case ..<1: return "Aujourd'hui"
        case 1: return "Hier"
        default: return "Il y a \(days) jours"
        }
    }
}

extension ISO8601DateFormatter {
    static let day: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withFullDate]
        return formatter
    }()
}

struct Memory: Codable, Hashable, Identifiable {
    var yearsAgo: Int
    var label: String
    var dateLabel: String
    var plays: Int
    var tracks: [Track]

    enum CodingKeys: String, CodingKey {
        case label, plays, tracks
        case yearsAgo = "years_ago"
        case dateLabel = "date_label"
    }

    var id: Int { yearsAgo }
}

struct TrackMoment: Codable, Hashable, Identifiable {
    var id: Int
    var position: Double
    var emoji: String
    var text: String?
    var name: String
    var avatarURL: String?
    var isMe: Bool

    enum CodingKeys: String, CodingKey {
        case id, position, emoji, text, name
        case avatarURL = "avatar_url"
        case isMe = "is_me"
    }
}

struct ListeningPlace: Codable, Hashable, Identifiable {
    struct TopTrack: Codable, Hashable {
        var title: String
        var artist: String?
        var plays: Int
    }

    var lat: Double
    var lon: Double
    var plays: Int
    var topArtist: String?
    var topTracks: [TopTrack]
    var coverURL: String?
    var track: Track?

    enum CodingKeys: String, CodingKey {
        case lat, lon, plays, track
        case topArtist = "top_artist"
        case topTracks = "top_tracks"
        case coverURL = "cover_url"
    }

    var id: String { "\(lat),\(lon)" }
}

struct Challenges: Codable, Hashable {
    struct Challenge: Codable, Hashable, Identifiable {
        var id: String
        var title: String
        var icon: String
        var value: Int
        var goal: Int
        var unit: String
        var done: Bool
    }

    struct Badge: Codable, Hashable, Identifiable {
        var id: String
        var title: String
        var description: String
        var icon: String
        var earned: Bool
    }

    var weekLabel: String
    var endsInDays: Int
    var challenges: [Challenge]
    var badges: [Badge]

    enum CodingKeys: String, CodingKey {
        case challenges, badges
        case weekLabel = "week_label"
        case endsInDays = "ends_in_days"
    }
}

// MARK: - TV / PS5

struct TVScreen: Codable, Hashable, Identifiable {
    var screenId: String
    var name: String

    enum CodingKeys: String, CodingKey {
        case name
        case screenId = "screen_id"
    }

    var id: String { screenId }
}

/// Ce que joue l'écran : position, durée, état, titre et volume, relevés
/// par le serveur auprès de l'appli YouTube de la PS5 / TV.
struct TVState: Decodable {
    struct Playing: Decodable {
        var source: String
        var sourceId: String
        enum CodingKeys: String, CodingKey {
            case source
            case sourceId = "source_id"
        }
    }

    var connected: Bool
    var state: String
    var position: Double
    var duration: Double
    var track: Playing?
    var volume: Int?
}

// MARK: - Blind test en direct

struct LivePlayer: Codable, Hashable, Identifiable {
    var name: String
    var avatarURL: String?
    var isHost: Bool
    var isMe: Bool
    var score: Int
    var correct: Int
    var streak: Int
    var answered: Bool
    var gained: Int?
    var wasRight: Bool?

    enum CodingKeys: String, CodingKey {
        case name, score, correct, streak, answered, gained
        case avatarURL = "avatar_url"
        case isHost = "is_host"
        case isMe = "is_me"
        case wasRight = "was_right"
    }

    var id: String { name }
}

struct LiveQuestion: Codable, Hashable {
    struct Stream: Codable, Hashable {
        var source: String
        var sourceId: String

        enum CodingKeys: String, CodingKey {
            case source
            case sourceId = "source_id"
        }
    }

    var index: Int
    var previewURL: String
    var choices: [BlindChoice]
    var answer: Int?
    var track: Track?
    var coverURL: String?
    var myChoice: Int?
    var answered: Int
    /// « Complète les paroles » (voir `BlindQuestion`) : le titre complet
    /// joue via `stream`, de `clipStart` à `lineTime`.
    var kind: String?
    var before: [String]?
    var prompt: String?
    var clipStart: Double?
    var lineTime: Double?
    var revealEnd: Double?
    var stream: Stream?

    var isLyrics: Bool { kind == "lyrics" }

    enum CodingKeys: String, CodingKey {
        case index, choices, answer, track, answered, kind, before, prompt, stream
        case previewURL = "preview_url"
        case coverURL = "cover_url"
        case myChoice = "my_choice"
        case clipStart = "clip_start"
        case lineTime = "line_time"
        case revealEnd = "reveal_end"
    }
}

struct LiveState: Codable, Equatable {
    var code: String
    var isHost: Bool
    var hostName: String?
    var phase: String
    var mode: String
    var ref: String?
    var label: String?
    var count: Int
    var guess: String
    var total: Int
    var serverTime: Double
    var startsAt: Double?
    var deadline: Double?
    var nextAt: Double?
    var question: LiveQuestion?
    var players: [LivePlayer]
    var tracks: [Track]
    var version: Int

    enum CodingKeys: String, CodingKey {
        case code, phase, mode, ref, label, count, guess, total, question, players, tracks, version
        case isHost = "is_host"
        case hostName = "host_name"
        case serverTime = "server_time"
        case startsAt = "starts_at"
        case deadline
        case nextAt = "next_at"
    }
}

struct LiveSummary: Codable, Hashable, Identifiable {
    var code: String
    var hostName: String?
    var hostAvatarURL: String?
    var players: Int
    var phase: String
    var label: String?
    var joined: Bool

    enum CodingKeys: String, CodingKey {
        case code, players, phase, label, joined
        case hostName = "host_name"
        case hostAvatarURL = "host_avatar_url"
    }

    var id: String { code }
}

// MARK: - Concerts

struct Concert: Codable, Hashable, Identifiable {
    var id: String
    var artist: String
    var artistPictureURL: String?
    var datetime: String
    var venue: String?
    var city: String?
    var region: String?
    var country: String?
    var latitude: Double?
    var longitude: Double?
    var url: String?
    var artistRank: Int?

    enum CodingKeys: String, CodingKey {
        case id, artist, datetime, venue, city, region, country, latitude, longitude, url
        case artistPictureURL = "artist_picture_url"
        case artistRank = "artist_rank"
    }

    /// « 2026-11-20T20:00:00 » (heure locale de la salle).
    var date: Date? {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        return formatter.date(from: String(datetime.prefix(19)))
    }
}


// MARK: - AutoMix

/// Analyse audio d'un titre (serveur) : sonie (LUFS), début réel, moment où
/// il retombe (outro) et fin réelle, en secondes.
struct TrackAnalysis: Codable, Hashable {
    var loudness: Double
    var start: Double
    var mixOut: Double
    var end: Double
    var duration: Double

    enum CodingKeys: String, CodingKey {
        case loudness, start, end, duration
        case mixOut = "mix_out"
    }
}

// MARK: - Blend et playlists intelligentes

struct Blend: Codable, Hashable {
    var title: String
    var friendName: String
    var friendAvatarURL: String?
    var compatibility: Int?
    var sharedTracks: Int
    var sharedArtists: [String]
    var tracks: [Track]

    enum CodingKeys: String, CodingKey {
        case title, compatibility, tracks
        case friendName = "friend_name"
        case friendAvatarURL = "friend_avatar_url"
        case sharedTracks = "shared_tracks"
        case sharedArtists = "shared_artists"
    }
}

struct SmartPlaylist: Codable, Hashable, Identifiable {
    var id: String
    var title: String
    var subtitle: String
    var icon: String
    var count: Int
    var covers: [String]
}

// MARK: - Sona Connect

struct ConnectDevice: Codable, Hashable, Identifiable {
    var id: String
    var name: String
    var kind: String
    var isMe: Bool
    var playing: Bool
    var track: Track?
    var volume: Double?
    /// Position dans son titre au relevé (chaque appareil a sa lecture).
    var position: Double?
    /// Options de lecture de l'appareil (nil : il ne les donne pas).
    var shuffle: Bool?
    var repeatMode: String?
    var liked: Bool?

    enum CodingKeys: String, CodingKey {
        case id, name, kind, playing, track, volume, position, shuffle, liked
        case isMe = "is_me"
        case repeatMode = "repeat"
    }
}

/// File d'attente d'un autre appareil (« À suivre » de la télécommande).
struct ConnectQueue: Codable, Hashable {
    var index: Int
    var name: String?
    var queue: [Track]
}

/// Appareil enregistré dans « Appareils » (PC…) : gardé sur le compte,
/// même éteint ; un appui le pilote quand il est allumé.
struct SavedDevice: Codable, Hashable, Identifiable {
    var id: String
    var name: String
    var kind: String
    var online: Bool
    var playing: Bool
    var track: Track?
    var volume: Double?
    var position: Double?
    var seenSeconds: Double?
    /// Nom choisi dans « Appareils » (sinon celui que donne l'appareil).
    var renamed: Bool?

    enum CodingKeys: String, CodingKey {
        case id, name, kind, online, playing, track, volume, position, renamed
        case seenSeconds = "seen_seconds"
    }
}

struct ConnectSession: Codable, Hashable {
    var deviceId: String
    var deviceName: String
    var queue: [Track]
    var index: Int
    var name: String?
    var track: Track
    var position: Double
    var paused: Bool
    var ageSeconds: Double

    enum CodingKeys: String, CodingKey {
        case queue, index, name, track, position, paused
        case deviceId = "device_id"
        case deviceName = "device_name"
        case ageSeconds = "age_seconds"
    }
}

struct ConnectCommand: Codable, Hashable {
    var action: String
    var from: String?
    var position: Double?
    var volume: Double?
    var queue: [Track]?
    var index: Int?
    var name: String?
}

struct ConnectSyncResponse: Codable {
    var devices: [ConnectDevice]
    var activeDeviceId: String?
    var session: ConnectSession?
    var commands: [ConnectCommand]

    enum CodingKeys: String, CodingKey {
        case devices, session, commands
        case activeDeviceId = "active_device_id"
    }
}

struct ConnectPlayback: Codable {
    var queue: [Track]
    var index: Int
    var position: Double
    var paused: Bool
    var volume: Double?
    var name: String?
    var shuffle: Bool?
    var repeatMode: String?

    enum CodingKeys: String, CodingKey {
        case queue, index, position, paused, volume, name, shuffle
        case repeatMode = "repeat"
    }
}

// MARK: - Santé de la lecture

struct StreamingStatus: Codable {
    struct Health: Codable {
        var state: String
        var cause: String?
        var causeLabel: String?
        var advice: String?
        var recentOk: Int
        var recentFailures: Int
        var lastSuccessSeconds: Double?

        enum CodingKeys: String, CodingKey {
            case state, cause, advice
            case causeLabel = "cause_label"
            case recentOk = "recent_ok"
            case recentFailures = "recent_failures"
            case lastSuccessSeconds = "last_success_seconds"
        }
    }

    struct Ytdlp: Codable {
        struct Update: Codable {
            var checkedAt: Double
            var result: String
            var message: String

            enum CodingKeys: String, CodingKey {
                case result, message
                case checkedAt = "checked_at"
            }
        }

        var version: String?
        var lastUpdate: Update?

        enum CodingKeys: String, CodingKey {
            case version
            case lastUpdate = "last_update"
        }
    }

    struct Cookies: Codable {
        var present: Bool
        var updatedAt: Double?
        var loggedIn: Bool?

        enum CodingKeys: String, CodingKey {
            case present
            case updatedAt = "updated_at"
            case loggedIn = "logged_in"
        }
    }

    var health: Health
    var ytdlp: Ytdlp
    var cookies: Cookies
}

/// Réponse des actions d'admin (cookies, essai, mise à jour).
struct AdminResult: Codable {
    var message: String?
    var ok: Bool?
    var loggedIn: Bool?

    enum CodingKeys: String, CodingKey {
        case message, ok
        case loggedIn = "logged_in"
    }
}
