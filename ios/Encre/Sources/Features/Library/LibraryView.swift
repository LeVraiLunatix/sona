import SwiftUI

struct LibraryView: View {
    @StateObject private var viewModel = LibraryViewModel()
    @EnvironmentObject private var player: PlayerManager
    @Binding var path: NavigationPath
    @State private var openingId: String?
    @State private var showingNewPlaylist = false
    @State private var showingImport = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                Picker("Type", selection: $viewModel.kind) {
                    ForEach(LibraryKind.allCases) { kind in
                        Text(kind.label).tag(kind)
                    }
                }
                .pickerStyle(.segmented)
                .padding(.horizontal, 20)
                .sensoryFeedback(.selection, trigger: viewModel.kind)

                Group {
                    if viewModel.kind == .playlists {
                        playlistSection
                    } else if viewModel.isLoading && viewModel.items.isEmpty {
                        ProgressView().tint(.white).frame(maxWidth: .infinity).padding(.top, 60)
                    } else if viewModel.items.isEmpty {
                        EmptyState(
                            systemImage: emptyIcon,
                            title: "Rien ici pour l'instant",
                            message: "Ajoute un titre depuis le lecteur (cœur), un album ou un artiste depuis sa fiche."
                        )
                    } else {
                        switch viewModel.kind {
                        case .tracks: trackList
                        case .albums: albumGrid
                        case .artists: artistList
                        case .playlists: EmptyView()
                        }
                    }
                }
                .id(viewModel.kind)
                .transition(.opacity.combined(with: .offset(y: 12)))

                if let message = viewModel.errorMessage {
                    Text(message).font(Typo.rowSubtitle).foregroundStyle(Tone.danger).padding(.horizontal, 20)
                }
            }
            .padding(.top, 8)
            .padding(.bottom, 24)
            .animation(Motion.smooth, value: viewModel.kind)
            .animation(Motion.smooth, value: viewModel.items)
        }
        .scrollIndicators(.hidden)
        .background(Tone.background)
        .navigationTitle("Bibliothèque")
        .navigationBarTitleDisplayMode(.large)
        .task { await viewModel.load() }
        .refreshable { await viewModel.load() }
        .task(id: viewModel.hasImportInProgress) {
            // Avancement des imports affiché en direct dans la grille.
            while viewModel.hasImportInProgress {
                try? await Task.sleep(for: .seconds(2))
                guard !Task.isCancelled else { return }
                await viewModel.refreshPlaylists()
            }
        }
        .onAppear {
            // Retour d'une fiche playlist (renommée, vidée, supprimée...).
            if viewModel.kind == .playlists { Task { await viewModel.refreshPlaylists() } }
        }
        .sheet(isPresented: $showingNewPlaylist) {
            NewPlaylistSheet { playlist in
                viewModel.insert(playlist)
                path.append(Route.userPlaylist(id: playlist.id))
            }
        }
        .sheet(isPresented: $showingImport) {
            ImportPlaylistSheet { playlist in
                viewModel.insert(playlist)
                path.append(Route.userPlaylist(id: playlist.id))
            }
        }
    }

    // MARK: - Playlists

    private var playlistSection: some View {
        VStack(alignment: .leading, spacing: 22) {
            HStack(spacing: 12) {
                PillButton(title: "Nouvelle", systemImage: "plus") { showingNewPlaylist = true }
                PillButton(title: "Importer", systemImage: "square.and.arrow.down", kind: .secondary) {
                    showingImport = true
                }
            }
            .padding(.horizontal, 20)

            DownloadsRow { path.append(Route.downloads) }
                .padding(.horizontal, 20)

            SmartPlaylistsRow(path: $path)

            if viewModel.isLoading && viewModel.playlists.isEmpty {
                ProgressView().tint(.white).frame(maxWidth: .infinity).padding(.top, 40)
            } else if viewModel.playlists.isEmpty {
                EmptyState(
                    systemImage: "music.note.list",
                    title: "Aucune playlist",
                    message: "Crée ta première playlist, ou importe-en une depuis Spotify, Apple Music ou Deezer."
                )
            } else {
                playlistGrid
            }
        }
    }

    private var playlistGrid: some View {
        LazyVGrid(columns: [GridItem(.flexible(), spacing: 16), GridItem(.flexible(), spacing: 16)], spacing: 22) {
            ForEach(viewModel.playlists) { playlist in
                let route = Route.userPlaylist(id: playlist.id)
                Button { path.append(route) } label: {
                    VStack(alignment: .leading, spacing: 8) {
                        PlaylistCover(playlist: playlist)
                            .aspectRatio(1, contentMode: .fit)
                            .overlay {
                                if playlist.isImporting {
                                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                                        .fill(Color.black.opacity(0.45))
                                    ProgressView().tint(.white)
                                }
                            }
                            .zoomSource(route)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(playlist.name).font(Typo.rowTitle).foregroundStyle(Tone.primary).lineLimit(1)
                            Text(playlist.trackCountLabel)
                                .font(Typo.rowSubtitle)
                                .foregroundStyle(playlist.importFailed ? Tone.danger : Tone.secondary)
                                .lineLimit(1)
                                .contentTransition(.numericText())
                        }
                    }
                }
                .buttonStyle(.pressable)
                .contextMenu {
                    if playlist.mine {
                        Button(role: .destructive) {
                            Task { await viewModel.deletePlaylist(playlist) }
                        } label: {
                            Label("Supprimer la playlist", systemImage: "trash")
                        }
                    } else if let owner = playlist.ownerName {
                        Text("Playlist à plusieurs de \(owner)")
                    }
                }
            }
        }
        .padding(.horizontal, 20)
        .animation(Motion.smooth, value: viewModel.playlists)
    }

    private var emptyIcon: String {
        switch viewModel.kind {
        case .tracks: "music.note"
        case .albums: "square.stack"
        case .artists: "person.2"
        case .playlists: "music.note.list"
        }
    }

    private var trackList: some View {
        LazyVStack(spacing: 2) {
            ForEach(viewModel.items) { item in
                if let track = viewModel.tracks["\(item.source):\(item.sourceId)"] {
                    TrackRow(
                        track: track,
                        isCurrent: player.current?.id == track.id,
                        isPlaying: player.isPlaying,
                        onOpenArtist: track.artistSourceId.map { id in { path.append(Route.artist(source: track.source, id: id)) } },
                        onOpenAlbum: track.albumSourceId.map { id in { path.append(Route.album(source: track.source, id: id)) } },
                        onRemove: { Task { await viewModel.remove(item) } }
                    ) {
                        player.play(track, context: viewModel.playableTracks, name: "Bibliothèque")
                    }
                } else {
                    placeholderRow(item)
                }
            }
        }
        .padding(.horizontal, 20)
    }

    /// Titre dont la fiche complète n'est pas encore arrivée : jouable quand
    /// même (fiche demandée au tap).
    private func placeholderRow(_ item: LibraryItem) -> some View {
        Button {
            openingId = item.id
            Task {
                if let track = try? await APIClient.shared.track(source: item.source, id: item.sourceId) {
                    player.play(track, context: viewModel.playableTracks.contains(track) ? viewModel.playableTracks : [])
                }
                openingId = nil
            }
        } label: {
            HStack(spacing: 14) {
                Artwork(url: item.coverURL, cornerRadius: 6).frame(width: 50, height: 50)
                VStack(alignment: .leading, spacing: 3) {
                    Text(item.title).font(Typo.rowTitle).foregroundStyle(Tone.primary).lineLimit(1)
                    Text(item.subtitle ?? " ").font(Typo.rowSubtitle).foregroundStyle(Tone.secondary).lineLimit(1)
                }
                Spacer()
                if openingId == item.id { ProgressView().tint(.white) }
            }
            .padding(.vertical, 6)
        }
        .buttonStyle(.pressable(scale: 0.98))
        .contextMenu { removeButton(item) }
    }

    private var albumGrid: some View {
        LazyVGrid(columns: [GridItem(.flexible(), spacing: 16), GridItem(.flexible(), spacing: 16)], spacing: 22) {
            ForEach(viewModel.items) { item in
                let route = Route.album(source: item.source, id: item.sourceId)
                Button { path.append(route) } label: {
                    VStack(alignment: .leading, spacing: 8) {
                        Artwork(url: item.coverURL, cornerRadius: 10, symbol: "square.stack")
                            .aspectRatio(1, contentMode: .fit)
                            .zoomSource(route)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(item.title).font(Typo.rowTitle).foregroundStyle(Tone.primary).lineLimit(1)
                            if let subtitle = item.subtitle {
                                Text(subtitle).font(Typo.rowSubtitle).foregroundStyle(Tone.secondary).lineLimit(1)
                            }
                        }
                    }
                }
                .buttonStyle(.pressable)
                .contextMenu { removeButton(item) }
            }
        }
        .padding(.horizontal, 20)
    }

    private var artistList: some View {
        LazyVStack(spacing: 4) {
            ForEach(viewModel.items) { item in
                let route = Route.artist(source: item.source, id: item.sourceId)
                Button { path.append(route) } label: {
                    HStack(spacing: 14) {
                        Artwork(url: item.coverURL, cornerRadius: 30, symbol: "person.fill")
                            .frame(width: 60, height: 60)
                            .zoomSource(route)
                        Text(item.title).font(Typo.headline).foregroundStyle(Tone.primary)
                        Spacer()
                        Image(systemName: "chevron.right").font(.system(size: 13, weight: .semibold)).foregroundStyle(Tone.tertiary)
                    }
                    .padding(.vertical, 6)
                }
                .buttonStyle(.pressable(scale: 0.98))
                .contextMenu { removeButton(item) }
            }
        }
        .padding(.horizontal, 20)
    }

    private func removeButton(_ item: LibraryItem) -> some View {
        Button(role: .destructive) {
            Task { await viewModel.remove(item) }
        } label: {
            Label("Retirer de la bibliothèque", systemImage: "trash")
        }
    }
}
