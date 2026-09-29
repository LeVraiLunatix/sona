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
    private var receivedAt = Date()
    private var loop: Task<Void, Never>?
    private var claimPending = false
    /// Lecture lancée par une commande reçue : pas de « prise de main ».
    private var remoteStartUntil = Date.distantPast
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
                guard let self, playing, Date() > self.remoteStartUntil else { return }
                self.claimPending = true
                self.syncSoon()
            }
            .store(in: &cancellables)
        loop = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                await self.sync()
                let busy = PlayerManager.shared.isPlaying || self.remoteDevice != nil
                let active = UIApplication.shared.applicationState == .active
                try? await Task.sleep(for: .seconds(busy ? (active ? 2.5 : 5) : (active ? 5 : 20)))
            }
        }
    }

    func syncSoon() {
        Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(400))
            await self?.sync()
        }
    }

    func sync() async {
        let player = PlayerManager.shared
        let claim = claimPending && player.isPlaying
        if claim { claimPending = false }
        guard let response = try? await APIClient.shared.connectSync(
            deviceId: deviceId, name: UIDevice.current.name, state: player.connectPlayback, claim: claim
        ) else { return }
        receivedAt = Date()
        devices = response.devices
        session = response.session
        activeDeviceId = response.activeDeviceId
        for command in response.commands { run(command) }
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
        case "transfer":
            guard let queue = command.queue, !queue.isEmpty else { return }
            remoteStartUntil = Date().addingTimeInterval(3)
            player.playTransferred(
                queue: queue, index: min(command.index ?? 0, queue.count - 1),
                position: command.position ?? 0, name: command.name
            )
            if let from = command.from { show("Musique reprise depuis \(from)") }
        default:
            break  // volume : celui de l'iPhone ne se règle pas à distance
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
            resumeHere()
            return
        }
        await sync()  // position à jour avant l'envoi
        try? await APIClient.shared.connectCommand(from: deviceId, to: device.id, action: "transfer")
        PlayerManager.shared.pause()
        show("Musique envoyée sur \(device.name)")
        syncSoon()
    }

    /// Télécommande de l'appareil qui joue ailleurs.
    func remote(_ action: String, position: Double? = nil) {
        guard let target = remoteDevice else { return }
        Task {
            try? await APIClient.shared.connectCommand(from: deviceId, to: target.id, action: action, position: position)
            syncSoon()
        }
    }
}

// MARK: - Interface

/// Bouton du lecteur plein écran : tes appareils.
struct ConnectButton: View {
    @ObservedObject private var connect = ConnectManager.shared
    @State private var showing = false

    var body: some View {
        Button { showing = true } label: {
            Image(systemName: connect.otherDevices.isEmpty ? "hifispeaker.and.appletv" : "hifispeaker.and.appletv.fill")
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(connect.otherDevices.isEmpty ? Tone.secondary : Color.accentColor)
                .frame(width: 44, height: 36)
        }
        .buttonStyle(.pressable(scale: 0.85))
        .accessibilityLabel("Sona Connect")
        .sheet(isPresented: $showing) {
            ConnectSheet().presentationDetents([.medium, .large])
        }
    }
}

struct ConnectSheet: View {
    @ObservedObject private var connect = ConnectManager.shared
    @ObservedObject private var player = PlayerManager.shared
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                if let remote = connect.remoteDevice, let session = connect.session {
                    Section("En lecture sur \(remote.name)") {
                        RemoteControls(session: session)
                    }
                }
                Section {
                    ForEach(connect.devices) { device in
                        Button {
                            Task {
                                await connect.listen(on: device)
                                dismiss()
                            }
                        } label: {
                            deviceRow(device)
                        }
                        .disabled(device.isMe && connect.remoteDevice == nil && connect.session?.deviceId == connect.deviceId)
                    }
                } header: {
                    Text("Écouter sur")
                } footer: {
                    Text(connect.otherDevices.isEmpty
                         ? "Ouvre Sona sur ton ordinateur (soonaa.vercel.app) : il apparaîtra ici."
                         : "La musique continue sur l'appareil choisi, à la même seconde.")
                }
            }
            .navigationTitle("Sona Connect")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("OK") { dismiss() } } }
            .task {
                while !Task.isCancelled {
                    await connect.sync()
                    try? await Task.sleep(for: .seconds(2))
                }
            }
        }
    }

    private func deviceRow(_ device: ConnectDevice) -> some View {
        HStack(spacing: 14) {
            Image(systemName: device.kind == "iphone" ? "iphone" : "laptopcomputer")
                .font(.system(size: 20, weight: .semibold))
                .foregroundStyle(device.playing ? .white : Tone.secondary)
                .frame(width: 42, height: 42)
                .background(RoundedRectangle(cornerRadius: 11, style: .continuous)
                    .fill(device.playing ? Color.accentColor : Tone.surfaceStrong))
            VStack(alignment: .leading, spacing: 2) {
                Text(device.isMe ? "Cet iPhone" : device.name).font(Typo.rowTitle).foregroundStyle(Tone.primary)
                if device.playing, let track = device.track {
                    HStack(spacing: 6) {
                        EqualizerBars(isAnimating: true).frame(width: 12, height: 10)
                        Text(track.title).lineLimit(1)
                    }
                    .font(Typo.caption).foregroundStyle(Color.accentColor)
                } else {
                    Text(device.isMe ? device.name : "Connecté").font(Typo.caption).foregroundStyle(Tone.secondary)
                }
            }
            Spacer()
            if !device.playing {
                Text(device.isMe ? "Écouter ici" : "Écouter dessus")
                    .font(Typo.caption).foregroundStyle(Color.accentColor)
            }
        }
    }
}

/// Télécommande de la lecture sur un autre appareil.
private struct RemoteControls: View {
    let session: ConnectSession
    @ObservedObject private var connect = ConnectManager.shared

    var body: some View {
        VStack(spacing: 14) {
            HStack(spacing: 12) {
                Artwork(url: session.track.coverURL, cornerRadius: 8).frame(width: 54, height: 54)
                VStack(alignment: .leading, spacing: 2) {
                    Text(session.track.title).font(Typo.rowTitle).foregroundStyle(Tone.primary).lineLimit(1)
                    Text(session.track.artist).font(Typo.rowSubtitle).foregroundStyle(Tone.secondary).lineLimit(1)
                }
                Spacer()
            }
            HStack(spacing: 36) {
                button("backward.fill", "previous")
                button("pause.fill", "toggle", size: 30)
                button("forward.fill", "next")
            }
        }
        .padding(.vertical, 6)
    }

    private func button(_ icon: String, _ action: String, size: CGFloat = 22) -> some View {
        Button { connect.remote(action) } label: {
            Image(systemName: icon).font(.system(size: size, weight: .semibold)).foregroundStyle(Tone.primary)
        }
        .buttonStyle(.plain)
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
