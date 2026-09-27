import SwiftUI

struct SearchView: View {
    @StateObject private var viewModel = SearchViewModel()
    @EnvironmentObject private var player: PlayerManager
    @Binding var path: NavigationPath
    @FocusState private var focused: Bool

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Titres, artistes, liens")
                        .font(EncreFont.bodyItalic(15))
                        .foregroundStyle(EncreColor.neutral600)
                    Text("Rechercher")
                        .font(EncreFont.heading(46))
                        .foregroundStyle(EncreColor.text)
                }

                searchField

                if viewModel.isSearching {
                    ProgressView().frame(maxWidth: .infinity).padding(.top, 20)
                } else if let link = viewModel.resolvedLink {
                    resolvedView(link)
                } else if !viewModel.results.isEmpty {
                    VStack(spacing: 16) {
                        ForEach(viewModel.results) { track in
                            TrackRow(track: track, isCurrent: player.current?.id == track.id) {
                                player.play(track, context: viewModel.results)
                            }
                        }
                    }
                } else if !viewModel.query.trimmingCharacters(in: .whitespaces).isEmpty {
                    if let message = viewModel.errorMessage {
                        Text(message).font(EncreFont.body(15)).foregroundStyle(EncreColor.accent2_700)
                    } else {
                        Text("Rien dans nos colonnes pour « \(viewModel.query) ».")
                            .font(EncreFont.bodyItalic(17))
                            .foregroundStyle(EncreColor.neutral600)
                    }
                } else {
                    hint
                }
            }
            .padding(.horizontal, 24)
            .padding(.top, 12)
            .padding(.bottom, 120)
        }
        .background(EncreColor.bg)
    }

    private var searchField: some View {
        HStack(spacing: 10) {
            Image(systemName: "magnifyingglass").foregroundStyle(EncreColor.spotDeep)
            TextField("Saif, Aya Nakamura, ou un lien…", text: $viewModel.query)
                .font(EncreFont.body(18))
                .focused($focused)
                .autocorrectionDisabled()
                .textInputAutocapitalization(.never)
            if !viewModel.query.isEmpty {
                Button { viewModel.query = "" } label: {
                    Image(systemName: "xmark.circle.fill").foregroundStyle(EncreColor.neutral500)
                }
            }
        }
        .padding(.horizontal, 18)
        .frame(height: 52)
        .glassCapsule()
    }

    private var hint: some View {
        Text("Collez un lien Deezer, Spotify, Apple Music ou YouTube pour ouvrir directement un titre, un album ou un artiste.")
            .font(EncreFont.body(15))
            .foregroundStyle(EncreColor.neutral600)
            .padding(.top, 20)
    }

    @ViewBuilder
    private func resolvedView(_ link: ResolvedLink) -> some View {
        switch link.kind {
        case .track:
            if let track = link.track {
                TrackRow(track: track) { player.play(track) }
            }
        case .album, .playlist:
            if let album = link.album {
                Button { path.append(Route.album(source: album.source, id: album.sourceId)) } label: {
                    HStack(spacing: 14) {
                        CoverArt(url: album.coverURL, title: album.title).frame(width: 58, height: 58)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(album.title).font(EncreFont.heading(17)).foregroundStyle(EncreColor.text)
                            Text(album.artist).font(EncreFont.bodyItalic(14)).foregroundStyle(EncreColor.neutral600)
                        }
                        Spacer()
                        Image(systemName: "chevron.right").foregroundStyle(EncreColor.neutral600)
                    }
                }
                .buttonStyle(.plain)
            }
        case .artist:
            if let artist = link.artist {
                Button { path.append(Route.artist(source: artist.source, id: artist.sourceId)) } label: {
                    HStack(spacing: 16) {
                        CoverArt(url: artist.pictureURL, title: artist.name, cornerRadius: 1000)
                            .frame(width: 64, height: 64).clipShape(Circle())
                        Text(artist.name).font(EncreFont.heading(19)).foregroundStyle(EncreColor.text)
                        Spacer()
                        Image(systemName: "chevron.right").foregroundStyle(EncreColor.neutral600)
                    }
                }
                .buttonStyle(.plain)
            }
        }
    }
}
