import Foundation
import SwiftUI

struct HomeView: View {
    @StateObject private var viewModel = HomeViewModel()
    @EnvironmentObject private var player: PlayerManager
    @Binding var path: NavigationPath

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 36) {
                header

                if let hero = viewModel.heroTrack {
                    heroCard(hero)
                }

                if !viewModel.recentTracks.isEmpty {
                    VStack(alignment: .leading, spacing: 14) {
                        SectionHeader(title: "Écouté récemment")
                        ScrollView(.horizontal, showsIndicators: false) {
                            HStack(spacing: 14) {
                                ForEach(viewModel.recentTracks) { track in
                                    TrackTile(track: track) { player.play(track, context: viewModel.recentTracks) }
                                }
                            }
                        }
                    }
                }

                if !viewModel.artists.isEmpty {
                    VStack(alignment: .leading, spacing: 14) {
                        SectionHeader(title: "Vos artistes")
                        ScrollView(.horizontal, showsIndicators: false) {
                            HStack(spacing: 18) {
                                ForEach(viewModel.artists) { artist in
                                    ArtistBubble(name: artist.name, coverURL: artist.coverURL) {
                                        path.append(Route.artist(source: artist.source, id: artist.artistSourceId))
                                    }
                                }
                            }
                        }
                    }
                }

                if !viewModel.libraryTracks.isEmpty {
                    VStack(alignment: .leading, spacing: 16) {
                        SectionHeader(title: "Votre bibliothèque")
                        VStack(spacing: 18) {
                            ForEach(viewModel.libraryTracks) { track in
                                TrackRow(
                                    track: track, isCurrent: player.current?.id == track.id,
                                    onOpenArtist: track.artistSourceId.map { id in { path.append(Route.artist(source: track.source, id: id)) } },
                                    onOpenAlbum: track.albumSourceId.map { id in { path.append(Route.album(source: track.source, id: id)) } },
                                    action: { player.play(track, context: viewModel.libraryTracks) }
                                )
                            }
                        }
                    }
                }

                if viewModel.recentTracks.isEmpty && viewModel.libraryTracks.isEmpty && !viewModel.isLoading {
                    emptyState
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

    // Le sous-titre "édition du matin/soir" (clin d'œil imprimerie du thème
    // Encre) jurait avec l'esthétique Apple Music visée ici — un simple grand
    // titre, comme l'en-tête de l'onglet "Écouter" d'Apple Music.
    private var header: some View {
        Text("Écouter")
            .font(EncreFont.heading(46))
            .foregroundStyle(EncreColor.text)
    }

    private func heroCard(_ track: Track) -> some View {
        ZStack(alignment: .bottom) {
            CoverArt(url: track.coverURL, title: track.title, cornerRadius: 6, showsHalftone: true)
                .frame(height: 260)
                .encreShadow(EncreShadow.md)

            HStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Reprendre l'écoute")
                        .font(EncreFont.heading(18))
                        .foregroundStyle(EncreColor.text)
                    Text(track.artist)
                        .font(EncreFont.bodyItalic(14))
                        .foregroundStyle(EncreColor.neutral700)
                }
                .lineLimit(1)
                Spacer(minLength: 8)
                Button { player.play(track, context: viewModel.recentTracks) } label: {
                    Image(systemName: "play.fill")
                        .font(.system(size: 22))
                        .foregroundStyle(EncreColor.bg)
                        .frame(width: 52, height: 52)
                        .background(Circle().fill(EncreColor.spot))
                }
            }
            .padding(.leading, 22)
            .padding(.trailing, 8)
            .frame(height: 68)
            .glassCapsule()
            .padding(12)
        }
        .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
    }

    private var emptyState: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Rien à afficher pour l'instant")
                .font(EncreFont.heading(20))
            Text("Cherchez un titre pour commencer à écouter — l'historique et votre bibliothèque apparaîtront ici.")
                .font(EncreFont.body(15))
                .foregroundStyle(EncreColor.neutral600)
        }
        .padding(.top, 40)
    }
}
