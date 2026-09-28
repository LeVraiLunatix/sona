import Foundation

/// Pas de KeyPath sur un tuple labellisé pour `ForEach(id:)` : un petit type
/// nominal `Identifiable` évite le problème et se relit mieux.
///
/// Porte `source`/`artistSourceId` (tirés de `Track.artistSourceId`, déjà
/// renvoyé par l'API) plutôt qu'un simple nom : sans ces identifiants, ces
/// bulles n'avaient nulle part où naviguer et leur tap ne faisait rien.
struct ArtistSummary: Identifiable, Hashable {
    var name: String
    var coverURL: String?
    var source: String
    var artistSourceId: String
    var id: String { "\(source):\(artistSourceId)" }
}

@MainActor
final class HomeViewModel: ObservableObject {
    @Published var recentTracks: [Track] = []
    @Published var libraryTracks: [Track] = []
    @Published var artists: [ArtistSummary] = []
    /// Une station par univers (rap, pop, électro...) : de quoi lancer
    /// quelque chose d'un tap même avec un historique vide.
    @Published var radios: [RadioStation] = []
    @Published var isLoading = false
    @Published var errorMessage: String?

    /// L'API n'a pas (encore) de "Mix de la semaine" éditorial : plutôt que
    /// d'en inventer un, la mise en avant reprend simplement le dernier
    /// morceau écouté ("Reprendre l'écoute").
    var heroTrack: Track? { recentTracks.first }

    func load() async {
        isLoading = true
        errorMessage = nil
        if radios.isEmpty, let groups = try? await APIClient.shared.radioGroups() {
            radios = groups.compactMap(\.radios.first)
        }
        do {
            async let playsTask = Self.recentlyPlayed()
            async let libraryPage = APIClient.shared.library(kind: "track", limit: 15)
            let (played, library) = try await (playsTask, libraryPage)

            if played.isEmpty {
                // Pas encore d'écoute enregistrée : l'historique des fiches
                // consultées, en ne gardant que les titres (il contient aussi
                // des albums et artistes, qu'on ne peut pas lire).
                let history = try await APIClient.shared.history(limit: 15)
                recentTracks = try await resolve(history.items.map { ($0.source, $0.sourceId) })
            } else {
                recentTracks = played
            }
            libraryTracks = try await resolve(library.items.map { ($0.source, $0.sourceId) })

            // Sans `artistSourceId`, impossible d'ouvrir une vraie fiche
            // artiste (voir `ArtistDetailView`) : ces morceaux-là (source sans
            // identifiant d'artiste exploité) n'alimentent pas "Vos artistes"
            // plutôt que d'y figurer comme une bulle qui ne mène nulle part.
            var seen = Set<String>()
            artists = (recentTracks + libraryTracks).compactMap { t -> ArtistSummary? in
                guard let artistSourceId = t.artistSourceId else { return nil }
                let key = "\(t.source):\(artistSourceId)"
                guard seen.insert(key).inserted else { return nil }
                return ArtistSummary(name: t.artist, coverURL: t.coverURL, source: t.source, artistSourceId: artistSourceId)
            }
        } catch {
            errorMessage = error.localizedDescription
        }
        isLoading = false
    }

    /// Derniers titres réellement écoutés (les écoutes des stats), sans
    /// doublon : ils portent déjà tout ce qu'il faut pour les relancer, pas
    /// besoin de redemander chaque fiche.
    private static func recentlyPlayed() async -> [Track] {
        guard let plays = try? await APIClient.shared.recentPlays(limit: 80) else { return [] }
        var seen = Set<String>()
        var tracks: [Track] = []
        for play in plays {
            guard let source = play.source, let sourceId = play.sourceId,
                  seen.insert("\(source):\(sourceId)").inserted else { continue }
            tracks.append(Track(
                source: source, sourceId: sourceId, title: play.title, artist: play.artist,
                album: play.album, year: nil, durationSeconds: play.durationSeconds, coverURL: play.coverURL,
                artistSourceId: play.artistSourceId, albumSourceId: play.albumSourceId
            ))
            if tracks.count == 15 { break }
        }
        return tracks
    }

    /// L'historique et la bibliothèque ne portent que des résumés (titre,
    /// sous-titre, pochette) : on redemande la fiche complète pour retrouver
    /// artiste/durée exacts et pouvoir lancer la lecture.
    private func resolve(_ refs: [(source: String, id: String)]) async throws -> [Track] {
        // `history`/`library` sont déjà triés (le plus récent d'abord) :
        // on indexe les résultats pour restituer cet ordre, un group task ne
        // garantissant pas de renvoyer les tâches dans l'ordre de lancement.
        try await withThrowingTaskGroup(of: (Int, Track?).self) { group in
            for (index, ref) in refs.enumerated() {
                group.addTask { (index, try? await APIClient.shared.track(source: ref.source, id: ref.id)) }
            }
            var slots = [Track?](repeating: nil, count: refs.count)
            for try await (index, track) in group {
                slots[index] = track
            }
            return slots.compactMap { $0 }
        }
    }
}
