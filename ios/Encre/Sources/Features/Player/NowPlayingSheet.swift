import Foundation
import SwiftUI

/// Lecteur plein écran — variante "intégrée" du prototype (Encre.dc.html
/// §1a) : pochette, transport, paroles/file d'attente. Le geste de
/// fermeture est celui, natif, de la feuille SwiftUI (glisser vers le bas)
/// plutôt qu'une reproduction à la main de l'animation `clip-path` du
/// prototype.
struct NowPlayingSheet: View {
    @ObservedObject var player: PlayerManager
    @Environment(\.dismiss) private var dismiss

    // `Equatable` explicite : Swift ne synthétise `==` que si la conformance
    // est déclarée, même pour un enum sans valeur associée.
    private enum Mode: Equatable { case cover, lyrics, queue }
    @State private var mode: Mode = .cover
    @State private var isLiked = false

    var body: some View {
        VStack(spacing: 0) {
            Capsule()
                .fill(EncreColor.neutral400)
                .frame(width: 44, height: 5)
                .padding(.top, 10)
                .padding(.bottom, 18)

            if let track = player.current {
                Group {
                    switch mode {
                    case .cover: coverPanel(track)
                    case .lyrics: lyricsPanel
                    case .queue: queuePanel
                    }
                }
                .frame(height: 360)

                titleRow(track)
                    .padding(.horizontal, 30)
                    .padding(.top, 22)

                WaveformScrubber(trackId: track.id, progress: player.progress) { fraction in
                    player.seek(toFraction: fraction)
                }
                .frame(height: 40)
                .padding(.horizontal, 30)
                .padding(.top, 18)

                HStack {
                    Text(formatted(player.positionSeconds))
                    Spacer()
                    Text("-" + formatted(max(0, Double(track.durationSeconds ?? 0) - player.positionSeconds)))
                }
                .font(EncreFont.body(13))
                .foregroundStyle(EncreColor.neutral700)
                .monospacedDigit()
                .padding(.horizontal, 30)
                .padding(.top, 4)

                transportRow
                    .padding(.top, 26)

                volumeRow
                    .padding(.horizontal, 36)
                    .padding(.top, 26)

                modeRow
                    .padding(.top, 22)

                if let message = player.errorMessage {
                    Text(message)
                        .font(EncreFont.body(14))
                        .foregroundStyle(EncreColor.accent2_700)
                        .padding(.top, 16)
                        .padding(.horizontal, 36)
                }
            }

            Spacer(minLength: 12)
        }
        .frame(maxWidth: .infinity)
        .background(EncreColor.bg.ignoresSafeArea())
        .task(id: player.current?.id) { await refreshLikeState() }
    }

    // MARK: - Panneaux

    private func coverPanel(_ track: Track) -> some View {
        ZStack {
            // Clin d'œil au décalage CMJN du prototype : deux aplats
            // légèrement décalés derrière la pochette.
            RoundedRectangle(cornerRadius: 6, style: .continuous)
                .fill(EncreColor.accent.opacity(0.7))
                .frame(width: 300, height: 300)
                .offset(x: -6, y: 4)
                .blendMode(.multiply)
            RoundedRectangle(cornerRadius: 6, style: .continuous)
                .fill(EncreColor.accent2.opacity(0.7))
                .frame(width: 300, height: 300)
                .offset(x: 6, y: -4)
                .blendMode(.multiply)
            CoverArt(url: track.coverURL, title: track.title)
                .frame(width: 300, height: 300)
                .encreShadow(EncreShadow.lg)
        }
        .compositingGroup()
    }

    private var lyricsPanel: some View {
        VStack(spacing: 10) {
            Image(systemName: "quote.opening")
                .font(.system(size: 30))
                .foregroundStyle(EncreColor.neutral500)
            Text("Paroles indisponibles")
                .font(EncreFont.heading(20))
                .foregroundStyle(EncreColor.text)
            Text("Sona ne connaît pas les paroles de ce morceau — aucune source de paroles n'est branchée côté serveur pour l'instant.")
                .font(EncreFont.body(15))
                .foregroundStyle(EncreColor.neutral600)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 40)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var queuePanel: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                Text("À SUIVRE")
                    .font(EncreFont.heading(12))
                    .tracking(2)
                    .foregroundStyle(EncreColor.accent2_700)
                    .padding(.horizontal, 30)

                if player.upNext.isEmpty {
                    Text("Rien après ce morceau — il vient d'un résultat isolé plutôt que d'un album ou d'une liste.")
                        .font(EncreFont.bodyItalic(15))
                        .foregroundStyle(EncreColor.neutral600)
                        .padding(.horizontal, 30)
                } else {
                    VStack(spacing: 10) {
                        ForEach(player.upNext) { track in
                            Button { player.playFromUpNext(track) } label: {
                                HStack(spacing: 14) {
                                    CoverArt(url: track.coverURL, title: track.title).frame(width: 52, height: 52)
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(track.title).font(EncreFont.heading(17)).foregroundStyle(EncreColor.text).lineLimit(1)
                                        Text(track.artist).font(EncreFont.bodyItalic(14)).foregroundStyle(EncreColor.neutral700).lineLimit(1)
                                    }
                                    Spacer()
                                }
                                .padding(8)
                            }
                            .buttonStyle(.plain)
                            .glassRounded(18)
                        }
                    }
                    .padding(.horizontal, 30)
                }
            }
            .padding(.vertical, 8)
        }
    }

    // MARK: - Rangées communes

    private func titleRow(_ track: Track) -> some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text(track.title)
                    .font(EncreFont.heading(24))
                    .foregroundStyle(EncreColor.text)
                    .lineLimit(1)
                Text(track.artist)
                    .font(EncreFont.bodyItalic(18))
                    .foregroundStyle(EncreColor.spotDeep)
                    .lineLimit(1)
            }
            Spacer(minLength: 8)
            Button {
                Task { await toggleLike(track) }
            } label: {
                Image(systemName: isLiked ? "heart.fill" : "heart")
                    .font(.system(size: 20))
                    .frame(width: 44, height: 44)
            }
            .glassCircle()
            .foregroundStyle(isLiked ? EncreColor.accent2 : EncreColor.text)
        }
    }

    private var transportRow: some View {
        HStack(spacing: 40) {
            Button { player.previous() } label: {
                Image(systemName: "backward.fill").font(.system(size: 26))
            }
            .foregroundStyle(EncreColor.text)

            Button { player.togglePlayPause() } label: {
                Image(systemName: player.isLoading ? "hourglass" : (player.isPlaying ? "pause.fill" : "play.fill"))
                    .font(.system(size: 34))
                    .frame(width: 78, height: 78)
            }
            .glassCircle()
            .foregroundStyle(EncreColor.text)

            Button { player.next() } label: {
                Image(systemName: "forward.fill").font(.system(size: 26))
            }
            .foregroundStyle(EncreColor.text)
        }
    }

    private var volumeRow: some View {
        HStack(spacing: 12) {
            Image(systemName: "speaker.fill").font(.system(size: 14))
            Slider(value: $player.volume, in: 0...1)
            Image(systemName: "speaker.wave.3.fill").font(.system(size: 14))
        }
        .foregroundStyle(EncreColor.neutral700)
        .tint(EncreColor.text)
    }

    private var modeRow: some View {
        HStack(spacing: 56) {
            modeButton(.lyrics, icon: "quote.opening")
            modeButton(.queue, icon: "list.bullet")
        }
    }

    private func modeButton(_ target: Mode, icon: String) -> some View {
        Button {
            mode = (mode == target) ? .cover : target
        } label: {
            Image(systemName: icon)
                .font(.system(size: 22))
                .frame(width: 46, height: 46)
        }
        .foregroundStyle(mode == target ? EncreColor.spot : EncreColor.neutral700)
    }

    // MARK: - Bibliothèque ("aimé")

    private func refreshLikeState() async {
        guard let track = player.current else { return }
        // Pas de route API pour vérifier un seul morceau : on relit la
        // bibliothèque (déjà rapide, usage personnel) et on regarde s'il y est.
        if let page = try? await APIClient.shared.library(kind: "track", limit: 200) {
            isLiked = page.items.contains { $0.source == track.source && $0.sourceId == track.sourceId }
        }
    }

    private func toggleLike(_ track: Track) async {
        do {
            if isLiked {
                try await APIClient.shared.removeFromLibrary(kind: "track", source: track.source, sourceId: track.sourceId)
            } else {
                try await APIClient.shared.addToLibrary(kind: "track", source: track.source, sourceId: track.sourceId)
            }
            isLiked.toggle()
        } catch {
            player.errorMessage = error.localizedDescription
        }
    }

    private func formatted(_ seconds: Double) -> String {
        let total = max(0, Int(seconds))
        return String(format: "%d:%02d", total / 60, total % 60)
    }
}
