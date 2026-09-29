import ActivityKit
import Foundation

/// Live Activity « paroles » : la ligne chantée en direct sur l'écran
/// verrouillé et dans la Dynamic Island. Partagé entre l'app (qui la met à
/// jour à chaque ligne) et l'extension de widgets (qui l'affiche).
struct LyricsActivityAttributes: ActivityAttributes {
    struct ContentState: Codable, Hashable {
        var title: String
        var artist: String
        var line: String?
        var nextLine: String?
        var paused: Bool
        /// Début théorique du titre (barre qui avance toute seule) et durée.
        var startedAt: Date?
        var duration: Double?
    }

    var id: String
}
