import AVFoundation
import SwiftUI

/// Mode voiture : un écran à très gros boutons (rien à viser en roulant),
/// et la musique qui repart toute seule quand l'iPhone se connecte au
/// Bluetooth de la voiture.
///
/// iOS ne réveille pas une app fermée pour un Bluetooth : le démarrage
/// automatique marche quand Sona tourne déjà (en lecture ou en pause
/// récente). Pour tous les cas, une automatisation Raccourcis « quand
/// l'iPhone se connecte à <ma voiture> → Mode voiture Sona » fait le reste.
@MainActor
final class CarMode: ObservableObject {
    static let shared = CarMode()

    /// Nom de la sortie Bluetooth de la voiture (choisie une fois, connecté).
    @Published var carName: String? { didSet { UserDefaults.standard.set(carName, forKey: "car.name") } }
    @Published var autoStart: Bool { didSet { UserDefaults.standard.set(autoStart, forKey: "car.autoStart") } }
    /// Le lecteur voiture est demandé (RootTabView l'affiche).
    @Published var requested = false

    private var observer: NSObjectProtocol?

    private init() {
        carName = UserDefaults.standard.string(forKey: "car.name")
        autoStart = UserDefaults.standard.object(forKey: "car.autoStart") as? Bool ?? true
    }

    /// La sortie audio Bluetooth (ou CarPlay) branchée en ce moment.
    static var currentCarOutput: AVAudioSessionPortDescription? {
        let kinds: Set<AVAudioSession.Port> = [.bluetoothA2DP, .bluetoothHFP, .bluetoothLE, .carAudio]
        return AVAudioSession.sharedInstance().currentRoute.outputs.first { kinds.contains($0.portType) }
    }

    func start() {
        guard observer == nil else { return }
        observer = NotificationCenter.default.addObserver(
            forName: AVAudioSession.routeChangeNotification, object: nil, queue: .main
        ) { note in
            let reason = (note.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt)
                .flatMap(AVAudioSession.RouteChangeReason.init(rawValue:))
            guard reason == .newDeviceAvailable else { return }
            Task { @MainActor in CarMode.shared.routeChanged() }
        }
    }

    private func routeChanged() {
        guard autoStart, let output = Self.currentCarOutput else { return }
        let isCar = output.portType == .carAudio || output.portName == carName
        guard isCar else { return }
        enter(play: true)
    }

    /// Ouvre l'écran voiture ; `play` : relance la musique (ou le mix du jour).
    func enter(play: Bool) {
        requested = true
        guard play else { return }
        let player = PlayerManager.shared
        if player.current != nil {
            if !player.isPlaying { player.resume() }
        } else {
            Task {
                guard let mix = try? await APIClient.shared.mixes().first(where: { !$0.tracks.isEmpty }),
                      let first = mix.tracks.first else { return }
                player.play(first, context: mix.tracks, name: mix.title)
            }
        }
    }
}

/// L'écran voiture : la pochette, le titre en gros, et des boutons géants.
struct CarModeView: View {
    @ObservedObject private var player = PlayerManager.shared
    @Environment(\.dismiss) private var dismiss
    @State private var liked = false

    var body: some View {
        GeometryReader { geo in
            let big = min(geo.size.width / 3.4, 130)
            VStack(spacing: 18) {
                HStack {
                    Button { dismiss() } label: {
                        Image(systemName: "chevron.down").font(.system(size: 22, weight: .bold))
                            .frame(width: 64, height: 64).background(Circle().fill(.white.opacity(0.12)))
                    }
                    Spacer()
                    Label("Mode voiture", systemImage: "car.fill").font(.system(size: 17, weight: .semibold)).foregroundStyle(.white.opacity(0.7))
                    Spacer()
                    Color.clear.frame(width: 64, height: 64)
                }
                Spacer(minLength: 0)
                if let track = player.current {
                    Artwork(url: track.coverURL, cornerRadius: 18)
                        .frame(width: min(geo.size.width * 0.5, 220), height: min(geo.size.width * 0.5, 220))
                        .shadow(color: .black.opacity(0.5), radius: 20, y: 8)
                    Text(track.title).font(.system(size: 30, weight: .heavy)).lineLimit(2).multilineTextAlignment(.center)
                    Text(track.artist).font(.system(size: 22, weight: .semibold)).foregroundStyle(.white.opacity(0.7)).lineLimit(1)
                } else {
                    Text("Rien en lecture").font(.system(size: 28, weight: .bold)).foregroundStyle(.white.opacity(0.7))
                }
                Spacer(minLength: 0)
                HStack(spacing: 14) {
                    bigButton("backward.fill", size: big) { player.previous() }
                    bigButton(player.isPlaying ? "pause.fill" : "play.fill", size: big * 1.15, filled: true) {
                        if player.current == nil { CarMode.shared.enter(play: true) }
                        else if player.isPlaying { player.pause() } else { player.resume() }
                    }
                    bigButton("forward.fill", size: big) { player.next() }
                }
                HStack(spacing: 14) {
                    wideButton(liked ? "heart.fill" : "heart", liked ? "Aimé" : "J'aime") { Task { await toggleLike() } }
                    wideButton("dial.medium", "Radio DJ") {
                        if let track = player.current { Task { try? await player.playDJRadio(from: track) } }
                    }
                }
            }
            .padding(20)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .foregroundStyle(.white)
        .background(Color.black.ignoresSafeArea())
        .preferredColorScheme(.dark)
        .onAppear { UIApplication.shared.isIdleTimerDisabled = true }
        .onDisappear { UIApplication.shared.isIdleTimerDisabled = false }
        .task(id: player.current?.id) { await refreshLiked() }
    }

    private func bigButton(_ icon: String, size: CGFloat, filled: Bool = false, action: @escaping () -> Void) -> some View {
        Button {
            UIImpactFeedbackGenerator(style: .heavy).impactOccurred()
            action()
        } label: {
            Image(systemName: icon)
                .font(.system(size: size * 0.36, weight: .bold))
                .foregroundStyle(filled ? .black : .white)
                .frame(width: size, height: size)
                .background(Circle().fill(filled ? Color.white : Color.white.opacity(0.14)))
        }
        .buttonStyle(.pressable(scale: 0.92))
    }

    private func wideButton(_ icon: String, _ title: String, action: @escaping () -> Void) -> some View {
        Button {
            UIImpactFeedbackGenerator(style: .medium).impactOccurred()
            action()
        } label: {
            Label(title, systemImage: icon)
                .font(.system(size: 22, weight: .bold))
                .frame(maxWidth: .infinity, minHeight: 76)
                .background(RoundedRectangle(cornerRadius: 22, style: .continuous).fill(.white.opacity(0.12)))
        }
        .buttonStyle(.pressable(scale: 0.96))
    }

    private func refreshLiked() async {
        guard let track = player.current else { liked = false; return }
        if let page = try? await APIClient.shared.library(kind: "track", limit: 200) {
            liked = page.items.contains { $0.source == track.source && $0.sourceId == track.sourceId }
        }
    }

    private func toggleLike() async {
        guard let track = player.current else { return }
        do {
            if liked {
                try await APIClient.shared.removeFromLibrary(kind: "track", source: track.source, sourceId: track.sourceId)
            } else {
                try await APIClient.shared.addToLibrary(kind: "track", source: track.source, sourceId: track.sourceId)
            }
            liked.toggle()
        } catch {}
    }
}

/// Réglages du mode voiture : la voiture (sortie Bluetooth) et le démarrage automatique.
struct CarModeSettingsView: View {
    @ObservedObject private var car = CarMode.shared
    @State private var output = CarMode.currentCarOutput?.portName

    var body: some View {
        Form {
            Section {
                Button {
                    car.enter(play: false)
                } label: {
                    Label("Ouvrir le mode voiture", systemImage: "car.fill")
                }
            }
            Section {
                LabeledContent("Ma voiture", value: car.carName ?? "Pas encore choisie")
                if let output, output != car.carName {
                    Button("Choisir « \(output) »") { car.carName = output }
                } else if output == nil {
                    Text("Connecte l'iPhone au Bluetooth de la voiture pour la choisir.")
                        .font(Typo.caption).foregroundStyle(Tone.secondary)
                }
                Toggle("Démarrer en montant dans la voiture", isOn: $car.autoStart)
            } header: {
                Text("Bluetooth")
            } footer: {
                Text("Quand l'iPhone se connecte à ta voiture, Sona ouvre le mode voiture et relance la musique — si Sona tourne déjà. Pour que ça marche à chaque fois : app Raccourcis → Automatisation → Bluetooth → ta voiture → « Mode voiture Sona ».")
            }
        }
        .navigationTitle("Mode voiture")
        .onReceive(NotificationCenter.default.publisher(for: AVAudioSession.routeChangeNotification).receive(on: DispatchQueue.main)) { _ in
            output = CarMode.currentCarOutput?.portName
        }
    }
}
