import Combine
import SwiftUI
import UIKit

/// Sona Connect : un seul lecteur pour tous tes appareils, comme Spotify
/// Connect — reprendre sur l'iPhone ce qui jouait sur le PC (et l'inverse),
/// piloter l'un depuis l'autre, envoyer la musique d'un appareil à l'autre.
/// L'iPhone se signale au serveur toutes les quelques secondes
/// (`/connect/sync`) et exécute les commandes reçues.
@MainActor
final class ConnectManager: ObservableObject {
    static let shared = ConnectManager()

    @Published private(set) var devices: [ConnectDevice] = []
    @Published private(set) var session: ConnectSession?
    @Published private(set) var activeDeviceId: String?
    @Published private(set) var lastMessage: String?
    /// Appareil choisi dans « Appareils » pour le piloter (gardé d'un
    /// lancement à l'autre).
    @Published private(set) var controlId: String? = UserDefaults.standard.string(forKey: "encre.connectControl")
    /// Appareils enregistrés du compte (PC…), allumés ou non.
    @Published private(set) var saved: [SavedDevice] = []
    private var receivedAt = Date()
    private var loop: Task<Void, Never>?
    private var claimPending = false
    /// Lecture lancée par une commande reçue : pas de « prise de main ».
    private var remoteStartUntil = Date.distantPast
    /// Lecture/pause demandée à l'instant à l'autre appareil : gardée à
    /// l'écran jusqu'à sa confirmation (une réponse partie avant ne
    /// l'annule pas).
    private var expectedPaused: (target: String, value: Bool, until: Date)?
    private var cancellables = Set<AnyCancellable>()

    let deviceId: String = {
        if let saved = UserDefaults.standard.string(forKey: "encre.connectDevice") { return saved }
        let id = "iphone-" + UUID().uuidString.prefix(12).lowercased()
        UserDefaults.standard.set(id, forKey: "encre.connectDevice")
        return id
    }()

    private init() {}

    var otherDevices: [ConnectDevice] { devices.filter { !$0.isMe } }

    /// L'appareil qui joue ailleurs pendant que rien ne joue ici.
    var remoteDevice: ConnectDevice? {
        guard let activeDeviceId, activeDeviceId != deviceId, !PlayerManager.shared.isPlaying else { return nil }
        return devices.first { $0.id == activeDeviceId && $0.playing }
    }

    /// L'appareil choisi dans « Appareils », s'il est allumé.
    var chosenDevice: ConnectDevice? {
        guard let controlId else { return nil }
        return devices.first { $0.id == controlId && !$0.isMe }
    }

    /// L'appareil à piloter depuis le lecteur, tant que rien ne joue sur cet
    /// iPhone : celui choisi dans « Appareils », sinon celui de la dernière
    /// lecture du compte, s'il est connecté — qu'il joue ou soit en pause.
    var remoteTarget: ConnectDevice? {
        guard !PlayerManager.shared.isPlaying else { return nil }
        if let chosen = chosenDevice { return chosen }
        guard let session, session.deviceId != deviceId else { return nil }
        return devices.first { $0.id == session.deviceId && !$0.isMe }
    }

    /// Ce que joue un autre appareil : titre, pause, position (qui avance).
    struct RemoteNow {
        var track: Track?
        var paused: Bool
        var position: Double
    }

    func now(on device: ConnectDevice) -> RemoteNow {
        if let session, session.deviceId == device.id {
            return RemoteNow(track: session.track, paused: session.paused, position: remotePosition)
        }
        var position = (device.position ?? 0) + (device.playing ? Date().timeIntervalSince(receivedAt) : 0)
        if let duration = device.track?.durationSeconds, duration > 0 { position = min(position, Double(duration)) }
        return RemoteNow(track: device.track, paused: !device.playing, position: position)
    }

    /// Position de la lecture distante (elle avance entre deux relevés).
    var remotePosition: Double {
        guard let session else { return 0 }
        return session.position + (session.paused ? 0 : Date().timeIntervalSince(receivedAt))
    }

    func start() {
        guard loop == nil else { return }
        // Lecture lancée ici à la main : les autres appareils se mettent en pause.
        PlayerManager.shared.$isPlaying
            .removeDuplicates()
            .dropFirst()
            .sink { [weak self] playing in
                guard let self else { return }
                // Lecture lancée ici à la main : on ne pilote plus un autre appareil.
                if playing, Date() > self.remoteStartUntil, self.controlId != nil { self.setControl(nil) }
                RemoteFlag.shared.update(!playing && self.remoteTarget != nil)
                // Lecture/pause ici : les autres appareils le savent tout de suite.
                if playing, Date() > self.remoteStartUntil { self.claimPending = true }
                self.syncSoon()
            }
            .store(in: &cancellables)
        PlayerManager.shared.$current
            .map { $0?.id }
            .removeDuplicates()
            .dropFirst()
            .sink { [weak self] _ in self?.syncSoon() }
            .store(in: &cancellables)
        // Connexion qui attend les nouvelles : le serveur répond dès qu'une
        // commande arrive ou que la lecture change sur un autre appareil.
        loop = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                let active = UIApplication.shared.applicationState == .active
                let listening = active || PlayerManager.shared.isPlaying || self.remoteTarget != nil
                if listening {
                    if !(await self.sync(wait: 25)) { try? await Task.sleep(for: .seconds(3)) }
                } else {
                    await self.sync()
                    try? await Task.sleep(for: .seconds(20))
                }
            }
        }
    }

    func syncSoon() {
        Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(150))
            await self?.sync()
        }
    }

    /// Relevé (et, avec `wait`, attente d'une nouveauté côté serveur).
    /// Faux si le serveur n'a pas répondu.
    @discardableResult
    func sync(wait: Double = 0) async -> Bool {
        let player = PlayerManager.shared
        let claim = claimPending && player.isPlaying
        if claim { claimPending = false }
        guard let response = try? await APIClient.shared.connectSync(
            deviceId: deviceId, name: UIDevice.current.name, state: player.connectPlayback, claim: claim, wait: wait
        ) else { return false }
        receivedAt = Date()
        var freshDevices = response.devices
        var fresh = response.session
        if let expected = expectedPaused {
            let index = freshDevices.firstIndex { $0.id == expected.target }
            let confirmed = index.map { freshDevices[$0].playing == !expected.value }
                ?? (fresh?.paused == expected.value)
            if Date() > expected.until || confirmed {
                expectedPaused = nil
            } else {
                if var current = fresh, current.deviceId == expected.target {
                    current.paused = expected.value
                    fresh = current
                }
                if let index { freshDevices[index].playing = !expected.value }
            }
        }
        devices = freshDevices
        session = fresh
        activeDeviceId = response.activeDeviceId
        for command in response.commands { run(command) }
        RemoteFlag.shared.update(remoteTarget != nil)
        return true
    }

    private func run(_ command: ConnectCommand) {
        let player = PlayerManager.shared
        switch command.action {
        case "play":
            remoteStartUntil = Date().addingTimeInterval(3)
            player.resume()
        case "pause":
            if player.isPlaying {
                player.pause()
                if let from = command.from { show("Lecture passée sur \(from)") }
            }
        case "toggle":
            remoteStartUntil = Date().addingTimeInterval(3)
            player.togglePlayPause()
        case "next":
            player.next()
        case "previous":
            player.previous()
        case "seek":
            if let position = command.position { player.seek(toSeconds: position) }
        case "volume":
            if let volume = command.volume { SystemVolume.set(volume) }
        case "transfer":
            guard let queue = command.queue, !queue.isEmpty else { return }
            remoteStartUntil = Date().addingTimeInterval(3)
            player.playTransferred(
                queue: queue, index: min(command.index ?? 0, queue.count - 1),
                position: command.position ?? 0, name: command.name
            )
            if let from = command.from { show("Musique reprise depuis \(from)") }
        default:
            break
        }
    }

    private func show(_ message: String) {
        lastMessage = message
        Task { [weak self] in
            try? await Task.sleep(for: .seconds(3))
            if self?.lastMessage == message { self?.lastMessage = nil }
        }
    }

    // MARK: Actions

    /// Choisit l'appareil à piloter (nil : plus aucun).
    func setControl(_ id: String?) {
        controlId = id
        UserDefaults.standard.set(id, forKey: "encre.connectControl")
        RemoteFlag.shared.update(remoteTarget != nil)
    }

    /// Choisi dans « Appareils » : l'iPhone devient sa télécommande (sa
    /// propre musique s'arrête ; « Envoyer » la fait continuer dessus).
    func control(_ device: ConnectDevice) {
        if PlayerManager.shared.isPlaying {
            remoteStartUntil = Date().addingTimeInterval(1)
            PlayerManager.shared.pause()
        }
        setControl(device.id)
        syncSoon()
    }

    /// « Écouter sur cet iPhone » depuis la télécommande d'un appareil.
    func listenHere(from device: ConnectDevice) {
        setControl(nil)
        if session?.deviceId == device.id {
            resumeHere()
            return
        }
        let playing = self.now(on: device)
        guard let track = playing.track else { return }
        PlayerManager.shared.playTransferred(queue: [track], index: 0, position: playing.position, name: nil)
        Task { try? await APIClient.shared.connectCommand(from: deviceId, to: device.id, action: "pause") }
    }

    // MARK: Appareils enregistrés

    func refreshSaved() async {
        if let list = try? await APIClient.shared.connectSaved() { saved = list }
    }

    func save(_ device: ConnectDevice) async throws {
        let item = try await APIClient.shared.connectSave(deviceId: device.id)
        saved = saved.filter { $0.id != item.id } + [item]
    }

    func forget(_ id: String) async {
        try? await APIClient.shared.connectForget(deviceId: id)
        saved.removeAll { $0.id == id }
        if controlId == id { setControl(nil) }
    }

    /// Reprend ici la dernière lecture du compte (sur un autre appareil).
    func resumeHere() {
        guard let session else { return }
        PlayerManager.shared.playTransferred(
            queue: session.queue, index: session.index, position: remotePosition, name: session.name
        )
    }

    /// « Écouter sur… » : la musique continue sur cet appareil, à la même seconde.
    func listen(on device: ConnectDevice) async {
        if device.isMe {
            setControl(nil)
            resumeHere()
            return
        }
        await sync()  // position à jour avant l'envoi
        // La télécommande s'affiche tout de suite, sans attendre que l'autre
        // appareil ait repris : le serveur confirme juste après.
        if let playback = PlayerManager.shared.connectPlayback, playback.queue.indices.contains(playback.index) {
            session = ConnectSession(
                deviceId: device.id, deviceName: device.name, queue: playback.queue, index: playback.index,
                name: playback.name, track: playback.queue[playback.index], position: playback.position,
                paused: false, ageSeconds: 0
            )
            receivedAt = Date()
        }
        try? await APIClient.shared.connectCommand(from: deviceId, to: device.id, action: "transfer")
        remoteStartUntil = Date().addingTimeInterval(3)
        PlayerManager.shared.pause()
        RemoteFlag.shared.update(remoteTarget != nil)
        show("Musique envoyée sur \(device.name)")
    }

    /// Télécommande de l'appareil qui joue ailleurs.
    func remote(_ action: String, position: Double? = nil, volume: Double? = nil) {
        guard let target = remoteTarget else { return }
        var action = action
        // « lecture » ou « pause » explicite (pas « bascule ») : plusieurs
        // appuis rapprochés ne s'annulent pas.
        if action == "toggle" { action = now(on: target).paused ? "play" : "pause" }
        // Réponse immédiate à l'écran, confirmée par l'autre appareil.
        if action == "play" || action == "pause" {
            let paused = action == "pause"
            let current = now(on: target)
            if var session, session.deviceId == target.id {
                session.position = current.position
                session.paused = paused
                self.session = session
            }
            if let index = devices.firstIndex(where: { $0.id == target.id }) {
                devices[index].position = current.position
                devices[index].playing = !paused
            }
            receivedAt = Date()
            expectedPaused = (target.id, paused, Date().addingTimeInterval(4))
        }
        let command = action
        Task {
            try? await APIClient.shared.connectCommand(
                from: deviceId, to: target.id, action: command, position: position, volume: volume
            )
            syncSoon()
        }
    }
}

/// « Un autre appareil est à piloter » : un simple booléen, publié
/// seulement quand il change — la barre d'onglets l'observe sans se
/// redessiner à chaque relevé de Sona Connect.
@MainActor
final class RemoteFlag: ObservableObject {
    static let shared = RemoteFlag()
    @Published private(set) var isRemote = false

    func update(_ value: Bool) {
        if value != isRemote { isRemote = value }
    }
}

// MARK: - Interface

/// Tes autres appareils Sona (PC, autre iPhone) : « Écouter dessus ».
/// Dans « Écouter sur » (menu de sortie du lecteur) et `ConnectSheet`.
struct ConnectDevicesSection: View {
    var includeSelf = false
    @ObservedObject private var connect = ConnectManager.shared
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        let devices = connect.devices.filter { includeSelf || !$0.isMe }
        Section {
            ForEach(devices) { device in
                Button {
                    Task {
                        await connect.listen(on: device)
                        dismiss()
                    }
                } label: {
                    row(device)
                }
                .disabled(device.isMe && connect.remoteTarget == nil)
            }
            if devices.isEmpty {
                Label("Aucun autre appareil connecté", systemImage: "laptopcomputer.slash")
                    .font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
            }
        } header: {
            Text("Sona Connect")
        } footer: {
            Text(connect.otherDevices.isEmpty
                 ? "Ouvre Sona sur ton ordinateur (soonaa.vercel.app) : il apparaîtra ici."
                 : "La musique continue sur l'appareil choisi, à la même seconde.")
        }
        .task { await connect.sync() }
    }

    private func row(_ device: ConnectDevice) -> some View {
        let isTarget = connect.remoteTarget?.id == device.id
        return HStack(spacing: 14) {
            Image(systemName: device.kind == "iphone" ? "iphone" : "laptopcomputer")
                .font(.system(size: 19, weight: .semibold))
                .foregroundStyle(device.playing || isTarget ? .white : Tone.secondary)
                .frame(width: 42, height: 42)
                .background(RoundedRectangle(cornerRadius: 11, style: .continuous)
                    .fill(device.playing || isTarget ? Color.accentColor : Tone.surfaceStrong))
            VStack(alignment: .leading, spacing: 2) {
                Text(device.isMe ? "Cet iPhone" : device.name).font(Typo.rowTitle).foregroundStyle(Tone.primary)
                if device.playing, let track = device.track {
                    HStack(spacing: 6) {
                        EqualizerBars(isAnimating: true).frame(width: 12, height: 10)
                        Text(track.title).lineLimit(1)
                    }
                    .font(Typo.caption).foregroundStyle(Color.accentColor)
                } else {
                    Text(isTarget ? "En pause · piloté depuis cet iPhone" : "Connecté")
                        .font(Typo.caption).foregroundStyle(Tone.secondary)
                }
            }
            Spacer()
            if isTarget {
                Image(systemName: "checkmark").foregroundStyle(Color.accentColor)
            } else if !device.playing {
                Text(device.isMe ? "Écouter ici" : "Écouter dessus")
                    .font(Typo.caption).foregroundStyle(Color.accentColor)
            }
        }
    }
}

struct ConnectSheet: View {
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List { ConnectDevicesSection(includeSelf: true) }
                .navigationTitle("Écouter sur")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("OK") { dismiss() } } }
        }
    }
}

// MARK: - Télécommande dans le lecteur

/// Lecteur plein écran quand la musique joue (ou est en pause) sur un autre
/// appareil : pochette, titre, progression, commandes et volume de cet
/// appareil — comme si elle jouait ici.
struct RemotePlayerView: View {
    var onClose: () -> Void
    @ObservedObject private var connect = ConnectManager.shared
    @State private var palette: [Color] = ArtworkPalette.fallback
    @State private var volume: Double?
    @State private var seeking: Double?

    var body: some View {
        ZStack {
            LivingBackground(colors: palette, animated: !(connect.remoteTarget.map { connect.now(on: $0).paused } ?? true))
                .id(palette)
            if let device = connect.remoteTarget {
                let now = connect.now(on: device)
                VStack(spacing: 0) {
                    HStack {
                        Button(action: onClose) {
                            Image(systemName: "chevron.down")
                                .font(.system(size: 17, weight: .semibold))
                                .foregroundStyle(Tone.primary)
                                .frame(width: 40, height: 40)
                        }
                        .buttonStyle(.pressable(scale: 0.85))
                        Spacer()
                        Label("Lecture sur \(device.name)", systemImage: device.kind == "iphone" ? "iphone" : "laptopcomputer")
                            .font(Typo.caption).foregroundStyle(Tone.primary)
                            .padding(.horizontal, 12).padding(.vertical, 6)
                            .background(Capsule().fill(Color.white.opacity(0.15)))
                        Spacer()
                        Color.clear.frame(width: 40, height: 40)
                    }
                    .padding(.top, 8)

                    Spacer(minLength: 16)
                    if let track = now.track {
                        Artwork(url: track.coverURL, cornerRadius: 14)
                            .aspectRatio(1, contentMode: .fit)
                            .scaleEffect(now.paused ? 0.82 : 1)
                            .shadow(color: .black.opacity(0.4), radius: 26, y: 16)
                            .animation(Motion.bouncy, value: now.paused)
                            .id(track.id)
                        Spacer(minLength: 24)

                        VStack(alignment: .leading, spacing: 3) {
                            Text(track.title).font(.system(size: 22, weight: .bold)).foregroundStyle(Tone.primary).lineLimit(1)
                            Text(track.artist).font(.system(size: 19)).foregroundStyle(Tone.secondary).lineLimit(1)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.bottom, 18)

                        progress(device, track: track)
                    } else {
                        VStack(spacing: 10) {
                            Image(systemName: device.kind == "iphone" ? "iphone" : "laptopcomputer")
                                .font(.system(size: 54, weight: .light)).foregroundStyle(Tone.tertiary)
                            Text("Rien en lecture sur \(device.name)").font(Typo.headline).foregroundStyle(Tone.primary)
                            Text("Envoie-lui ta musique, ou lance un titre dessus.")
                                .font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
                        }
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: .infinity)
                        Spacer(minLength: 24)
                    }

                    HStack {
                        Spacer()
                        control("backward.fill", 30) { connect.remote("previous") }
                        Spacer()
                        control(now.paused ? "play.fill" : "pause.fill", 46) { connect.remote("toggle") }
                        Spacer()
                        control("forward.fill", 30) { connect.remote("next") }
                        Spacer()
                    }
                    .disabled(now.track == nil)
                    .opacity(now.track == nil ? 0.35 : 1)
                    .padding(.vertical, 20)

                    HStack(spacing: 12) {
                        Image(systemName: "speaker.fill").font(.system(size: 12)).foregroundStyle(Tone.tertiary)
                        Slider(value: Binding(
                            get: { volume ?? device.volume ?? 1 },
                            set: { volume = $0 }
                        ), in: 0...1) { editing in
                            if !editing, let volume { connect.remote("volume", volume: volume) }
                        }
                        .tint(.white)
                        Image(systemName: "speaker.wave.3.fill").font(.system(size: 12)).foregroundStyle(Tone.tertiary)
                    }

                    HStack {
                        if now.track != nil {
                            Button {
                                connect.listenHere(from: device)
                            } label: {
                                Label("Écouter sur cet iPhone", systemImage: "iphone")
                                    .font(Typo.rowTitle).foregroundStyle(.black)
                                    .padding(.horizontal, 16).frame(height: 38)
                                    .background(Capsule().fill(.white))
                            }
                            .buttonStyle(.pressable(scale: 0.95))
                        } else if let session = connect.session, session.deviceId != device.id {
                            Button {
                                Task { await connect.listen(on: device) }
                            } label: {
                                Label("Envoyer « \(session.track.title) »", systemImage: "laptopcomputer.and.arrow.down")
                                    .font(Typo.rowTitle).foregroundStyle(.black).lineLimit(1)
                                    .padding(.horizontal, 16).frame(height: 38)
                                    .background(Capsule().fill(.white))
                            }
                            .buttonStyle(.pressable(scale: 0.95))
                        }
                        Spacer()
                        OutputButton()
                    }
                    .padding(.top, 18)
                }
                .padding(.horizontal, 26)
                .padding(.bottom, 8)
                .task(id: now.track?.coverURL) {
                    palette = await ArtworkPalette.colors(for: now.track?.coverURL)
                }
            }
        }
        .animation(.easeInOut(duration: 0.9), value: palette)
    }

    private func progress(_ device: ConnectDevice, track: Track) -> some View {
        let duration = Double(track.durationSeconds ?? 0)
        return TimelineView(.periodic(from: .now, by: 0.5)) { _ in
            let position = seeking ?? min(connect.now(on: device).position, duration)
            VStack(spacing: 6) {
                Slider(value: Binding(
                    get: { duration > 0 ? position / duration : 0 },
                    set: { seeking = $0 * duration }
                )) { editing in
                    if !editing, let seeking {
                        connect.remote("seek", position: seeking)
                        self.seeking = nil
                    }
                }
                .tint(.white)
                .disabled(duration <= 0)
                HStack {
                    Text(Self.time(position))
                    Spacer()
                    Text("-" + Self.time(max(0, duration - position)))
                }
                .font(Typo.caption).monospacedDigit().foregroundStyle(Tone.tertiary)
            }
        }
    }

    private func control(_ icon: String, _ size: CGFloat, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: icon)
                .font(.system(size: size))
                .contentTransition(.symbolEffect(.replace.downUp))
                .foregroundStyle(Tone.primary)
                .frame(width: 80, height: 80)
        }
        .buttonStyle(.pressable(scale: 0.82))
        .sensoryFeedback(.impact(weight: .light), trigger: icon)
    }

    static func time(_ seconds: Double) -> String {
        let s = max(0, Int(seconds))
        return String(format: "%d:%02d", s / 60, s % 60)
    }
}

/// Mini-lecteur quand la musique est sur un autre appareil.
struct RemoteMiniPlayer: View {
    var onExpand: () -> Void
    @ObservedObject private var connect = ConnectManager.shared

    var body: some View {
        if let device = connect.remoteTarget {
            let now = connect.now(on: device)
            HStack(spacing: 12) {
                Artwork(url: now.track?.coverURL, cornerRadius: 7).frame(width: 34, height: 34)
                VStack(alignment: .leading, spacing: 1) {
                    Text(now.track?.title ?? "Rien en lecture").font(Typo.rowTitle).foregroundStyle(Tone.primary).lineLimit(1)
                    Label("Sur \(device.name)", systemImage: device.kind == "iphone" ? "iphone" : "laptopcomputer")
                        .font(.system(size: 12, weight: .semibold)).foregroundStyle(Color.accentColor).lineLimit(1)
                }
                Spacer(minLength: 4)
                Button {
                    connect.remote("toggle")
                } label: {
                    Image(systemName: now.paused ? "play.fill" : "pause.fill")
                        .contentTransition(.symbolEffect(.replace.downUp))
                        .font(.system(size: 19, weight: .semibold))
                        .foregroundStyle(Tone.primary)
                        .frame(width: 40, height: 40)
                }
                .buttonStyle(.pressable(scale: 0.85))
                Button {
                    connect.remote("next")
                } label: {
                    Image(systemName: "forward.fill")
                        .font(.system(size: 18, weight: .semibold))
                        .foregroundStyle(Tone.primary)
                        .frame(width: 36, height: 40)
                }
                .buttonStyle(.pressable(scale: 0.85))
            }
            .padding(.horizontal, 8)
            .frame(maxHeight: .infinity)
            .contentShape(Rectangle())
            .onTapGesture(perform: onExpand)
        }
    }
}

/// Accueil : reprendre ici ce qui jouait sur un autre appareil.
struct ConnectResumeBanner: View {
    @ObservedObject private var connect = ConnectManager.shared
    @ObservedObject private var player = PlayerManager.shared
    @State private var showing = false

    var body: some View {
        if let session = connect.session, session.deviceId != connect.deviceId, !player.isPlaying,
           session.ageSeconds < 6 * 3600 {
            HStack(spacing: 14) {
                Artwork(url: session.track.coverURL, cornerRadius: 10).frame(width: 58, height: 58)
                VStack(alignment: .leading, spacing: 2) {
                    Text(session.paused ? "REPRENDRE DEPUIS \(session.deviceName.uppercased())" : "EN LECTURE SUR \(session.deviceName.uppercased())")
                        .font(.system(size: 11, weight: .bold)).tracking(0.8).foregroundStyle(Color.accentColor).lineLimit(1)
                    Text(session.track.title).font(Typo.headline).foregroundStyle(Tone.primary).lineLimit(1)
                    Text(session.track.artist).font(Typo.rowSubtitle).foregroundStyle(Tone.secondary).lineLimit(1)
                }
                Spacer(minLength: 0)
                Button {
                    connect.resumeHere()
                } label: {
                    Label("Ici", systemImage: "play.fill")
                        .font(Typo.rowTitle).foregroundStyle(.black)
                        .padding(.horizontal, 14).frame(height: 36)
                        .background(Capsule().fill(.white))
                }
                .buttonStyle(.pressable(scale: 0.95))
            }
            .padding(12)
            .background(
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .fill(LinearGradient(colors: [Color.accentColor.opacity(0.35), Tone.surfaceStrong],
                                         startPoint: .topLeading, endPoint: .bottomTrailing))
            )
            .contentShape(Rectangle())
            .onTapGesture { showing = true }
            .sheet(isPresented: $showing) { ConnectSheet().presentationDetents([.medium, .large]) }
            .padding(.horizontal, 20)
            .transition(.move(edge: .top).combined(with: .opacity))
        }
    }
}

/// Message bref (« Lecture passée sur Chrome · Mac »).
struct ConnectToast: View {
    @ObservedObject private var connect = ConnectManager.shared

    var body: some View {
        ZStack {
            if let message = connect.lastMessage {
                toast(message)
            }
        }
        .animation(Motion.smooth, value: connect.lastMessage)
    }

    private func toast(_ message: String) -> some View {
        Label(message, systemImage: "hifispeaker.and.appletv.fill")
            .font(Typo.rowTitle)
            .foregroundStyle(.black)
            .padding(.horizontal, 16).padding(.vertical, 10)
            .background(Capsule().fill(.white))
            .shadow(color: .black.opacity(0.3), radius: 12, y: 4)
            .transition(.move(edge: .top).combined(with: .opacity))
    }
}
