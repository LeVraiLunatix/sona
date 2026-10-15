import SwiftUI

/// Carte en tête d'une playlist importée : ce qu'il reste à vérifier, et ce
/// que la dernière resynchronisation a ajouté. Un appui ouvre le rapport.
struct ImportSummaryCard: View {
    let playlist: UserPlaylist
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 14) {
                Image(systemName: uncertain > 0 ? "exclamationmark.circle" : "checklist")
                    .font(.system(size: 22, weight: .semibold))
                    .foregroundStyle(Tone.primary)
                    .frame(width: 30)
                VStack(alignment: .leading, spacing: 3) {
                    Text(title).font(Typo.rowTitle).foregroundStyle(Tone.primary)
                    Text(detail).font(Typo.caption).foregroundStyle(Tone.secondary)
                }
                Spacer(minLength: 8)
                Image(systemName: "chevron.right")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(Tone.tertiary)
            }
            .padding(14)
            .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Tone.surfaceStrong))
        }
        .buttonStyle(.pressable(scale: 0.98))
        .accessibilityHint("Ouvre le rapport d'import")
    }

    private var uncertain: Int { playlist.importUncertain ?? 0 }
    private var added: Int { playlist.importAdded ?? 0 }

    private var title: String {
        if uncertain > 0 { return uncertain == 1 ? "1 titre à vérifier" : "\(uncertain) titres à vérifier" }
        if playlist.importMissing > 0 {
            return playlist.importMissing == 1 ? "1 titre introuvable" : "\(playlist.importMissing) titres introuvables"
        }
        return added == 1 ? "1 nouveau titre" : "\(added) nouveaux titres"
    }

    private var detail: String {
        var parts: [String] = []
        if uncertain > 0 && playlist.importMissing > 0 {
            parts.append(playlist.importMissing == 1 ? "1 introuvable" : "\(playlist.importMissing) introuvables")
        }
        if added > 0 && (uncertain > 0 || playlist.importMissing > 0) {
            parts.append("+\(added) à la dernière synchro")
        }
        parts.append(uncertain + playlist.importMissing > 0 ? "Vérifie et corrige en un geste" : "Ajoutés depuis la playlist d'origine")
        return parts.joined(separator: " · ")
    }
}

/// Rapport d'import titre par titre : trouvés, à vérifier, introuvables.
/// Balayer un titre le valide (vers la droite) ou le retire (vers la
/// gauche) ; un appui ouvre la correction (autre titre, ou lien collé).
struct ImportReportView: View {
    let playlistId: Int

    @Environment(\.dismiss) private var dismiss
    @State private var report: ImportReport?
    @State private var filter = "uncertain"
    @State private var errorMessage: String?
    @State private var fixing: ImportItem?

    private struct Filter: Hashable {
        let key: String
        let label: String
        let icon: String
    }

    private static let filters = [
        Filter(key: "uncertain", label: "À vérifier", icon: "exclamationmark.circle"),
        Filter(key: "missing", label: "Introuvables", icon: "xmark.circle"),
        Filter(key: "found", label: "Trouvés", icon: "checkmark.circle"),
    ]

    var body: some View {
        NavigationStack {
            Group {
                if let report {
                    content(report)
                } else if let errorMessage {
                    EmptyState(systemImage: "exclamationmark.triangle", title: "Rapport indisponible", message: errorMessage)
                        .padding(.top, 80)
                } else {
                    ProgressView().tint(.white).frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            }
            .background(Tone.background)
            .navigationTitle("Rapport d'import")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("OK") { dismiss() }
                }
            }
        }
        .sheet(item: $fixing) { item in
            ImportFixSheet(playlistId: playlistId, item: item) { updated in apply(updated) }
        }
        .task { await load() }
    }

    private func content(_ report: ImportReport) -> some View {
        let shown = report.items.filter { $0.status == filter }
        return List {
            HStack(spacing: 10) {
                ForEach(Self.filters, id: \.key) { entry in
                    filterTile(entry.key, label: entry.label, icon: entry.icon, count: report.counts[entry.key] ?? 0)
                }
            }
            .padding(.vertical, 8)
            .reportRow()

            if shown.isEmpty {
                EmptyState(
                    systemImage: filter == "found" ? "music.note" : "checkmark.seal",
                    title: filter == "uncertain" ? "Rien à vérifier" : filter == "missing" ? "Rien d'introuvable" : "Aucun titre",
                    message: filter == "found" ? nil : "Tout est en ordre de ce côté."
                )
                .padding(.top, 40)
                .reportRow()
            }

            ForEach(shown) { item in
                row(item)
                    .reportRow()
                    .swipeActions(edge: .leading, allowsFullSwipe: true) {
                        if item.matched != nil && item.status != "found" {
                            Button { Task { await fix(item, action: "accept") } } label: {
                                Label("C'est le bon", systemImage: "checkmark")
                            }
                            .tint(.green)
                        }
                    }
                    .swipeActions(edge: .trailing, allowsFullSwipe: true) {
                        if item.entryId != nil {
                            Button(role: .destructive) { Task { await fix(item, action: "remove") } } label: {
                                Label("Retirer", systemImage: "minus.circle")
                            }
                        }
                    }
            }
        }
        .listStyle(.plain)
        .scrollContentBackground(.hidden)
        .refreshable { await load() }
        .animation(Motion.smooth, value: report.items)
        .animation(Motion.snappy, value: filter)
    }

    private func filterTile(_ key: String, label: String, icon: String, count: Int) -> some View {
        let selected = filter == key
        return Button { filter = key } label: {
            VStack(spacing: 4) {
                Image(systemName: icon).font(.system(size: 16, weight: .semibold))
                Text("\(count)").font(.system(size: 20, weight: .bold).monospacedDigit())
                    .contentTransition(.numericText(value: Double(count)))
                Text(label).font(Typo.caption)
            }
            .foregroundStyle(selected ? Color.black : Tone.primary)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 12)
            .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(selected ? Color.white : Tone.surfaceStrong))
        }
        .buttonStyle(.pressable(scale: 0.95))
        .accessibilityLabel("\(label) : \(count)")
        .accessibilityAddTraits(selected ? .isSelected : [])
    }

    private func row(_ item: ImportItem) -> some View {
        Button { fixing = item } label: {
            HStack(alignment: .top, spacing: 12) {
                Artwork(url: item.matched?.coverURL ?? item.original.coverURL, cornerRadius: 6)
                    .frame(width: 48, height: 48)
                VStack(alignment: .leading, spacing: 3) {
                    Text(item.original.title).font(Typo.rowTitle).foregroundStyle(Tone.primary).lineLimit(1)
                    Text("\(item.original.artist) · \(sourceName(item.original.source))")
                        .font(Typo.rowSubtitle).foregroundStyle(Tone.secondary).lineLimit(1)
                    if let matched = item.matched, matched.title != item.original.title || matched.artist != item.original.artist {
                        Label("\(matched.title) — \(matched.artist)", systemImage: "arrow.turn.down.right")
                            .font(Typo.rowSubtitle).foregroundStyle(Tone.primary.opacity(0.85)).lineLimit(1)
                    }
                    if let reason = item.reason {
                        Text(reason).font(Typo.caption).foregroundStyle(Tone.tertiary).lineLimit(2)
                    }
                }
                Spacer(minLength: 6)
                Image(systemName: item.fixed ? "hand.thumbsup.fill" : "chevron.right")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(Tone.tertiary)
                    .padding(.top, 4)
            }
            .padding(.vertical, 8)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    private func load() async {
        do {
            let fresh = try await APIClient.shared.importReport(playlistId: playlistId)
            if report == nil {
                // Premier affichage : le filtre qui a du travail.
                filter = (fresh.counts["uncertain"] ?? 0) > 0 ? "uncertain" : (fresh.counts["missing"] ?? 0) > 0 ? "missing" : "found"
            }
            report = fresh
            errorMessage = nil
        } catch {
            if report == nil { errorMessage = error.localizedDescription }
        }
    }

    private func fix(_ item: ImportItem, action: String) async {
        if let updated = try? await APIClient.shared.fixImportItem(playlistId: playlistId, itemId: item.id, action: action) {
            apply(updated)
        } else {
            await load()
        }
    }

    /// Titre corrigé : remis à sa place, compteurs ajustés sans recharger.
    private func apply(_ updated: ImportItem) {
        guard var current = report, let index = current.items.firstIndex(where: { $0.id == updated.id }) else { return }
        let before = current.items[index].status
        current.items[index] = updated
        if before != updated.status {
            current.counts[before, default: 1] -= 1
            current.counts[updated.status, default: 0] += 1
        }
        report = current
    }
}

/// « Ça, c'est le bon titre » : valider, chercher un autre titre au
/// catalogue, coller un lien YouTube / SoundCloud, ou retirer le titre.
struct ImportFixSheet: View {
    let playlistId: Int
    let item: ImportItem
    var onFixed: (ImportItem) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var query = ""
    @State private var results: [Track] = []
    @State private var searching = false
    @State private var link = ""
    @State private var sending = false
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            List {
                Section {
                    trackLine(item.original, caption: sourceName(item.original.source))
                    if let reason = item.reason {
                        Text(reason).font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
                    }
                } header: {
                    Text("Dans la playlist d'origine")
                }

                if let matched = item.matched {
                    Section {
                        trackLine(matched, caption: sourceName(matched.source))
                        if item.status != "found" {
                            Button { Task { await send("accept") } } label: {
                                Label("C'est le bon titre", systemImage: "checkmark.circle")
                            }
                        }
                    } header: {
                        Text("Retenu par Sona")
                    }
                }

                Section {
                    HStack {
                        Image(systemName: "magnifyingglass").foregroundStyle(Tone.tertiary)
                        TextField("Titre, artiste", text: $query)
                            .submitLabel(.search)
                            .onSubmit { Task { await search() } }
                            .autocorrectionDisabled()
                        if searching { ProgressView().tint(.white) }
                    }
                    ForEach(results) { track in
                        Button { Task { await send("replace", track: track) } } label: {
                            trackLine(track, caption: track.album ?? sourceName(track.source))
                        }
                        .buttonStyle(.plain)
                    }
                } header: {
                    Text("Choisir un autre titre")
                }

                Section {
                    HStack(spacing: 10) {
                        TextField("https://youtu.be/… ou soundcloud.com/…", text: $link)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .keyboardType(.URL)
                        PasteButton(payloadType: String.self) { strings in
                            if let first = strings.first { link = first }
                        }
                        .labelStyle(.iconOnly)
                        .buttonBorderShape(.circle)
                        .tint(.white)
                    }
                    Button { Task { await send("link", url: link.trimmingCharacters(in: .whitespacesAndNewlines)) } } label: {
                        Label("Utiliser ce lien", systemImage: "link")
                    }
                    .disabled(link.trimmingCharacters(in: .whitespaces).isEmpty)
                } header: {
                    Text("Ou coller un lien YouTube / SoundCloud")
                } footer: {
                    Text("Le titre se lira depuis cet audio-là.")
                }

                if item.entryId != nil {
                    Section {
                        Button(role: .destructive) { Task { await send("remove") } } label: {
                            Label("Retirer de la playlist", systemImage: "minus.circle")
                        }
                    }
                }

                if let errorMessage {
                    Text(errorMessage).font(Typo.rowSubtitle).foregroundStyle(Tone.danger)
                }
            }
            .scrollContentBackground(.hidden)
            .background(Tone.background)
            .disabled(sending)
            .overlay { if sending { ProgressView().tint(.white) } }
            .navigationTitle("Corriger le titre")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Annuler") { dismiss() }
                }
            }
            .task {
                query = "\(item.original.artist) \(item.original.title)"
                await search()
            }
        }
        .presentationDetents([.large])
    }

    private func trackLine(_ track: Track, caption: String) -> some View {
        HStack(spacing: 12) {
            Artwork(url: track.coverURL, cornerRadius: 6).frame(width: 44, height: 44)
            VStack(alignment: .leading, spacing: 2) {
                Text(track.title).font(Typo.rowTitle).foregroundStyle(Tone.primary).lineLimit(1)
                Text("\(track.artist) · \(caption)").font(Typo.rowSubtitle).foregroundStyle(Tone.secondary).lineLimit(1)
            }
            Spacer(minLength: 0)
            if let duration = track.durationSeconds {
                Text(String(format: "%d:%02d", duration / 60, duration % 60))
                    .font(Typo.mono).foregroundStyle(Tone.tertiary)
            }
        }
        .contentShape(Rectangle())
    }

    private func search() async {
        let text = query.trimmingCharacters(in: .whitespaces)
        guard !text.isEmpty else { return }
        searching = true
        defer { searching = false }
        results = (try? await APIClient.shared.search(query: text).tracks.prefix(8).map { $0 }) ?? []
    }

    private func send(_ action: String, track: Track? = nil, url: String? = nil) async {
        sending = true
        errorMessage = nil
        defer { sending = false }
        do {
            let updated = try await APIClient.shared.fixImportItem(
                playlistId: playlistId, itemId: item.id, action: action, track: track, url: url
            )
            onFixed(updated)
            dismiss()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

/// « Deezer », « Spotify »… pour une source de titre.
func sourceName(_ source: String) -> String {
    switch source {
    case "deezer": "Deezer"
    case "spotify": "Spotify"
    case "apple": "Apple Music"
    case "youtube": "YouTube"
    case "soundcloud": "SoundCloud"
    default: source
    }
}

private extension View {
    func reportRow() -> some View {
        self
            .listRowBackground(Color.clear)
            .listRowSeparator(.hidden)
            .listRowInsets(EdgeInsets(top: 0, leading: 20, bottom: 0, trailing: 20))
    }
}
