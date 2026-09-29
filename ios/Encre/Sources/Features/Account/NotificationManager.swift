import BackgroundTasks
import UIKit
import UserNotifications

/// Notifications de Sona, créées par l'app elle-même (notifications
/// locales) : les notifications « poussées » par un serveur exigent un
/// compte développeur Apple payant, que l'installation sans compte ne
/// permet pas.
///
/// - récap de la semaine (lundi) et du mois (le 1er), prévus à l'avance ;
/// - défi du jour du blind test, en fin de journée ;
/// - un ami lance un blind test en direct ou une écoute ensemble : vérifié
///   toutes les 90 s tant que l'app tourne (au premier plan ou en lecture),
///   et de temps en temps en arrière-plan quand iOS le permet.
@MainActor
final class NotificationManager: NSObject, ObservableObject {
    static let shared = NotificationManager()
    nonisolated static let refreshTaskIdentifier = "com.sona.encre.refresh"

    @Published var recaps: Bool { didSet { save("recaps", recaps) } }
    @Published var dailyChallenge: Bool { didSet { save("daily", dailyChallenge) } }
    @Published var friends: Bool { didSet { save("friends", friends) } }
    @Published var releases: Bool { didSet { save("releases", releases) } }

    private let center = UNUserNotificationCenter.current()
    private var polling: Task<Void, Never>?

    private override init() {
        let defaults = UserDefaults.standard
        recaps = defaults.object(forKey: "notifications.recaps") as? Bool ?? true
        dailyChallenge = defaults.object(forKey: "notifications.daily") as? Bool ?? true
        friends = defaults.object(forKey: "notifications.friends") as? Bool ?? true
        releases = defaults.object(forKey: "notifications.releases") as? Bool ?? true
        super.init()
    }

    /// À appeler au lancement : les notifications touchées ouvrent le bon écran.
    func setUp() {
        center.delegate = self
    }

    /// Vérification des amis en arrière-plan : à déclarer avant la fin du
    /// lancement, sinon iOS refuse la tâche.
    nonisolated static func registerBackgroundTask() {
        BGTaskScheduler.shared.register(forTaskWithIdentifier: refreshTaskIdentifier, using: nil) { task in
            Task { @MainActor in
                NotificationManager.shared.scheduleRefresh()
                let work = Task {
                    await NotificationManager.shared.checkFriends()
                    await NotificationManager.shared.checkReleases()
                }
                task.expirationHandler = { work.cancel() }
                await work.value
                task.setTaskCompleted(success: true)
            }
        }
    }

    /// Une fois connecté : autorisation (demandée une seule fois), rappels
    /// prévus, et surveillance des amis.
    func start() async {
        let settings = await center.notificationSettings()
        if settings.authorizationStatus == .notDetermined {
            _ = try? await center.requestAuthorization(options: [.alert, .sound, .badge])
        }
        reschedule()
        startPolling()
    }

    private func save(_ key: String, _ value: Bool) {
        UserDefaults.standard.set(value, forKey: "notifications.\(key)")
        reschedule()
        if key == "friends" {
            if value {
                startPolling()
            } else {
                polling?.cancel()
            }
        }
    }

    // MARK: Rappels prévus

    private enum Planned: String, CaseIterable {
        case weekRecap = "sona.recap.week"
        case monthRecap = "sona.recap.month"
        case daily = "sona.daily"
    }

    func reschedule() {
        center.removePendingNotificationRequests(withIdentifiers: Planned.allCases.map(\.rawValue))
        if recaps {
            // Lundi 10 h : la semaine écoulée ; le 1er à 10 h : le mois écoulé.
            add(.weekRecap, title: "Ton récap de la semaine est prêt ✨",
                body: "Tes titres, tes artistes et tes habitudes de la semaine dernière.",
                url: "encre://recap?period=week", date: DateComponents(hour: 10, minute: 0, weekday: 2))
            add(.monthRecap, title: "Ton récap du mois est prêt ✨",
                body: "Ton mois en musique : tops, découvertes, profil d'écoute.",
                url: "encre://recap?period=month", date: DateComponents(day: 1, hour: 10, minute: 5))
        }
        if dailyChallenge {
            add(.daily, title: "Défi du jour 🎯", body: "10 extraits, un classement entre amis. Tu tiens combien ?",
                url: "encre://blindtest", date: DateComponents(hour: 18, minute: 30))
        }
    }

    private func add(_ id: Planned, title: String, body: String, url: String, date: DateComponents) {
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default
        content.userInfo = ["url": url]
        let trigger = UNCalendarNotificationTrigger(dateMatching: date, repeats: true)
        center.add(UNNotificationRequest(identifier: id.rawValue, content: content, trigger: trigger))
    }

    // MARK: Amis

    private func startPolling() {
        guard friends, polling == nil || polling?.isCancelled == true else { return }
        polling = Task {
            while !Task.isCancelled {
                await checkFriends()
                await checkReleases()
                try? await Task.sleep(for: .seconds(90))
            }
        }
    }

    /// Nouvelles parties des amis (blind test en direct, écoute ensemble) :
    /// une notification chacune, une seule fois.
    func checkFriends() async {
        guard friends, APIConfig.shared.isConfigured else { return }
        var seen = Set(UserDefaults.standard.stringArray(forKey: "notifications.seen") ?? [])
        let firstRun = seen.isEmpty
        var fresh: [(id: String, title: String, body: String, url: String)] = []

        if let rooms = try? await APIClient.shared.activeLive() {
            for room in rooms where !room.joined && room.phase != "finished" {
                fresh.append((
                    "live-\(room.code)",
                    "\(room.hostName ?? "Un ami") lance un blind test 🎮",
                    room.label.map { "Thème : \($0). Rejoins la partie !" } ?? "Rejoins la partie avant qu'elle commence !",
                    "encre://live?code=\(room.code)"
                ))
            }
        }
        if let parties = try? await APIClient.shared.activeParties() {
            for party in parties where !party.joined {
                fresh.append((
                    "party-\(party.code)",
                    "\(party.hostName ?? "Un ami") lance une écoute ensemble 🎧",
                    party.track.map { "En ce moment : \($0.title) — \($0.artist)" } ?? "Viens écouter en même temps !",
                    "encre://party?code=\(party.code)"
                ))
            }
        }
        for item in fresh where !seen.contains(item.id) {
            seen.insert(item.id)
            // Au tout premier passage, on mémorise sans notifier ce qui
            // tournait déjà.
            guard !firstRun else { continue }
            let content = UNMutableNotificationContent()
            content.title = item.title
            content.body = item.body
            content.sound = .default
            content.userInfo = ["url": item.url]
            try? await center.add(UNNotificationRequest(identifier: item.id, content: content, trigger: nil))
        }
        if firstRun && seen.isEmpty { seen.insert("-") }
        UserDefaults.standard.set(Array(seen.suffix(200)), forKey: "notifications.seen")
    }

    /// Nouvelles sorties de tes artistes : vérifiées au plus toutes les 6 h,
    /// une notification par sortie, une seule fois.
    func checkReleases() async {
        guard releases, APIConfig.shared.isConfigured else { return }
        let defaults = UserDefaults.standard
        if let last = defaults.object(forKey: "notifications.releasesCheckedAt") as? Date,
           Date().timeIntervalSince(last) < 6 * 3600 { return }
        guard let found = try? await APIClient.shared.releases() else { return }
        defaults.set(Date(), forKey: "notifications.releasesCheckedAt")
        var seen = Set(defaults.stringArray(forKey: "notifications.releasesSeen") ?? [])
        let firstRun = defaults.object(forKey: "notifications.releasesSeen") == nil
        for release in found.prefix(10) where !seen.contains(release.id) {
            seen.insert(release.id)
            guard !firstRun else { continue }  // premières sorties connues : pas de rafale
            let content = UNMutableNotificationContent()
            content.title = "\(release.artist) : nouvel\(release.kind == "Single" ? "" : "le") \(release.kind.lowercased()) 🔥"
            content.body = "« \(release.title) » est sorti. Écoute-le maintenant."
            content.sound = .default
            content.userInfo = ["url": "encre://album?source=\(release.source)&id=\(release.sourceId)"]
            try? await center.add(UNNotificationRequest(identifier: "release-\(release.id)", content: content, trigger: nil))
        }
        defaults.set(Array(seen.suffix(300)), forKey: "notifications.releasesSeen")
    }

    /// Prochaine vérification en arrière-plan (iOS choisit le moment).
    func scheduleRefresh() {
        guard friends else { return }
        let request = BGAppRefreshTaskRequest(identifier: Self.refreshTaskIdentifier)
        request.earliestBeginDate = Date(timeIntervalSinceNow: 15 * 60)
        try? BGTaskScheduler.shared.submit(request)
    }
}

extension NotificationManager: UNUserNotificationCenterDelegate {
    /// Aussi affichées quand l'app est ouverte.
    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter, willPresent notification: UNNotification
    ) async -> UNNotificationPresentationOptions {
        [.banner, .list, .sound]
    }

    /// Toucher la notification ouvre le bon écran (liens `encre://`).
    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse
    ) async {
        guard let link = response.notification.request.content.userInfo["url"] as? String,
              let url = URL(string: link) else { return }
        await MainActor.run { UIApplication.shared.open(url) }
    }
}
