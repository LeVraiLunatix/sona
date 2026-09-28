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
            case 502, 503, 504: return message.isEmpty ? "Le serveur n'arrive pas à joindre ses sources pour l'instant." : message
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
        _ path: String, method: String = "GET", query: [URLQueryItem] = [], bodyData: Data? = nil
    ) throws -> URLRequest {
        guard let base = APIConfig.shared.baseURL, APIConfig.shared.isConfigured else {
            throw APIError.notConfigured
        }
        var components = URLComponents(url: base.appendingPathComponent(path), resolvingAgainstBaseURL: false)
        if !query.isEmpty { components?.queryItems = query }
        guard let url = components?.url else { throw APIError.invalidResponse }

        var req = URLRequest(url: url)
        req.httpMethod = method
        req.setValue("Bearer \(APIConfig.shared.token)", forHTTPHeaderField: "Authorization")
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

    private func send<T: Decodable>(_ req: URLRequest) async throws -> T {
        let (data, response) = try await session.data(for: req)
        guard let http = response as? HTTPURLResponse else { throw APIError.invalidResponse }
        guard (200..<300).contains(http.statusCode) else {
            throw APIError.server(status: http.statusCode, message: APIError.serverMessage(from: data))
        }
        return try decoder.decode(T.self, from: data)
    }

    private func sendNoContent(_ req: URLRequest) async throws {
        let (data, response) = try await session.data(for: req)
        guard let http = response as? HTTPURLResponse else { throw APIError.invalidResponse }
        guard (200..<300).contains(http.statusCode) else {
            throw APIError.server(status: http.statusCode, message: APIError.serverMessage(from: data))
        }
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

    /// URL + en-têtes à passer à `AVURLAsset` pour lire un morceau : le
    /// serveur télécharge (si besoin), vérifie l'audio puis le sert avec
    /// support des requêtes `Range`, indispensable pour qu'`AVPlayer` puisse
    /// démarrer la lecture avant d'avoir tout reçu.
    func streamRequest(source: String, id: String, quality: String = "best", format: String = "auto") throws -> (url: URL, headers: [String: String]) {
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
        guard let url = components?.url else { throw APIError.invalidResponse }
        return (url, ["Authorization": "Bearer \(APIConfig.shared.token)"])
    }
}
