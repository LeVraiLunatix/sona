import Foundation

@MainActor
final class SearchViewModel: ObservableObject {
    @Published var query = "" {
        didSet { scheduleSearch() }
    }
    @Published private(set) var results: [Track] = []
    @Published private(set) var artists: [Artist] = []
    @Published private(set) var albums: [Album] = []
    @Published private(set) var isSearching = false
    @Published private(set) var errorMessage: String?
    @Published var resolvedLink: ResolvedLink?
    /// Radios thématiques, affichées quand le champ est vide (le « Parcourir »
    /// de l'onglet Recherche d'Apple Music).
    @Published private(set) var radioGroups: [RadioGroup] = []

    var hasResults: Bool { !results.isEmpty || !artists.isEmpty || !albums.isEmpty }

    private var searchTask: Task<Void, Never>?
    private var queryId: String?

    private var looksLikeLink: Bool {
        query.contains("http://") || query.contains("https://")
    }

    private func scheduleSearch() {
        searchTask?.cancel()
        resolvedLink = nil
        let text = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else {
            results = []
            artists = []
            albums = []
            errorMessage = nil
            return
        }
        searchTask = Task {
            try? await Task.sleep(for: .milliseconds(300))
            guard !Task.isCancelled else { return }
            if looksLikeLink {
                await resolve(text)
            } else {
                await search(text)
            }
        }
    }

    /// Titres, artistes et albums en parallèle : les deux derniers sont un
    /// bonus (tolérant aux fautes côté serveur : « eiak » trouve Ziak) — leur
    /// échec ne masque pas les titres, et inversement.
    private func search(_ text: String) async {
        isSearching = true
        errorMessage = nil
        async let artistsTask = Self.findArtists(text)
        async let albumsTask = Self.findAlbums(text)
        var tracks: [Track] = []
        do {
            let response = try await APIClient.shared.search(query: text)
            queryId = response.queryId
            tracks = response.tracks
        } catch {
            if !Task.isCancelled { errorMessage = error.localizedDescription }
        }
        let (foundArtists, foundAlbums) = await (artistsTask, albumsTask)
        guard !Task.isCancelled else { return }
        results = tracks
        artists = foundArtists
        albums = foundAlbums
        if hasResults { errorMessage = nil }
        isSearching = false
    }

    private static func findArtists(_ text: String) async -> [Artist] {
        (try? await APIClient.shared.searchArtists(query: text)) ?? []
    }

    private static func findAlbums(_ text: String) async -> [Album] {
        (try? await APIClient.shared.searchAlbums(query: text)) ?? []
    }

    func loadRadios() async {
        guard radioGroups.isEmpty else { return }
        radioGroups = (try? await APIClient.shared.radioGroups()) ?? []
    }

    private func resolve(_ text: String) async {
        isSearching = true
        errorMessage = nil
        results = []
        artists = []
        albums = []
        do {
            resolvedLink = try await APIClient.shared.resolve(text: text)
        } catch {
            if !Task.isCancelled { errorMessage = "Lien non reconnu ou indisponible." }
        }
        isSearching = false
    }
}
