import SwiftUI

struct LibraryView: View {
    @StateObject private var viewModel = LibraryViewModel()
    @EnvironmentObject private var player: PlayerManager
    @Binding var path: NavigationPath

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Tout ce que vous gardez")
                        .font(EncreFont.bodyItalic(15))
                        .foregroundStyle(EncreColor.neutral600)
                    Text("Bibliothèque")
                        .font(EncreFont.heading(46))
                        .foregroundStyle(EncreColor.text)
                }

                chips

                if viewModel.isLoading && viewModel.items.isEmpty {
                    ProgressView().padding(.top, 40).frame(maxWidth: .infinity)
                } else if viewModel.items.isEmpty {
                    Text("Rien ici pour l'instant. Ajoutez un morceau, un album ou un artiste depuis sa fiche.")
                        .font(EncreFont.body(15))
                        .foregroundStyle(EncreColor.neutral600)
                        .padding(.top, 20)
                } else {
                    switch viewModel.kind {
                    case .tracks: trackList
                    case .albums: albumGrid
                    case .artists: artistList
                    }
                }

                if let message = viewModel.errorMessage {
                    Text(message).font(EncreFont.body(14)).foregroundStyle(EncreColor.accent2_700)
                }
            }
            .padding(.horizontal, 24)
            .padding(.top, 12)
            .padding(.bottom, 120)
        }
        .background(EncreColor.bg)
        .task { await viewModel.load() }
        .refreshable { await viewModel.load() }
    }

    private var chips: some View {
        HStack(spacing: 10) {
            ForEach(LibraryKind.allCases) { kind in
                Button {
                    viewModel.kind = kind
                } label: {
                    Text(kind.label)
                        .font(EncreFont.heading(15))
                        .foregroundStyle(viewModel.kind == kind ? EncreColor.bg : EncreColor.text)
                        .padding(.horizontal, 18)
                        .frame(height: 38)
                        .background(
                            Capsule().fill(viewModel.kind == kind ? EncreColor.spot : EncreColor.surface)
                        )
                }
                .buttonStyle(.plain)
            }
        }
    }

    private var trackList: some View {
        VStack(spacing: 16) {
            ForEach(viewModel.items) { item in
                Button {
                    Task {
                        if let track = try? await APIClient.shared.track(source: item.source, id: item.sourceId) {
                            player.play(track)
                        }
                    }
                } label: {
                    HStack(spacing: 14) {
                        CoverArt(url: item.coverURL, title: item.title).frame(width: 58, height: 58)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(item.title).font(EncreFont.heading(17)).foregroundStyle(EncreColor.text).lineLimit(1)
                            if let subtitle = item.subtitle {
                                Text(subtitle).font(EncreFont.bodyItalic(14)).foregroundStyle(EncreColor.neutral600).lineLimit(1)
                            }
                        }
                        Spacer()
                    }
                }
                .buttonStyle(.plain)
            }
        }
    }

    private var albumGrid: some View {
        LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 16) {
            ForEach(viewModel.items) { item in
                Button { path.append(Route.album(source: item.source, id: item.sourceId)) } label: {
                    VStack(alignment: .leading, spacing: 8) {
                        CoverArt(url: item.coverURL, title: item.title).aspectRatio(1, contentMode: .fit).encreShadow(EncreShadow.sm)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(item.title).font(EncreFont.heading(16)).foregroundStyle(EncreColor.text).lineLimit(1)
                            if let subtitle = item.subtitle {
                                Text(subtitle).font(EncreFont.bodyItalic(14)).foregroundStyle(EncreColor.neutral600).lineLimit(1)
                            }
                        }
                    }
                }
                .buttonStyle(.plain)
            }
        }
    }

    private var artistList: some View {
        VStack(spacing: 16) {
            ForEach(viewModel.items) { item in
                Button { path.append(Route.artist(source: item.source, id: item.sourceId)) } label: {
                    HStack(spacing: 16) {
                        CoverArt(url: item.coverURL, title: item.title, cornerRadius: 1000)
                            .frame(width: 64, height: 64)
                            .clipShape(Circle())
                        Text(item.title).font(EncreFont.heading(19)).foregroundStyle(EncreColor.text)
                        Spacer()
                        Image(systemName: "chevron.right").foregroundStyle(EncreColor.neutral600)
                    }
                }
                .buttonStyle(.plain)
            }
        }
    }
}
