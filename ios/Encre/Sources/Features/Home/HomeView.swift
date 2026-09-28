import SwiftUI

struct HomeView: View {
    @StateObject private var viewModel = HomeViewModel()
    @EnvironmentObject private var player: PlayerManager
    @Binding var path: NavigationPath
    @State private var startingRadioId: String?
    @State private var radioError: String?

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 34) {
                if let hero = viewModel.heroTrack {
                    heroCard(hero).padding(.horizontal, 20).reveal(0)
                }

                if !viewModel.recentTracks.isEmpty {
                    section("Écouté récemment", index: 1) {
                        Carousel(items: viewModel.recentTracks) { track in
                            TrackTile(track: track) { player.play(track, context: viewModel.recentTracks) }
                        }
                    }
                }

                if !viewModel.radios.isEmpty {
                    section("Radios", index: 2) {
                        Carousel(items: viewModel.radios) { radio in
                            RadioTile(radio: radio, isLoading: startingRadioId == radio.id) { startRadio(radio) }
                        }
                    }
                }

                if let radioError {
                    Text(radioError).font(Typo.rowSubtitle).foregroundStyle(Tone.danger).padding(.horizontal, 20)
                }

                if !viewModel.artists.isEmpty {
                    section("Vos artistes", index: 3) {
                        Carousel(items: viewModel.artists, spacing: 18) { artist in
                            let route = Route.artist(source: artist.source, id: artist.artistSourceId)
                            ArtistBubble(name: artist.name, pictureURL: artist.coverURL, route: route) {
                                path.append(route)
                            }
                        }
                    }
                }

                if !viewModel.libraryTracks.isEmpty {
                    section("Vos titres", index: 4) {
                        LazyVStack(spacing: 2) {
                            ForEach(viewModel.libraryTracks) { track in
                                TrackRow(
                                    track: track,
                                    isCurrent: player.current?.id == track.id,
                                    isPlaying: player.isPlaying,
                                    onOpenArtist: track.artistSourceId.map { id in { path.append(Route.artist(source: track.source, id: id)) } },
                                    onOpenAlbum: track.albumSourceId.map { id in { path.append(Route.album(source: track.source, id: id)) } }
                                ) {
                                    player.play(track, context: viewModel.libraryTracks)
                                }
                            }
                        }
                        .padding(.horizontal, 20)
                    }
                }

                if viewModel.recentTracks.isEmpty && viewModel.libraryTracks.isEmpty && !viewModel.isLoading {
                    EmptyState(
                        systemImage: "music.note",
                        title: "Rien à afficher pour l'instant",
                        message: "Lance une radio ou cherche un titre : ton historique et ta bibliothèque apparaîtront ici."
                    )
                }

                if let message = viewModel.errorMessage {
                    Text(message).font(Typo.rowSubtitle).foregroundStyle(Tone.danger).padding(.horizontal, 20)
                }
            }
            .padding(.top, 8)
            .padding(.bottom, 110)
        }
        .scrollIndicators(.hidden)
        .background(Tone.background)
        .navigationTitle("Écouter")
        .navigationBarTitleDisplayMode(.large)
        .overlay {
            if viewModel.isLoading && viewModel.recentTracks.isEmpty && viewModel.libraryTracks.isEmpty {
                ProgressView().tint(.white)
            }
        }
        .task { await viewModel.load() }
        .refreshable { await viewModel.load() }
    }

    private func section<Content: View>(_ title: String, index: Int, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionHeader(title: title).padding(.horizontal, 20)
            content()
        }
        .reveal(index)
    }

    /// « Reprendre l'écoute » : la pochette en grand, fondue dans un voile
    /// sombre, titre et bouton lecture posés dessus.
    private func heroCard(_ track: Track) -> some View {
        Button {
            player.play(track, context: viewModel.recentTracks)
        } label: {
            ZStack(alignment: .bottomLeading) {
                Artwork(url: track.coverURL, cornerRadius: 20)
                    .frame(height: 300)
                LinearGradient(colors: [.clear, .black.opacity(0.85)], startPoint: .center, endPoint: .bottom)
                    .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
                HStack(alignment: .bottom) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("REPRENDRE")
                            .font(Typo.caption)
                            .tracking(1.5)
                            .foregroundStyle(Tone.secondary)
                        Text(track.title)
                            .font(Typo.largeTitle)
                            .foregroundStyle(Tone.primary)
                            .lineLimit(2)
                        Text(track.artist)
                            .font(Typo.body)
                            .foregroundStyle(Tone.secondary)
                            .lineLimit(1)
                    }
                    Spacer(minLength: 12)
                    Image(systemName: player.current?.id == track.id && player.isPlaying ? "pause.fill" : "play.fill")
                        .font(.system(size: 20, weight: .bold))
                        .foregroundStyle(.black)
                        .frame(width: 54, height: 54)
                        .background(Circle().fill(.white))
                        .contentTransition(.symbolEffect(.replace))
                }
                .padding(20)
            }
        }
        .buttonStyle(.pressable(scale: 0.97))
    }

    private func startRadio(_ radio: RadioStation) {
        guard startingRadioId == nil else { return }
        startingRadioId = radio.id
        radioError = nil
        let radioId = radio.id
        Task {
            do {
                try await player.playStation { try await APIClient.shared.radioTracks(id: radioId) }
            } catch {
                radioError = "« \(radio.title) » : \(error.localizedDescription)"
            }
            startingRadioId = nil
        }
    }
}
