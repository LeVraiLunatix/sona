import SwiftUI

struct AlbumDetailView: View {
    let source: String
    let id: String
    var isPlaylist = false
    @Binding var path: NavigationPath

    @State private var album: Album?
    @State private var errorMessage: String?
    @State private var palette: [Color] = ArtworkPalette.fallback
    @State private var inLibrary = false
    @State private var libraryBounce = 0
    @EnvironmentObject private var player: PlayerManager

    var body: some View {
        ScrollView {
            if let album {
                VStack(spacing: 0) {
                    header(album)
                    tracks(album).reveal(2)
                    footer(album).reveal(3)
                }
                .padding(.bottom, 24)
            } else if let errorMessage {
                EmptyState(systemImage: "exclamationmark.triangle", title: "Album indisponible", message: errorMessage)
                    .padding(.top, 80)
            } else {
                ProgressView().tint(.white).frame(maxWidth: .infinity).padding(.top, 120)
            }
        }
        .scrollIndicators(.hidden)
        .background(alignment: .top) { glow }
        .background(Tone.background)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                if album != nil && !isPlaylist {
                    Button { Task { await toggleLibrary() } } label: {
                        Image(systemName: inLibrary ? "checkmark" : "plus")
                            .contentTransition(.symbolEffect(.replace))
                            .symbolEffect(.bounce, value: libraryBounce)
                    }
                    .sensoryFeedback(.success, trigger: libraryBounce)
                }
            }
        }
        .task { await load() }
    }

    /// Halo diffus aux couleurs de la pochette, fondu dans le noir.
    private var glow: some View {
        LinearGradient(colors: [palette[0].opacity(0.9), palette[3].opacity(0.4), .clear], startPoint: .top, endPoint: .bottom)
            .frame(height: 520)
            .blur(radius: 40)
            .ignoresSafeArea()
            .animation(.easeInOut(duration: 0.8), value: palette)
    }

    private func header(_ album: Album) -> some View {
        VStack(spacing: 18) {
            Artwork(url: album.coverURL, cornerRadius: 12, symbol: "square.stack")
                .frame(width: 250, height: 250)
                .shadow(color: .black.opacity(0.5), radius: 30, y: 16)
                .padding(.top, 12)

            VStack(spacing: 6) {
                Text(album.title)
                    .font(.system(size: 24, weight: .bold))
                    .foregroundStyle(Tone.primary)
                    .multilineTextAlignment(.center)
                Button {
                    if let artistId = album.artistSourceId {
                        path.append(Route.artist(source: album.source, id: artistId))
                    }
                } label: {
                    Text(album.artist)
                        .font(.system(size: 19, weight: .medium))
                        .foregroundStyle(Tone.primary.opacity(0.85))
                }
                .buttonStyle(.pressable)
                .disabled(album.artistSourceId == nil)
                if let meta = metaLine(album) {
                    Text(meta).font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
                }
            }
            .padding(.horizontal, 24)
            .reveal(0)

            HStack(spacing: 12) {
                PillButton(title: "Lecture", systemImage: "play.fill") {
                    if let first = album.tracks.first { player.play(first, context: album.tracks, name: album.title) }
                }
                PillButton(title: "Aléatoire", systemImage: "shuffle", kind: .secondary) {
                    let shuffled = album.tracks.shuffled()
                    if let first = shuffled.first { player.play(first, context: shuffled, name: album.title) }
                }
            }
            .padding(.horizontal, 20)
            .disabled(album.tracks.isEmpty)
            .reveal(1)
        }
        .padding(.bottom, 20)
    }

    private func tracks(_ album: Album) -> some View {
        LazyVStack(spacing: 0) {
            ForEach(Array(album.tracks.enumerated()), id: \.offset) { index, track in
                TrackRow(
                    track: track,
                    index: index + 1,
                    showsArtwork: false,
                    isCurrent: player.current?.id == track.id,
                    isPlaying: player.isPlaying,
                    onOpenArtist: track.artistSourceId.map { id in { path.append(Route.artist(source: track.source, id: id)) } }
                ) {
                    player.play(track, context: album.tracks, name: album.title)
                }
                .padding(.vertical, 4)
                if index < album.tracks.count - 1 {
                    Divider().overlay(Tone.separator).padding(.leading, 40)
                }
            }
        }
        .padding(.horizontal, 20)
    }

    private func footer(_ album: Album) -> some View {
        Text(footerLine(album))
            .font(Typo.rowSubtitle)
            .foregroundStyle(Tone.tertiary)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 20)
            .padding(.top, 18)
    }

    private func metaLine(_ album: Album) -> String? {
        let isAlbum = album.tracks.count > 1 || (album.trackCount ?? 0) > 1
        let kind = isPlaylist ? "Playlist" : (isAlbum ? "Album" : "Single")
        let parts = [kind, album.year].compactMap { $0 }
        return parts.joined(separator: " · ")
    }

    private func footerLine(_ album: Album) -> String {
        let count = album.trackCount ?? album.tracks.count
        let seconds = album.durationSeconds ?? album.tracks.compactMap(\.durationSeconds).reduce(0, +)
        var parts = ["\(count) titre\(count > 1 ? "s" : "")"]
        if seconds > 0 { parts.append("\(max(1, seconds / 60)) min") }
        return parts.joined(separator: ", ")
    }

    private func load() async {
        do {
            let loaded: Album
            if isPlaylist {
                loaded = try await APIClient.shared.playlist(source: source, id: id)
            } else {
                loaded = try await APIClient.shared.album(source: source, id: id)
            }
            withAnimation(Motion.smooth) { album = loaded }
            palette = await ArtworkPalette.colors(for: loaded.coverURL)
            if !isPlaylist, let page = try? await APIClient.shared.library(kind: "album", limit: 200) {
                inLibrary = page.items.contains { $0.source == source && $0.sourceId == id }
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func toggleLibrary() async {
        do {
            if inLibrary {
                try await APIClient.shared.removeFromLibrary(kind: "album", source: source, sourceId: id)
            } else {
                try await APIClient.shared.addToLibrary(kind: "album", source: source, sourceId: id)
            }
            inLibrary.toggle()
            libraryBounce += 1
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
