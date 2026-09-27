import SwiftUI

struct AlbumDetailView: View {
    let source: String
    let id: String

    @State private var album: Album?
    @State private var errorMessage: String?
    @EnvironmentObject private var player: PlayerManager
    @Binding var path: NavigationPath

    var body: some View {
        ScrollView {
            if let album {
                VStack(alignment: .leading, spacing: 22) {
                    CoverArt(url: album.coverURL, title: album.title)
                        .frame(width: 220, height: 220)
                        .encreShadow(EncreShadow.lg)
                        .frame(maxWidth: .infinity, alignment: .center)

                    VStack(alignment: .center, spacing: 6) {
                        Text(album.title)
                            .font(EncreFont.heading(30))
                            .multilineTextAlignment(.center)
                        Button {
                            path.append(Route.artist(source: album.source, id: album.artistSourceId ?? ""))
                        } label: {
                            Text(album.artist)
                                .font(EncreFont.bodyItalic(19))
                                .foregroundStyle(EncreColor.spotDeep)
                        }
                        .disabled(album.artistSourceId == nil)
                        if let meta = metaLine {
                            Text(meta).font(EncreFont.body(14)).foregroundStyle(EncreColor.neutral600)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .center)

                    HStack(spacing: 12) {
                        Button {
                            if let first = album.tracks.first { player.play(first) }
                        } label: {
                            Label("Lecture", systemImage: "play.fill")
                                .font(EncreFont.heading(17))
                                .padding(.horizontal, 22)
                                .frame(height: 48)
                        }
                        .buttonStyle(.plain)
                        .background(Capsule().fill(EncreColor.spot))
                        .foregroundStyle(EncreColor.bg)

                        Button {
                            if let random = album.tracks.randomElement() { player.play(random) }
                        } label: {
                            Label("Aléatoire", systemImage: "shuffle")
                                .font(EncreFont.heading(16))
                                .padding(.horizontal, 20)
                                .frame(height: 48)
                        }
                        .buttonStyle(.plain)
                        .glassCapsule()
                        .foregroundStyle(EncreColor.text)
                    }
                    .frame(maxWidth: .infinity, alignment: .center)

                    VStack(spacing: 4) {
                        // Indices plutôt que `.enumerated()` : un keypath sur
                        // le membre labellisé d'un tuple (`\.element.id`) est
                        // trop récent pour qu'on en dépende ici.
                        ForEach(album.tracks.indices, id: \.self) { index in
                            let track = album.tracks[index]
                            HStack(spacing: 16) {
                                Text("\(index + 1)")
                                    .font(EncreFont.body(16))
                                    .foregroundStyle(EncreColor.neutral600)
                                    .frame(width: 22, alignment: .leading)
                                    .monospacedDigit()
                                Button { player.play(track) } label: {
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(track.title)
                                            .font(EncreFont.heading(17))
                                            .foregroundStyle(player.current?.id == track.id ? EncreColor.spotDeep : EncreColor.text)
                                            .lineLimit(1)
                                        Text(track.artist)
                                            .font(EncreFont.bodyItalic(14))
                                            .foregroundStyle(EncreColor.neutral600)
                                            .lineLimit(1)
                                    }
                                }
                                .buttonStyle(.plain)
                                Spacer()
                                Text(track.durationLabel)
                                    .font(EncreFont.body(14))
                                    .foregroundStyle(EncreColor.neutral600)
                                    .monospacedDigit()
                            }
                            .padding(.vertical, 8)
                        }
                    }
                }
                .padding(.horizontal, 24)
                .padding(.top, 24)
                .padding(.bottom, 120)
            } else if let errorMessage {
                Text(errorMessage).font(EncreFont.body(15)).padding(24)
            } else {
                ProgressView().padding(.top, 80)
            }
        }
        .background(EncreColor.bg)
        .navigationTitle(album?.title ?? "")
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
    }

    private var metaLine: String? {
        guard let album else { return nil }
        var parts: [String] = []
        if let count = album.trackCount { parts.append("\(count) titre\(count > 1 ? "s" : "")") }
        if let seconds = album.durationSeconds { parts.append("\(seconds / 60) min") }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    private func load() async {
        do {
            album = try await APIClient.shared.album(source: source, id: id)
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
