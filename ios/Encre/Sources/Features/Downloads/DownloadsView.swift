import SwiftUI

/// Titres gardés sur l'iPhone : écoute hors ligne, file de téléchargement,
/// place occupée.
struct DownloadsView: View {
    @Binding var path: NavigationPath
    @ObservedObject private var downloads = DownloadManager.shared
    @EnvironmentObject private var player: PlayerManager
    @State private var confirmingClear = false

    var body: some View {
        List {
            header.plainDownloadRow()

            if !downloads.queue.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        ProgressView().tint(.white).controlSize(.small)
                        Text("\(downloads.queue.count) en attente")
                            .font(Typo.rowSubtitle)
                            .foregroundStyle(Tone.secondary)
                        Spacer()
                        Button("Annuler") { downloads.cancelAll() }
                            .font(Typo.rowSubtitle)
                            .foregroundStyle(Tone.secondary)
                    }
                    if let active = downloads.queue.first(where: { $0.id == downloads.activeId }) {
                        Text("\(active.title) — \(active.artist)")
                            .font(Typo.caption)
                            .foregroundStyle(Tone.tertiary)
                            .lineLimit(1)
                    }
                }
                .padding(.vertical, 8)
                .plainDownloadRow()
            }

            if downloads.items.isEmpty && downloads.queue.isEmpty {
                EmptyState(
                    systemImage: "arrow.down.circle",
                    title: "Aucun téléchargement",
                    message: "Appui long sur un titre › Télécharger, ou ⋯ sur une playlist ou un album, pour l'écouter sans réseau."
                )
                .plainDownloadRow()
            }

            ForEach(Array(downloads.items.enumerated()), id: \.element.id) { index, item in
                TrackRow(
                    track: item.track,
                    isCurrent: player.current?.id == item.track.id,
                    isPlaying: player.isPlaying
                ) {
                    let tracks = downloads.tracks
                    player.play(tracks[index], context: tracks, name: "Téléchargements")
                }
                .plainDownloadRow()
                .swipeActions(edge: .trailing, allowsFullSwipe: true) {
                    Button(role: .destructive) {
                        withAnimation(Motion.smooth) { downloads.remove(item.track) }
                    } label: {
                        Label("Supprimer", systemImage: "trash")
                    }
                }
            }
        }
        .listStyle(.plain)
        .scrollContentBackground(.hidden)
        .background(Tone.background)
        .navigationTitle("Téléchargements")
        .navigationBarTitleDisplayMode(.large)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Menu {
                    Toggle(isOn: Binding(get: { downloads.wifiOnly }, set: { downloads.wifiOnly = $0 })) {
                        Label("Wi-Fi uniquement", systemImage: "wifi")
                    }
                    Button(role: .destructive) { confirmingClear = true } label: {
                        Label("Tout supprimer", systemImage: "trash")
                    }
                    .disabled(downloads.items.isEmpty)
                } label: {
                    Image(systemName: "ellipsis")
                }
            }
        }
        .confirmationDialog("Supprimer tous les téléchargements ?", isPresented: $confirmingClear, titleVisibility: .visible) {
            Button("Tout supprimer", role: .destructive) { downloads.removeAll() }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(summary)
                .font(Typo.rowSubtitle)
                .foregroundStyle(Tone.secondary)
            HStack(spacing: 12) {
                PillButton(title: "Lecture", systemImage: "play.fill") {
                    let tracks = downloads.tracks
                    if let first = tracks.first { player.play(first, context: tracks, name: "Téléchargements") }
                }
                PillButton(title: "Aléatoire", systemImage: "shuffle", kind: .secondary) {
                    let tracks = downloads.tracks.shuffled()
                    if let first = tracks.first { player.play(first, context: tracks, name: "Téléchargements") }
                }
            }
            .disabled(downloads.items.isEmpty)
        }
        .padding(.bottom, 12)
    }

    private var summary: String {
        let count = downloads.items.count
        let titles = count <= 1 ? "\(count) titre" : "\(count) titres"
        return "\(titles) · \(downloads.totalBytes.byteLabel) sur l'iPhone"
    }
}

private extension View {
    func plainDownloadRow() -> some View {
        self
            .listRowBackground(Color.clear)
            .listRowSeparator(.hidden)
            .listRowInsets(EdgeInsets(top: 0, leading: 20, bottom: 0, trailing: 20))
    }
}

/// Bouton / état de téléchargement d'une liste (playlist, album) : pour les
/// menus « ⋯ » des fiches.
struct DownloadMenuItems: View {
    let tracks: [Track]
    @ObservedObject private var downloads = DownloadManager.shared

    var body: some View {
        if downloads.allDownloaded(tracks) {
            Button(role: .destructive) { downloads.remove(tracks) } label: {
                Label("Supprimer les téléchargements", systemImage: "trash")
            }
        } else {
            Button { downloads.download(tracks) } label: {
                Label("Télécharger", systemImage: "arrow.down.circle")
            }
            .disabled(tracks.isEmpty)
            if downloads.progress(of: tracks).done > 0 {
                Button(role: .destructive) { downloads.remove(tracks) } label: {
                    Label("Supprimer les téléchargements", systemImage: "trash")
                }
            }
        }
    }
}

/// « ⬇︎ 12 / 40 téléchargés » sous l'en-tête d'une playlist ou d'un album.
struct DownloadStatusLine: View {
    let tracks: [Track]
    @ObservedObject private var downloads = DownloadManager.shared

    var body: some View {
        let progress = downloads.progress(of: tracks)
        if progress.done > 0 || progress.pending > 0 {
            HStack(spacing: 6) {
                if progress.pending > 0 {
                    ProgressView().controlSize(.mini).tint(.white)
                } else {
                    Image(systemName: "arrow.down.circle.fill")
                }
                Text(progress.done == tracks.count
                     ? "Téléchargé"
                     : "\(progress.done) / \(tracks.count) téléchargés")
                    .contentTransition(.numericText())
            }
            .font(Typo.caption)
            .foregroundStyle(Tone.secondary)
            .animation(Motion.smooth, value: progress.done)
        }
    }
}

/// Entrée « Téléchargements » de la bibliothèque.
struct DownloadsRow: View {
    var action: () -> Void
    @ObservedObject private var downloads = DownloadManager.shared

    var body: some View {
        Button(action: action) {
            HStack(spacing: 14) {
                Image(systemName: "arrow.down.circle.fill")
                    .font(.system(size: 22, weight: .semibold))
                    .foregroundStyle(Tone.primary)
                    .frame(width: 52, height: 52)
                    .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(Tone.surfaceStrong))
                VStack(alignment: .leading, spacing: 2) {
                    Text("Téléchargements").font(Typo.rowTitle).foregroundStyle(Tone.primary)
                    Text(subtitle).font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
                }
                Spacer()
                if !downloads.queue.isEmpty { ProgressView().tint(.white) }
                Image(systemName: "chevron.right").font(.system(size: 13, weight: .semibold)).foregroundStyle(Tone.tertiary)
            }
        }
        .buttonStyle(.pressable(scale: 0.98))
    }

    private var subtitle: String {
        let count = downloads.items.count
        if count == 0 { return "Écoute sans réseau" }
        return count == 1 ? "1 titre · \(downloads.totalBytes.byteLabel)" : "\(count) titres · \(downloads.totalBytes.byteLabel)"
    }
}
