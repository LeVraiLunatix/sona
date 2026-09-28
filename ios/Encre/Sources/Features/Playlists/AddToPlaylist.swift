import SwiftUI

/// « Ajouter à une playlist… » : action disponible partout où un écran peut
/// présenter la feuille de choix (voir `RootTabView`, `FullPlayerView`).
/// Absente de l'environnement, l'entrée de menu n'apparaît pas.
struct AddToPlaylistAction {
    let perform: ([Track]) -> Void

    init(_ perform: @escaping ([Track]) -> Void) {
        self.perform = perform
    }

    func callAsFunction(_ tracks: [Track]) { perform(tracks) }
}

private struct AddToPlaylistKey: EnvironmentKey {
    static let defaultValue: AddToPlaylistAction? = nil
}

extension EnvironmentValues {
    var addToPlaylist: AddToPlaylistAction? {
        get { self[AddToPlaylistKey.self] }
        set { self[AddToPlaylistKey.self] = newValue }
    }
}

struct PlaylistPickRequest: Identifiable {
    let id = UUID()
    let tracks: [Track]
}

/// Feuille de choix : les playlists de l'utilisateur (la plus récente en
/// haut) et « Nouvelle playlist ». Un tap ajoute et referme.
struct AddToPlaylistSheet: View {
    let tracks: [Track]
    @Environment(\.dismiss) private var dismiss
    @State private var playlists: [UserPlaylist] = []
    @State private var isLoading = true
    @State private var addingId: Int?
    @State private var errorMessage: String?
    @State private var showingNew = false
    @State private var added = 0

    var body: some View {
        NavigationStack {
            List {
                Button { showingNew = true } label: {
                    HStack(spacing: 14) {
                        Image(systemName: "plus")
                            .font(.system(size: 20, weight: .semibold))
                            .foregroundStyle(Tone.primary)
                            .frame(width: 52, height: 52)
                            .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(Tone.surfaceStrong))
                        Text("Nouvelle playlist").font(Typo.rowTitle).foregroundStyle(Tone.primary)
                    }
                }
                .listRowBackground(Color.clear)

                if isLoading && playlists.isEmpty {
                    ProgressView().tint(.white).frame(maxWidth: .infinity).listRowBackground(Color.clear)
                }
                ForEach(playlists.filter { !$0.isImporting }) { playlist in
                    Button { Task { await add(to: playlist) } } label: {
                        HStack(spacing: 14) {
                            PlaylistCover(playlist: playlist, cornerRadius: 8).frame(width: 52, height: 52)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(playlist.name).font(Typo.rowTitle).foregroundStyle(Tone.primary).lineLimit(1)
                                Text(playlist.trackCountLabel).font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
                            }
                            Spacer()
                            if addingId == playlist.id { ProgressView().tint(.white) }
                        }
                    }
                    .disabled(addingId != nil)
                    .listRowBackground(Color.clear)
                }
                if let errorMessage {
                    Text(errorMessage).font(Typo.rowSubtitle).foregroundStyle(Tone.danger).listRowBackground(Color.clear)
                }
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
            .background(Tone.background)
            .navigationTitle(tracks.count == 1 ? "Ajouter à une playlist" : "Ajouter \(tracks.count) titres")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Annuler") { dismiss() }
                }
            }
            .sheet(isPresented: $showingNew) {
                NewPlaylistSheet(initialTracks: tracks) { _ in
                    added += 1
                    dismiss()
                }
            }
        }
        .presentationDetents([.medium, .large])
        .sensoryFeedback(.success, trigger: added)
        .task { await load() }
    }

    private func load() async {
        isLoading = true
        do {
            playlists = try await APIClient.shared.playlists()
        } catch {
            errorMessage = error.localizedDescription
        }
        isLoading = false
    }

    private func add(to playlist: UserPlaylist) async {
        addingId = playlist.id
        errorMessage = nil
        do {
            _ = try await APIClient.shared.addToPlaylist(id: playlist.id, tracks: tracks)
            added += 1
            try? await Task.sleep(for: .milliseconds(250))
            dismiss()
        } catch {
            errorMessage = error.localizedDescription
        }
        addingId = nil
    }
}

/// Nom de la nouvelle playlist (éventuellement créée avec des titres).
struct NewPlaylistSheet: View {
    var initialTracks: [Track] = []
    var onCreated: (UserPlaylist) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var isSaving = false
    @State private var errorMessage: String?
    @FocusState private var focused: Bool

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 16) {
                TextField("Nom de la playlist", text: $name)
                    .font(.system(size: 22, weight: .semibold))
                    .foregroundStyle(Tone.primary)
                    .focused($focused)
                    .submitLabel(.done)
                    .onSubmit { Task { await create() } }
                    .padding(16)
                    .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Tone.surfaceStrong))
                if let errorMessage {
                    Text(errorMessage).font(Typo.rowSubtitle).foregroundStyle(Tone.danger)
                }
                Spacer()
            }
            .padding(20)
            .background(Tone.background)
            .navigationTitle("Nouvelle playlist")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Annuler") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    if isSaving {
                        ProgressView().tint(.white)
                    } else {
                        Button("Créer") { Task { await create() } }
                            .disabled(name.trimmingCharacters(in: .whitespaces).isEmpty)
                    }
                }
            }
        }
        .presentationDetents([.height(220)])
        .onAppear { focused = true }
    }

    private func create() async {
        let trimmed = name.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty, !isSaving else { return }
        isSaving = true
        errorMessage = nil
        do {
            let playlist = try await APIClient.shared.createPlaylist(name: trimmed, tracks: initialTracks)
            dismiss()
            onCreated(playlist)
        } catch {
            errorMessage = error.localizedDescription
        }
        isSaving = false
    }
}

/// Import d'une playlist Deezer, Spotify ou Apple Music par son lien de
/// partage.
struct ImportPlaylistSheet: View {
    var onStarted: (UserPlaylist) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var link = ""
    @State private var isSending = false
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 18) {
                HStack(spacing: 10) {
                    ForEach(["Spotify", "Apple Music", "Deezer"], id: \.self) { name in
                        Text(name)
                            .font(Typo.caption)
                            .foregroundStyle(Tone.secondary)
                            .padding(.horizontal, 10)
                            .padding(.vertical, 6)
                            .background(Capsule().fill(Tone.surfaceStrong))
                    }
                }
                Text("Dans l'app d'origine : Partager › Copier le lien, puis colle-le ici. La playlist doit être publique.")
                    .font(Typo.rowSubtitle)
                    .foregroundStyle(Tone.secondary)

                HStack(spacing: 10) {
                    TextField("https://open.spotify.com/playlist/…", text: $link)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                        .foregroundStyle(Tone.primary)
                    PasteButton(payloadType: String.self) { strings in
                        if let first = strings.first { link = first }
                    }
                    .labelStyle(.iconOnly)
                    .buttonBorderShape(.circle)
                    .tint(.white)
                }
                .padding(14)
                .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Tone.surfaceStrong))

                if let errorMessage {
                    Text(errorMessage).font(Typo.rowSubtitle).foregroundStyle(Tone.danger)
                }

                PillButton(title: "Importer", systemImage: "square.and.arrow.down", isLoading: isSending) {
                    Task { await start() }
                }
                .disabled(link.trimmingCharacters(in: .whitespaces).isEmpty)
                Spacer()
            }
            .padding(20)
            .background(Tone.background)
            .navigationTitle("Importer une playlist")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Annuler") { dismiss() }
                }
            }
        }
        .presentationDetents([.medium])
    }

    private func start() async {
        isSending = true
        errorMessage = nil
        do {
            let playlist = try await APIClient.shared.importPlaylist(url: link.trimmingCharacters(in: .whitespacesAndNewlines))
            dismiss()
            onStarted(playlist)
        } catch {
            errorMessage = error.localizedDescription
        }
        isSending = false
    }
}

/// Pochette de playlist : son image si elle en a une, sinon une mosaïque
/// des pochettes de ses premiers titres (ou une seule), sinon une note.
struct PlaylistCover: View {
    let playlist: UserPlaylist
    var cornerRadius: CGFloat = 10

    var body: some View {
        Group {
            if let url = playlist.coverURL {
                Artwork(url: url, cornerRadius: cornerRadius, symbol: "music.note.list")
            } else if playlist.covers.count >= 4 {
                GeometryReader { proxy in
                    let side = proxy.size.width / 2
                    VStack(spacing: 0) {
                        ForEach(0..<2, id: \.self) { row in
                            HStack(spacing: 0) {
                                ForEach(0..<2, id: \.self) { column in
                                    Artwork(url: playlist.covers[row * 2 + column], cornerRadius: 0)
                                        .frame(width: side, height: side)
                                }
                            }
                        }
                    }
                }
                .aspectRatio(1, contentMode: .fit)
                .clipShape(RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
            } else {
                Artwork(url: playlist.covers.first, cornerRadius: cornerRadius, symbol: "music.note.list")
            }
        }
    }
}

extension UserPlaylist {
    var trackCountLabel: String {
        if isImporting {
            if let total = importTotal { return "Import… \(importDone)/\(total)" }
            return "Import en cours…"
        }
        if importFailed { return "Import échoué" }
        return trackCount <= 1 ? "\(trackCount) titre" : "\(trackCount) titres"
    }
}
