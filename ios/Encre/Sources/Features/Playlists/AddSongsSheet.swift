import SwiftUI

/// « Ajouter des morceaux » à une playlist : on cherche, on touche +, le titre entre dans la playlist.
struct AddSongsSheet: View {
    let playlistId: Int
    let existing: [Track]

    @Environment(\.dismiss) private var dismiss
    @State private var query = ""
    @State private var found: [Track] = []
    @State private var added: Set<String> = []
    @State private var isSearching = false
    @State private var addingId: String?
    @State private var errorMessage: String?
    @State private var searchTask: Task<Void, Never>?

    var body: some View {
        NavigationStack {
            List {
                if isSearching {
                    ProgressView().tint(.white).frame(maxWidth: .infinity).listRowBackground(Color.clear)
                } else if found.isEmpty {
                    Text(query.trimmingCharacters(in: .whitespaces).isEmpty ? "Tape le nom d'un morceau." : "Aucun résultat.")
                        .font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
                        .listRowBackground(Color.clear)
                }
                ForEach(found) { track in
                    HStack(spacing: 12) {
                        Artwork(url: track.coverURL, cornerRadius: 6).frame(width: 48, height: 48)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(track.title).font(Typo.rowTitle).foregroundStyle(Tone.primary).lineLimit(1)
                            Text([track.artist, track.album].compactMap { $0 }.joined(separator: " · "))
                                .font(Typo.rowSubtitle).foregroundStyle(Tone.secondary).lineLimit(1)
                        }
                        Spacer(minLength: 0)
                        if addingId == track.id {
                            ProgressView().tint(.white)
                        } else {
                            Button { Task { await add(track) } } label: {
                                Image(systemName: isIn(track) ? "checkmark" : "plus")
                                    .font(.system(size: 16, weight: .semibold))
                                    .foregroundStyle(Tone.primary)
                                    .frame(width: 36, height: 36)
                                    .background(Circle().fill(Tone.surfaceStrong))
                            }
                            .buttonStyle(.pressable)
                            .disabled(isIn(track))
                        }
                    }
                    .listRowBackground(Color.clear)
                }
                if let errorMessage {
                    Text(errorMessage).font(Typo.rowSubtitle).foregroundStyle(Tone.danger).listRowBackground(Color.clear)
                }
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
            .background(Tone.background)
            .navigationTitle("Ajouter des morceaux")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("OK") { dismiss() } } }
            .searchable(text: $query, placement: .navigationBarDrawer(displayMode: .always), prompt: "Titre, artiste, album…")
            .autocorrectionDisabled()
            .textInputAutocapitalization(.never)
            .onChange(of: query) { _, text in schedule(text) }
        }
        .presentationDetents([.large])
        .sensoryFeedback(.success, trigger: added.count)
    }

    private func isIn(_ track: Track) -> Bool {
        added.contains(track.id) || existing.contains { $0.id == track.id }
    }

    private func schedule(_ text: String) {
        searchTask?.cancel()
        let trimmed = text.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty else { found = []; isSearching = false; return }
        isSearching = true
        searchTask = Task {
            try? await Task.sleep(for: .milliseconds(300))
            guard !Task.isCancelled else { return }
            let response = try? await APIClient.shared.search(query: trimmed)
            guard !Task.isCancelled else { return }
            found = response?.tracks ?? []
            isSearching = false
        }
    }

    private func add(_ track: Track) async {
        addingId = track.id
        errorMessage = nil
        do {
            _ = try await APIClient.shared.addToPlaylist(id: playlistId, tracks: [track])
            added.insert(track.id)
        } catch {
            errorMessage = error.localizedDescription
        }
        addingId = nil
    }
}
