import Foundation

enum LibraryKind: String, CaseIterable, Identifiable {
    case playlists = "playlist"
    case tracks = "track"
    case albums = "album"
    case artists = "artist"

    var id: String { rawValue }
    var label: String {
        switch self {
        case .playlists: "Playlists"
        case .tracks: "Titres"
        case .albums: "Albums"
        case .artists: "Artistes"
        }
    }
}

@MainActor
final class LibraryViewModel: ObservableObject {
    @Published var kind: LibraryKind = .playlists {
        didSet { if kind != oldValue { Task { await load() } } }
    }
    @Published private(set) var items: [LibraryItem] = []
    @Published private(set) var playlists: [UserPlaylist] = []
    /// Fiches complètes des titres (artiste, durée, pochette...) : la
    /// bibliothèque ne stocke qu'un résumé, et il faut de vrais `Track` pour
    /// jouer la liste d'un bout à l'autre.
    @Published private(set) var tracks: [String: Track] = [:]
    @Published private(set) var isLoading = false
    @Published var errorMessage: String?

    /// Titres résolus, dans l'ordre de la bibliothèque — le contexte de
    /// lecture (suivant/précédent) d'un titre tapé ici.
    var playableTracks: [Track] {
        items.compactMap { tracks["\($0.source):\($0.sourceId)"] }
    }

    func load() async {
        isLoading = true
        errorMessage = nil
        let requested = kind
        if requested == .playlists {
            do {
                playlists = try await APIClient.shared.playlists()
            } catch {
                errorMessage = error.localizedDescription
            }
            isLoading = false
            return
        }
        do {
            let page = try await APIClient.shared.library(kind: requested.rawValue, limit: 200)
            guard requested == kind else { return }
            items = page.items
        } catch {
            if requested == kind { errorMessage = error.localizedDescription }
        }
        isLoading = false
        if requested == .tracks { await resolveTracks() }
    }

    var hasImportInProgress: Bool { playlists.contains(where: \.isImporting) }

    /// Rafraîchit la liste des playlists sans indicateur de chargement
    /// (suivi d'un import en cours).
    func refreshPlaylists() async {
        if let fresh = try? await APIClient.shared.playlists() { playlists = fresh }
    }

    func insert(_ playlist: UserPlaylist) {
        playlists.removeAll { $0.id == playlist.id }
        playlists.insert(playlist, at: 0)
    }

    func deletePlaylist(_ playlist: UserPlaylist) async {
        do {
            try await APIClient.shared.deletePlaylist(id: playlist.id)
            playlists.removeAll { $0.id == playlist.id }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func remove(_ item: LibraryItem) async {
        do {
            try await APIClient.shared.removeFromLibrary(kind: item.kind, source: item.source, sourceId: item.sourceId)
            items.removeAll { $0.id == item.id }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    /// 6 requêtes à la fois : assez pour remplir vite, sans inonder le
    /// serveur (chaque fiche = un appel au catalogue d'origine).
    private func resolveTracks() async {
        let missing = items.filter { tracks["\($0.source):\($0.sourceId)"] == nil }
        guard !missing.isEmpty else { return }
        let resolved = await withTaskGroup(of: Track?.self, returning: [Track].self) { group in
            var iterator = missing.makeIterator()
            for _ in 0..<6 {
                guard let item = iterator.next() else { break }
                group.addTask { try? await APIClient.shared.track(source: item.source, id: item.sourceId) }
            }
            var found: [Track] = []
            while let result = await group.next() {
                if let track = result { found.append(track) }
                if let item = iterator.next() {
                    group.addTask { try? await APIClient.shared.track(source: item.source, id: item.sourceId) }
                }
            }
            return found
        }
        for track in resolved { tracks[track.id] = track }
    }
}
