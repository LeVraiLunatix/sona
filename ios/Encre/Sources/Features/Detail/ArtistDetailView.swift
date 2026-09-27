import SwiftUI

struct ArtistDetailView: View {
    let source: String
    let id: String

    @State private var artist: Artist?
    @State private var topTracks: [Track] = []
    @State private var albums: [Album] = []
    @State private var singles: [Album] = []
    @State private var errorMessage: String?
    @EnvironmentObject private var player: PlayerManager
    @Binding var path: NavigationPath

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 30) {
                if let artist {
                    ZStack(alignment: .bottomLeading) {
                        CoverArt(url: artist.pictureURL, title: artist.name, cornerRadius: 0, showsHalftone: true)
                            .frame(height: 320)
                            .clipped()
                        LinearGradient(colors: [.clear, EncreColor.bg], startPoint: .center, endPoint: .bottom)
                            .frame(height: 320)
                        VStack(alignment: .leading, spacing: 6) {
                            Text("ARTISTE")
                                .font(EncreFont.heading(12))
                                .tracking(2)
                                .foregroundStyle(EncreColor.accent2_700)
                            Text(artist.name)
                                .font(EncreFont.heading(48))
                                .foregroundStyle(EncreColor.text)
                        }
                        .padding(24)
                    }

                    if !topTracks.isEmpty {
                        Button {
                            player.play(topTracks[0], context: topTracks)
                        } label: {
                            Label("Écouter", systemImage: "play.fill")
                                .font(EncreFont.heading(17))
                                .padding(.horizontal, 26)
                                .frame(height: 48)
                        }
                        .buttonStyle(.plain)
                        .background(Capsule().fill(EncreColor.spot))
                        .foregroundStyle(EncreColor.bg)
                        .padding(.horizontal, 24)
                    }

                    if !topTracks.isEmpty {
                        VStack(alignment: .leading, spacing: 14) {
                            SectionHeader(title: "Titres populaires")
                            VStack(spacing: 14) {
                                ForEach(topTracks) { track in
                                    TrackRow(track: track, isCurrent: player.current?.id == track.id) {
                                        player.play(track, context: topTracks)
                                    }
                                }
                            }
                        }
                        .padding(.horizontal, 24)
                    }

                    if !albums.isEmpty {
                        VStack(alignment: .leading, spacing: 14) {
                            SectionHeader(title: "Albums")
                            albumGrid(albums)
                        }
                        .padding(.horizontal, 24)
                    }

                    if !singles.isEmpty {
                        VStack(alignment: .leading, spacing: 14) {
                            SectionHeader(title: "Singles et EPs")
                            albumGrid(singles)
                        }
                        .padding(.horizontal, 24)
                    }
                } else if let errorMessage {
                    Text(errorMessage).font(EncreFont.body(15)).padding(24)
                } else {
                    ProgressView().padding(.top, 80)
                }
            }
            .padding(.bottom, 120)
        }
        .background(EncreColor.bg)
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
    }

    private func albumGrid(_ list: [Album]) -> some View {
        LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 16) {
            ForEach(list) { album in
                Button { path.append(Route.album(source: album.source, id: album.sourceId)) } label: {
                    VStack(alignment: .leading, spacing: 8) {
                        CoverArt(url: album.coverURL, title: album.title)
                            .aspectRatio(1, contentMode: .fit)
                            .encreShadow(EncreShadow.sm)
                        Text(album.title).font(EncreFont.heading(16)).foregroundStyle(EncreColor.text).lineLimit(1)
                    }
                }
                .buttonStyle(.plain)
            }
        }
    }

    private func load() async {
        do {
            async let artistTask = APIClient.shared.artist(source: source, id: id)
            async let topTask = APIClient.shared.artistTopTracks(source: source, id: id)
            async let albumsTask = APIClient.shared.artistAlbums(source: source, id: id)
            let (a, top, albumSet) = try await (artistTask, topTask, albumsTask)
            artist = a
            topTracks = top
            albums = albumSet.albums
            singles = albumSet.singles
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
