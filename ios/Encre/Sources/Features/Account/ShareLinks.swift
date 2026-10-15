import SwiftUI

/// Ce qu'on partage : un titre, un album ou une playlist Sona.
struct ShareTarget: Identifiable, Hashable {
    var kind: String
    var source: String
    var sourceId: String
    var title: String
    var subtitle: String?
    var coverURL: String?

    var id: String { "\(kind):\(source):\(sourceId)" }

    static func track(_ track: Track) -> ShareTarget {
        ShareTarget(kind: "track", source: track.source, sourceId: track.sourceId,
                    title: track.title, subtitle: track.artist, coverURL: track.coverURL)
    }

    static func album(_ album: Album) -> ShareTarget {
        ShareTarget(kind: "album", source: album.source, sourceId: album.sourceId,
                    title: album.title, subtitle: album.artist, coverURL: album.coverURL)
    }

    static func playlist(_ playlist: UserPlaylist) -> ShareTarget {
        ShareTarget(kind: "playlist", source: "sona", sourceId: String(playlist.id),
                    title: playlist.name, subtitle: playlist.trackCountLabel,
                    coverURL: playlist.coverURL ?? playlist.covers.first)
    }

    var kindLabel: String {
        switch kind {
        case "album": "Album"
        case "playlist": "Playlist"
        default: "Titre"
        }
    }
}

/// « Partager » : un lien vers une page publique en lecture seule —
/// pochette et extraits de 30 s, jamais le titre complet (Sona est privé).
/// Les membres l'ouvrent dans Sona. Validité au choix, révocable à tout
/// moment (Réglages › Liens de partage).
struct SonaShareSheet: View {
    let target: ShareTarget

    @Environment(\.dismiss) private var dismiss
    @State private var validity = 0
    @State private var link: SonaShare?
    @State private var busy = false
    @State private var errorMessage: String?
    @State private var copied = false

    private static let validities: [(label: String, hours: Int?)] = [
        ("Sans limite", nil), ("24 h", 24), ("7 jours", 24 * 7), ("30 jours", 24 * 30),
    ]

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 20) {
                    previewCard

                    VStack(alignment: .leading, spacing: 8) {
                        Text("Validité du lien").font(Typo.caption).foregroundStyle(Tone.secondary)
                        Picker("Validité du lien", selection: $validity) {
                            ForEach(Self.validities.indices, id: \.self) { index in
                                Text(Self.validities[index].label).tag(index)
                            }
                        }
                        .pickerStyle(.segmented)
                        .onChange(of: validity) { _, _ in link = nil }
                    }

                    if let link, let url = URL(string: link.url) {
                        VStack(spacing: 12) {
                            Text(link.url)
                                .font(Typo.mono)
                                .foregroundStyle(Tone.secondary)
                                .textSelection(.enabled)
                                .lineLimit(2)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .padding(12)
                                .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(Tone.surface))
                            HStack(spacing: 12) {
                                ShareLink(item: url, subject: Text(target.title), message: Text(shareMessage)) {
                                    Label("Partager", systemImage: "square.and.arrow.up")
                                        .font(Typo.headline)
                                        .foregroundStyle(.black)
                                        .frame(maxWidth: .infinity)
                                        .frame(height: 50)
                                        .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Color.white))
                                }
                                PillButton(title: copied ? "Copié" : "Copier", systemImage: copied ? "checkmark" : "doc.on.doc", kind: .secondary) {
                                    UIPasteboard.general.url = url
                                    copied = true
                                }
                                .sensoryFeedback(.success, trigger: copied)
                            }
                        }
                        .transition(.opacity.combined(with: .move(edge: .bottom)))
                    } else {
                        PillButton(title: "Créer le lien", systemImage: "link", isLoading: busy) {
                            Task { await create() }
                        }
                    }

                    if let errorMessage {
                        Text(errorMessage).font(Typo.rowSubtitle).foregroundStyle(Tone.danger)
                    }

                    Label {
                        Text("Sans compte Sona, on voit la pochette et des extraits officiels de 30 s, jamais le titre complet. Les membres l'ouvrent dans l'app, sur le site ou dans Telegram. Tu peux le révoquer à tout moment dans Réglages › Liens de partage.")
                    } icon: {
                        Image(systemName: "lock.shield")
                    }
                    .font(Typo.caption)
                    .foregroundStyle(Tone.tertiary)
                }
                .padding(20)
                .animation(Motion.smooth, value: link)
            }
            .background(Tone.background)
            .navigationTitle("Partager")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("OK") { dismiss() }
                }
            }
        }
        .presentationDetents([.medium, .large])
    }

    /// Aperçu tel qu'il s'affichera dans une messagerie.
    private var previewCard: some View {
        HStack(spacing: 14) {
            Artwork(url: target.coverURL, cornerRadius: 10)
                .frame(width: 72, height: 72)
            VStack(alignment: .leading, spacing: 3) {
                Text(target.kindLabel.uppercased())
                    .font(.system(size: 11, weight: .bold))
                    .kerning(1)
                    .foregroundStyle(Tone.tertiary)
                Text(target.title).font(Typo.headline).foregroundStyle(Tone.primary).lineLimit(2)
                if let subtitle = target.subtitle {
                    Text(subtitle).font(Typo.rowSubtitle).foregroundStyle(Tone.secondary).lineLimit(1)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(14)
        .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(Tone.surfaceStrong))
    }

    private var shareMessage: String {
        if let subtitle = target.subtitle { return "\(target.title) — \(subtitle)" }
        return target.title
    }

    private func create() async {
        busy = true
        errorMessage = nil
        defer { busy = false }
        do {
            link = try await APIClient.shared.createShare(
                kind: target.kind, source: target.source, id: target.sourceId,
                expiresInHours: Self.validities[validity].hours
            )
            copied = false
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

/// Réglages › Liens de partage : les liens actifs, leurs vues, et de quoi
/// les révoquer (la page publique disparaît aussitôt).
struct ShareLinksView: View {
    @State private var links: [SonaShare] = []
    @State private var loaded = false
    @State private var errorMessage: String?

    var body: some View {
        List {
            if loaded && links.isEmpty {
                EmptyState(
                    systemImage: "link",
                    title: "Aucun lien de partage",
                    message: "Partage un titre, un album ou une playlist depuis son menu « … »."
                )
                .listRowBackground(Color.clear)
            }
            ForEach(links) { link in
                HStack(spacing: 12) {
                    Artwork(url: link.coverURL, cornerRadius: 6).frame(width: 48, height: 48)
                    VStack(alignment: .leading, spacing: 3) {
                        Text(link.title).font(Typo.rowTitle).foregroundStyle(Tone.primary).lineLimit(1)
                        Text(detail(link)).font(Typo.caption).foregroundStyle(link.active ? Tone.secondary : Tone.danger)
                    }
                    Spacer(minLength: 8)
                    if link.active, let url = URL(string: link.url) {
                        ShareLink(item: url) {
                            Image(systemName: "square.and.arrow.up").foregroundStyle(Tone.primary)
                        }
                        .buttonStyle(.borderless)
                    }
                }
                .swipeActions(edge: .trailing, allowsFullSwipe: true) {
                    Button(role: .destructive) { Task { await revoke(link) } } label: {
                        Label("Révoquer", systemImage: "trash")
                    }
                }
            }
            if let errorMessage {
                Text(errorMessage).font(Typo.rowSubtitle).foregroundStyle(Tone.danger)
            }
        }
        .navigationTitle("Liens de partage")
        .refreshable { await load() }
        .task { await load() }
        .animation(Motion.smooth, value: links)
    }

    private func detail(_ link: SonaShare) -> String {
        var parts = [link.kindLabel, link.views == 1 ? "1 vue" : "\(link.views) vues"]
        if !link.active {
            parts.append("expiré")
        } else if let expires = link.expiresAt {
            parts.append("jusqu'au \(String(expires.prefix(10)))")
        }
        return parts.joined(separator: " · ")
    }

    private func load() async {
        do {
            links = try await APIClient.shared.shares()
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
        loaded = true
    }

    private func revoke(_ link: SonaShare) async {
        links.removeAll { $0.token == link.token }
        do {
            try await APIClient.shared.revokeShare(token: link.token)
        } catch {
            errorMessage = error.localizedDescription
            await load()
        }
    }
}
