import SwiftUI

/// Fiche d'une playlist de l'utilisateur : pochette, Lecture / Aléatoire,
/// titres (appui long pour déplacer, balayage pour retirer), renommage et
/// suppression. Pendant un import, l'avancement se met à jour tout seul.
struct UserPlaylistView: View {
    let playlistId: Int
    @Binding var path: NavigationPath

    @EnvironmentObject private var player: PlayerManager
    @Environment(\.dismiss) private var dismiss
    @State private var playlist: UserPlaylist?
    @State private var entries: [PlaylistEntry] = []
    @State private var errorMessage: String?
    @State private var renaming = false
    @State private var newName = ""
    @State private var confirmingDelete = false

    var body: some View {
        Group {
            if let playlist {
                content(playlist)
            } else if let errorMessage {
                EmptyState(systemImage: "exclamationmark.triangle", title: "Playlist indisponible", message: errorMessage)
                    .padding(.top, 80)
            } else {
                ProgressView().tint(.white).frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .background(Tone.background)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                if let playlist {
                    Menu {
                        DownloadMenuItems(tracks: entries.map(\.track))
                        Toggle(isOn: Binding(
                            get: { DownloadManager.shared.offlinePlaylistIds.contains(playlist.id) },
                            set: { value in
                                DownloadManager.shared.setOffline(playlistId: playlist.id, value)
                                if value { DownloadManager.shared.download(entries.map(\.track)) }
                            }
                        )) {
                            Label("Garder hors ligne", systemImage: "arrow.down.circle.dotted")
                        }
                        Button { player.playNext(entries.map(\.track)) } label: {
                            Label("Lire ensuite", systemImage: "text.line.first.and.arrowtriangle.forward")
                        }
                        .disabled(entries.isEmpty)
                        if playlist.mine {
                            Divider()
                            Picker(selection: Binding(
                                get: { playlist.visibility ?? "private" },
                                set: { value in Task { await setVisibility(value) } }
                            )) {
                                Label("Privée", systemImage: "lock").tag("private")
                                Label("Visible par tes amis", systemImage: "person.2").tag("friends")
                                Label("À plusieurs (amis peuvent ajouter)", systemImage: "person.2.badge.plus").tag("collaborative")
                            } label: {
                                Label("Partage", systemImage: "person.2")
                            }
                            .pickerStyle(.menu)
                            if let origin = playlist.originLabel, !playlist.isImporting {
                                Button { Task { await reimport() } } label: {
                                    Label("Mettre à jour depuis \(origin)", systemImage: "arrow.triangle.2.circlepath")
                                }
                            }
                            Button {
                                newName = playlist.name
                                renaming = true
                            } label: {
                                Label("Renommer", systemImage: "pencil")
                            }
                            Button(role: .destructive) { confirmingDelete = true } label: {
                                Label("Supprimer la playlist", systemImage: "trash")
                            }
                        }
                    } label: {
                        Image(systemName: "ellipsis")
                    }
                }
            }
        }
        .alert("Renommer la playlist", isPresented: $renaming) {
            TextField("Nom", text: $newName)
            Button("Annuler", role: .cancel) {}
            Button("Renommer") { Task { await rename() } }
        }
        .confirmationDialog(
            "Supprimer « \(playlist?.name ?? "") » ?", isPresented: $confirmingDelete, titleVisibility: .visible
        ) {
            Button("Supprimer", role: .destructive) { Task { await delete() } }
        }
        .task { await load() }
        .task(id: playlist?.isImporting) {
            // Suivi de l'import : recharge tant que le serveur travaille.
            while playlist?.isImporting == true {
                try? await Task.sleep(for: .seconds(1.5))
                guard !Task.isCancelled else { return }
                await load()
            }
        }
    }

    private func content(_ playlist: UserPlaylist) -> some View {
        List {
            header(playlist).plainRow()

            if playlist.isImporting {
                importProgress(playlist).plainRow()
            } else if playlist.importFailed, let error = playlist.importError {
                Text(error)
                    .font(Typo.rowSubtitle)
                    .foregroundStyle(Tone.danger)
                    .padding(.vertical, 8)
                    .plainRow()
            } else if entries.isEmpty {
                EmptyState(
                    systemImage: "music.note.list",
                    title: "Playlist vide",
                    message: "Ajoute des titres depuis le lecteur ou d'un appui long sur un titre."
                )
                .plainRow()
            }

            ForEach(Array(entries.enumerated()), id: \.element.id) { index, entry in
                TrackRow(
                    track: entry.track,
                    isCurrent: player.current?.id == entry.track.id,
                    isPlaying: player.isPlaying,
                    onOpenArtist: entry.track.artistSourceId.map { id in
                        { path.append(Route.artist(source: entry.track.source, id: id)) }
                    },
                    onOpenAlbum: entry.track.albumSourceId.map { id in
                        { path.append(Route.album(source: entry.track.source, id: id)) }
                    }
                ) {
                    play(from: index)
                }
                .plainRow()
                .swipeActions(edge: .trailing, allowsFullSwipe: true) {
                    if playlist.editable {
                        Button(role: .destructive) {
                            Task { await remove(entry) }
                        } label: {
                            Label("Retirer", systemImage: "minus.circle")
                        }
                    }
                }
            }
            .onMove(perform: moveHandler(playlist))

            if !playlist.importFailed, !playlist.isImporting, let note = playlist.importError {
                // Import terminé mais partiel : la raison, telle que le serveur l'a vue.
                Label(note, systemImage: "exclamationmark.triangle")
                    .font(Typo.rowSubtitle)
                    .foregroundStyle(Tone.secondary)
                    .padding(.top, 10)
                    .plainRow()
            }

            if !entries.isEmpty {
                Text(footer(playlist))
                    .font(Typo.rowSubtitle)
                    .foregroundStyle(Tone.tertiary)
                    .padding(.top, 10)
                    .padding(.bottom, 24)
                    .plainRow()
            }
        }
        .listStyle(.plain)
        .scrollContentBackground(.hidden)
        .scrollIndicators(.hidden)
        .refreshable { await load() }
        .animation(Motion.smooth, value: entries)
    }

    private func header(_ playlist: UserPlaylist) -> some View {
        VStack(spacing: 18) {
            PlaylistCover(playlist: playlist, cornerRadius: 12)
                .frame(width: 240, height: 240)
                .shadow(color: .black.opacity(0.5), radius: 30, y: 16)
                .padding(.top, 12)

            VStack(spacing: 6) {
                Text(playlist.name)
                    .font(.system(size: 24, weight: .bold))
                    .foregroundStyle(Tone.primary)
                    .multilineTextAlignment(.center)
                if let owner = playlist.ownerName, !playlist.mine {
                    Text("Par \(owner)").font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
                } else if let origin = playlist.originLabel {
                    Text("Importée de \(origin)").font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
                }
                if playlist.visibility != nil && playlist.visibility != "private" {
                    Label(playlist.visibilityLabel, systemImage: playlist.visibility == "collaborative" ? "person.2.badge.plus" : "person.2")
                        .font(Typo.caption)
                        .foregroundStyle(Tone.tertiary)
                }
                DownloadStatusLine(tracks: entries.map(\.track))
            }
            .padding(.horizontal, 24)

            HStack(spacing: 12) {
                PillButton(title: "Lecture", systemImage: "play.fill") { play(from: 0) }
                PillButton(title: "Aléatoire", systemImage: "shuffle", kind: .secondary) {
                    player.playShuffled(entries.map(\.track), name: playlist.name)
                }
            }
            .disabled(entries.isEmpty)
        }
        .frame(maxWidth: .infinity)
        .padding(.bottom, 16)
    }

    private func importProgress(_ playlist: UserPlaylist) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            if let total = playlist.importTotal, total > 0 {
                ProgressView(value: Double(playlist.importDone), total: Double(total)).tint(.white)
                Text("Import en cours… \(playlist.importDone) / \(total) titres")
            } else {
                ProgressView().tint(.white)
                Text("Lecture de la playlist…")
            }
        }
        .font(Typo.rowSubtitle)
        .foregroundStyle(Tone.secondary)
        .padding(.vertical, 12)
    }

    private func footer(_ playlist: UserPlaylist) -> String {
        let minutes = entries.compactMap(\.track.durationSeconds).reduce(0, +) / 60
        var parts = [entries.count == 1 ? "1 titre" : "\(entries.count) titres"]
        parts.append(minutes >= 60 ? "\(minutes / 60) h \(minutes % 60) min" : "\(minutes) min")
        if playlist.importMissing > 0 {
            parts.append("\(playlist.importMissing) introuvable\(playlist.importMissing > 1 ? "s" : "") à l'import")
        }
        return parts.joined(separator: " · ")
    }

    private func play(from index: Int) {
        let tracks = entries.map(\.track)
        guard tracks.indices.contains(index), let playlist else { return }
        player.play(tracks[index], context: tracks, name: playlist.name)
    }

    // MARK: - Actions

    private func apply(_ updated: UserPlaylist) {
        playlist = updated
        if let fresh = updated.entries { entries = fresh }
    }

    private func load() async {
        do {
            apply(try await APIClient.shared.userPlaylist(id: playlistId))
            errorMessage = nil
        } catch {
            if playlist == nil { errorMessage = error.localizedDescription }
        }
    }

    private func remove(_ entry: PlaylistEntry) async {
        entries.removeAll { $0.id == entry.id }
        if let updated = try? await APIClient.shared.removeFromPlaylist(id: playlistId, entryId: entry.entryId) {
            apply(updated)
        } else {
            await load()
        }
    }

    private func saveOrder() async {
        if let updated = try? await APIClient.shared.reorderPlaylist(id: playlistId, entryIds: entries.map(\.entryId)) {
            apply(updated)
        } else {
            await load()
        }
    }

    /// Glisser-déposer seulement si l'on peut modifier la playlist.
    private func moveHandler(_ playlist: UserPlaylist) -> ((IndexSet, Int) -> Void)? {
        guard playlist.editable else { return nil }
        return { source, destination in
            entries.move(fromOffsets: source, toOffset: destination)
            Task { await saveOrder() }
        }
    }

    private func setVisibility(_ visibility: String) async {
        if let updated = try? await APIClient.shared.setPlaylistVisibility(id: playlistId, visibility: visibility) {
            playlist?.visibility = updated.visibility
        }
    }

    private func reimport() async {
        do {
            let updated = try await APIClient.shared.reimportPlaylist(id: playlistId)
            playlist = updated  // `importing` : le suivi de l'import démarre
        } catch {
            playlist?.importError = error.localizedDescription
            playlist?.importStatus = "failed"
        }
    }

    private func rename() async {
        let name = newName.trimmingCharacters(in: .whitespaces)
        guard !name.isEmpty else { return }
        if let updated = try? await APIClient.shared.renamePlaylist(id: playlistId, name: name) {
            playlist?.name = updated.name
        }
    }

    private func delete() async {
        do {
            try await APIClient.shared.deletePlaylist(id: playlistId)
            dismiss()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

private extension View {
    func plainRow() -> some View {
        self
            .listRowBackground(Color.clear)
            .listRowSeparator(.hidden)
            .listRowInsets(EdgeInsets(top: 0, leading: 20, bottom: 0, trailing: 20))
    }
}
