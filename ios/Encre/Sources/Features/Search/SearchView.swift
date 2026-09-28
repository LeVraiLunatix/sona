import SwiftUI

struct SearchView: View {
    @StateObject private var viewModel = SearchViewModel()
    @EnvironmentObject private var player: PlayerManager
    @Binding var path: NavigationPath
    @State private var loadingRadioId: String?
    @State private var radioError: String?

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 30) {
                content
            }
            .padding(.top, 8)
            .padding(.bottom, 110)
            .animation(Motion.smooth, value: viewModel.isSearching)
        }
        .scrollIndicators(.hidden)
        .scrollDismissesKeyboard(.immediately)
        .background(Tone.background)
        .navigationTitle("Rechercher")
        .navigationBarTitleDisplayMode(.large)
        .searchable(text: $viewModel.query, prompt: "Artistes, titres, albums ou lien")
        .autocorrectionDisabled()
        .textInputAutocapitalization(.never)
        .task { await viewModel.loadRadios() }
    }

    @ViewBuilder
    private var content: some View {
        let hasQuery = !viewModel.query.trimmingCharacters(in: .whitespaces).isEmpty
        if viewModel.isSearching {
            ProgressView().tint(.white).frame(maxWidth: .infinity).padding(.top, 60)
        } else if let link = viewModel.resolvedLink {
            resolvedView(link).padding(.horizontal, 20).reveal(0)
        } else if viewModel.hasResults {
            results
        } else if hasQuery {
            if let message = viewModel.errorMessage {
                EmptyState(systemImage: "exclamationmark.triangle", title: "Recherche impossible", message: message)
            } else {
                EmptyState(systemImage: "magnifyingglass", title: "Aucun résultat", message: "Rien pour « \(viewModel.query) ».")
            }
        } else {
            browse
        }
    }

    // MARK: - Résultats

    @ViewBuilder
    private var results: some View {
        if let top = viewModel.artists.first {
            topResult(top).padding(.horizontal, 20).reveal(0)
        }

        if viewModel.artists.count > 1 {
            section("Artistes", index: 1) {
                Carousel(items: Array(viewModel.artists.dropFirst()), spacing: 18) { artist in
                    let route = Route.artist(source: artist.source, id: artist.sourceId)
                    ArtistBubble(name: artist.name, pictureURL: artist.pictureURL, route: route, size: 96) {
                        path.append(route)
                    }
                }
            }
        }

        if !viewModel.albums.isEmpty {
            section("Albums", index: 2) {
                Carousel(items: viewModel.albums) { album in
                    AlbumTile(album: album) { path.append(Route.album(source: album.source, id: album.sourceId)) }
                }
            }
        }

        if !viewModel.results.isEmpty {
            section("Titres", index: 3) {
                LazyVStack(spacing: 2) {
                    ForEach(viewModel.results) { track in
                        TrackRow(
                            track: track,
                            isCurrent: player.current?.id == track.id,
                            isPlaying: player.isPlaying,
                            onOpenArtist: track.artistSourceId.map { id in { path.append(Route.artist(source: track.source, id: id)) } },
                            onOpenAlbum: track.albumSourceId.map { id in { path.append(Route.album(source: track.source, id: id)) } }
                        ) {
                            player.play(track, context: viewModel.results)
                        }
                        .onAppear {
                            if track.id == viewModel.results.last?.id {
                                Task { await viewModel.loadMore() }
                            }
                        }
                    }
                    if viewModel.isLoadingMore {
                        ProgressView().tint(.white).frame(maxWidth: .infinity).padding(.vertical, 16)
                    }
                }
                .padding(.horizontal, 20)
            }
        }
    }

    /// « Meilleur résultat » : le premier artiste en grande carte, comme
    /// Musique — chercher un nom doit mener à sa fiche d'un tap.
    private func topResult(_ artist: Artist) -> some View {
        let route = Route.artist(source: artist.source, id: artist.sourceId)
        return VStack(alignment: .leading, spacing: 12) {
            Text("Meilleur résultat").font(Typo.title).foregroundStyle(Tone.primary)
            Button { path.append(route) } label: {
                HStack(spacing: 16) {
                    Artwork(url: artist.pictureURL, cornerRadius: 44, symbol: "person.fill")
                        .frame(width: 88, height: 88)
                        .zoomSource(route)
                    VStack(alignment: .leading, spacing: 4) {
                        Text(artist.name).font(Typo.title).foregroundStyle(Tone.primary).lineLimit(2)
                        Text(fansLabel(artist)).font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
                    }
                    Spacer()
                    Image(systemName: "chevron.right").font(.system(size: 14, weight: .semibold)).foregroundStyle(Tone.tertiary)
                }
                .padding(16)
                .background(RoundedRectangle(cornerRadius: 18, style: .continuous).fill(Tone.surface))
            }
            .buttonStyle(.pressable(scale: 0.98))
        }
    }

    private func fansLabel(_ artist: Artist) -> String {
        guard let fans = artist.fans, fans > 0 else { return "Artiste" }
        return "Artiste · \(fans.formatted(.number.notation(.compactName))) fans"
    }

    // MARK: - Parcourir (champ vide)

    @ViewBuilder
    private var browse: some View {
        if let radioError {
            Text(radioError).font(Typo.rowSubtitle).foregroundStyle(Tone.danger).padding(.horizontal, 20)
        }
        ForEach(Array(viewModel.radioGroups.enumerated()), id: \.offset) { index, group in
            section(group.title, index: index) {
                Carousel(items: group.radios) { radio in
                    RadioTile(radio: radio, isLoading: loadingRadioId == radio.id) { startRadio(radio) }
                }
            }
        }
        if viewModel.radioGroups.isEmpty {
            EmptyState(
                systemImage: "magnifyingglass",
                title: "Cherche un artiste, un titre, un album",
                message: "Ou colle un lien Deezer, Spotify, Apple Music ou YouTube."
            )
        }
    }

    private func section<Content: View>(_ title: String, index: Int, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionHeader(title: title).padding(.horizontal, 20)
            content()
        }
        .reveal(index)
    }

    private func startRadio(_ radio: RadioStation) {
        guard loadingRadioId == nil else { return }
        loadingRadioId = radio.id
        radioError = nil
        let radioId = radio.id
        Task {
            do {
                try await player.playStation { try await APIClient.shared.radioTracks(id: radioId) }
            } catch {
                radioError = "« \(radio.title) » : \(error.localizedDescription)"
            }
            loadingRadioId = nil
        }
    }

    // MARK: - Lien collé

    @ViewBuilder
    private func resolvedView(_ link: ResolvedLink) -> some View {
        switch link.kind {
        case .track:
            if let track = link.track {
                TrackRow(
                    track: track,
                    isCurrent: player.current?.id == track.id,
                    isPlaying: player.isPlaying,
                    onOpenArtist: track.artistSourceId.map { id in { path.append(Route.artist(source: track.source, id: id)) } },
                    onOpenAlbum: track.albumSourceId.map { id in { path.append(Route.album(source: track.source, id: id)) } }
                ) { player.play(track) }
            }
        case .album, .playlist:
            if let album = link.album {
                let route = link.kind == .playlist
                    ? Route.playlist(source: album.source, id: album.sourceId)
                    : Route.album(source: album.source, id: album.sourceId)
                linkCard(title: album.title, subtitle: album.artist, imageURL: album.coverURL, round: false, route: route)
            }
        case .artist:
            if let artist = link.artist {
                let route = Route.artist(source: artist.source, id: artist.sourceId)
                linkCard(title: artist.name, subtitle: "Artiste", imageURL: artist.pictureURL, round: true, route: route)
            }
        }
    }

    private func linkCard(title: String, subtitle: String, imageURL: String?, round: Bool, route: Route) -> some View {
        Button { path.append(route) } label: {
            HStack(spacing: 16) {
                Artwork(url: imageURL, cornerRadius: round ? 36 : 10, symbol: round ? "person.fill" : "square.stack")
                    .frame(width: 72, height: 72)
                    .zoomSource(route)
                VStack(alignment: .leading, spacing: 3) {
                    Text(title).font(Typo.headline).foregroundStyle(Tone.primary).lineLimit(2)
                    Text(subtitle).font(Typo.rowSubtitle).foregroundStyle(Tone.secondary).lineLimit(1)
                }
                Spacer()
                Image(systemName: "chevron.right").font(.system(size: 14, weight: .semibold)).foregroundStyle(Tone.tertiary)
            }
            .padding(14)
            .background(RoundedRectangle(cornerRadius: 18, style: .continuous).fill(Tone.surface))
        }
        .buttonStyle(.pressable(scale: 0.98))
    }
}
