import Foundation

enum StatsPeriod: String, CaseIterable, Identifiable {
    case day, week, month, year, all

    var id: String { rawValue }
    var label: String {
        switch self {
        case .day: "Jour"
        case .week: "Semaine"
        case .month: "Mois"
        case .year: "Année"
        case .all: "Tout"
        }
    }
}

@MainActor
final class StatsViewModel: ObservableObject {
    @Published var period: StatsPeriod = .week {
        didSet {
            guard period != oldValue else { return }
            offset = 0
            Task { await load() }
        }
    }
    @Published private(set) var offset = 0
    @Published private(set) var report: StatsReport?
    @Published private(set) var isLoading = false
    @Published var errorMessage: String?
    @Published private(set) var importStatus: LastfmImportStatus?

    private var importPolling: Task<Void, Never>?

    var canGoForward: Bool { offset < 0 }
    var canGoBack: Bool { period != .all }

    func step(_ delta: Int) {
        let target = min(0, offset + delta)
        guard target != offset else { return }
        offset = target
        Task { await load() }
    }

    func load() async {
        isLoading = true
        errorMessage = nil
        let requested = (period, offset)
        do {
            let loaded = try await APIClient.shared.stats(period: requested.0.rawValue, offset: requested.1)
            guard requested == (period, offset) else { return }
            report = loaded
        } catch {
            if requested == (period, offset) { errorMessage = error.localizedDescription }
        }
        isLoading = false
        if importStatus == nil { await refreshImportStatus() }
    }

    func refreshImportStatus() async {
        importStatus = try? await APIClient.shared.lastfmImportStatus()
    }

    /// Lance l'import Last.fm puis suit sa progression jusqu'au bout, en
    /// rechargeant les stats à la fin.
    func startImport() async {
        do {
            importStatus = try await APIClient.shared.startLastfmImport()
        } catch {
            errorMessage = error.localizedDescription
            return
        }
        importPolling?.cancel()
        importPolling = Task {
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(1.5))
                await refreshImportStatus()
                if importStatus?.running != true { break }
            }
            await load()
        }
    }
}
