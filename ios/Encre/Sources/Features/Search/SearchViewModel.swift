import Foundation

@MainActor
final class SearchViewModel: ObservableObject {
    @Published var query = "" {
        didSet { scheduleSearch() }
    }
    @Published private(set) var results: [Track] = []
    @Published private(set) var isSearching = false
    @Published private(set) var errorMessage: String?
    @Published var resolvedLink: ResolvedLink?

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

    private func search(_ text: String) async {
        isSearching = true
        errorMessage = nil
        do {
            let response = try await APIClient.shared.search(query: text)
            guard !Task.isCancelled else { return }
            queryId = response.queryId
            results = response.tracks
        } catch {
            if !Task.isCancelled { errorMessage = error.localizedDescription }
        }
        isSearching = false
    }

    private func resolve(_ text: String) async {
        isSearching = true
        errorMessage = nil
        results = []
        do {
            resolvedLink = try await APIClient.shared.resolve(text: text)
        } catch {
            if !Task.isCancelled { errorMessage = "Lien non reconnu ou indisponible." }
        }
        isSearching = false
    }
}
