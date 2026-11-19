import ActivityKit
import Foundation

/// Live Activity « sortie d'un album » : le compte à rebours jusqu'à la sortie,
/// sur l'écran verrouillé et dans la Dynamic Island. Partagé entre l'app (qui la
/// lance) et l'extension de widgets (qui l'affiche). Le décompte est dessiné par
/// le système (`Text(timerInterval:)`) : il tourne tout seul, app fermée.
struct ReleaseActivityAttributes: ActivityAttributes {
    struct ContentState: Codable, Hashable {
        /// Jamais mis à jour par l'app : à l'heure de sortie, la Live Activity
        /// devient « périmée » (`staleDate`) et l'extension affiche « Sorti ».
        var released: Bool
    }

    var source: String
    var albumID: String
    var title: String
    var artist: String
    var releaseAt: Date
}
