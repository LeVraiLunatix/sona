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

/// « Dis Siri, lance le titre du jour sur Sona ».
struct PlayDailyTrackIntent: AppIntent {
    static let title: LocalizedStringResource = "Jouer le titre du jour"
    static let description = IntentDescription("Une découverte choisie d'après tes goûts, la même toute la journée.")

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        let daily = try await APIClient.shared.dailyTrack()
        guard let track = daily.track else { return .result(dialog: "Pas encore de titre du jour : écoute un peu de musique d'abord.") }
        PlayerManager.shared.play(track, context: [track], name: "Titre du jour")
        return .result(dialog: "Titre du jour : \(track.title), de \(track.artist).")
    }
}

/// Une de tes playlists, pour Siri et Raccourcis (« mets ma playlist Sport »).
struct PlaylistEntity: AppEntity {
    static let typeDisplayRepresentation: TypeDisplayRepresentation = "Playlist"
    static let defaultQuery = PlaylistQuery()
    let id: Int
    let name: String
    var displayRepresentation: DisplayRepresentation { DisplayRepresentation(title: "\(name)") }
}

struct PlaylistQuery: EntityStringQuery {
    @MainActor
    func entities(for identifiers: [Int]) async throws -> [PlaylistEntity] {
        try await all().filter { identifiers.contains($0.id) }
    }

    @MainActor
    func entities(matching string: String) async throws -> [PlaylistEntity] {
        let needle = string.folding(options: [.caseInsensitive, .diacriticInsensitive], locale: .current)
        return try await all().filter {
            $0.name.folding(options: [.caseInsensitive, .diacriticInsensitive], locale: .current).contains(needle)
        }
    }

    @MainActor
    func suggestedEntities() async throws -> [PlaylistEntity] { try await all() }

    @MainActor
    private func all() async throws -> [PlaylistEntity] {
        try await APIClient.shared.playlists().map { PlaylistEntity(id: $0.id, name: $0.name) }
    }
}

struct PlayUserPlaylistIntent: AppIntent {
    static let title: LocalizedStringResource = "Jouer une de mes playlists"
    static let description = IntentDescription("Lance une de tes playlists Sona (« Sport », « Soirée »…).")

    @Parameter(title: "Playlist")
    var playlist: PlaylistEntity

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        let detail = try await APIClient.shared.userPlaylist(id: playlist.id)
        let tracks = detail.tracks
        guard let first = tracks.first else { return .result(dialog: "La playlist \(playlist.name) est vide.") }
        PlayerManager.shared.play(first, context: tracks, name: detail.name)
        return .result(dialog: "Lecture de \(detail.name).")
    }
}

/// « Dis Siri, envoie la musique sur le PC » : la lecture continue sur le
/// PC (à la même seconde), l'iPhone devient sa télécommande.
struct SendToPCIntent: AppIntent {
    static let title: LocalizedStringResource = "Envoyer la musique sur mon PC"
    static let description = IntentDescription("Ce que joue l'iPhone continue sur ton PC (Sona pour Windows ouvert).")

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        let connect = ConnectManager.shared
        guard PlayerManager.shared.current != nil else { return .result(dialog: "Rien ne joue sur l'iPhone.") }
        await connect.sync()
        let pc = connect.chosenDevice ?? connect.devices.first { !$0.isMe && $0.kind != "iphone" }
        guard let pc, !pc.isMe else { return .result(dialog: "Aucun PC allumé : ouvre Sona pour Windows.") }
        await connect.listen(on: pc)
        return .result(dialog: "La musique continue sur \(pc.name).")
    }
}

/// Mode voiture : à lancer par une automatisation Raccourcis (« quand
/// l'iPhone se connecte au Bluetooth de la voiture »).
struct CarModeIntent: AppIntent {
    static let title: LocalizedStringResource = "Mode voiture Sona"
    static let description = IntentDescription("Ouvre l'écran voiture (gros boutons) et relance la musique.")
    static let openAppWhenRun = true

    @MainActor
    func perform() async throws -> some IntentResult {
        AppRouter.shared.pendingURL = URL(string: "encre://car?play=1")
        return .result()
    }
}

/// Reconnaître le titre qui passe autour de soi (ShazamKit).
struct RecognizeSongIntent: AppIntent {
    static let title: LocalizedStringResource = "Reconnaître un titre avec Sona"
    static let openAppWhenRun = true

    @MainActor
    func perform() async throws -> some IntentResult {
        AppRouter.shared.pendingURL = URL(string: "encre://shazam")
        return .result()
    }
}

struct PauseIntent: AppIntent {
    static let title: LocalizedStringResource = "Mettre Sona en pause"

    @MainActor
    func perform() async throws -> some IntentResult {
        // On pilote le PC : c'est lui qui se met en pause.
        if await ConnectManager.shared.intentCommand("pause") { return .result() }
        PlayerManager.shared.pause()
        return .result()
    }
}

struct ResumeIntent: AppIntent {
    static let title: LocalizedStringResource = "Reprendre la lecture Sona"

    @MainActor
    func perform() async throws -> some IntentResult {
        if await ConnectManager.shared.intentCommand("play") { return .result() }
        PlayerManager.shared.resume()
        return .result()
    }
}

struct NextTrackIntent: AppIntent {
    static let title: LocalizedStringResource = "Titre suivant sur Sona"

    @MainActor
    func perform() async throws -> some IntentResult {
        if await ConnectManager.shared.intentCommand("next") { return .result() }
        PlayerManager.shared.next()
        return .result()
    }
}

// MARK: - Piloter le PC (Raccourcis, bouton Action)

/// Commande pour l'appareil piloté (choisi dans « Appareils », ou celui
/// qui joue ailleurs), sans ouvrir l'app.
enum RemoteAction: String, AppEnum {
    case toggle, next, previous

    static let typeDisplayRepresentation: TypeDisplayRepresentation = "Commande"
    static let caseDisplayRepresentations: [RemoteAction: DisplayRepresentation] = [
        .toggle: "Lecture / pause",
        .next: "Titre suivant",
        .previous: "Titre précédent",
    ]
}

struct RemoteDeviceIntent: AppIntent {
    static let title: LocalizedStringResource = "Piloter mon PC"
    static let description = IntentDescription("Lecture/pause, suivant ou précédent sur l'appareil choisi dans « Appareils » (ton PC).")

    @Parameter(title: "Commande", default: .toggle)
    var action: RemoteAction

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        guard let device = await ConnectManager.shared.intentTarget() else {
            return .result(dialog: "Aucun appareil à piloter : choisis ton PC dans Appareils, et vérifie que Sona y est ouvert.")
        }
        guard await ConnectManager.shared.intentCommand(action.rawValue) else {
            return .result(dialog: "\(device.name) ne répond pas.")
        }
        return .result(dialog: "C'est fait sur \(device.name).")
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
        // 10 phrases au plus par app : pause, reprise et suivant restent
        // dans Raccourcis (et Siri sait déjà les faire pour l'app qui joue).
        AppShortcut(
            intent: PlayDailyTrackIntent(),
            phrases: ["Lance le titre du jour sur \(.applicationName)", "Titre du jour \(.applicationName)"],
            shortTitle: "Titre du jour",
            systemImageName: "sparkle"
        )
        AppShortcut(
            intent: PlayUserPlaylistIntent(),
            phrases: ["Mets ma playlist \(\.$playlist) sur \(.applicationName)", "Joue ma playlist \(\.$playlist) sur \(.applicationName)"],
            shortTitle: "Ma playlist",
            systemImageName: "music.note.list"
        )
        AppShortcut(
            intent: SendToPCIntent(),
            phrases: ["Envoie la musique sur le PC avec \(.applicationName)", "Mets \(.applicationName) sur le PC"],
            shortTitle: "Sur le PC",
            systemImageName: "laptopcomputer"
        )
    }
}
