import Foundation

extension LibraryItem {
    /// Le titre complet quand le serveur l'a donné, sinon de quoi le rejouer.
    var asTrack: Track {
        track ?? Track(source: source, sourceId: sourceId, title: title, artist: subtitle ?? "", coverURL: coverURL)
    }
}

/// « Ta file perso » : un titre lancé depuis une recherche joue seul, et la suite est un mélange
/// de tes titres aimés et de morceaux proches de lui (comme Apple Music), pas des autres résultats.
enum PersonalQueue {
    static let name = "Ta file perso"

    static func mix(seed: Track, size: Int = 24) async -> [Track] {
        async let likedPage = APIClient.shared.library(kind: "track", limit: 500)
        async let nearby = APIClient.shared.djRadio(seed: seed, exclude: [seed.sourceId])
        let liked = ((try? await likedPage)?.items ?? []).map(\.asTrack).filter { $0.id != seed.id }.shuffled()
        let similar = ((try? await nearby) ?? []).filter { $0.id != seed.id }.shuffled()

        var out: [Track] = []
        var seen: Set<String> = [seed.id]
        var index = 0
        while out.count < size && (index < liked.count || index < similar.count) {
            for candidate in [liked.indices.contains(index) ? liked[index] : nil,
                              similar.indices.contains(index) ? similar[index] : nil] {
                if let track = candidate, out.count < size, seen.insert(track.id).inserted { out.append(track) }
            }
            index += 1
        }
        return out
    }

    /// Lance `track` seul, puis ajoute la file perso à la suite dès qu'elle est prête.
    @MainActor
    static func play(_ track: Track, with player: PlayerManager) {
        let alreadyCurrent = player.current?.id == track.id
        player.play(track, context: [track], name: name)
        guard !alreadyCurrent else { return }
        Task {
            let following = await mix(seed: track)
            // Le titre a changé pendant la préparation : on ne touche pas à la file.
            guard player.current?.id == track.id, !following.isEmpty else { return }
            player.playLater(following)
        }
    }
}
