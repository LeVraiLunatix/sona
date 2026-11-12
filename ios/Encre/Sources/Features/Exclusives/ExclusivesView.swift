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

// MARK: - Exclus rangés par artiste

/// Les exclus d'un même artiste. Un artiste à identités (FEMTOGO…) s'affiche « FEMTO (archives) » avec le sceau SPK.
struct ExclusiveArtistGroup: Identifiable, Hashable {
    let id: String
    let source: String?
    let artistId: String?
    let name: String
    let isArchive: Bool
    let tracks: [Track]

    var label: String { isArchive ? archiveArtistName : name }

    static func groups(from tracks: [Track]) -> [ExclusiveArtistGroup] {
        var order: [String] = []
        var buckets: [String: [Track]] = [:]
        for track in tracks {
            let key = track.artistSourceId.map { "\(track.artistRouteSource):\($0)" } ?? "n:\(track.artist.folded)"
            if buckets[key] == nil { order.append(key) }
            buckets[key, default: []].append(track)
        }
        return order.compactMap { key in
            guard let list = buckets[key], let first = list.first else { return nil }
            // Le nom le plus fréquent : chez un artiste à identités, chaque titre porte le nom de son identité.
            var counts: [String: Int] = [:]
            for track in list { counts[track.artist, default: 0] += 1 }
            let name = counts.max { $0.value < $1.value }?.key ?? first.artist
            let sorted = list.sorted {
                let left = ($0.persona ?? "", $0.album ?? "", $0.trackNumber ?? 0, $0.title)
                let right = ($1.persona ?? "", $1.album ?? "", $1.trackNumber ?? 0, $1.title)
                return left < right
            }
            return ExclusiveArtistGroup(
                id: key, source: first.artistSourceId == nil ? nil : first.artistRouteSource, artistId: first.artistSourceId,
                name: name, isArchive: list.contains { $0.persona != nil }, tracks: sorted
            )
        }
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
    @State private var query = ""
    @State private var sortByCount = false

    private var artists: [ExclusiveArtistGroup] {
        let needle = query.trimmingCharacters(in: .whitespaces).folded
        let shown = ExclusiveArtistGroup.groups(from: tracks).filter {
            needle.isEmpty || $0.name.folded.contains(needle) || $0.label.folded.contains(needle)
        }
        return shown.sorted {
            if sortByCount, $0.tracks.count != $1.tracks.count { return $0.tracks.count > $1.tracks.count }
            return $0.label.localizedCaseInsensitiveCompare($1.label) == .orderedAscending
        }
    }

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 18) {
                Text("Des titres inédits, introuvables ailleurs : choisis un artiste pour voir ses exclus.")
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
                } else if !tracks.isEmpty {
                    HStack {
                        Text("\(artists.count) artiste\(artists.count > 1 ? "s" : "")")
                            .font(Typo.rowSubtitle).foregroundStyle(Tone.tertiary)
                        Spacer()
                        Picker("Tri", selection: $sortByCount) {
                            Text("A–Z").tag(false)
                            Text("Plus d'exclus").tag(true)
                        }
                        .pickerStyle(.segmented)
                        .frame(maxWidth: 210)
                    }
                    .padding(.horizontal, 20)

                    if artists.isEmpty {
                        EmptyState(systemImage: "magnifyingglass", title: "Aucun artiste", message: "Aucun artiste ne correspond à cette recherche.")
                    } else {
                        LazyVGrid(columns: [GridItem(.flexible(), spacing: 16), GridItem(.flexible(), spacing: 16)], spacing: 20) {
                            ForEach(artists) { group in
                                NavigationLink {
                                    ExclusiveArtistView(group: group, path: $path)
                                } label: {
                                    card(group)
                                }
                                .buttonStyle(.pressable)
                            }
                        }
                        .padding(.horizontal, 20)
                    }
                }
            }
            .padding(.top, 8)
            .padding(.bottom, 24)
        }
        .scrollIndicators(.hidden)
        .background(Tone.background)
        .navigationTitle("Exclus")
        .navigationBarTitleDisplayMode(.large)
        .searchable(text: $query, prompt: "Chercher un artiste")
        .overlay { if isLoading && tracks.isEmpty { ProgressView().tint(.white) } }
        .sheet(item: $editor) { request in
            ExclusiveEditorView(existing: request.existing) { Task { await load() } }
        }
        .task { await load() }
        .refreshable { await load() }
    }

    private func card(_ group: ExclusiveArtistGroup) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            ZStack {
                if group.isArchive {
                    SPKSeal().aspectRatio(1, contentMode: .fit)
                } else {
                    Artwork(url: group.tracks.first?.coverURL, cornerRadius: 12, symbol: "person.fill")
                        .aspectRatio(1, contentMode: .fit)
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            VStack(alignment: .leading, spacing: 1) {
                Text(group.label).font(Typo.rowTitle).foregroundStyle(Tone.primary).lineLimit(1)
                if group.isArchive {
                    Text("(archives)").font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
                }
                Text("\(group.tracks.count) exclu\(group.tracks.count > 1 ? "s" : "")")
                    .font(Typo.rowSubtitle).foregroundStyle(Tone.tertiary)
            }
        }
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

// MARK: - Exclus d'un artiste

/// Les exclus d'un artiste, triés (identité, album, numéro) et filtrables.
struct ExclusiveArtistView: View {
    let group: ExclusiveArtistGroup
    @Binding var path: NavigationPath
    @ObservedObject private var player = PlayerManager.shared
    @State private var query = ""

    private struct ReleaseSection: Identifiable {
        let id: String
        let title: String
        let tracks: [Track]
    }

    private var filtered: [Track] {
        let needle = query.trimmingCharacters(in: .whitespaces).folded
        guard !needle.isEmpty else { return group.tracks }
        return group.tracks.filter {
            "\($0.title) \($0.album ?? "") \($0.persona ?? "") \($0.artist)".folded.contains(needle)
        }
    }

    private var sections: [ReleaseSection] {
        var order: [String] = []
        var buckets: [String: [Track]] = [:]
        for track in filtered {
            let key = "\(track.persona ?? "")\u{1F}\(track.album ?? "")"
            if buckets[key] == nil { order.append(key) }
            buckets[key, default: []].append(track)
        }
        return order.map { key in
            let list = buckets[key] ?? []
            let title = [list.first?.persona, list.first?.album.map { FeatSplit.split($0).title }]
                .compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " · ")
            return ReleaseSection(id: key, title: title.isEmpty ? "Titres" : title, tracks: list)
        }
    }

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 22) {
                VStack(alignment: .leading, spacing: 14) {
                    if group.isArchive {
                        HStack(spacing: 16) {
                            SPKSeal(size: 84)
                            VStack(alignment: .leading, spacing: 3) {
                                Text("EXCLUS · ARCHIVES").font(Typo.caption).tracking(0.6).foregroundStyle(Tone.tertiary)
                                Text(group.label).font(Typo.largeTitle).foregroundStyle(Tone.primary)
                                Text("(archives)").font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
                            }
                        }
                    }
                    Text("\(group.tracks.count) exclu\(group.tracks.count > 1 ? "s" : "")")
                        .font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
                    HStack(spacing: 12) {
                        PillButton(title: "Lecture", systemImage: "play.fill") {
                            if let first = group.tracks.first { player.play(first, context: group.tracks, name: group.label) }
                        }
                        PillButton(title: "Aléatoire", systemImage: "shuffle", kind: .secondary) {
                            player.playShuffled(group.tracks, name: group.label)
                        }
                    }
                    if let source = group.source, let artistId = group.artistId {
                        PillButton(title: "Voir la page", systemImage: "person.crop.circle", kind: .secondary) {
                            path.append(Route.artist(source: source, id: artistId))
                        }
                    }
                }
                .padding(.horizontal, 20)

                if sections.isEmpty {
                    Text("Aucun exclu ne correspond à « \(query) ».")
                        .font(Typo.rowSubtitle).foregroundStyle(Tone.secondary).padding(.horizontal, 20)
                }
                ForEach(sections) { section in
                    VStack(alignment: .leading, spacing: 8) {
                        HStack(alignment: .firstTextBaseline) {
                            Text(section.title).font(Typo.headline).foregroundStyle(Tone.primary).lineLimit(1)
                            Spacer()
                            Text("\(section.tracks.count) titre\(section.tracks.count > 1 ? "s" : "")")
                                .font(Typo.rowSubtitle).foregroundStyle(Tone.tertiary)
                        }
                        LazyVStack(spacing: 2) {
                            ForEach(section.tracks) { track in
                                TrackRow(
                                    track: track,
                                    isCurrent: player.current?.id == track.id,
                                    isPlaying: player.isPlaying
                                ) {
                                    player.play(track, context: group.tracks, name: group.label)
                                }
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
        .navigationTitle(group.isArchive ? "" : group.label)
        .navigationBarTitleDisplayMode(.inline)
        .searchable(text: $query, prompt: "Chercher un titre, un album…")
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
    @State private var persona = ""
    @State private var album = ""
    @State private var albumKind = "album"
    @State private var trackNumber = ""
    @State private var releaseOrder = ""
    /// Place d'origine dans la discographie : on ne renvoie la sortie au serveur que si elle a changé.
    @State private var initialRelease = ExclusiveReleaseInfo()
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
                Section {
                    TextField("Identité (ex. baby hayabusa)", text: $persona)
                    TextField("Album, EP ou single", text: $album)
                    Picker("Sortie", selection: $albumKind) {
                        Text("Album").tag("album")
                        Text("EP").tag("ep")
                        Text("Single").tag("single")
                    }
                    TextField("Numéro de piste", text: $trackNumber).keyboardType(.numberPad)
                    TextField("Rang de la sortie", text: $releaseOrder).keyboardType(.numberPad)
                } header: {
                    Text("Discographie (facultatif)")
                } footer: {
                    Text("Pour un artiste à identités : l'identité et l'album rangent le titre dans sa page d'artiste.")
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
                persona = existing.persona ?? ""
                album = existing.persona == nil ? "" : (existing.album ?? "")
                trackNumber = existing.trackNumber.map(String.init) ?? ""
                initialRelease = currentRelease
                await loadVersions(existing)
                await loadReleaseDetails(existing)
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

    private var currentRelease: ExclusiveReleaseInfo {
        ExclusiveReleaseInfo(
            persona: persona.trimmingCharacters(in: .whitespaces),
            album: album.trimmingCharacters(in: .whitespaces),
            albumKind: albumKind,
            trackNumber: Int(trackNumber.trimmingCharacters(in: .whitespaces)),
            releaseOrder: Int(releaseOrder.trimmingCharacters(in: .whitespaces))
        )
    }

    /// Le type et le rang de la sortie ne figurent pas sur le titre : on les relit dans la discographie.
    private func loadReleaseDetails(_ track: Track) async {
        guard track.persona != nil, let id = track.artistSourceId,
              let disco = try? await APIClient.shared.artistDiscography(source: track.artistRouteSource, id: id),
              let release = disco.releases.first(where: { $0.persona == track.persona && $0.album == track.album })
        else { return }
        albumKind = release.kind
        releaseOrder = release.order > 0 ? String(release.order) : ""
        initialRelease = currentRelease
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
                        artistSource: artistSource, artistSourceId: artistSourceId, year: year, kind: kind,
                        release: currentRelease == initialRelease ? nil : currentRelease
                    )
                } else if let audioFile {
                    progressText = "Envoi vers Drivecord…"
                    let scoped = audioFile.startAccessingSecurityScopedResource()
                    defer { if scoped { audioFile.stopAccessingSecurityScopedResource() } }
                    let made = try await APIClient.shared.addExclusive(
                        file: audioFile, title: trimmedTitle, artist: trimmedArtist,
                        artistSource: artistSource, artistSourceId: artistSourceId, year: year, kind: kind,
                        release: currentRelease
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
