import AVFoundation
import SwiftUI

/// « Reconnaître un titre » : l'iPhone écoute 8 secondes autour de lui,
/// le serveur Sona identifie l'extrait (service de Shazam) et le retrouve
/// dans le catalogue ; le titre est rangé dans la playlist « Entendu dehors ».
///
/// Pas de ShazamKit : il exige un compte développeur Apple, que
/// l'installation re-signée n'a pas.
struct RecognizeView: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject private var player = PlayerManager.shared

    private enum Phase: Equatable {
        case listening(Int)
        case searching
        case found(title: String, artist: String, artwork: URL?)
        case notFound
        case failed(String)
    }

    private static let seconds = 8

    @State private var phase: Phase = .listening(seconds)
    @State private var match: Track?
    @State private var saved: String?
    @State private var pulse = false
    @State private var task: Task<Void, Never>?

    var body: some View {
        NavigationStack {
            VStack(spacing: 22) {
                Spacer()
                switch phase {
                case .listening(let left):
                    ZStack {
                        Circle().fill(Color.accentColor.opacity(0.18)).frame(width: 200, height: 200)
                            .scaleEffect(pulse ? 1.25 : 0.9).opacity(pulse ? 0.2 : 0.8)
                        Circle().fill(Color.accentColor).frame(width: 120, height: 120)
                        Image(systemName: "waveform").font(.system(size: 50, weight: .bold)).foregroundStyle(.white)
                    }
                    .onAppear { withAnimation(.easeInOut(duration: 1).repeatForever(autoreverses: true)) { pulse = true } }
                    Text("J'écoute… \(left) s").font(Typo.headline).monospacedDigit()
                    Text("Approche l'iPhone de la musique.").font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
                case .searching:
                    ProgressView().controlSize(.large)
                    Text("Recherche du titre…").font(Typo.headline)
                case .found(let title, let artist, let artwork):
                    AsyncImage(url: artwork ?? match?.coverURL.flatMap(URL.init(string:))) { image in
                        image.resizable().scaledToFill()
                    } placeholder: { Tone.surfaceStrong }
                        .frame(width: 220, height: 220).clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                        .shadow(color: .black.opacity(0.4), radius: 18, y: 8)
                    VStack(spacing: 4) {
                        Text(title).font(.system(size: 24, weight: .bold)).multilineTextAlignment(.center)
                        Text(artist).font(Typo.headline).foregroundStyle(Tone.secondary)
                    }
                    if let saved { Label(saved, systemImage: "checkmark.circle.fill").font(Typo.caption).foregroundStyle(.green) }
                    if let match {
                        Button {
                            player.play(match, context: [match], name: "Entendu dehors")
                            dismiss()
                        } label: {
                            Label("Écouter dans Sona", systemImage: "play.fill").font(Typo.headline)
                                .frame(maxWidth: .infinity, minHeight: 50).foregroundStyle(.black)
                                .background(Capsule().fill(.white))
                        }
                        .padding(.horizontal, 30)
                    } else {
                        Text("Introuvable dans le catalogue de Sona.").font(Typo.caption).foregroundStyle(Tone.secondary)
                    }
                case .notFound:
                    Image(systemName: "questionmark.circle").font(.system(size: 64)).foregroundStyle(Tone.secondary)
                    Text("Titre non reconnu").font(Typo.headline)
                    Text("Rapproche-toi de la musique et réessaie.").font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
                case .failed(let message):
                    Image(systemName: "exclamationmark.triangle").font(.system(size: 56)).foregroundStyle(.orange)
                    Text(message).font(Typo.rowSubtitle).foregroundStyle(Tone.secondary).multilineTextAlignment(.center).padding(.horizontal, 30)
                }
                Spacer()
                if canRetry {
                    Button("Réessayer") { start() }.font(Typo.headline).padding(.bottom, 20)
                }
            }
            .frame(maxWidth: .infinity)
            .navigationTitle("Reconnaître un titre")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Fermer") { task?.cancel(); dismiss() } } }
        }
        .onAppear { start() }
        .onDisappear { task?.cancel() }
    }

    private var canRetry: Bool {
        switch phase {
        case .listening, .searching: return false
        default: return true
        }
    }

    private func start() {
        task?.cancel()
        task = Task { await listen() }
    }

    private func listen() async {
        match = nil
        saved = nil
        phase = .listening(Self.seconds)
        guard await AVAudioApplication.requestRecordPermission() else {
            phase = .failed("Autorise le micro pour Sona dans Réglages › Sona.")
            return
        }
        // La musique de Sona joue : on la coupe, sinon Sona se reconnaît elle-même.
        if player.isPlaying { player.pause() }
        let audio: Data
        do {
            audio = try await record()
        } catch is CancellationError {
            return
        } catch {
            phase = .failed("Impossible d'enregistrer : \(error.localizedDescription)")
            return
        }
        phase = .searching
        do {
            let result = try await APIClient.shared.recognize(audio: audio)
            guard let found = result.found else { phase = .notFound; return }
            match = result.track
            phase = .found(title: found.title, artist: found.artist, artwork: found.coverURL.flatMap(URL.init(string:)))
            UINotificationFeedbackGenerator().notificationOccurred(.success)
            if let track = result.track { await save(track) }
        } catch {
            if Task.isCancelled { return }
            phase = .failed(error.localizedDescription)
        }
    }

    /// 8 secondes de micro, en WAV mono 16 kHz (environ 250 Ko).
    private func record() async throws -> Data {
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playAndRecord, mode: .default, options: [.defaultToSpeaker])
        try session.setActive(true)
        defer {
            // Retour à la lecture seule, comme le reste de l'app.
            try? session.setCategory(.playback, mode: .default, options: [])
        }
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("sona-ecoute.wav")
        let settings: [String: Any] = [
            AVFormatIDKey: kAudioFormatLinearPCM, AVSampleRateKey: 16000, AVNumberOfChannelsKey: 1,
            AVLinearPCMBitDepthKey: 16, AVLinearPCMIsFloatKey: false, AVLinearPCMIsBigEndianKey: false,
        ]
        let recorder = try AVAudioRecorder(url: url, settings: settings)
        guard recorder.record() else { throw CocoaError(.fileWriteUnknown) }
        defer { recorder.stop() }
        for left in stride(from: Self.seconds - 1, through: 0, by: -1) {
            try await Task.sleep(for: .seconds(1))
            phase = .listening(left)
        }
        recorder.stop()
        return try Data(contentsOf: url)
    }

    /// Range le titre dans la playlist « Entendu dehors » (créée au besoin).
    private func save(_ track: Track) async {
        let name = "Entendu dehors"
        do {
            if let existing = try await APIClient.shared.playlists().first(where: { $0.name == name }) {
                _ = try await APIClient.shared.addToPlaylist(id: existing.id, tracks: [track])
            } else {
                _ = try await APIClient.shared.createPlaylist(name: name, tracks: [track])
            }
            saved = "Ajouté à « \(name) »"
        } catch {}
    }
}
