import ShazamKit
import SwiftUI

/// « Reconnaître un titre » : Sona écoute quelques secondes autour de toi
/// (ShazamKit), retrouve le titre dans son catalogue, et le range dans la
/// playlist « Entendu dehors ».
///
/// ShazamKit doit être activé pour l'identifiant de l'app chez Apple : une
/// installation re-signée sans compte développeur peut ne pas y avoir
/// droit — l'écran le dit alors clairement.
struct RecognizeView: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject private var player = PlayerManager.shared

    private enum Phase: Equatable {
        case listening
        case found(title: String, artist: String, artwork: URL?)
        case notFound
        case failed(String)
    }

    @State private var phase: Phase = .listening
    @State private var match: Track?
    @State private var saved: String?
    @State private var session: SHManagedSession?
    @State private var pulse = false

    var body: some View {
        NavigationStack {
            VStack(spacing: 22) {
                Spacer()
                switch phase {
                case .listening:
                    ZStack {
                        Circle().fill(Color.accentColor.opacity(0.18)).frame(width: 200, height: 200)
                            .scaleEffect(pulse ? 1.25 : 0.9).opacity(pulse ? 0.2 : 0.8)
                        Circle().fill(Color.accentColor).frame(width: 120, height: 120)
                        Image(systemName: "shazam.logo.fill").font(.system(size: 56)).foregroundStyle(.white)
                    }
                    .onAppear { withAnimation(.easeInOut(duration: 1).repeatForever(autoreverses: true)) { pulse = true } }
                    Text("J'écoute…").font(Typo.headline)
                    Text("Approche l'iPhone de la musique.").font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
                case .found(let title, let artist, let artwork):
                    AsyncImage(url: artwork) { image in image.resizable().scaledToFill() } placeholder: { Tone.surfaceStrong }
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
                if phase != .listening {
                    Button("Réessayer") { Task { await listen() } }.font(Typo.headline).padding(.bottom, 20)
                }
            }
            .frame(maxWidth: .infinity)
            .navigationTitle("Reconnaître un titre")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Fermer") { session?.cancel(); dismiss() } } }
        }
        .task { await listen() }
        .onDisappear { session?.cancel() }
    }

    private func listen() async {
        phase = .listening
        match = nil
        saved = nil
        let session = SHManagedSession()
        self.session = session
        // Si la musique de Sona joue, on la coupe : sinon Sona se reconnaît elle-même.
        if player.isPlaying { player.pause() }
        switch await session.result() {
        case .match(let found):
            guard let item = found.mediaItems.first else { phase = .notFound; return }
            let title = item.title ?? "Titre inconnu"
            let artist = item.artist ?? ""
            phase = .found(title: title, artist: artist, artwork: item.artworkURL)
            UINotificationFeedbackGenerator().notificationOccurred(.success)
            await findInSona(title: title, artist: artist)
        case .noMatch:
            phase = .notFound
        case .error(let error, _):
            let code = (error as NSError).code
            phase = .failed(code == SHError.Code.matchAttemptFailed.rawValue
                ? "La reconnaissance n'est pas disponible pour cette installation de Sona (ShazamKit n'est pas activé pour son identifiant)."
                : "Impossible d'écouter : autorise le micro pour Sona dans Réglages. (\(error.localizedDescription))")
        }
    }

    /// Retrouve le titre dans Sona et le range dans « Entendu dehors ».
    private func findInSona(title: String, artist: String) async {
        guard let track = try? await APIClient.shared.search(query: "\(title) \(artist)").tracks.first else { return }
        match = track
        do {
            let name = "Entendu dehors"
            let existing = try await APIClient.shared.playlists().first { $0.name == name }
            if let existing {
                _ = try await APIClient.shared.addToPlaylist(id: existing.id, tracks: [track])
            } else {
                _ = try await APIClient.shared.createPlaylist(name: name, tracks: [track])
            }
            saved = "Ajouté à « \(name) »"
        } catch {}
    }
}
