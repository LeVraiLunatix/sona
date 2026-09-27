import Foundation

enum LibraryKind: String, CaseIterable, Identifiable {
    case tracks = "track"
    case albums = "album"
    case artists = "artist"

    var id: String { rawValue }
    var label: String {
        switch self {
        case .tracks: "Titres"
        case .albums: "Albums"
        case .artists: "Artistes"
        }
    }
}

@MainActor
final class LibraryViewModel: ObservableObject {
    @Published var kind: LibraryKind = .tracks {
        didSet { Task { await load() } }
    }
    @Published var items: [LibraryItem] = []
    @Published var isLoading = false
    @Published var errorMessage: String?

    func load() async {
        isLoading = true
        errorMessage = nil
        do {
            let page = try await APIClient.shared.library(kind: kind.rawValue, limit: 100)
            items = page.items
        } catch {
            errorMessage = error.localizedDescription
        }
        isLoading = false
    }
}
