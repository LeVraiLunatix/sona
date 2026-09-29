import ActivityKit
import Foundation

/// Live Activity de l'écoute ensemble : lancée en entrant dans une session,
/// mise à jour quand le titre, la pause, le nombre d'auditeurs ou une
/// réaction change, arrêtée en sortant. Affichée par l'extension de widgets
/// (`Widgets/SonaWidgets.swift`).
@MainActor
enum PartyActivity {
    private static var activity: Activity<PartyActivityAttributes>?
    private static var lastState: PartyActivityAttributes.ContentState?

    static var isActive: Bool { activity != nil }

    static func sync(_ party: PartyState?, reaction: String?) {
        guard let party else {
            end()
            return
        }
        guard ActivityAuthorizationInfo().areActivitiesEnabled else { return }
        let content = PartyActivityAttributes.ContentState(
            title: party.track?.title,
            artist: party.track?.artist,
            listeners: party.members.count,
            paused: party.paused,
            startedAt: party.paused ? nil : Date().addingTimeInterval(-party.position),
            duration: party.track?.durationSeconds.map(Double.init),
            lastReaction: reaction ?? lastState?.lastReaction
        )
        if let activity, activity.attributes.code == party.code {
            // Sans changement visible, pas de mise à jour (le début du titre
            // bouge de quelques dixièmes à chaque relecture).
            if let lastState, lastState.title == content.title, lastState.paused == content.paused,
               lastState.listeners == content.listeners, lastState.lastReaction == content.lastReaction,
               abs((lastState.startedAt ?? .distantPast).timeIntervalSince(content.startedAt ?? .distantPast)) < 3 {
                return
            }
            lastState = content
            Task { await activity.update(ActivityContent(state: content, staleDate: nil)) }
            return
        }
        end()
        let attributes = PartyActivityAttributes(
            code: party.code, hostName: party.hostName ?? "l'hôte", isHost: party.isHost
        )
        // Une seule Live Activity à la fois : celle de la session remplace les paroles.
        LyricsActivity.shared.end()
        activity = try? Activity.request(attributes: attributes, content: ActivityContent(state: content, staleDate: nil))
        lastState = content
    }

    static func end() {
        guard let current = activity else { return }
        activity = nil
        lastState = nil
        Task { await current.end(nil, dismissalPolicy: .immediate) }
    }
}
