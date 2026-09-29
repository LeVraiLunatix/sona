import AppIntents
import Combine
import Foundation

/// Liens à ouvrir dans l'app, posés par un raccourci Siri qui ouvre Sona
/// (voir `RootTabView.open`).
@MainActor
final class AppRouter: ObservableObject {
    static let shared = AppRouter()
    @Published var pendingURL: URL?
}

// MARK: - Lecture

/// « Dis Siri, mets mon mix du jour sur Sona ».
struct PlayDailyMixIntent: AppIntent {
    static let title: LocalizedStringResource = "Jouer mon mix du jour"
    static let description = IntentDescription("Lance ton premier mix « Faits pour toi » dans Sona.")

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        let mixes = try await APIClient.shared.mixes()
        guard let mix = mixes.first(where: { !$0.tracks.isEmpty }), let first = mix.tracks.first else {
            return .result(dialog: "Pas encore de mix : écoute un peu de musique d'abord.")
        }
        PlayerManager.shared.play(first, context: mix.tracks, name: mix.title)
        return .result(dialog: "C'est parti : \(mix.title).")
    }
}

/// Les playlists intelligentes, au choix dans Raccourcis.
enum SmartPlaylistKind: String, AppEnum {
    case onRepeat = "on_repeat"
    case forgotten
    case discoveries
    case nights
    case mornings
    case crushes

    static let typeDisplayRepresentation: TypeDisplayRepresentation = "Playlist intelligente"
    static let caseDisplayRepresentations: [SmartPlaylistKind: DisplayRepresentation] = [
        .onRepeat: "En boucle",
        .forgotten: "Titres oubliés",
        .discoveries: "Découvertes du mois",
        .nights: "Tes nuits",
        .mornings: "Tes matins",
        .crushes: "Coups de cœur d'un jour",
    ]
}

struct PlaySmartPlaylistIntent: AppIntent {
    static let title: LocalizedStringResource = "Jouer une playlist intelligente"
    static let description = IntentDescription("En boucle, titres oubliés, découvertes du mois…")

    @Parameter(title: "Playlist", default: .onRepeat)
    var playlist: SmartPlaylistKind

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        let tracks = try await APIClient.shared.smartPlaylist(playlist.rawValue)
        let name = String(localized: SmartPlaylistKind.caseDisplayRepresentations[playlist]?.title ?? "Sona")
        guard let first = tracks.first else {
            return .result(dialog: "Cette playlist est vide pour l'instant.")
        }
        PlayerManager.shared.play(first, context: tracks, name: name)
        return .result(dialog: "Lecture de \(name).")
    }
}

/// Radio DJ à partir du titre en cours (ou du mix du jour).
struct StartDJRadioIntent: AppIntent {
    static let title: LocalizedStringResource = "Lancer la radio DJ"
    static let description = IntentDescription("Une suite sans fin à partir du titre en cours, enchaînée en AutoMix.")

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        var seed = PlayerManager.shared.current
        if seed == nil { seed = try await APIClient.shared.mixes().first?.tracks.first }
        guard let seed else { return .result(dialog: "Lance d'abord un titre dans Sona.") }
        try await PlayerManager.shared.playDJRadio(from: seed)
        return .result(dialog: "Radio DJ à partir de \(seed.title).")
    }
}

struct PauseIntent: AppIntent {
    static let title: LocalizedStringResource = "Mettre Sona en pause"

    @MainActor
    func perform() async throws -> some IntentResult {
        PlayerManager.shared.pause()
        return .result()
    }
}

struct ResumeIntent: AppIntent {
    static let title: LocalizedStringResource = "Reprendre la lecture Sona"

    @MainActor
    func perform() async throws -> some IntentResult {
        PlayerManager.shared.resume()
        return .result()
    }
}

struct NextTrackIntent: AppIntent {
    static let title: LocalizedStringResource = "Titre suivant sur Sona"

    @MainActor
    func perform() async throws -> some IntentResult {
        PlayerManager.shared.next()
        return .result()
    }
}

/// « Qu'est-ce que j'écoute ? »
struct WhatsPlayingIntent: AppIntent {
    static let title: LocalizedStringResource = "Titre en cours sur Sona"

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        guard let track = PlayerManager.shared.current else {
            return .result(dialog: "Rien en lecture sur Sona.")
        }
        return .result(dialog: "\(track.title), de \(track.artist).")
    }
}

// MARK: - Ouvrir l'app

struct DailyChallengeIntent: AppIntent {
    static let title: LocalizedStringResource = "Défi du jour Sona"
    static let description = IntentDescription("Ouvre le blind test du jour.")
    static let openAppWhenRun = true

    @MainActor
    func perform() async throws -> some IntentResult {
        AppRouter.shared.pendingURL = URL(string: "encre://blindtest")
        return .result()
    }
}

struct ListenTogetherIntent: AppIntent {
    static let title: LocalizedStringResource = "Écouter ensemble sur Sona"
    static let openAppWhenRun = true

    @MainActor
    func perform() async throws -> some IntentResult {
        AppRouter.shared.pendingURL = URL(string: "encre://party")
        return .result()
    }
}

struct LastRecapIntent: AppIntent {
    static let title: LocalizedStringResource = "Mon récap Sona"
    static let openAppWhenRun = true

    @MainActor
    func perform() async throws -> some IntentResult {
        AppRouter.shared.pendingURL = URL(string: "encre://recap?period=week")
        return .result()
    }
}

// MARK: - Phrases Siri

struct SonaShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: PlayDailyMixIntent(),
            phrases: ["Joue mon mix du jour sur \(.applicationName)", "Mets mon mix \(.applicationName)"],
            shortTitle: "Mix du jour",
            systemImageName: "sparkles"
        )
        AppShortcut(
            intent: StartDJRadioIntent(),
            phrases: ["Lance la radio DJ sur \(.applicationName)", "Radio DJ \(.applicationName)"],
            shortTitle: "Radio DJ",
            systemImageName: "dial.medium"
        )
        AppShortcut(
            intent: PlaySmartPlaylistIntent(),
            phrases: ["Joue \(\.$playlist) sur \(.applicationName)", "Mets mes titres \(\.$playlist) sur \(.applicationName)"],
            shortTitle: "Playlist intelligente",
            systemImageName: "wand.and.stars"
        )
        AppShortcut(
            intent: DailyChallengeIntent(),
            phrases: ["Défi du jour \(.applicationName)", "Lance le blind test \(.applicationName)"],
            shortTitle: "Défi du jour",
            systemImageName: "waveform.badge.magnifyingglass"
        )
        AppShortcut(
            intent: WhatsPlayingIntent(),
            phrases: ["Qu'est-ce que j'écoute sur \(.applicationName)", "C'est quoi ce titre \(.applicationName)"],
            shortTitle: "Titre en cours",
            systemImageName: "music.note"
        )
        AppShortcut(
            intent: ListenTogetherIntent(),
            phrases: ["Écoute ensemble sur \(.applicationName)"],
            shortTitle: "Écouter ensemble",
            systemImageName: "person.2.wave.2.fill"
        )
        AppShortcut(
            intent: LastRecapIntent(),
            phrases: ["Mon récap \(.applicationName)"],
            shortTitle: "Récap",
            systemImageName: "chart.bar.fill"
        )
        AppShortcut(
            intent: PauseIntent(),
            phrases: ["Pause \(.applicationName)", "Mets \(.applicationName) en pause"],
            shortTitle: "Pause",
            systemImageName: "pause.fill"
        )
        AppShortcut(
            intent: ResumeIntent(),
            phrases: ["Reprends \(.applicationName)"],
            shortTitle: "Reprendre",
            systemImageName: "play.fill"
        )
        AppShortcut(
            intent: NextTrackIntent(),
            phrases: ["Titre suivant \(.applicationName)"],
            shortTitle: "Suivant",
            systemImageName: "forward.fill"
        )
    }
}
