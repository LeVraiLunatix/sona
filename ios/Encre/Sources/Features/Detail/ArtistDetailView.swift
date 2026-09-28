import SwiftUI

struct ArtistDetailView: View {
    let source: String
    let id: String
    @Binding var path: NavigationPath

    @State private var artist: Artist?
    @State private var topTracks: [Track] = []
    @State private var albums: [Album] = []
    @State private var singles: [Album] = []
    @State private var related: [Artist] = []
    @State private var errorMessage: String?
    @State private var showsAllTracks = false
    @State private var isStartingRadio = false
    @State private var radioError: String?
    @State private var inLibrary = false
    @State private var libraryBounce = 0
    @EnvironmentObject private var player: PlayerManager

    private let headerHeight: CGFloat = 400

    var body: some View {
        ScrollView {
            if let artist {
                VStack(alignment: .leading, spacing: 0) {
                    header(artist)
                    VStack(alignment: .leading, spacing: 34) {
                        actions.reveal(0)
                        if !topTracks.isEmpty { popular.reveal(1) }
                        if !albums.isEmpty {
                            carousel("Albums", albums).reveal(2)
                        }
                        if !singles.isEmpty {
                            carousel("Singles et EP", singles).reveal(3)
                        }
                        if !related.isEmpty { relatedSection.reveal(4) }
                    }
                    .padding(.top, 20)
                }
                .padding(.bottom, 110)
            } else if let errorMessage {
                EmptyState(systemImage: "exclamationmark.triangle", title: "Artiste indisponible", message: errorMessage)
                    .padding(.top, 140)
            } else {
                ProgressView().tint(.white).frame(maxWidth: .infinity).padding(.top, 200)
            }
        }
        .scrollIndicators(.hidden)
        .ignoresSafeArea(edges: .top)
        .background(Tone.background)
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(.hidden, for: .navigationBar)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                if artist != nil {
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

    // MARK: - En-tête

    /// Photo pleine largeur : s'étire quand on tire vers le bas, défile plus
    /// lentement que le contenu en remontant (parallaxe).
    private func header(_ artist: Artist) -> some View {
        GeometryReader { proxy in
            let minY = proxy.frame(in: .scrollView).minY
            let stretch = max(0, minY)
            ZStack(alignment: .bottomLeading) {
                Artwork(url: artist.pictureURL, cornerRadius: 0, symbol: "person.fill")
                    .frame(width: proxy.size.width, height: headerHeight + stretch)
                    .offset(y: minY > 0 ? -minY : -minY * 0.4)
                LinearGradient(
                    stops: [
                        .init(color: .clear, location: 0.35),
                        .init(color: .black.opacity(0.6), location: 0.75),
                        .init(color: .black, location: 1),
                    ],
                    startPoint: .top, endPoint: .bottom
                )
                .frame(height: headerHeight + stretch)
                .offset(y: -stretch)
                VStack(alignment: .leading, spacing: 4) {
                    Text(artist.name)
                        .font(Typo.hero)
                        .foregroundStyle(Tone.primary)
                        .lineLimit(2)
                        .minimumScaleFactor(0.6)
                    if let fans = artist.fans, fans > 0 {
                        Text("\(fans.formatted(.number.notation(.compactName))) fans")
                            .font(Typo.rowSubtitle)
                            .foregroundStyle(Tone.secondary)
                    }
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 16)
                .reveal(0)
            }
            .clipped()
        }
        .frame(height: headerHeight)
    }

    private var actions: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 12) {
                PillButton(title: "Lecture", systemImage: "play.fill") {
                    if let first = topTracks.first { player.play(first, context: topTracks) }
                }
                .disabled(topTracks.isEmpty)
                // Station sans fin autour de l'artiste (le « mix » Deezer, ou
                // ses titres populaires mélangés ailleurs).
                PillButton(title: "Radio", systemImage: "dot.radiowaves.left.and.right", kind: .secondary, isLoading: isStartingRadio) {
                    startRadio()
                }
            }
            if let radioError {
                Text(radioError).font(Typo.rowSubtitle).foregroundStyle(Tone.danger)
            }
        }
        .padding(.horizontal, 20)
    }

    private var popular: some View {
        let visible = showsAllTracks ? topTracks : Array(topTracks.prefix(5))
        return VStack(alignment: .leading, spacing: 10) {
            SectionHeader(
                title: "Populaires",
                actionLabel: topTracks.count > 5 ? (showsAllTracks ? "Moins" : "Tout voir") : nil,
                action: { withAnimation(Motion.smooth) { showsAllTracks.toggle() } }
            )
            LazyVStack(spacing: 2) {
                ForEach(visible) { track in
                    TrackRow(
                        track: track,
                        isCurrent: player.current?.id == track.id,
                        isPlaying: player.isPlaying,
                        onOpenAlbum: track.albumSourceId.map { id in { path.append(Route.album(source: track.source, id: id)) } }
                    ) {
                        player.play(track, context: topTracks)
                    }
                    .transition(.opacity.combined(with: .move(edge: .top)))
                }
            }
        }
        .padding(.horizontal, 20)
    }

    private func carousel(_ title: String, _ list: [Album]) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionHeader(title: title).padding(.horizontal, 20)
            Carousel(items: list) { album in
                AlbumTile(album: album) { path.append(Route.album(source: album.source, id: album.sourceId)) }
            }
        }
    }

    private var relatedSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionHeader(title: "Artistes similaires").padding(.horizontal, 20)
            Carousel(items: related, spacing: 18) { other in
                let route = Route.artist(source: other.source, id: other.sourceId)
                ArtistBubble(name: other.name, pictureURL: other.pictureURL, route: route, size: 100) {
                    path.append(route)
                }
            }
        }
    }

    // MARK: - Données

    private func load() async {
        do {
            async let artistTask = APIClient.shared.artist(source: source, id: id)
            async let topTask = APIClient.shared.artistTopTracks(source: source, id: id)
            async let albumsTask = APIClient.shared.artistAlbums(source: source, id: id)
            let loaded = try await artistTask
            // Titres et albums facultatifs : une fiche avec photo et nom vaut
            // mieux qu'un écran d'erreur si l'un des deux ne répond pas.
            let top = (try? await topTask) ?? []
            let albumSet = try? await albumsTask
            withAnimation(Motion.smooth) {
                artist = loaded
                topTracks = top
                albums = albumSet?.albums ?? []
                singles = albumSet?.singles ?? []
            }
        } catch {
            errorMessage = error.localizedDescription
            return
        }
        let similar = (try? await APIClient.shared.relatedArtists(source: source, id: id)) ?? []
        withAnimation(Motion.smooth) { related = similar }
        if let page = try? await APIClient.shared.library(kind: "artist", limit: 200) {
            inLibrary = page.items.contains { $0.source == source && $0.sourceId == id }
        }
    }

    private func startRadio() {
        isStartingRadio = true
        radioError = nil
        let source = source, id = id
        Task {
            do {
                try await player.playStation {
                    try await APIClient.shared.artistRadio(source: source, id: id)
                }
            } catch {
                radioError = error.localizedDescription
            }
            isStartingRadio = false
        }
    }

    private func toggleLibrary() async {
        do {
            if inLibrary {
                try await APIClient.shared.removeFromLibrary(kind: "artist", source: source, sourceId: id)
            } else {
                try await APIClient.shared.addToLibrary(kind: "artist", source: source, sourceId: id)
            }
            inLibrary.toggle()
            libraryBounce += 1
        } catch {
            radioError = error.localizedDescription
        }
    }
}
