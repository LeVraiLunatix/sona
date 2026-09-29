import ActivityKit
import Foundation

/// Live Activity de l'« Écoute ensemble » (écran verrouillé, Dynamic
/// Island). Partagé entre l'app, qui la lance et la met à jour, et
/// l'extension de widgets, qui l'affiche.
struct PartyActivityAttributes: ActivityAttributes {
    struct ContentState: Codable, Hashable {
        var title: String?
        var artist: String?
        var listeners: Int
        var paused: Bool
        /// Heure à laquelle le titre en cours aurait commencé (barre de
        /// progression qui avance toute seule) et sa durée.
        var startedAt: Date?
        var duration: Double?
        var lastReaction: String?
    }

    var code: String
    var hostName: String
    var isHost: Bool
}
