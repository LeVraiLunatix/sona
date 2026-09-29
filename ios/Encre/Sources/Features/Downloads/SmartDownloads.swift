import BackgroundTasks
import Foundation
import Network
import UserNotifications

/// Téléchargements intelligents : la nuit (Wi-Fi et en charge, quand iOS le
/// permet) et à l'ouverture de l'app en Wi-Fi, Sona télécharge le Mix du
/// jour, « En boucle » et les nouveaux titres des playlists gardées hors
/// ligne. Ce qu'on écoute démarre alors instantanément, même en 5G. Les
/// titres ainsi ajoutés repartent seuls quand ils ne servent plus.
/// Au passage, prévient des nouveaux concerts proches (voir `ConcertAlerts`).
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
        guard enabled, onUnmeteredNetwork, running == nil else { return }
        if let lastRun, Date().timeIntervalSince(lastRun) < 6 * 3600 { return }
        running = Task {
            await run()
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

        await ConcertAlerts.check()
        await downloads.waitUntilIdle()
    }
}

/// Alerte quand un artiste qu'on écoute beaucoup annonce une date près de
/// la dernière position connue (jamais envoyée au serveur).
enum ConcertAlerts {
    static let radiusKm: Double = 150

    static var enabled: Bool {
        get { UserDefaults.standard.bool(forKey: "encre.concerts.alerts") }
        set { UserDefaults.standard.set(newValue, forKey: "encre.concerts.alerts") }
    }

    /// Dernière position connue (latitude, longitude), mise à jour par l'écran Concerts.
    static var lastLocation: (Double, Double)? {
        get {
            guard let values = UserDefaults.standard.array(forKey: "encre.concerts.location") as? [Double], values.count == 2 else { return nil }
            return (values[0], values[1])
        }
        set {
            if let newValue { UserDefaults.standard.set([newValue.0, newValue.1], forKey: "encre.concerts.location") }
        }
    }

    static func requestPermission() async -> Bool {
        (try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge])) ?? false
    }

    @MainActor
    static func check() async {
        guard enabled, let location = lastLocation, let concerts = try? await APIClient.shared.concerts() else { return }
        let (lat, lon) = location
        var notified = Set(UserDefaults.standard.stringArray(forKey: "encre.concerts.notified") ?? [])
        let near = concerts.filter { concert in
            guard let cLat = concert.latitude, let cLon = concert.longitude else { return false }
            return distanceKm(lat, lon, cLat, cLon) <= radiusKm && !notified.contains(concert.id)
        }
        for concert in near.prefix(5) {
            let content = UNMutableNotificationContent()
            content.title = "🎤 \(concert.artist) en concert près de toi"
            content.body = [concert.venue, concert.city, concert.date.map(dayLabel)].compactMap { $0 }.joined(separator: " · ")
            content.sound = .default
            let request = UNNotificationRequest(identifier: "concert-\(concert.id)", content: content, trigger: nil)
            try? await UNUserNotificationCenter.current().add(request)
            notified.insert(concert.id)
        }
        UserDefaults.standard.set(Array(notified), forKey: "encre.concerts.notified")
    }

    static func distanceKm(_ lat1: Double, _ lon1: Double, _ lat2: Double, _ lon2: Double) -> Double {
        let r = 6371.0
        let dLat = (lat2 - lat1) * .pi / 180
        let dLon = (lon2 - lon1) * .pi / 180
        let a = sin(dLat / 2) * sin(dLat / 2)
            + cos(lat1 * .pi / 180) * cos(lat2 * .pi / 180) * sin(dLon / 2) * sin(dLon / 2)
        return 2 * r * atan2(sqrt(a), sqrt(1 - a))
    }

    static func dayLabel(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "fr_FR")
        formatter.dateFormat = "EEEE d MMMM"
        return formatter.string(from: date)
    }
}
