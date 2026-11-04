import BackgroundTasks
import Foundation
import Network
import UserNotifications

/// Téléchargements intelligents : la nuit (Wi-Fi et en charge, quand iOS le
/// permet) et à l'ouverture de l'app en Wi-Fi, Sona télécharge le Mix du
/// jour, « En boucle » et les nouveaux titres des playlists gardées hors
/// ligne. Ce qu'on écoute démarre alors instantanément, même en 5G. Les
/// titres ainsi ajoutés repartent seuls quand ils ne servent plus.
@MainActor
final class SmartDownloads {
    static let shared = SmartDownloads()
    static let taskIdentifier = "com.sona.encre.smart-downloads"

    private let monitor = NWPathMonitor()
    private var onUnmeteredNetwork = false
    private var running: Task<Void, Never>?

    var enabled: Bool {
        get { UserDefaults.standard.object(forKey: "encre.smart.enabled") as? Bool ?? true }
        set { UserDefaults.standard.set(newValue, forKey: "encre.smart.enabled") }
    }

    private(set) var lastRun: Date? {
        get { UserDefaults.standard.object(forKey: "encre.smart.lastRun") as? Date }
        set { UserDefaults.standard.set(newValue, forKey: "encre.smart.lastRun") }
    }

    private init() {
        monitor.pathUpdateHandler = { path in
            let unmetered = path.status == .satisfied && !path.isExpensive && !path.isConstrained
            Task { @MainActor in SmartDownloads.shared.onUnmeteredNetwork = unmetered }
        }
        monitor.start(queue: DispatchQueue(label: "sona.smart.network"))
    }

    // MARK: - Tâche de fond

    /// À appeler au lancement (avant la fin du démarrage de l'app).
    nonisolated static func registerBackgroundTask() {
        BGTaskScheduler.shared.register(forTaskWithIdentifier: taskIdentifier, using: nil) { task in
            guard let task = task as? BGProcessingTask else { return }
            Task { @MainActor in
                SmartDownloads.shared.schedule()
                let work = Task { await SmartDownloads.shared.run() }
                task.expirationHandler = { work.cancel() }
                await work.value
                task.setTaskCompleted(success: !work.isCancelled)
            }
        }
    }

    /// Prochaine fenêtre : cette nuit, en Wi-Fi et en charge.
    func schedule() {
        guard enabled else { return }
        let request = BGProcessingTaskRequest(identifier: Self.taskIdentifier)
        request.requiresNetworkConnectivity = true
        request.requiresExternalPower = true
        var components = Calendar.current.dateComponents([.year, .month, .day], from: Date())
        components.hour = 3
        let tonight = Calendar.current.date(from: components) ?? Date()
        request.earliestBeginDate = tonight > Date() ? tonight : tonight.addingTimeInterval(86_400)
        try? BGTaskScheduler.shared.submit(request)
    }

    /// À l'ouverture de l'app : si c'est en Wi-Fi et que le dernier passage
    /// date de plus de 6 h.
    func runIfDue() {
        guard enabled, running == nil else { return }
        if let lastRun, Date().timeIntervalSince(lastRun) < 6 * 3600 { return }
        running = Task {
            // Au lancement, iOS met un instant à dire si on est en Wi-Fi.
            try? await Task.sleep(for: .seconds(3))
            if onUnmeteredNetwork { await run() }
            running = nil
        }
    }

    // MARK: - Passage

    func run() async {
        guard enabled, APIConfig.shared.isConfigured else { return }
        let downloads = DownloadManager.shared
        var wanted: [Track] = []

        if let mixes = try? await APIClient.shared.mixes() {
            for mix in mixes where mix.id == "daily" || mix.id == "repeat" {
                wanted += mix.tracks.prefix(40)
            }
        }
        for playlistId in downloads.offlinePlaylistIds {
            if let playlist = try? await APIClient.shared.userPlaylist(id: playlistId) {
                wanted += playlist.tracks
            }
        }
        let wantedIds = Set(wanted.map(\.id))
        downloads.download(wanted.filter { !downloads.isDownloaded($0) }, auto: true)
        downloads.pruneAuto(keeping: wantedIds)
        lastRun = Date()

        await downloads.waitUntilIdle()
    }
}
