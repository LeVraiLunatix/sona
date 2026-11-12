import Foundation

/// Filtres de la recherche (puces sous le champ).
enum SearchFilter: String, CaseIterable, Identifiable {
    case all, songs, artists, albums, library

    var id: String { rawValue }
    var label: String {
        switch self {
        case .all: return "Tout"
        case .songs: return "Titres"
        case .artists: return "Artistes"
        case .albums: return "Albums"
        case .library: return "Ta bibliothèque"
        }
    }
}

@MainActor
final class SearchViewModel: ObservableObject {
    @Published var query = "" {
        didSet { scheduleSearch() }
    }
    @Published private(set) var results: [Track] = []
    @Published private(set) var artists: [Artist] = []
    @Published private(set) var albums: [Album] = []
    @Published private(set) var libraryTracks: [Track] = []
    @Published private(set) var libraryPlaylists: [UserPlaylist] = []
    @Published private(set) var suggestions: [SearchSuggestion] = []
    @Published private(set) var recents: [String] = SearchViewModel.loadRecents()
    @Published var filter: SearchFilter = .all
    @Published private(set) var isSearching = false
    @Published private(set) var errorMessage: String?
    @Published var resolvedLink: ResolvedLink?
    /// Radios thématiques, affichées quand le champ est vide (le « Parcourir »
    /// de l'onglet Recherche d'Apple Music).
    @Published private(set) var radioGroups: [RadioGroup] = []

    var libraryCount: Int { libraryTracks.count + libraryPlaylists.count }
    var hasResults: Bool { !results.isEmpty || !artists.isEmpty || !albums.isEmpty || libraryCount > 0 }

    /// Filtres qui ont de quoi s'afficher (« Tout » reste toujours).
    var availableFilters: [SearchFilter] {
        SearchFilter.allCases.filter { filter in
            switch filter {
            case .all: return true
            case .songs: return !results.isEmpty
            case .artists: return !artists.isEmpty
            case .albums: return !albums.isEmpty
            case .library: return libraryCount > 0
            }
        }
    }

    func count(for filter: SearchFilter) -> Int {
        switch filter {
        case .all: return 0
        case .songs: return results.count
        case .artists: return artists.count
        case .albums: return albums.count
        case .library: return libraryCount
        }
    }

    @Published private(set) var isLoadingMore = false

    private var searchTask: Task<Void, Never>?
    private var suggestTask: Task<Void, Never>?
    private var queryId: String?
    private var total = 0

    var canLoadMore: Bool { queryId != nil && results.count < total }

    private var looksLikeLink: Bool {
        query.contains("http://") || query.contains("https://")
    }

    private func scheduleSearch() {
        searchTask?.cancel()
        suggestTask?.cancel()
        resolvedLink = nil
        let text = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else {
            results = []
            artists = []
            albums = []
            libraryTracks = []
            libraryPlaylists = []
            suggestions = []
            filter = .all
            errorMessage = nil
            // Sans ça, effacer le champ pendant une recherche laissait le
            // sablier tourner indéfiniment (la tâche annulée ne le coupe pas).
            isSearching = false
            return
        }
        if !looksLikeLink { scheduleSuggestions(text) }
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

    /// Artistes et titres proposés pendant la frappe : montrés en attendant les résultats.
    private func scheduleSuggestions(_ text: String) {
        guard text.count >= 2 else { suggestions = []; return }
        suggestTask = Task {
            try? await Task.sleep(for: .milliseconds(180))
            guard !Task.isCancelled else { return }
            let found = (try? await APIClient.shared.searchSuggest(query: text)) ?? []
            if !Task.isCancelled { suggestions = found }
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
        async let libraryTask = LibraryMatches.find(text)
        var tracks: [Track] = []
        do {
            let response = try await APIClient.shared.search(query: text)
            queryId = response.queryId
            total = response.total
            tracks = response.tracks
        } catch {
            if !Task.isCancelled { errorMessage = error.localizedDescription }
        }
        let (foundArtists, foundAlbums, foundLibrary) = await (artistsTask, albumsTask, libraryTask)
        guard !Task.isCancelled else { return }
        results = tracks
        artists = foundArtists
        albums = foundAlbums
        libraryTracks = foundLibrary.tracks
        libraryPlaylists = foundLibrary.playlists
        if !availableFilters.contains(filter) { filter = .all }
        if hasResults { errorMessage = nil }
        if !tracks.isEmpty || !foundArtists.isEmpty || !foundAlbums.isEmpty { remember(text) }
        isSearching = false
    }

    /// Page suivante des titres, quand on arrive en bas de la liste.
    func loadMore() async {
        guard canLoadMore, !isLoadingMore, let queryId else { return }
        isLoadingMore = true
        defer { isLoadingMore = false }
        guard let response = try? await APIClient.shared.search(queryId: queryId, offset: results.count),
              queryId == self.queryId else { return }
        let known = Set(results.map(\.id))
        let fresh = response.tracks.filter { !known.contains($0.id) }
        results.append(contentsOf: fresh)
        // Page vide ou déjà vue : on s'arrête là plutôt que de boucler.
        total = fresh.isEmpty ? results.count : response.total
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
        libraryTracks = []
        libraryPlaylists = []
        suggestions = []
        queryId = nil
        do {
            resolvedLink = try await APIClient.shared.resolve(text: text)
        } catch {
            if !Task.isCancelled { errorMessage = "Lien non reconnu ou indisponible." }
        }
        isSearching = false
    }

    // MARK: - Recherches récentes

    private static let recentsKey = "sona.searches"

    private static func loadRecents() -> [String] {
        UserDefaults.standard.stringArray(forKey: recentsKey) ?? []
    }

    private func remember(_ text: String) {
        var list = recents.filter { $0.caseInsensitiveCompare(text) != .orderedSame }
        list.insert(text, at: 0)
        recents = Array(list.prefix(10))
        UserDefaults.standard.set(recents, forKey: Self.recentsKey)
    }

    func forget(_ text: String) {
        recents.removeAll { $0 == text }
        UserDefaults.standard.set(recents, forKey: Self.recentsKey)
    }

    func clearRecents() {
        recents = []
        UserDefaults.standard.removeObject(forKey: Self.recentsKey)
    }
}

/// Ce de ta bibliothèque qui correspond à la recherche : titres aimés et playlists, filtrés
/// ici (liste gardée 5 minutes pour ne pas solliciter le serveur à chaque frappe).
@MainActor
enum LibraryMatches {
    private static var cachedAt = Date.distantPast
    private static var tracks: [Track] = []
    private static var playlists: [UserPlaylist] = []

    private static func refresh() async {
        guard Date().timeIntervalSince(cachedAt) > 300 else { return }
        async let page = APIClient.shared.library(kind: "track", limit: 500)
        async let lists = APIClient.shared.playlists()
        if let page = try? await page { tracks = page.items.map(\.asTrack) }
        if let lists = try? await lists { playlists = lists }
        cachedAt = Date()
    }

    static func find(_ text: String) async -> (tracks: [Track], playlists: [UserPlaylist]) {
        await refresh()
        let words = text.folded.split(separator: " ").map(String.init)
        guard !words.isEmpty else { return ([], []) }
        func matches(_ haystack: String) -> Bool {
            let folded = haystack.folded
            return words.allSatisfy { folded.contains($0) }
        }
        return (
            Array(tracks.filter { matches("\($0.title) \($0.artist) \($0.album ?? "")") }.prefix(30)),
            Array(playlists.filter { !$0.isImporting && matches($0.name) }.prefix(12))
        )
    }
}
