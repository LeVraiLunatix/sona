import Foundation

/// Enregistre les écoutes terminées côté serveur (nos propres « scrobbles »,
/// base de l'onglet Stats). Règle de Last.fm : un titre de plus de 30 s
/// compte s'il a été écouté au moins la moitié de sa durée ou 4 minutes.
/// Hors connexion, les écoutes attendent sur l'appareil et partent au
/// prochain envoi — le serveur ignore les doublons.
@MainActor
final class Scrobbler {
    static let shared = Scrobbler()

    private let storageKey = "encre.pendingPlays"
    private var pending: [PlayPayload]
    private var isFlushing = false

    private init() {
        if let data = UserDefaults.standard.data(forKey: storageKey),
           let saved = try? JSONDecoder().decode([PlayPayload].self, from: data) {
            pending = saved
        } else {
            pending = []
        }
    }

    static func qualifies(listened: Double, duration: Double) -> Bool {
        guard duration > 30 else { return false }
        return listened >= min(duration / 2, 240)
    }

    func record(_ track: Track, startedAt: Date, listened: Double, duration: Double) {
        guard Self.qualifies(listened: listened, duration: duration) else { return }
        let formatter = ISO8601DateFormatter()
        pending.append(PlayPayload(
            title: track.title,
            artist: track.artist,
            album: track.album,
            source: track.source,
            sourceId: track.sourceId,
            artistSourceId: track.artistSourceId,
            albumSourceId: track.albumSourceId,
            coverURL: track.coverURL,
            durationSeconds: Int(duration.rounded()),
            listenedSeconds: Int(listened.rounded()),
            playedAt: formatter.string(from: startedAt)
        ))
        // Garde-fou : jamais plus de 2 000 écoutes en attente sur l'appareil.
        if pending.count > 2000 { pending.removeFirst(pending.count - 2000) }
        save()
        Task { await flush() }
    }

    func flush() async {
        guard !isFlushing, !pending.isEmpty, APIConfig.shared.isConfigured else { return }
        isFlushing = true
        defer { isFlushing = false }
        let batch = Array(pending.prefix(200))
        do {
            try await APIClient.shared.submitPlays(batch)
            pending.removeFirst(min(batch.count, pending.count))
            save()
            if !pending.isEmpty { Task { await flush() } }
        } catch {
            // Réessayé à la prochaine écoute ou au prochain lancement.
        }
    }

    private func save() {
        if let data = try? JSONEncoder().encode(pending) {
            UserDefaults.standard.set(data, forKey: storageKey)
        }
    }
}
