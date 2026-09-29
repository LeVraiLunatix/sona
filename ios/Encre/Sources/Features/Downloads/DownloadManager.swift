import Combine
import Foundation

/// Écoute hors ligne : fichiers audio gardés sur l'iPhone (dossier
/// Application Support, exclu de la sauvegarde iCloud), lus en priorité par
/// le lecteur — démarrage instantané, et plus besoin de réseau.
///
/// Les téléchargements passent un par un (le serveur, petit, prépare un
/// fichier à la fois de toute façon) ; la file reprend au prochain
/// lancement si l'app est fermée en route.
@MainActor
final class DownloadManager: ObservableObject {
    static let shared = DownloadManager()

    enum State: Equatable {
        case none, queued, downloading, done, failed(String)
    }

    struct Item: Codable, Identifiable, Hashable {
        var track: Track
        var fileName: String
        var bytes: Int64
        var addedAt: Date
        var id: String { track.id }
    }

    /// Titres téléchargés, du plus récent au plus ancien.
    @Published private(set) var items: [Item] = []
    @Published private(set) var queue: [Track] = []
    @Published private(set) var activeId: String?
    @Published private(set) var failures: [String: String] = [:]
    /// Wi-Fi uniquement (réglage) : pas de téléchargement en données mobiles.
    var wifiOnly: Bool {
        get { UserDefaults.standard.bool(forKey: "encre.downloads.wifiOnly") }
        set {
            objectWillChange.send()
            UserDefaults.standard.set(newValue, forKey: "encre.downloads.wifiOnly")
        }
    }

    private var worker: Task<Void, Never>?
    private let directory: URL
    private let indexURL: URL
    private let queueURL: URL
    private lazy var session: URLSession = {
        let config = URLSessionConfiguration.default
        // Le serveur peut devoir télécharger puis vérifier le titre avant de
        // l'envoyer : jusqu'à plusieurs minutes pour un titre jamais écouté.
        config.timeoutIntervalForRequest = 600
        config.timeoutIntervalForResource = 1800
        config.waitsForConnectivity = true
        return URLSession(configuration: config)
    }()

    private init() {
        let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        directory = support.appendingPathComponent("Downloads", isDirectory: true)
        indexURL = directory.appendingPathComponent("index.json")
        queueURL = directory.appendingPathComponent("queue.json")
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        var dir = directory
        try? dir.setResourceValues(values)

        if let data = try? Data(contentsOf: indexURL),
           let saved = try? JSONDecoder().decode([Item].self, from: data) {
            // Un fichier supprimé par iOS (stockage saturé) n'est plus listé.
            items = saved.filter { FileManager.default.fileExists(atPath: directory.appendingPathComponent($0.fileName).path) }
        }
        if let data = try? Data(contentsOf: queueURL),
           let saved = try? JSONDecoder().decode([Track].self, from: data) {
            queue = saved.filter { track in !items.contains { $0.id == track.id } }
        }
        startWorkerIfNeeded()
    }

    // MARK: - Lecture

    func isDownloaded(_ track: Track) -> Bool {
        items.contains { $0.id == track.id }
    }

    func localURL(for track: Track) -> URL? {
        guard let item = items.first(where: { $0.id == track.id }) else { return nil }
        let url = directory.appendingPathComponent(item.fileName)
        return FileManager.default.fileExists(atPath: url.path) ? url : nil
    }

    func state(of track: Track) -> State {
        if isDownloaded(track) { return .done }
        if activeId == track.id { return .downloading }
        if queue.contains(where: { $0.id == track.id }) { return .queued }
        if let failure = failures[track.id] { return .failed(failure) }
        return .none
    }

    /// Tous téléchargés (pour une playlist, un album) ?
    func allDownloaded(_ tracks: [Track]) -> Bool {
        !tracks.isEmpty && tracks.allSatisfy(isDownloaded)
    }

    /// Combien de `tracks` sont déjà là, ou en cours / en attente.
    func progress(of tracks: [Track]) -> (done: Int, pending: Int) {
        var done = 0, pending = 0
        for track in tracks {
            switch state(of: track) {
            case .done: done += 1
            case .queued, .downloading: pending += 1
            default: break
            }
        }
        return (done, pending)
    }

    var totalBytes: Int64 { items.reduce(0) { $0 + $1.bytes } }

    var tracks: [Track] { items.map(\.track) }

    // MARK: - Actions

    func download(_ tracks: [Track]) {
        for track in tracks where !isDownloaded(track) && !queue.contains(where: { $0.id == track.id }) && activeId != track.id {
            failures[track.id] = nil
            queue.append(track)
        }
        saveQueue()
        startWorkerIfNeeded()
    }

    func remove(_ track: Track) {
        queue.removeAll { $0.id == track.id }
        if let item = items.first(where: { $0.id == track.id }) {
            try? FileManager.default.removeItem(at: directory.appendingPathComponent(item.fileName))
            items.removeAll { $0.id == track.id }
        }
        saveIndex()
        saveQueue()
    }

    func remove(_ tracks: [Track]) {
        for track in tracks { remove(track) }
    }

    func cancelAll() {
        queue.removeAll()
        saveQueue()
    }

    func removeAll() {
        queue.removeAll()
        for item in items {
            try? FileManager.default.removeItem(at: directory.appendingPathComponent(item.fileName))
        }
        items.removeAll()
        failures.removeAll()
        saveIndex()
        saveQueue()
    }

    // MARK: - File de téléchargement

    private func startWorkerIfNeeded() {
        guard worker == nil, !queue.isEmpty else { return }
        worker = Task { [weak self] in
            await self?.runQueue()
            self?.worker = nil
        }
    }

    private func runQueue() async {
        while let track = queue.first {
            activeId = track.id
            do {
                let item = try await fetch(track)
                items.insert(item, at: 0)
                saveIndex()
            } catch is CancellationError {
                break
            } catch {
                failures[track.id] = error.localizedDescription
            }
            queue.removeAll { $0.id == track.id }
            saveQueue()
            activeId = nil
        }
        activeId = nil
    }

    private func fetch(_ track: Track) async throws -> Item {
        let (url, headers) = try APIClient.shared.streamRequest(source: track.source, id: track.sourceId, live: false)
        var request = URLRequest(url: url)
        for (name, value) in headers { request.setValue(value, forHTTPHeaderField: name) }
        request.allowsCellularAccess = !wifiOnly
        request.allowsExpensiveNetworkAccess = !wifiOnly

        let (temporary, response) = try await session.download(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIError.invalidResponse }
        guard (200..<300).contains(http.statusCode) else {
            let body = (try? Data(contentsOf: temporary)) ?? Data()
            throw APIError.server(status: http.statusCode, message: APIError.serverMessage(from: body))
        }
        let ext = (http.mimeType == "audio/mpeg") ? "mp3" : "m4a"
        let safeId = track.sourceId.filter { $0.isLetter || $0.isNumber || $0 == "-" || $0 == "_" }
        let fileName = "\(track.source)_\(safeId).\(ext)"
        let destination = directory.appendingPathComponent(fileName)
        try? FileManager.default.removeItem(at: destination)
        try FileManager.default.moveItem(at: temporary, to: destination)
        let bytes = (try? FileManager.default.attributesOfItem(atPath: destination.path)[.size] as? Int64) ?? 0
        return Item(track: track, fileName: fileName, bytes: bytes, addedAt: Date())
    }

    private func saveIndex() {
        if let data = try? JSONEncoder().encode(items) { try? data.write(to: indexURL, options: .atomic) }
    }

    private func saveQueue() {
        if let data = try? JSONEncoder().encode(queue) { try? data.write(to: queueURL, options: .atomic) }
    }
}

extension Int64 {
    /// « 128 Mo »
    var byteLabel: String {
        ByteCountFormatter.string(fromByteCount: self, countStyle: .file)
    }
}
