import SwiftUI

/// Playlists intelligentes (Bibliothèque) : faites toutes seules à partir
/// de tes écoutes et remises à jour à chaque ouverture — en boucle, oubliés,
/// découvertes du mois, tes nuits, tes matins, coups de cœur d'un jour.
struct SmartPlaylistsRow: View {
    @Binding var path: NavigationPath
    @State private var playlists: [SmartPlaylist] = []

    var body: some View {
        Group {
            if !playlists.isEmpty {
                VStack(alignment: .leading, spacing: 12) {
                    SectionHeader(title: "Faites pour toi").padding(.horizontal, 20)
                    ScrollView(.horizontal) {
                        HStack(spacing: 14) {
                            ForEach(playlists) { playlist in
                                Button {
                                    path.append(Route.smart(id: playlist.id, title: playlist.title))
                                } label: {
                                    SmartPlaylistTile(playlist: playlist)
                                }
                                .buttonStyle(.pressable)
                            }
                        }
                        .padding(.horizontal, 20)
                    }
                    .scrollIndicators(.hidden)
                }
            }
        }
        .task { playlists = (try? await APIClient.shared.smartPlaylists()) ?? playlists }
    }
}

private struct SmartPlaylistTile: View {
    let playlist: SmartPlaylist

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            ZStack(alignment: .bottomLeading) {
                SmartCover(playlist: playlist)
                Image(systemName: playlist.icon)
                    .font(.system(size: 18, weight: .bold))
                    .foregroundStyle(.white)
                    .padding(10)
                    .shadow(radius: 6)
            }
            .frame(width: 140, height: 140)
            Text(playlist.title).font(Typo.rowTitle).foregroundStyle(Tone.primary).lineLimit(1)
            Text("\(playlist.count) titres").font(Typo.rowSubtitle).foregroundStyle(Tone.secondary).lineLimit(1)
        }
        .frame(width: 140, alignment: .leading)
    }
}

/// Mosaïque de 4 pochettes (ou une seule) sous un voile coloré.
private struct SmartCover: View {
    let playlist: SmartPlaylist

    var body: some View {
        GeometryReader { proxy in
            let side = proxy.size.width
            ZStack {
                if playlist.covers.count >= 4 {
                    VStack(spacing: 0) {
                        HStack(spacing: 0) { cover(0, side / 2); cover(1, side / 2) }
                        HStack(spacing: 0) { cover(2, side / 2); cover(3, side / 2) }
                    }
                } else {
                    cover(0, side)
                }
                LinearGradient(colors: [tint.opacity(0.15), tint.opacity(0.75)], startPoint: .top, endPoint: .bottom)
            }
            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        }
    }

    private func cover(_ index: Int, _ side: CGFloat) -> some View {
        Artwork(url: playlist.covers.indices.contains(index) ? playlist.covers[index] : nil, cornerRadius: 0)
            .frame(width: side, height: side)
    }

    private var tint: Color {
        switch playlist.id {
        case "on_repeat": .pink
        case "forgotten": .orange
        case "discoveries": .green
        case "nights": .indigo
        case "mornings": .yellow
        default: .purple
        }
    }
}

struct SmartPlaylistView: View {
    let id: String
    let title: String
    @EnvironmentObject private var player: PlayerManager
    @State private var tracks: [Track] = []
    @State private var loading = true

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                if loading && tracks.isEmpty {
                    ProgressView().tint(.white).frame(maxWidth: .infinity).padding(.top, 80)
                } else if tracks.isEmpty {
                    EmptyState(systemImage: "sparkles", title: "Rien pour l'instant", message: "Écoute encore un peu de musique : cette playlist se remplit toute seule.")
                } else {
                    HStack(spacing: 12) {
                        PillButton(title: "Lecture", systemImage: "play.fill") {
                            if let first = tracks.first { player.play(first, context: tracks, name: title) }
                        }
                        PillButton(title: "Aléatoire", systemImage: "shuffle", kind: .secondary) {
                            let shuffled = tracks.shuffled()
                            if let first = shuffled.first { player.play(first, context: shuffled, name: title) }
                        }
                    }
                    .padding(.horizontal, 20)
                    LazyVStack(spacing: 0) {
                        ForEach(tracks) { track in
                            TrackRow(track: track, isCurrent: player.current?.id == track.id, isPlaying: player.isPlaying) {
                                player.play(track, context: tracks, name: title)
                            }
                        }
                    }
                    .padding(.horizontal, 20)
                }
            }
            .padding(.vertical, 12)
        }
        .scrollIndicators(.hidden)
        .background(Tone.background)
        .navigationTitle(title)
        .navigationBarTitleDisplayMode(.large)
        .task {
            tracks = (try? await APIClient.shared.smartPlaylist(id)) ?? tracks
            loading = false
        }
        .refreshable { tracks = (try? await APIClient.shared.smartPlaylist(id)) ?? tracks }
    }
}
