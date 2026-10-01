import SwiftUI

/// « Écouter sur la TV / PS5 » : l'appli YouTube de la PS5 (ou d'une TV) est
/// pilotée à distance par le serveur (voir `app/services/tv_cast.py`). Tant
/// qu'un écran est choisi, chaque titre lancé dans Sona part sur l'écran au
/// lieu de jouer sur l'iPhone, et lecture/pause le pilote.
@MainActor
final class CastManager: ObservableObject {
    static let shared = CastManager()

    @Published private(set) var screens: [TVScreen] = []
    @Published private(set) var active: TVScreen?
    @Published private(set) var paused = false
    @Published private(set) var isSending = false
    @Published var errorMessage: String?
    /// Feuille d'association (code YouTube) : son état vit ici, pas dans la
    /// liste, pour qu'elle ne se referme pas quand la liste est reconstruite.
    @Published var showingPairing = false

    private let player = PlayerManager.shared
    private static let savedKey = "encre.cast.screen"
    private var pollTask: Task<Void, Never>?
    /// Après l'envoi d'un titre, l'écran annonce encore l'ancien un instant.
    private var ignoreStateUntil = Date.distantPast

    private init() {}

    /// Volume de l'écran (0…100), tel qu'il l'annonce.
    @Published private(set) var volume: Double?

    func loadScreens() async {
        screens = (try? await APIClient.shared.tvScreens()) ?? screens
    }

    /// Relance du suivi au démarrage de l'appli : l'écran choisi reste
    /// connecté tant qu'on ne l'a pas quitté soi-même (l'appli peut avoir été
    /// fermée par iOS pendant que YouTube continue sur la TV).
    func restore() async {
        guard active == nil, let id = UserDefaults.standard.string(forKey: Self.savedKey) else { return }
        for attempt in 0..<4 {
            await loadScreens()
            if let screen = screens.first(where: { $0.screenId == id }) {
                attach(to: screen)
                return
            }
            if !screens.isEmpty { break }  // l'écran n'est plus associé
            try? await Task.sleep(for: .seconds(2 + attempt * 2))
        }
        if screens.isEmpty == false { UserDefaults.standard.removeObject(forKey: Self.savedKey) }
    }

    func pair(code: String) async -> Bool {
        do {
            let screen = try await APIClient.shared.pairTV(code: code)
            errorMessage = nil
            await loadScreens()
            if !screens.contains(screen) { screens.insert(screen, at: 0) }
            return true
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }

    func remove(_ screen: TVScreen) async {
        if active == screen { await stop() }
        try? await APIClient.shared.unpairTV(screen.screenId)
        screens.removeAll { $0 == screen }
    }

    /// Branche le lecteur sur `screen` (sans rien envoyer à l'écran).
    private func attach(to screen: TVScreen) {
        active = screen
        UserDefaults.standard.set(screen.screenId, forKey: Self.savedKey)
        player.remotePlayback = { [weak self] track, upNext in
            Task { await self?.send(track, upNext: upNext) }
        }
        player.remoteToggle = { [weak self] in
            Task { await self?.togglePause() }
        }
        player.remoteSeek = { [weak self] seconds in
            Task { await self?.control("seek", seconds: seconds) }
        }
        startPolling()
    }

    /// Bascule la lecture sur `screen` : le titre en cours et la suite.
    func start(on screen: TVScreen) async {
        player.pause()
        attach(to: screen)
        if let current = player.current {
            await send(current, upNext: player.upNext)
        }
    }

    func stop() async {
        pollTask?.cancel()
        pollTask = nil
        if let active {
            try? await APIClient.shared.controlTV(active.screenId, action: "stop")
        }
        active = nil
        paused = false
        volume = nil
        UserDefaults.standard.removeObject(forKey: Self.savedKey)
        player.remotePlayback = nil
        player.remoteToggle = nil
        player.remoteSeek = nil
    }

    func control(_ action: String, seconds: Double? = nil) async {
        guard let active else { return }
        do {
            try await APIClient.shared.controlTV(active.screenId, action: action, seconds: seconds)
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func setVolume(_ value: Double) async {
        guard let active else { return }
        volume = value
        try? await APIClient.shared.controlTV(active.screenId, action: "volume", volume: Int(value.rounded()))
    }

    func togglePause() async {
        paused.toggle()
        player.applyCast(position: player.positionSeconds, duration: player.durationSeconds, playing: !paused)
        await control(paused ? "pause" : "play")
    }

    // MARK: Suivi de l'écran

    private func startPolling() {
        pollTask?.cancel()
        pollTask = Task { [weak self] in
            while !Task.isCancelled {
                await self?.refreshState()
                try? await Task.sleep(for: .seconds(1))
            }
        }
    }

    private func refreshState() async {
        guard let screen = active, !isSending, Date() >= ignoreStateUntil,
              let state = try? await APIClient.shared.tvState(screen.screenId),
              active == screen, !isSending, state.connected else { return }
        if let volume = state.volume { self.volume = Double(volume) }
        if let playing = state.track {
            player.followCast(source: playing.source, sourceId: playing.sourceId)
        } else if let expected = player.current?.durationSeconds, expected > 0, state.duration > 0,
                  abs(state.duration - Double(expected)) > 5 {
            return  // l'écran joue autre chose que ce titre
        }
        guard state.state != "idle" else { return }
        let playing = state.state == "playing" || state.state == "buffering"
        paused = state.state == "paused"
        player.applyCast(position: state.position, duration: state.duration, playing: playing)
    }

    private func send(_ track: Track, upNext: [Track]) async {
        guard let active else { return }
        isSending = true
        defer { isSending = false }
        do {
            try await APIClient.shared.playOnTV(active.screenId, tracks: [track] + upNext.prefix(15))
            paused = false
            errorMessage = nil
            ignoreStateUntil = Date().addingTimeInterval(3)
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

/// Volume de la TV / PS5, à la place du volume de l'iPhone pendant la
/// lecture sur un écran.
struct TVVolumeSlider: View {
    @ObservedObject private var cast = CastManager.shared
    @State private var value = 50.0
    @State private var editing = false

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: "speaker.fill").font(.system(size: 12)).foregroundStyle(Tone.tertiary)
            Slider(value: $value, in: 0...100) { editing = $0; if !$0 { Task { await cast.setVolume(value) } } }
                .tint(.white)
            Image(systemName: "speaker.wave.3.fill").font(.system(size: 12)).foregroundStyle(Tone.tertiary)
        }
        .frame(height: 30)
        .onChange(of: cast.volume) { _, new in
            if let new, !editing { value = new }
        }
        .onAppear { if let volume = cast.volume { value = volume } }
    }
}

/// Bouton du lecteur : ouvre le choix de l'écran (allumé quand on caste).
struct TVCastButton: View {
    @ObservedObject private var cast = CastManager.shared
    @State private var showing = false

    var body: some View {
        Button { showing = true } label: {
            Image(systemName: cast.active == nil ? "tv" : "tv.fill")
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(cast.active == nil ? Tone.secondary : Color.green)
                .frame(width: 44, height: 36)
        }
        .buttonStyle(.pressable(scale: 0.85))
        .sheet(isPresented: $showing) {
            TVCastSheet()
                .presentationDetents([.medium, .large])
        }
    }
}

/// Bandeau du lecteur pendant la lecture sur un écran.
struct TVCastBanner: View {
    @ObservedObject private var cast = CastManager.shared

    var body: some View {
        if let screen = cast.active {
            HStack(spacing: 10) {
                Image(systemName: "tv.fill").foregroundStyle(.green)
                VStack(alignment: .leading, spacing: 1) {
                    Text("Sur \(screen.name)").font(Typo.rowTitle).foregroundStyle(Tone.primary).lineLimit(1)
                    Text(cast.isSending ? "Envoi du titre…" : "Via l'appli YouTube")
                        .font(Typo.caption).foregroundStyle(Tone.secondary)
                }
                Spacer()
                Button("Arrêter") { Task { await cast.stop() } }
                    .font(Typo.caption)
                    .foregroundStyle(.black)
                    .padding(.horizontal, 12).padding(.vertical, 7)
                    .background(Capsule().fill(.white))
            }
            .padding(.horizontal, 14).padding(.vertical, 10)
            .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(Color.white.opacity(0.1)))
            .transition(.opacity)
        }
    }
}

/// Choix de l'écran, association par code, télécommande.
struct TVCastSheet: View {
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List { TVCastSections() }
                .navigationTitle("Écouter sur la TV")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .confirmationAction) { Button("OK") { dismiss() } }
                }
        }
        .tvPairingSheet()
    }
}

extension View {
    /// À poser sur une vue stable (hors `List`) qui contient `TVCastSections`.
    func tvPairingSheet() -> some View { modifier(TVPairingModifier()) }
}

private struct TVPairingModifier: ViewModifier {
    @ObservedObject private var cast = CastManager.shared

    func body(content: Content) -> some View {
        content.sheet(isPresented: $cast.showingPairing) { TVPairingView() }
    }
}

/// Écrans (PS5, TV) : lecture en cours et télécommande, écrans associés,
/// association d'un nouvel écran. Utilisé dans « Écouter sur » (le menu
/// de sortie du lecteur) et dans `TVCastSheet`.
struct TVCastSections: View {
    @ObservedObject private var cast = CastManager.shared
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        Group {
            if let active = cast.active {
                Section("En cours sur \(active.name)") {
                    HStack(spacing: 28) {
                        Spacer()
                        remote("backward.fill") { Task { await cast.control("previous") } }
                        remote(cast.paused ? "play.fill" : "pause.fill", size: 30) { Task { await cast.togglePause() } }
                        remote("forward.fill") { Task { await cast.control("next") } }
                        Spacer()
                    }
                    .padding(.vertical, 8)
                    Button(role: .destructive) { Task { await cast.stop() } } label: {
                        Label("Revenir sur l'iPhone", systemImage: "iphone")
                    }
                }
            }

            Section {
                ForEach(cast.screens) { screen in
                    Button {
                        Task {
                            await cast.start(on: screen)
                            if cast.errorMessage == nil { dismiss() }
                        }
                    } label: {
                        HStack(spacing: 14) {
                            Image(systemName: screen.name.localizedCaseInsensitiveContains("playstation") || screen.name.contains("PS")
                                  ? "playstation.logo" : "tv")
                                .font(.system(size: 18, weight: .semibold))
                                .frame(width: 42, height: 42)
                                .background(RoundedRectangle(cornerRadius: 11, style: .continuous).fill(Tone.surfaceStrong))
                            Text(screen.name)
                            Spacer()
                            if cast.active == screen { Image(systemName: "checkmark").foregroundStyle(.green) }
                        }
                        .foregroundStyle(Tone.primary)
                    }
                    .swipeActions {
                        Button(role: .destructive) { Task { await cast.remove(screen) } } label: {
                            Label("Oublier", systemImage: "trash")
                        }
                    }
                }
                Button { cast.showingPairing = true } label: {
                    Label("Associer une PS5 ou une TV", systemImage: "plus.circle")
                }
                if let error = cast.errorMessage {
                    Text(error).font(Typo.rowSubtitle).foregroundStyle(Tone.danger)
                }
            } header: {
                Text("PS5 et TV")
            } footer: {
                Text("Le son passe par l'appli YouTube de l'écran (avec ses pubs, sans YouTube Premium).")
            }
        }
        .task { await cast.loadScreens() }
    }

    private func remote(_ icon: String, size: CGFloat = 22, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: icon).font(.system(size: size, weight: .bold)).foregroundStyle(Tone.primary)
        }
        .buttonStyle(.borderless)
    }

}

private struct TVPairingView: View {
    @ObservedObject private var cast = CastManager.shared
    @State private var code = ""
    @State private var pairing = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Label("Sur la PS5, ouvre l'appli **YouTube**", systemImage: "1.circle")
                    Label("Va dans **Paramètres → Associer un appareil** (« Link with TV code »)", systemImage: "2.circle")
                    Label("Recopie le code affiché ci-dessous", systemImage: "3.circle")
                }
                Section {
                    TextField("123 456 789 012", text: $code)
                        .keyboardType(.numberPad)
                        .font(.system(size: 22, weight: .semibold, design: .monospaced))
                    Button {
                        Task {
                            pairing = true
                            if await cast.pair(code: code) {
                                code = ""
                                cast.showingPairing = false
                            }
                            pairing = false
                        }
                    } label: {
                        if pairing { ProgressView() } else { Text("Associer") }
                    }
                    .disabled(code.filter(\.isNumber).count < 8 || pairing)
                } footer: {
                    if let error = cast.errorMessage { Text(error).foregroundStyle(Tone.danger) }
                }
            }
            .navigationTitle("Associer un écran")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Annuler") { cast.showingPairing = false } }
            }
        }
        .presentationDetents([.medium, .large])
    }
}
