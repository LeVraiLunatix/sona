import AppIntents

/// Boutons du widget « Mon PC » et du Centre de contrôle : une commande pour
/// l'appareil piloté (choisi dans « Appareils », ou celui qui joue ailleurs).
///
/// Partagé avec le widget, qui ne sait pas joindre le serveur (pas de
/// données partagées sans « App Group ») : `AudioPlaybackIntent` fait
/// exécuter la commande par l'app elle-même, lancée en arrière-plan si
/// besoin, qui l'envoie via Sona Connect (voir `RemoteIntentBridge`).
struct PCRemoteButtonIntent: AudioPlaybackIntent {
    static let title: LocalizedStringResource = "Commande pour mon PC"
    static let isDiscoverable = false

    @Parameter(title: "Commande")
    var command: String

    init() { command = "toggle" }

    init(_ command: String) { self.command = command }

    @MainActor
    func perform() async throws -> some IntentResult {
        await RemoteIntentBridge.handler?(command)
        return .result()
    }
}

/// Rempli par l'app au lancement ; vide dans le widget (qui n'exécute pas
/// l'intent lui-même).
@MainActor
enum RemoteIntentBridge {
    static var handler: ((String) async -> Void)?
}
