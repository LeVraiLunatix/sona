import SwiftUI
import UniformTypeIdentifiers
import PhotosUI

// MARK: - Pastille

/// « EXCLU · 2019 » / « INÉDIT · 2019 », et « LOSSLESS » quand le meilleur
/// fichier est sans perte : sur les lignes de titres, le lecteur et les fiches.
struct ExclusiveTag: View {
    let track: Track
    var compact = true

    var body: some View {
        if track.isExclusive, let tag = track.tag {
            HStack(spacing: 4) {
                pill(([tag.uppercased(), track.year].compactMap { $0 }).joined(separator: " · "),
                     fill: Tone.surfaceStrong, text: Tone.primary)
                if track.lossless == true {
                    pill("LOSSLESS", fill: Color(red: 1, green: 0.78, blue: 0.3).opacity(0.18),
                         text: Color(red: 0.94, green: 0.72, blue: 0.29))
                }
            }
        }
    }

    private func pill(_ text: String, fill: Color, text color: Color) -> some View {
        Text(text)
            .font(.system(size: compact ? 9.5 : 11, weight: .bold))
            .tracking(0.4)
            .foregroundStyle(color)
            .padding(.horizontal, 6)
            .padding(.vertical, 2.5)
            .background(Capsule().fill(fill))
            .fixedSize()
    }
}

// MARK: - Page Exclus

struct ExclusivesView: View {
    @Binding var path: NavigationPath
    // Pas d'@EnvironmentObject : cette page s'ouvre aussi depuis les Réglages (une feuille),
    // où l'environnement du lecteur manque et fait planter l'app.
    @ObservedObject private var player = PlayerManager.shared
    @State private var tracks: [Track] = []
    @State private var status: ExclusiveStatusDTO?
    @State private var isLoading = true
    @State private var errorMessage: String?
    @State private var editor: ExclusiveEditorRequest?

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 18) {
                Text("Des titres inédits, introuvables ailleurs : ajoutés à la main, rangés sur la page de leur artiste.")
                    .font(Typo.rowSubtitle)
                    .foregroundStyle(Tone.secondary)
                    .padding(.horizontal, 20)

                HStack(spacing: 12) {
                    PillButton(title: "Tout lire", systemImage: "play.fill") {
                        if let first = tracks.first { player.play(first, context: tracks, name: "Exclus") }
                    }
                    .disabled(tracks.isEmpty)
                    if status?.canAdd == true {
                        PillButton(title: "Ajouter", systemImage: "plus", kind: .secondary) {
                            editor = ExclusiveEditorRequest(existing: nil)
                        }
                    }
                }
                .padding(.horizontal, 20)

                if let errorMessage {
                    Text(errorMessage).font(Typo.rowSubtitle).foregroundStyle(Tone.danger).padding(.horizontal, 20)
                }

                if tracks.isEmpty && !isLoading {
                    EmptyState(
                        systemImage: "sparkles", title: "Aucun exclu pour le moment",
                        message: status?.canAdd == true
                            ? "Ajoute ton premier titre inédit avec le bouton « Ajouter »."
                            : "Les titres inédits ajoutés par l'admin apparaîtront ici."
                    )
                    .padding(.top, 40)
                } else {
                    LazyVStack(spacing: 2) {
                        ForEach(tracks) { track in
                            TrackRow(
                                track: track,
                                isCurrent: player.current?.id == track.id,
                                isPlaying: player.isPlaying,
                                onOpenArtist: track.artistSourceId.map { id in { path.append(Route.artist(source: track.artistRouteSource, id: id)) } }
                            ) {
                                player.play(track, context: tracks, name: "Exclus")
                            }
                        }
                    }
                    .padding(.horizontal, 20)
                }
            }
            .padding(.top, 8)
            .padding(.bottom, 24)
        }
        .scrollIndicators(.hidden)
        .background(Tone.background)
        .navigationTitle("Exclus")
        .navigationBarTitleDisplayMode(.large)
        .overlay { if isLoading && tracks.isEmpty { ProgressView().tint(.white) } }
        .sheet(item: $editor) { request in
            ExclusiveEditorView(existing: request.existing) { Task { await load() } }
        }
        .task { await load() }
        .refreshable { await load() }
    }

    private func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            async let list = APIClient.shared.exclusives()
            async let state = APIClient.shared.exclusivesStatus()
            tracks = try await list
            status = try? await state
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

// MARK: - Menu Qualité

/// Choix du fichier d'un exclu (MP3, FLAC…) : « Automatique » suit le réglage
/// Qualité audio, sinon la version choisie est lue à la place.
struct ExclusiveQualitySheet: View {
    let track: Track
    @Environment(\.dismiss) private var dismiss
    @State private var versions: [ExclusiveVersionDTO] = []
    @State private var chosen: String?
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            List {
                Section {
                    row(title: "Automatique", detail: "Selon Réglages › Qualité audio (\(PlaybackQuality.label))", selected: chosen == nil) {
                        select(nil)
                    }
                    ForEach(versions) { version in
                        row(
                            title: version.label,
                            detail: (version.lossless ? "Sans perte · " : "") + version.sizeLabel,
                            selected: chosen == version.id
                        ) { select(version.id) }
                    }
                } footer: {
                    if let errorMessage { Text(errorMessage).foregroundStyle(Tone.danger) }
                }
            }
            .navigationTitle("Qualité")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("OK") { dismiss() } } }
            .task {
                chosen = ExclusiveVersionChoice.shared.version(source: track.source, id: track.sourceId)
                do { versions = try await APIClient.shared.exclusiveVersions(id: track.sourceId) }
                catch { errorMessage = error.localizedDescription }
            }
        }
        .presentationDetents([.medium])
    }

    private func row(title: String, detail: String, selected: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).foregroundStyle(Tone.primary)
                    Text(detail).font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
                }
                Spacer()
                if selected { Image(systemName: "checkmark").foregroundStyle(Tone.primary) }
            }
        }
    }

    private func select(_ version: String?) {
        chosen = version
        ExclusiveVersionChoice.shared.set(version, for: track.sourceId)
        // Le titre en cours repart à la même seconde avec le nouveau fichier.
        if PlayerManager.shared.current?.id == track.id { PlayerManager.shared.restartCurrent() }
    }
}

// MARK: - Ajout et modification (admin)

struct ExclusiveEditorRequest: Identifiable {
    let id = UUID()
    let existing: Track?
}

struct ExclusiveEditorView: View {
    let existing: Track?
    var onDone: () -> Void
    @Environment(\.dismiss) private var dismiss

    @State private var title = ""
    @State private var artist = ""
    @State private var artistSource: String?
    @State private var artistSourceId: String?
    @State private var year = String(Calendar.current.component(.year, from: Date()))
    @State private var kind = "exclu"
    @State private var audioFile: URL?
    @State private var coverItem: PhotosPickerItem?
    @State private var coverData: Data?
    @State private var coverMime = "image/jpeg"
    @State private var results: [Artist] = []
    @State private var searchTask: Task<Void, Never>?
    @State private var showsFileImporter = false
    @State private var showsVersionImporter = false
    @State private var versions: [ExclusiveVersionDTO] = []
    @State private var isWorking = false
    @State private var progressText: String?
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            Form {
                if existing == nil {
                    Section("Fichier audio") {
                        Button {
                            showsFileImporter = true
                        } label: {
                            Label(audioFile?.lastPathComponent ?? "Choisir un fichier (MP3, FLAC, M4A…)", systemImage: "waveform")
                        }
                    }
                }
                Section {
                    TextField("Titre", text: $title)
                    TextField("Artiste", text: $artist)
                        .onChange(of: artist) { _, value in searchArtists(value) }
                    ForEach(results) { found in
                        Button {
                            artist = found.name
                            artistSource = found.source
                            artistSourceId = found.sourceId
                            results = []
                        } label: {
                            HStack(spacing: 10) {
                                Artwork(url: found.pictureURL, cornerRadius: 16, symbol: "person.fill").frame(width: 32, height: 32)
                                Text(found.name).foregroundStyle(Tone.primary)
                            }
                        }
                    }
                } header: {
                    Text("Titre")
                } footer: {
                    Text(artistSourceId == nil
                         ? "Choisis l'artiste dans la liste pour afficher l'exclu sur sa page."
                         : "✓ Rattaché à la fiche de l'artiste : l'exclu s'affichera sur sa page.")
                }
                Section {
                    TextField("Année", text: $year).keyboardType(.numberPad)
                    Picker("Type", selection: $kind) {
                        Text("Exclu").tag("exclu")
                        Text("Inédit (jamais sorti)").tag("inedit")
                    }
                    PhotosPicker(selection: $coverItem, matching: .images) {
                        Label(coverData == nil ? "Pochette (facultatif)" : "Pochette choisie ✓", systemImage: "photo")
                    }
                    .onChange(of: coverItem) { _, item in loadCover(item) }
                }
                if let existing {
                    Section {
                        ForEach(versions) { version in
                            HStack {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(version.label)
                                    Text(version.sizeLabel + (version.main ? " · fichier d'origine" : ""))
                                        .font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
                                }
                                Spacer()
                                if !version.main {
                                    Button("Retirer", role: .destructive) { removeVersion(existing, version) }
                                        .font(Typo.rowSubtitle)
                                }
                            }
                        }
                        Button { showsVersionImporter = true } label: {
                            Label("Ajouter une version (ex. le FLAC)", systemImage: "plus")
                        }
                    } header: {
                        Text("Qualités disponibles")
                    }
                }
                if let progressText {
                    Section { HStack(spacing: 10) { ProgressView(); Text(progressText) } }
                }
                if let errorMessage {
                    Section { Text(errorMessage).foregroundStyle(Tone.danger) }
                }
            }
            .navigationTitle(existing == nil ? "Ajouter un exclu" : "Modifier l'exclu")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Annuler") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button(existing == nil ? "Ajouter" : "Enregistrer") { save() }.disabled(isWorking)
                }
            }
            .fileImporter(isPresented: $showsFileImporter, allowedContentTypes: [.audio], allowsMultipleSelection: false) { result in
                if case .success(let urls) = result, let url = urls.first {
                    audioFile = url
                    if title.isEmpty { title = url.deletingPathExtension().lastPathComponent }
                }
            }
            .fileImporter(isPresented: $showsVersionImporter, allowedContentTypes: [.audio], allowsMultipleSelection: false) { result in
                if case .success(let urls) = result, let url = urls.first, let existing { addVersion(existing, url) }
            }
            .task {
                guard let existing else { return }
                title = existing.title
                artist = existing.artist
                artistSource = existing.artistSource
                artistSourceId = existing.artistSourceId
                year = existing.year ?? year
                kind = existing.tag == "Inédit" ? "inedit" : "exclu"
                await loadVersions(existing)
            }
        }
        .interactiveDismissDisabled(isWorking)
    }

    private func searchArtists(_ text: String) {
        artistSource = nil
        artistSourceId = nil
        searchTask?.cancel()
        let query = text.trimmingCharacters(in: .whitespaces)
        guard query.count >= 2 else { results = []; return }
        searchTask = Task {
            try? await Task.sleep(for: .milliseconds(300))
            guard !Task.isCancelled else { return }
            let found = (try? await APIClient.shared.searchArtists(query: query, limit: 5)) ?? []
            if !Task.isCancelled { results = found }
        }
    }

    private func loadCover(_ item: PhotosPickerItem?) {
        guard let item else { return }
        Task {
            if let data = try? await item.loadTransferable(type: Data.self) {
                coverData = data
                coverMime = item.supportedContentTypes.first?.preferredMIMEType ?? "image/jpeg"
            }
        }
    }

    private func loadVersions(_ track: Track) async {
        versions = (try? await APIClient.shared.exclusiveVersions(id: track.sourceId)) ?? []
    }

    private func save() {
        let trimmedTitle = title.trimmingCharacters(in: .whitespaces)
        let trimmedArtist = artist.trimmingCharacters(in: .whitespaces)
        guard !trimmedTitle.isEmpty, !trimmedArtist.isEmpty else { errorMessage = "Titre et artiste obligatoires."; return }
        if existing == nil && audioFile == nil { errorMessage = "Choisis un fichier audio."; return }
        isWorking = true
        errorMessage = nil
        Task {
            defer { isWorking = false; progressText = nil }
            do {
                var id = existing?.sourceId
                if let existing {
                    progressText = "Enregistrement…"
                    try await APIClient.shared.updateExclusive(
                        id: existing.sourceId, title: trimmedTitle, artist: trimmedArtist,
                        artistSource: artistSource, artistSourceId: artistSourceId, year: year, kind: kind
                    )
                } else if let audioFile {
                    progressText = "Envoi vers Drivecord…"
                    let scoped = audioFile.startAccessingSecurityScopedResource()
                    defer { if scoped { audioFile.stopAccessingSecurityScopedResource() } }
                    let made = try await APIClient.shared.addExclusive(
                        file: audioFile, title: trimmedTitle, artist: trimmedArtist,
                        artistSource: artistSource, artistSourceId: artistSourceId, year: year, kind: kind
                    )
                    id = made.sourceId
                }
                if let coverData, let id {
                    try await APIClient.shared.setExclusiveCover(id: id, image: coverData, mime: coverMime)
                }
                onDone()
                dismiss()
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }

    private func addVersion(_ track: Track, _ file: URL) {
        isWorking = true
        errorMessage = nil
        progressText = "Envoi de \(file.lastPathComponent) vers Drivecord…"
        Task {
            defer { isWorking = false; progressText = nil }
            let scoped = file.startAccessingSecurityScopedResource()
            defer { if scoped { file.stopAccessingSecurityScopedResource() } }
            do {
                _ = try await APIClient.shared.addExclusiveVersion(id: track.sourceId, file: file)
                await loadVersions(track)
                onDone()
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }

    private func removeVersion(_ track: Track, _ version: ExclusiveVersionDTO) {
        Task {
            do {
                try await APIClient.shared.deleteExclusiveVersion(id: track.sourceId, version: version.id)
                ExclusiveVersionChoice.shared.set(nil, for: track.sourceId)
                await loadVersions(track)
                onDone()
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }
}
