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
            .padding(.bottom, 24)
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
            if viewModel.suggestions.isEmpty {
                SearchSkeleton()
            } else {
                suggestionList
            }
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

    // MARK: - Suggestions

    /// Artistes et titres proposés pendant la frappe, en attendant les résultats complets.
    private var suggestionList: some View {
        VStack(spacing: 2) {
            ForEach(viewModel.suggestions) { suggestion in
                Button { choose(suggestion) } label: {
                    HStack(spacing: 14) {
                        Artwork(
                            url: suggestion.pictureURL,
                            cornerRadius: suggestion.kind == "artist" ? 22 : 6,
                            symbol: suggestion.kind == "artist" ? "person.fill" : "music.note"
                        )
                        .frame(width: 44, height: 44)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(suggestion.text).font(Typo.rowTitle).foregroundStyle(Tone.primary).lineLimit(1)
                            if let subtitle = suggestion.subtitle {
                                Text(subtitle).font(Typo.rowSubtitle).foregroundStyle(Tone.secondary).lineLimit(1)
                            }
                        }
                        Spacer(minLength: 0)
                    }
                    .padding(.vertical, 4)
                }
                .buttonStyle(.pressable)
            }
        }
        .padding(.horizontal, 20)
    }

    private func choose(_ suggestion: SearchSuggestion) {
        if suggestion.kind == "artist" {
            path.append(Route.artist(source: suggestion.source, id: suggestion.sourceId))
        } else {
            viewModel.query = suggestion.text
        }
    }

    // MARK: - Résultats

    private var filterChips: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(viewModel.availableFilters) { filter in
                    let selected = viewModel.filter == filter
                    Button {
                        withAnimation(Motion.snappy) { viewModel.filter = filter }
                    } label: {
                        HStack(spacing: 5) {
                            Text(filter.label)
                            if filter != .all {
                                Text("\(viewModel.count(for: filter))").opacity(0.55)
                            }
                        }
                        .font(Typo.rowSubtitle.weight(.semibold))
                        .foregroundStyle(selected ? Color.black : Tone.primary)
                        .padding(.horizontal, 14).padding(.vertical, 8)
                        .background(Capsule().fill(selected ? Color.white : Tone.surfaceStrong))
                    }
                    .buttonStyle(.pressable)
                }
            }
            .padding(.horizontal, 20)
        }
    }

    @ViewBuilder
    private var results: some View {
        if viewModel.availableFilters.count > 1 {
            filterChips
        }
        switch viewModel.filter {
        case .all: allResults
        case .songs: songsSection(viewModel.results, title: "Titres", index: 0)
        case .artists: artistsGrid
        case .albums: albumsGrid
        case .library: librarySections
        }
    }

    @ViewBuilder
    private var allResults: some View {
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

        if viewModel.libraryCount > 0 {
            section("Dans ta bibliothèque", index: 2, actionLabel: "Tout voir") {
                withAnimation(Motion.snappy) { viewModel.filter = .library }
            } content: {
                VStack(alignment: .leading, spacing: 14) {
                    trackList(Array(viewModel.libraryTracks.prefix(4)), name: "Ta bibliothèque").padding(.horizontal, 20)
                    if !viewModel.libraryPlaylists.isEmpty { playlistCarousel(viewModel.libraryPlaylists) }
                }
            }
        }

        if !viewModel.albums.isEmpty {
            section("Albums", index: 3) {
                Carousel(items: viewModel.albums) { album in
                    AlbumTile(album: album) { path.append(Route.album(source: album.source, id: album.sourceId)) }
                }
            }
        }

        if !viewModel.results.isEmpty {
            songsSection(viewModel.results, title: "Titres", index: 4)
        }
    }

    private func songsSection(_ tracks: [Track], title: String, index: Int) -> some View {
        section(title, index: index) {
            LazyVStack(spacing: 2) {
                ForEach(tracks) { track in
                    TrackRow(
                        track: track,
                        isCurrent: player.current?.id == track.id,
                        isPlaying: player.isPlaying,
                        onOpenArtist: track.artistSourceId.map { id in { path.append(Route.artist(source: track.artistRouteSource, id: id)) } },
                        onOpenAlbum: track.albumSourceId.map { id in { path.append(Route.album(source: track.source, id: id)) } },
                        highlight: viewModel.query
                    ) {
                        // Un titre lancé d'une recherche joue seul ; la suite est ta file perso.
                        PersonalQueue.play(track, with: player)
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

    private func trackList(_ tracks: [Track], name: String) -> some View {
        LazyVStack(spacing: 2) {
            ForEach(tracks) { track in
                TrackRow(
                    track: track,
                    isCurrent: player.current?.id == track.id,
                    isPlaying: player.isPlaying,
                    onOpenArtist: track.artistSourceId.map { id in { path.append(Route.artist(source: track.artistRouteSource, id: id)) } },
                    onOpenAlbum: track.albumSourceId.map { id in { path.append(Route.album(source: track.source, id: id)) } },
                    highlight: viewModel.query
                ) {
                    player.play(track, context: tracks, name: name)
                }
            }
        }
    }

    private var artistsGrid: some View {
        section("Artistes", index: 0) {
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 12), count: 3), spacing: 18) {
                ForEach(viewModel.artists) { artist in
                    let route = Route.artist(source: artist.source, id: artist.sourceId)
                    ArtistBubble(name: artist.name, pictureURL: artist.pictureURL, route: route, size: 96) {
                        path.append(route)
                    }
                }
            }
            .padding(.horizontal, 20)
        }
    }

    private var albumsGrid: some View {
        section("Albums", index: 0) {
            LazyVGrid(columns: [GridItem(.flexible(), spacing: 14), GridItem(.flexible(), spacing: 14)], alignment: .leading, spacing: 18) {
                ForEach(viewModel.albums) { album in
                    AlbumTile(album: album, size: 160) { path.append(Route.album(source: album.source, id: album.sourceId)) }
                }
            }
            .padding(.horizontal, 20)
        }
    }

    @ViewBuilder
    private var librarySections: some View {
        if !viewModel.libraryTracks.isEmpty {
            section("Titres de ta bibliothèque", index: 0) {
                trackList(viewModel.libraryTracks, name: "Ta bibliothèque").padding(.horizontal, 20)
            }
        }
        if !viewModel.libraryPlaylists.isEmpty {
            section("Playlists", index: 1) { playlistCarousel(viewModel.libraryPlaylists) }
        }
    }

    private func playlistCarousel(_ playlists: [UserPlaylist]) -> some View {
        Carousel(items: playlists) { playlist in
            let route = Route.userPlaylist(id: playlist.id)
            Button { path.append(route) } label: {
                VStack(alignment: .leading, spacing: 8) {
                    PlaylistCover(playlist: playlist)
                        .frame(width: 150, height: 150)
                        .zoomSource(route)
                    Text(playlist.name).font(Typo.rowTitle).foregroundStyle(Tone.primary).lineLimit(1)
                    Text(playlist.trackCountLabel).font(Typo.rowSubtitle).foregroundStyle(Tone.secondary).lineLimit(1)
                }
                .frame(width: 150, alignment: .leading)
            }
            .buttonStyle(.pressable)
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
        if !viewModel.recents.isEmpty { recentsSection }
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

    /// Recherches récentes, avec de quoi les retirer une à une ou toutes d'un coup.
    private var recentsSection: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline) {
                Text("Récentes").font(Typo.title).foregroundStyle(Tone.primary)
                Spacer()
                Button("Effacer") { withAnimation(Motion.snappy) { viewModel.clearRecents() } }
                    .font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
            }
            .padding(.horizontal, 20)
            ForEach(viewModel.recents, id: \.self) { text in
                HStack(spacing: 12) {
                    Button { viewModel.query = text } label: {
                        HStack(spacing: 12) {
                            Image(systemName: "clock.arrow.circlepath").foregroundStyle(Tone.tertiary)
                            Text(text).font(Typo.body).foregroundStyle(Tone.primary).lineLimit(1)
                            Spacer(minLength: 0)
                        }
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.pressable)
                    Button { withAnimation(Motion.snappy) { viewModel.forget(text) } } label: {
                        Image(systemName: "xmark").font(.system(size: 12, weight: .semibold)).foregroundStyle(Tone.tertiary)
                            .frame(width: 32, height: 32)
                    }
                    .accessibilityLabel("Retirer « \(text) »")
                }
                .padding(.horizontal, 20)
                .padding(.vertical, 4)
            }
        }
    }

    private func section<Content: View>(_ title: String, index: Int, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionHeader(title: title).padding(.horizontal, 20)
            content()
        }
        .reveal(index)
    }

    private func section<Content: View>(
        _ title: String, index: Int, actionLabel: String, action: @escaping () -> Void, @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionHeader(title: title, actionLabel: actionLabel, action: action).padding(.horizontal, 20)
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
                try await player.playStation(name: radio.title) { try await APIClient.shared.radioTracks(id: radioId) }
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
                    onOpenArtist: track.artistSourceId.map { id in { path.append(Route.artist(source: track.artistRouteSource, id: id)) } },
                    onOpenAlbum: track.albumSourceId.map { id in { path.append(Route.album(source: track.source, id: id)) } }
                ) { PersonalQueue.play(track, with: player) }
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
