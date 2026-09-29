import SwiftUI

/// Derniers mixes reçus : la fiche d'un mix les relit sans refaire le calcul.
@MainActor
final class MixStore {
    static let shared = MixStore()
    var mixes: [Mix] = []
}

/// Vignette de mix : mosaïque de pochettes sous un voile coloré, titre
/// posé dessus, et bouton lecture direct.
struct MixTile: View {
    let mix: Mix
    var action: () -> Void
    var onPlay: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 8) {
                ZStack(alignment: .bottomLeading) {
                    MixCover(mix: mix)
                    LinearGradient(colors: [.clear, tint.opacity(0.9)], startPoint: .top, endPoint: .bottom)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(mix.title)
                            .font(.system(size: 19, weight: .bold))
                            .foregroundStyle(.white)
                        Text("\(mix.tracks.count) titres")
                            .font(Typo.caption)
                            .foregroundStyle(.white.opacity(0.75))
                    }
                    .padding(12)
                    Button(action: onPlay) {
                        Image(systemName: "play.fill")
                            .font(.system(size: 14, weight: .bold))
                            .foregroundStyle(.black)
                            .frame(width: 34, height: 34)
                            .background(Circle().fill(.white))
                    }
                    .buttonStyle(.pressable(scale: 0.85))
                    .padding(10)
                    .frame(maxWidth: .infinity, alignment: .trailing)
                }
                .frame(width: 170, height: 170)
                .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))

                Text(mix.subtitle)
                    .font(Typo.rowSubtitle)
                    .foregroundStyle(Tone.secondary)
                    .lineLimit(2)
                    .frame(width: 170, alignment: .leading)
            }
        }
        .buttonStyle(.pressable)
    }

    private var tint: Color {
        switch mix.id {
        case "daily": Color(red: 0.36, green: 0.22, blue: 0.85)
        case "discoveries": Color(red: 0.05, green: 0.55, blue: 0.5)
        default: Color(red: 0.8, green: 0.25, blue: 0.35)
        }
    }
}

struct MixCover: View {
    let mix: Mix

    var body: some View {
        GeometryReader { proxy in
            let side = proxy.size.width / 2
            if mix.covers.count >= 4 {
                VStack(spacing: 0) {
                    ForEach(0..<2, id: \.self) { row in
                        HStack(spacing: 0) {
                            ForEach(0..<2, id: \.self) { column in
                                Artwork(url: mix.covers[row * 2 + column], cornerRadius: 0)
                                    .frame(width: side, height: side)
                            }
                        }
                    }
                }
            } else {
                Artwork(url: mix.covers.first, cornerRadius: 0, symbol: "sparkles")
            }
        }
        .aspectRatio(1, contentMode: .fit)
    }
}

/// Fiche d'un mix : pochette, Lecture / Aléatoire, titres.
struct MixDetailView: View {
    let mixId: String
    @Binding var path: NavigationPath
    @EnvironmentObject private var player: PlayerManager
    @State private var mix: Mix?
    @State private var errorMessage: String?

    var body: some View {
        ScrollView {
            if let mix {
                VStack(spacing: 18) {
                    MixCover(mix: mix)
                        .frame(width: 240, height: 240)
                        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                        .shadow(color: .black.opacity(0.5), radius: 30, y: 16)
                        .padding(.top, 12)
                    VStack(spacing: 6) {
                        Text(mix.title).font(.system(size: 24, weight: .bold)).foregroundStyle(Tone.primary)
                        Text(mix.subtitle)
                            .font(Typo.rowSubtitle)
                            .foregroundStyle(Tone.secondary)
                            .multilineTextAlignment(.center)
                        DownloadStatusLine(tracks: mix.tracks)
                    }
                    .padding(.horizontal, 24)
                    HStack(spacing: 12) {
                        PillButton(title: "Lecture", systemImage: "play.fill") {
                            if let first = mix.tracks.first { player.play(first, context: mix.tracks, name: mix.title) }
                        }
                        PillButton(title: "Aléatoire", systemImage: "shuffle", kind: .secondary) {
                            let shuffled = mix.tracks.shuffled()
                            if let first = shuffled.first { player.play(first, context: shuffled, name: mix.title) }
                        }
                    }
                    .padding(.horizontal, 20)

                    LazyVStack(spacing: 2) {
                        ForEach(mix.tracks) { track in
                            TrackRow(
                                track: track,
                                isCurrent: player.current?.id == track.id,
                                isPlaying: player.isPlaying,
                                onOpenArtist: track.artistSourceId.map { id in { path.append(Route.artist(source: track.source, id: id)) } },
                                onOpenAlbum: track.albumSourceId.map { id in { path.append(Route.album(source: track.source, id: id)) } }
                            ) {
                                player.play(track, context: mix.tracks, name: mix.title)
                            }
                        }
                    }
                    .padding(.horizontal, 20)
                }
                .padding(.bottom, 24)
            } else if let errorMessage {
                EmptyState(systemImage: "exclamationmark.triangle", title: "Mix indisponible", message: errorMessage)
                    .padding(.top, 80)
            } else {
                ProgressView().tint(.white).frame(maxWidth: .infinity).padding(.top, 120)
            }
        }
        .scrollIndicators(.hidden)
        .background(Tone.background)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                if let mix {
                    Menu {
                        DownloadMenuItems(tracks: mix.tracks)
                        Button { player.playNext(mix.tracks) } label: {
                            Label("Lire ensuite", systemImage: "text.line.first.and.arrowtriangle.forward")
                        }
                        Button {
                            Task { await saveAsPlaylist(mix) }
                        } label: {
                            Label("Enregistrer comme playlist", systemImage: "text.badge.plus")
                        }
                    } label: {
                        Image(systemName: "ellipsis")
                    }
                }
            }
        }
        .task { await load() }
    }

    private func load() async {
        if let cached = MixStore.shared.mixes.first(where: { $0.id == mixId }) {
            mix = cached
            return
        }
        do {
            let fresh = try await APIClient.shared.mixes()
            MixStore.shared.mixes = fresh
            mix = fresh.first { $0.id == mixId }
            if mix == nil { errorMessage = "Ce mix n'est plus disponible." }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    /// Fige le mix du jour dans une playlist (il change demain).
    private func saveAsPlaylist(_ mix: Mix) async {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "fr_FR")
        formatter.dateFormat = "d MMMM"
        let name = "\(mix.title) — \(formatter.string(from: Date()))"
        if let playlist = try? await APIClient.shared.createPlaylist(name: name, tracks: mix.tracks) {
            path.append(Route.userPlaylist(id: playlist.id))
        }
    }
}
