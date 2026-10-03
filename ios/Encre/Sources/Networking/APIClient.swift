import Foundation

enum APIError: LocalizedError {
    case notConfigured
    case invalidResponse
    case server(status: Int, message: String)

    var errorDescription: String? {
        switch self {
        case .notConfigured:
            return "Renseigne l'adresse du serveur et le jeton dans Réglages."
        case .invalidResponse:
            return "Réponse du serveur incompréhensible."
        case .server(let status, let message):
            switch status {
            case 401, 403: return "Jeton refusé par le serveur — vérifie-le dans Réglages."
            case 404: return message.isEmpty ? "Introuvable." : message
            case 502, 503, 504:
                // Sans texte : c'est le proxy HTTPS qui répond à la place de
                // l'API (arrêtée, en train de redémarrer, machine saturée).
                return message.isEmpty || message.hasPrefix("<")
                    ? "Le serveur ne répond pas pour l'instant (il redémarre peut-être). Réessaie dans un moment."
                    : message
            default: return message.isEmpty ? "Erreur \(status) du serveur." : message
            }
        }
    }

    /// FastAPI répond `{"detail": "…"}` : on n'affiche que ce texte-là, pas
    /// le JSON brut (qui finissait tel quel à l'écran).
    static func serverMessage(from data: Data) -> String {
        if let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            if let detail = object["detail"] as? String { return detail }
            if let details = object["detail"] as? [[String: Any]],
               let first = details.first?["msg"] as? String { return first }
        }
        return String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    }
}

/// Client de l'API privée Sona (voir `app/api/` côté serveur). Un seul
/// utilisateur, un seul jeton fixe — pas d'auth OAuth ni de session.
final class APIClient {
    static let shared = APIClient()

    private let session: URLSession
    private let decoder: JSONDecoder

    init(session: URLSession = .shared) {
        self.session = session
        self.decoder = JSONDecoder()
        // Chaque modèle porte ses propres `CodingKeys` (voir Models.swift) :
        // `.convertFromSnakeCase` transforme "cover_url" en "coverUrl", pas
        // "coverURL", et échoue silencieusement sur les champs optionnels.
    }

    private func request(
        _ path: String, method: String = "GET", query: [URLQueryItem] = [], bodyData: Data? = nil,
        authenticated: Bool = true
    ) throws -> URLRequest {
        guard let base = APIConfig.shared.baseURL, !authenticated || APIConfig.shared.isConfigured else {
            throw APIError.notConfigured
        }
        var components = URLComponents(url: base.appendingPathComponent(path), resolvingAgainstBaseURL: false)
        if !query.isEmpty { components?.queryItems = query }
        guard let url = components?.url else { throw APIError.invalidResponse }

        var req = URLRequest(url: url)
        req.httpMethod = method
        if authenticated {
            req.setValue("Bearer \(APIConfig.shared.bearer)", forHTTPHeaderField: "Authorization")
        }
        if let bodyData {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = bodyData
        }
        return req
    }

    /// `JSONEncoder.encode<T: Encodable>` exige un type concret : un
    /// paramètre `Encodable` existentiel ne s'y prête pas (`Encodable` ne se
    /// conforme pas à lui-même). On encode donc le corps chez l'appelant,
    /// qui connaît le type concret, et on ne fait circuler que du `Data`.
    private func encode(_ body: some Encodable) throws -> Data {
        try JSONEncoder().encode(body)
    }

    /// Une connexion restée ouverte peut avoir été fermée par le serveur
    /// (ou son proxy HTTPS) entre deux requêtes : iOS le découvre en
    /// réutilisant la connexion et renvoie « The network connection was
    /// lost ». Une nouvelle tentative, sur une connexion neuve, passe.
    private func perform(_ req: URLRequest) async throws -> (Data, URLResponse) {
        do {
            return try await session.data(for: req)
        } catch let error as URLError where error.code == .networkConnectionLost {
            try await Task.sleep(for: .milliseconds(400))
            return try await session.data(for: req)
        }
    }

    private func send<T: Decodable>(_ req: URLRequest) async throws -> T {
        let (data, response) = try await perform(req)
        guard let http = response as? HTTPURLResponse else { throw APIError.invalidResponse }
        guard (200..<300).contains(http.statusCode) else {
            throw APIError.server(status: http.statusCode, message: APIError.serverMessage(from: data))
        }
        return try decoder.decode(T.self, from: data)
    }

    private func sendNoContent(_ req: URLRequest) async throws {
        let (data, response) = try await perform(req)
        guard let http = response as? HTTPURLResponse else { throw APIError.invalidResponse }
        guard (200..<300).contains(http.statusCode) else {
            throw APIError.server(status: http.statusCode, message: APIError.serverMessage(from: data))
        }
    }

    // MARK: - Compte

    func authConfig() async throws -> AuthConfig {
        try await send(try request("/auth/config", authenticated: false))
    }

    func loginWithLastfm(token: String) async throws -> LoginResponse {
        struct Body: Encodable { let token: String }
        let data = try encode(Body(token: token))
        return try await send(try request("/auth/lastfm", method: "POST", bodyData: data, authenticated: false))
    }

    func me() async throws -> AppAccount {
        try await send(try request("/auth/me"))
    }

    func updateMe(scrobbleToLastfm: Bool) async throws -> AppAccount {
        struct Body: Encodable {
            let scrobbleToLastfm: Bool
            enum CodingKeys: String, CodingKey { case scrobbleToLastfm = "scrobble_to_lastfm" }
        }
        let data = try encode(Body(scrobbleToLastfm: scrobbleToLastfm))
        return try await send(try request("/auth/me", method: "PUT", bodyData: data))
    }

    func logout() async throws {
        try await sendNoContent(try request("/auth/logout", method: "POST"))
    }

    func adminAccounts() async throws -> [AppAccount] {
        try await send(try request("/admin/accounts"))
    }

    // MARK: - Santé de la lecture (admin)

    func streamingStatus() async throws -> StreamingStatus {
        try await send(try request("/admin/streaming"))
    }

    func uploadYouTubeCookies(_ content: String) async throws -> AdminResult {
        struct Body: Encodable { let content: String }
        return try await send(try request("/admin/youtube-cookies", method: "POST", bodyData: try encode(Body(content: content))))
    }

    func streamingSelftest() async throws -> AdminResult {
        try await send(try request("/admin/streaming/selftest", method: "POST"))
    }

    func updateYtdlp() async throws -> AdminResult {
        try await send(try request("/admin/ytdlp/update", method: "POST"))
    }

    /// `approve`, `reject`, `promote` ou `demote`.
    func adminDecide(accountId: Int, action: String) async throws -> AppAccount {
        try await send(try request("/admin/accounts/\(accountId)/\(action)", method: "POST"))
    }

    // MARK: - Recherche

    func search(query: String? = nil, queryId: String? = nil, offset: Int = 0) async throws -> SearchResponse {
        var items = [URLQueryItem(name: "offset", value: "\(offset)")]
        if let query { items.append(URLQueryItem(name: "q", value: query)) }
        if let queryId { items.append(URLQueryItem(name: "query_id", value: queryId)) }
        return try await send(try request("/search", query: items))
    }

    func searchArtists(query: String, limit: Int = 8) async throws -> [Artist] {
        try await send(try request("/search/artists", query: [
            URLQueryItem(name: "q", value: query),
            URLQueryItem(name: "limit", value: "\(limit)"),
        ]))
    }

    func searchAlbums(query: String, limit: Int = 8) async throws -> [Album] {
        try await send(try request("/search/albums", query: [
            URLQueryItem(name: "q", value: query),
            URLQueryItem(name: "limit", value: "\(limit)"),
        ]))
    }

    func resolve(text: String) async throws -> ResolvedLink {
        struct Body: Encodable { let text: String }
        let data = try encode(Body(text: text))
        return try await send(try request("/resolve", method: "POST", bodyData: data))
    }

    // MARK: - Fiches

    func track(source: String, id: String) async throws -> Track {
        try await send(try request("/tracks/\(source)/\(id)"))
    }

    func album(source: String, id: String) async throws -> Album {
        try await send(try request("/albums/\(source)/\(id)"))
    }

    func playlist(source: String, id: String) async throws -> Album {
        try await send(try request("/playlists/\(source)/\(id)"))
    }

    func artist(source: String, id: String) async throws -> Artist {
        try await send(try request("/artists/\(source)/\(id)"))
    }

    func artistTopTracks(source: String, id: String) async throws -> [Track] {
        try await send(try request("/artists/\(source)/\(id)/top-tracks"))
    }

    func artistAlbums(source: String, id: String) async throws -> ArtistAlbums {
        try await send(try request("/artists/\(source)/\(id)/albums"))
    }

    /// Vide (pas une erreur) pour les sources sans donnée d'artistes
    /// similaires — tout sauf Deezer.
    func relatedArtists(source: String, id: String) async throws -> [Artist] {
        try await send(try request("/artists/\(source)/\(id)/related"))
    }

    /// Nouveau tirage à chaque appel (le « mix » Deezer de l'artiste, ou ses
    /// titres populaires mélangés pour les autres sources).
    /// Radio DJ : la suite de la station à partir de `seed` (tempos qui
    /// s'enchaînent, artistes alternés), sans les titres de `exclude`.
    func djRadio(seed: Track, exclude: [String]) async throws -> [Track] {
        try await send(try request("/djradio/\(seed.source)/\(seed.sourceId)", query: [
            URLQueryItem(name: "title", value: seed.title),
            URLQueryItem(name: "artist", value: seed.artist),
            URLQueryItem(name: "exclude", value: exclude.joined(separator: ",")),
        ]))
    }

    func artistRadio(source: String, id: String) async throws -> [Track] {
        try await send(try request("/artists/\(source)/\(id)/radio"))
    }

    // MARK: - Paroles

    /// `nil` quand le serveur ne connaît pas de paroles pour ce morceau
    /// (404) : un cas normal, pas une erreur à afficher comme telle.
    func lyrics(for track: Track) async throws -> Lyrics? {
        var items = [
            URLQueryItem(name: "title", value: track.title),
            URLQueryItem(name: "artist", value: track.artist),
        ]
        if let album = track.album { items.append(URLQueryItem(name: "album", value: album)) }
        if let duration = track.durationSeconds, duration > 0 {
            items.append(URLQueryItem(name: "duration", value: "\(duration)"))
        }
        do {
            return try await send(try request("/lyrics", query: items))
        } catch APIError.server(let status, _) where status == 404 {
            return nil
        }
    }

    // MARK: - Stats d'écoute

    func submitPlays(_ plays: [PlayPayload]) async throws {
        struct Body: Encodable { let plays: [PlayPayload] }
        let data = try encode(Body(plays: plays))
        try await sendNoContent(try request("/plays", method: "POST", bodyData: data))
    }

    /// « En train d'écouter » sur Last.fm, dès qu'un titre démarre.
    /// « En train d'écouter » (Last.fm et amis) ; `position` quand on
    /// reprend un titre en cours.
    func nowPlaying(_ track: Track, position: Double = 0) async throws {
        struct Body: Encodable {
            let title: String
            let artist: String
            let album: String?
            let durationSeconds: Int?
            let source: String
            let sourceId: String
            let coverURL: String?
            let artistSourceId: String?
            let albumSourceId: String?
            let positionSeconds: Double
            enum CodingKeys: String, CodingKey {
                case title, artist, album, source
                case durationSeconds = "duration_seconds"
                case sourceId = "source_id"
                case coverURL = "cover_url"
                case artistSourceId = "artist_source_id"
                case albumSourceId = "album_source_id"
                case positionSeconds = "position_seconds"
            }
        }
        let data = try encode(Body(
            title: track.title, artist: track.artist, album: track.album, durationSeconds: track.durationSeconds,
            source: track.source, sourceId: track.sourceId, coverURL: track.coverURL,
            artistSourceId: track.artistSourceId, albumSourceId: track.albumSourceId, positionSeconds: position
        ))
        try await sendNoContent(try request("/plays/now", method: "POST", bodyData: data))
    }

    /// Pause : plus « en train d'écouter » pour les amis.
    func stopNowPlaying() async throws {
        try await sendNoContent(try request("/plays/now", method: "DELETE"))
    }

    func recentPlays(limit: Int = 50) async throws -> [RecentPlay] {
        try await send(try request("/plays/recent", query: [URLQueryItem(name: "limit", value: "\(limit)")]))
    }

    func stats(period: String, offset: Int) async throws -> StatsReport {
        try await send(try request("/stats", query: [
            URLQueryItem(name: "period", value: period),
            URLQueryItem(name: "offset", value: "\(offset)"),
            URLQueryItem(name: "tz", value: TimeZone.current.identifier),
        ]))
    }

    func recap(period: String, offset: Int) async throws -> Recap {
        try await send(try request("/stats/recap", query: [
            URLQueryItem(name: "period", value: period),
            URLQueryItem(name: "offset", value: "\(offset)"),
            URLQueryItem(name: "tz", value: TimeZone.current.identifier),
        ]))
    }

    func lastfmImportStatus() async throws -> LastfmImportStatus {
        try await send(try request("/stats/import/lastfm"))
    }

    func startLastfmImport() async throws -> LastfmImportStatus {
        try await send(try request("/stats/import/lastfm", method: "POST"))
    }

    // MARK: - Radios

    func radioGroups() async throws -> [RadioGroup] {
        try await send(try request("/browse/radios"))
    }

    func radioTracks(id: String) async throws -> [Track] {
        try await send(try request("/radios/\(id)/tracks"))
    }

    // MARK: - Bibliothèque

    func library(kind: String, offset: Int = 0, limit: Int = 50) async throws -> LibraryPage {
        try await send(try request("/library/\(kind)", query: [
            URLQueryItem(name: "offset", value: "\(offset)"),
            URLQueryItem(name: "limit", value: "\(limit)"),
        ]))
    }

    func addToLibrary(kind: String, source: String, sourceId: String) async throws {
        struct Body: Encodable { let source: String; let sourceId: String
            enum CodingKeys: String, CodingKey { case source; case sourceId = "source_id" }
        }
        let data = try encode(Body(source: source, sourceId: sourceId))
        try await sendNoContent(try request("/library/\(kind)", method: "POST", bodyData: data))
    }

    func removeFromLibrary(kind: String, source: String, sourceId: String) async throws {
        try await sendNoContent(try request("/library/\(kind)/\(source)/\(sourceId)", method: "DELETE"))
    }

    // MARK: - Playlists de l'app

    func playlists() async throws -> [UserPlaylist] {
        try await send(try request("/me/playlists"))
    }

    func userPlaylist(id: Int) async throws -> UserPlaylist {
        try await send(try request("/me/playlists/\(id)"))
    }

    func createPlaylist(name: String, tracks: [Track] = []) async throws -> UserPlaylist {
        struct Body: Encodable { let name: String; let tracks: [Track] }
        let data = try encode(Body(name: name, tracks: tracks))
        return try await send(try request("/me/playlists", method: "POST", bodyData: data))
    }

    func renamePlaylist(id: Int, name: String) async throws -> UserPlaylist {
        struct Body: Encodable { let name: String }
        let data = try encode(Body(name: name))
        return try await send(try request("/me/playlists/\(id)", method: "PATCH", bodyData: data))
    }

    func setPlaylistVisibility(id: Int, visibility: String) async throws -> UserPlaylist {
        struct Body: Encodable { let visibility: String }
        let data = try encode(Body(visibility: visibility))
        return try await send(try request("/me/playlists/\(id)", method: "PATCH", bodyData: data))
    }

    func deletePlaylist(id: Int) async throws {
        try await sendNoContent(try request("/me/playlists/\(id)", method: "DELETE"))
    }

    func addToPlaylist(id: Int, tracks: [Track]) async throws -> UserPlaylist {
        struct Body: Encodable { let tracks: [Track] }
        let data = try encode(Body(tracks: tracks))
        return try await send(try request("/me/playlists/\(id)/tracks", method: "POST", bodyData: data))
    }

    func removeFromPlaylist(id: Int, entryId: Int) async throws -> UserPlaylist {
        try await send(try request("/me/playlists/\(id)/tracks/\(entryId)", method: "DELETE"))
    }

    func reorderPlaylist(id: Int, entryIds: [Int]) async throws -> UserPlaylist {
        struct Body: Encodable { let entryIds: [Int]
            enum CodingKeys: String, CodingKey { case entryIds = "entry_ids" }
        }
        let data = try encode(Body(entryIds: entryIds))
        return try await send(try request("/me/playlists/\(id)/order", method: "PUT", bodyData: data))
    }

    /// Relit la playlist d'origine et remplace ses titres (en tâche de fond).
    func reimportPlaylist(id: Int) async throws -> UserPlaylist {
        try await send(try request("/me/playlists/\(id)/reimport", method: "POST"))
    }

    /// Lance l'import (en tâche de fond côté serveur) : la playlist revient
    /// tout de suite, `importStatus == "importing"`, à suivre jusqu'à la fin.
    func importPlaylist(url: String) async throws -> UserPlaylist {
        struct Body: Encodable { let url: String }
        let data = try encode(Body(url: url))
        return try await send(try request("/me/playlists/import", method: "POST", bodyData: data))
    }

    // MARK: - Accueil & amis

    func mixes(refresh: Bool = false) async throws -> [Mix] {
        try await send(try request("/home/mixes", query: refresh ? [URLQueryItem(name: "refresh", value: "true")] : []))
    }

    func friends() async throws -> [Friend] {
        try await send(try request("/friends"))
    }

    func friend(id: Int) async throws -> Friend {
        try await send(try request("/friends/\(id)"))
    }

    func updateMe(shareListening: Bool) async throws -> AppAccount {
        struct Body: Encodable { let shareListening: Bool
            enum CodingKeys: String, CodingKey { case shareListening = "share_listening" }
        }
        let data = try encode(Body(shareListening: shareListening))
        return try await send(try request("/auth/me", method: "PUT", bodyData: data))
    }

    // MARK: - Stats en direct & serveur

    func liveStats() async throws -> LiveStats {
        try await send(try request("/stats/live", query: [URLQueryItem(name: "tz", value: TimeZone.current.identifier)]))
    }

    /// Version (commit) du serveur : pour savoir s'il est à jour.
    func health() async throws -> ServerHealth {
        try await send(try request("/health", authenticated: false))
    }

    /// Playlist lue dans la bibliothèque Musique de l'iPhone (liste complète).
    func importDevicePlaylist(name: String, tracks: [DeviceTrack]) async throws -> UserPlaylist {
        struct Body: Encodable { let name: String; let tracks: [DeviceTrack] }
        let data = try encode(Body(name: name, tracks: tracks))
        return try await send(try request("/me/playlists/import-tracks", method: "POST", bodyData: data))
    }

    // MARK: - Écoute ensemble

    func createParty() async throws -> PartyState {
        try await send(try request("/party", method: "POST"))
    }

    func activeParties() async throws -> [PartySummary] {
        try await send(try request("/party/active"))
    }

    func partyState(code: String) async throws -> PartyState {
        try await send(try request("/party/\(code)"))
    }

    func joinParty(code: String) async throws -> PartyState {
        try await send(try request("/party/\(code)/join", method: "POST"))
    }

    func leaveParty(code: String) async throws {
        try await sendNoContent(try request("/party/\(code)/leave", method: "POST"))
    }

    func setPartyState(code: String, track: Track?, position: Double, paused: Bool) async throws -> PartyState {
        struct Body: Encodable { let track: Track?; let position: Double; let paused: Bool }
        let data = try encode(Body(track: track, position: position, paused: paused))
        return try await send(try request("/party/\(code)/state", method: "POST", bodyData: data))
    }

    func proposeToParty(code: String, track: Track) async throws -> PartyState {
        struct Body: Encodable { let track: Track }
        let data = try encode(Body(track: track))
        return try await send(try request("/party/\(code)/queue", method: "POST", bodyData: data))
    }

    func consumePartyQueue(code: String, ids: [Int]) async throws -> PartyState {
        struct Body: Encodable { let ids: [Int] }
        let data = try encode(Body(ids: ids))
        return try await send(try request("/party/\(code)/queue/consume", method: "POST", bodyData: data))
    }

    func reactInParty(code: String, emoji: String) async throws -> PartyState {
        struct Body: Encodable { let emoji: String }
        let data = try encode(Body(emoji: emoji))
        return try await send(try request("/party/\(code)/react", method: "POST", bodyData: data))
    }

    // MARK: - Blind test

    func blindRound(mode: String, ref: String? = nil, count: Int = 10, guess: String = "title") async throws -> BlindRound {
        var query = [
            URLQueryItem(name: "mode", value: mode),
            URLQueryItem(name: "count", value: "\(count)"),
            URLQueryItem(name: "guess", value: guess),
        ]
        if let ref { query.append(URLQueryItem(name: "ref", value: ref)) }
        return try await send(try request("/blindtest/round", query: query))
    }

    /// Analyse audio pour l'AutoMix ; nil tant qu'elle n'est pas prête.
    func analysis(source: String, id: String) async -> TrackAnalysis? {
        try? await send(try request("/analysis/\(source)/\(id)"))
    }

    func submitBlindScore(mode: String, score: Int, correct: Int, total: Int) async throws {
        struct Body: Encodable { let mode: String; let score: Int; let correct: Int; let total: Int }
        let data = try encode(Body(mode: mode, score: score, correct: correct, total: total))
        try await sendNoContent(try request("/blindtest/score", method: "POST", bodyData: data))
    }

    func blindLeaderboard(mode: String = "daily") async throws -> [BlindScore] {
        try await send(try request("/blindtest/leaderboard", query: [URLQueryItem(name: "mode", value: mode)]))
    }

    // MARK: - Extras

    func releases() async throws -> [Release] {
        try await send(try request("/releases"))
    }

    func memories() async throws -> [Memory] {
        try await send(try request("/memories", query: [URLQueryItem(name: "tz", value: TimeZone.current.identifier)]))
    }

    func sportTracks(bpm: Double, exclude: [String]) async throws -> [Track] {
        try await send(try request("/sport", query: [
            URLQueryItem(name: "bpm", value: String(Int(bpm.rounded()))),
            URLQueryItem(name: "exclude", value: exclude.joined(separator: ",")),
        ]))
    }

    /// Instrumentale YouTube du titre (à la même durée), ou nil.
    func instrumental(for track: Track) async -> (source: String, id: String)? {
        struct Found: Decodable { let source: String; let sourceId: String
            enum CodingKeys: String, CodingKey { case source; case sourceId = "source_id" } }
        var query = [
            URLQueryItem(name: "title", value: track.title),
            URLQueryItem(name: "artist", value: track.artist),
        ]
        if let duration = track.durationSeconds { query.append(URLQueryItem(name: "duration", value: "\(duration)")) }
        guard let found: Found = try? await send(try request("/instrumental/\(track.source)/\(track.sourceId)", query: query))
        else { return nil }
        return (found.source, found.sourceId)
    }

    // MARK: - Karaoké (voix / instru séparées par IA)

    /// Titre écouté maintenant en mode chant : le serveur le met en tête de
    /// sa file de séparation et répond tout de suite avec l'état.
    func karaokeRequest(_ track: Track) async throws -> KaraokeStatus {
        try await send(try request("/karaoke/\(track.source)/\(track.sourceId)", method: "POST"))
    }

    func karaokeStatus(_ track: Track) async throws -> KaraokeStatus {
        try await send(try request("/karaoke/\(track.source)/\(track.sourceId)"))
    }

    /// Titres suivants de la file : séparés d'avance, après le titre en cours.
    func karaokePrepare(_ tracks: [Track]) async {
        struct Ref: Encodable { let source: String; let source_id: String }
        struct Body: Encodable { let tracks: [Ref] }
        // Liste vide : le serveur retire simplement les titres « à venir »
        // demandés avant (mode chant coupé).
        guard let data = try? encode(Body(tracks: tracks.prefix(5).map { Ref(source: $0.source, source_id: $0.sourceId) })),
              let req = try? request("/karaoke/prepare", method: "POST", bodyData: data) else { return }
        _ = try? await perform(req)
    }

    /// File des séparations du serveur (menu karaoké).
    func karaokeQueue() async throws -> KaraokeQueue {
        try await send(try request("/karaoke/queue"))
    }

    /// Vide sa file de séparations (toute la file pour un administrateur).
    func clearKaraokeQueue() async throws -> KaraokeQueue {
        try await send(try request("/karaoke/queue", method: "DELETE"))
    }

    /// Une des deux pistes séparées (`vocals` ou `instrumental`), en m4a.
    func karaokeStemRequest(_ track: Track, stem: String, quality: String) throws -> URLRequest {
        var req = try request(
            "/stream/\(track.source)/\(track.sourceId)/karaoke/\(stem)",
            query: [URLQueryItem(name: "quality", value: quality)]
        )
        req.timeoutInterval = 60
        return req
    }

    func moments(for track: Track) async throws -> [TrackMoment] {
        try await send(try request("/moments/\(track.source)/\(track.sourceId)"))
    }

    func addMoment(for track: Track, position: Double, emoji: String, text: String?) async throws {
        struct Body: Encodable { let position: Double; let emoji: String; let text: String? }
        try await sendNoContent(try request(
            "/moments/\(track.source)/\(track.sourceId)", method: "POST",
            bodyData: try encode(Body(position: position, emoji: emoji, text: text))
        ))
    }

    func deleteMoment(_ id: Int) async throws {
        try await sendNoContent(try request("/moments/\(id)", method: "DELETE"))
    }

    func listeningPlaces() async throws -> [ListeningPlace] {
        try await send(try request("/map"))
    }

    func challenges() async throws -> Challenges {
        try await send(try request("/challenges", query: [URLQueryItem(name: "tz", value: TimeZone.current.identifier)]))
    }

    /// Annonce du DJ vocal : texte + MP3 d'une voix neuronale (nil si
    /// indisponible côté serveur).
    func djIntro(for track: Track, after previous: Track?, voice: String) async throws -> (text: String, audio: Data?) {
        struct Intro: Decodable { let text: String; let audio: String? }
        var query = [
            URLQueryItem(name: "title", value: track.title),
            URLQueryItem(name: "artist", value: track.artist),
            URLQueryItem(name: "voice", value: voice),
            URLQueryItem(name: "tz", value: TimeZone.current.identifier),
        ]
        if let previous {
            query.append(URLQueryItem(name: "prev_title", value: previous.title))
            query.append(URLQueryItem(name: "prev_artist", value: previous.artist))
        }
        if let year = track.year.flatMap({ Int($0.prefix(4)) }) {
            query.append(URLQueryItem(name: "year", value: String(year)))
        }
        let intro: Intro = try await send(try request("/dj/intro", query: query))
        return (intro.text, intro.audio.flatMap { Data(base64Encoded: $0) })
    }

    // MARK: - Sona Connect

    func connectSync(
        deviceId: String, name: String, state: ConnectPlayback?, claim: Bool, wait: Double = 0
    ) async throws -> ConnectSyncResponse {
        struct Body: Encodable {
            let device_id: String
            let name: String
            let kind = "iphone"
            let state: ConnectPlayback?
            let claim: Bool
            let wait: Double
        }
        let data = try encode(Body(device_id: deviceId, name: name, state: state, claim: claim, wait: wait))
        var req = try request("/connect/sync", method: "POST", bodyData: data)
        // Attente côté serveur (jusqu'à `wait` s) : délai du client au-delà.
        req.timeoutInterval = wait + 20
        return try await send(req)
    }

    func connectCommand(
        from deviceId: String, to target: String, action: String, position: Double? = nil, volume: Double? = nil,
        index: Int? = nil
    ) async throws {
        struct Body: Encodable {
            let device_id: String
            let target: String
            let action: String
            let position: Double?
            let volume: Double?
            let index: Int?
        }
        let data = try encode(Body(
            device_id: deviceId, target: target, action: action, position: position, volume: volume, index: index
        ))
        try await sendNoContent(try request("/connect/command", method: "POST", bodyData: data))
    }

    /// « Appareils » : les appareils enregistrés du compte.
    func connectSaved() async throws -> [SavedDevice] {
        try await send(try request("/connect/saved"))
    }

    func connectSave(deviceId: String) async throws -> SavedDevice {
        struct Body: Encodable { let device_id: String }
        let data = try encode(Body(device_id: deviceId))
        return try await send(try request("/connect/saved", method: "POST", bodyData: data))
    }

    func connectRename(deviceId: String, name: String) async throws -> SavedDevice {
        struct Body: Encodable { let name: String }
        let data = try encode(Body(name: name))
        return try await send(try request("/connect/saved/\(deviceId)", method: "PATCH", bodyData: data))
    }

    /// « À suivre » sur un autre appareil.
    func connectQueue(deviceId: String) async throws -> ConnectQueue {
        try await send(try request("/connect/devices/\(deviceId)/queue"))
    }

    func connectForget(deviceId: String) async throws {
        // Identifiants de Sona Connect : lettres, chiffres et tirets.
        try await sendNoContent(try request("/connect/saved/\(deviceId)", method: "DELETE"))
    }

    func smartPlaylists() async throws -> [SmartPlaylist] {
        try await send(try request("/smart", query: [URLQueryItem(name: "tz", value: TimeZone.current.identifier)]))
    }

    func smartPlaylist(_ id: String) async throws -> [Track] {
        try await send(try request("/smart/\(id)", query: [URLQueryItem(name: "tz", value: TimeZone.current.identifier)]))
    }

    func blend(with friendId: Int) async throws -> Blend {
        try await send(try request("/friends/\(friendId)/blend"))
    }

    func voteInParty(code: String, itemId: Int) async throws -> PartyState {
        try await send(try request("/party/\(code)/queue/\(itemId)/vote", method: "POST"))
    }

    // MARK: - TV / PS5

    func tvScreens() async throws -> [TVScreen] {
        try await send(try request("/tv"))
    }

    func pairTV(code: String) async throws -> TVScreen {
        struct Body: Encodable { let code: String }
        return try await send(try request("/tv/pair", method: "POST", bodyData: try encode(Body(code: code))))
    }

    func unpairTV(_ screenId: String) async throws {
        try await sendNoContent(try request("/tv/\(screenId)", method: "DELETE"))
    }

    func playOnTV(_ screenId: String, tracks: [Track]) async throws {
        struct Body: Encodable { let tracks: [Track] }
        try await sendNoContent(try request("/tv/\(screenId)/play", method: "POST", bodyData: try encode(Body(tracks: tracks))))
    }

    func controlTV(_ screenId: String, action: String, seconds: Double? = nil, volume: Int? = nil) async throws {
        struct Body: Encodable { let action: String; let seconds: Double?; let volume: Int? }
        try await sendNoContent(try request(
            "/tv/\(screenId)/control", method: "POST",
            bodyData: try encode(Body(action: action, seconds: seconds, volume: volume))
        ))
    }

    func tvState(_ screenId: String) async throws -> TVState {
        try await send(try request("/tv/\(screenId)/state"))
    }

    // MARK: - Blind test en direct

    func createLive() async throws -> LiveState {
        try await send(try request("/blindlive", method: "POST"))
    }

    func activeLive() async throws -> [LiveSummary] {
        try await send(try request("/blindlive/active"))
    }

    func liveState(code: String) async throws -> LiveState {
        try await send(try request("/blindlive/\(code)"))
    }

    func joinLive(code: String) async throws -> LiveState {
        try await send(try request("/blindlive/\(code)/join", method: "POST"))
    }

    func leaveLive(code: String) async throws {
        try await sendNoContent(try request("/blindlive/\(code)/leave", method: "POST"))
    }

    func configureLive(code: String, mode: String, ref: String?, label: String?, count: Int, guess: String) async throws -> LiveState {
        struct Body: Encodable { let mode: String; let ref: String?; let label: String?; let count: Int; let guess: String }
        let data = try encode(Body(mode: mode, ref: ref, label: label, count: count, guess: guess))
        return try await send(try request("/blindlive/\(code)/config", method: "POST", bodyData: data))
    }

    func startLive(code: String) async throws -> LiveState {
        try await send(try request("/blindlive/\(code)/start", method: "POST"))
    }

    func answerLive(code: String, index: Int, choice: Int) async throws -> LiveState {
        struct Body: Encodable { let index: Int; let choice: Int }
        let data = try encode(Body(index: index, choice: choice))
        return try await send(try request("/blindlive/\(code)/answer", method: "POST", bodyData: data))
    }

    // MARK: - Concerts

    func concerts() async throws -> [Concert] {
        try await send(try request("/concerts"))
    }

    // MARK: - Titres aimés Last.fm

    func lovedImportStatus() async throws -> LovedImportStatus {
        try await send(try request("/library/lastfm-loved/import"))
    }

    func startLovedImport() async throws -> LovedImportStatus {
        try await send(try request("/library/lastfm-loved/import", method: "POST"))
    }

    // MARK: - Historique

    func history(offset: Int = 0, limit: Int = 50) async throws -> HistoryPage {
        try await send(try request("/history", query: [
            URLQueryItem(name: "offset", value: "\(offset)"),
            URLQueryItem(name: "limit", value: "\(limit)"),
        ]))
    }

    func clearHistory() async throws {
        try await sendNoContent(try request("/history", method: "DELETE"))
    }

    // MARK: - Réglages

    func getSettings() async throws -> UserSettingsDTO {
        try await send(try request("/settings"))
    }

    func updateSettings(quality: String? = nil, format: String? = nil, autoplay: Bool? = nil) async throws -> UserSettingsDTO {
        struct Body: Encodable { let quality: String?; let format: String?; let autoplay: Bool? }
        let data = try encode(Body(quality: quality, format: format, autoplay: autoplay))
        return try await send(try request("/settings", method: "PUT", bodyData: data))
    }

    // MARK: - Streaming

    /// Demande au serveur de télécharger et vérifier le morceau, sans
    /// l'envoyer. Long délai : un premier téléchargement peut prendre du
    /// temps ; un morceau déjà prêt répond immédiatement.
    func prepareStream(source: String, id: String, quality: String = "best", format: String = "auto") async throws {
        var req = try request("/stream/\(source)/\(id)/prepare", method: "POST", query: [
            URLQueryItem(name: "quality", value: quality),
            URLQueryItem(name: "format", value: format),
        ])
        req.timeoutInterval = 180
        try await sendNoContent(req)
    }

    /// URL + en-têtes à passer à `AVURLAsset` pour lire un morceau : le
    /// serveur télécharge (si besoin), vérifie l'audio puis le sert avec
    /// support des requêtes `Range`, indispensable pour qu'`AVPlayer` puisse
    /// démarrer la lecture avant d'avoir tout reçu.
    /// « Mauvaise version ? » : le serveur écarte la source servie pour ce
    /// titre (et son cache) ; la prochaine lecture en cherche une autre.
    func reportWrongVersion(_ track: Track) async throws {
        try await sendNoContent(try request("/stream/\(track.source)/\(track.sourceId)/wrong-version", method: "POST"))
    }

    /// `live: false` : le fichier complet vérifié, jamais le relais direct de
    /// YouTube (téléchargement hors ligne).
    func streamRequest(
        source: String, id: String, quality: String = "best", format: String = "auto", live: Bool = true
    ) throws -> (url: URL, headers: [String: String]) {
        guard let base = APIConfig.shared.baseURL, APIConfig.shared.isConfigured else {
            throw APIError.notConfigured
        }
        var components = URLComponents(
            url: base.appendingPathComponent("/stream/\(source)/\(id)"), resolvingAgainstBaseURL: false
        )
        components?.queryItems = [
            URLQueryItem(name: "quality", value: quality),
            URLQueryItem(name: "format", value: format),
        ]
        if !live { components?.queryItems?.append(URLQueryItem(name: "live", value: "false")) }
        guard let url = components?.url else { throw APIError.invalidResponse }
        return (url, ["Authorization": "Bearer \(APIConfig.shared.bearer)"])
    }
}
