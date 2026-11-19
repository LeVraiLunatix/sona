import ActivityKit
import Foundation

/// Album dont l'utilisateur veut être prévenu : gardé pour lancer le compte à
/// rebours sur l'écran verrouillé quand la sortie approche.
struct ReleaseReminder: Codable, Hashable, Identifiable {
    var source: String
    var sourceId: String
    var title: String
    var artist: String
    var releaseAt: Date

    var id: String { "\(source):\(sourceId)" }
}

/// Compte à rebours de sortie sur l'écran verrouillé et dans la Dynamic Island
/// (`ReleaseLiveActivity`, dans l'extension de widgets).
///
/// iOS limite une Live Activity à 8 heures et n'en laisse lancer une que depuis
/// l'app ouverte : on la lance dans les `window` heures qui précèdent la sortie,
/// à l'ouverture de l'app (ou tout de suite si l'on est déjà dans la fenêtre).
@MainActor
enum ReleaseActivity {
    /// Avant la sortie, durée à partir de laquelle le compte à rebours peut s'afficher.
    static let window: TimeInterval = 7.5 * 3600
    /// Un album sorti depuis plus longtemps est oublié (activité retirée, rappel effacé).
    private static let keepAfter: TimeInterval = 3600
    private static let key = "encre.releaseReminders"

    // MARK: Rappels gardés

    static var reminders: [ReleaseReminder] {
        guard let data = UserDefaults.standard.data(forKey: key),
              let list = try? JSONDecoder().decode([ReleaseReminder].self, from: data) else { return [] }
        return list
    }

    private static func save(_ list: [ReleaseReminder]) {
        UserDefaults.standard.set(try? JSONEncoder().encode(list), forKey: key)
    }

    static func remember(_ album: Album) {
        guard let moment = album.releaseMoment else { return }
        let reminder = ReleaseReminder(
            source: album.source, sourceId: album.sourceId, title: album.title, artist: album.artist, releaseAt: moment
        )
        save(reminders.filter { $0.id != reminder.id } + [reminder])
    }

    static func forget(_ album: Album) {
        save(reminders.filter { $0.id != album.id })
        stop(album)
    }

    // MARK: Live Activity

    /// Le compte à rebours peut-il s'afficher maintenant (sortie dans la fenêtre) ?
    static func canShow(_ moment: Date) -> Bool {
        let left = moment.timeIntervalSinceNow
        return left > 0 && left <= window
    }

    private static func existing(_ id: String) -> Activity<ReleaseActivityAttributes>? {
        Activity<ReleaseActivityAttributes>.activities.first { "\($0.attributes.source):\($0.attributes.albumID)" == id }
    }

    static func isShowing(_ album: Album) -> Bool { existing(album.id) != nil }

    @discardableResult
    static func start(_ reminder: ReleaseReminder) -> Bool {
        guard ActivityAuthorizationInfo().areActivitiesEnabled, canShow(reminder.releaseAt) else { return false }
        if existing(reminder.id) != nil { return true }
        let attributes = ReleaseActivityAttributes(
            source: reminder.source, albumID: reminder.sourceId, title: reminder.title,
            artist: reminder.artist, releaseAt: reminder.releaseAt
        )
        // `staleDate` = l'heure de sortie : l'activité passe alors à « Sorti », sans l'app.
        let content = ActivityContent(state: ReleaseActivityAttributes.ContentState(released: false), staleDate: reminder.releaseAt)
        return (try? Activity.request(attributes: attributes, content: content)) != nil
    }

    @discardableResult
    static func start(_ album: Album) -> Bool {
        guard let moment = album.releaseMoment else { return false }
        return start(ReleaseReminder(
            source: album.source, sourceId: album.sourceId, title: album.title, artist: album.artist, releaseAt: moment
        ))
    }

    static func stop(_ album: Album) {
        guard let activity = existing(album.id) else { return }
        Task { await activity.end(nil, dismissalPolicy: .immediate) }
    }

    /// À l'ouverture de l'app : lance le compte à rebours des albums attendus dont
    /// la sortie approche, retire les activités et rappels des albums sortis depuis longtemps.
    static func resume() {
        let now = Date()
        let all = reminders
        let live = all.filter { $0.releaseAt.timeIntervalSince(now) > -keepAfter }
        if live.count != all.count { save(live) }
        for activity in Activity<ReleaseActivityAttributes>.activities
        where activity.attributes.releaseAt.timeIntervalSince(now) <= -keepAfter {
            Task { await activity.end(nil, dismissalPolicy: .immediate) }
        }
        for reminder in live where canShow(reminder.releaseAt) { start(reminder) }
    }
}
