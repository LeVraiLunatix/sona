import SwiftUI

/// Profil d'un ami : en direct, affinité et artistes en commun, ses tops du
/// mois, ses écoutes récentes et ses playlists partagées.
struct FriendProfileView: View {
    let accountId: Int
    @Binding var path: NavigationPath
    @EnvironmentObject private var player: PlayerManager
    @State private var friend: Friend?
    @State private var errorMessage: String?
    @State private var blend: Blend?

    var body: some View {
        ScrollView {
            if let friend {
                VStack(alignment: .leading, spacing: 28) {
                    header(friend)
                    if let playing = friend.nowPlaying { nowPlaying(playing, friend: friend) }
                    taste(friend)
                    if let blend, !blend.tracks.isEmpty { blendCard(blend) }
                    if let playlists = friend.playlists, !playlists.isEmpty { playlistSection(playlists) }
                    if let artists = friend.topArtists, !artists.isEmpty { ranked("Ses artistes du mois", artists, isArtist: true) }
                    if let tracks = friend.topTracks, !tracks.isEmpty { ranked("Ses titres du mois", tracks, isArtist: false) }
                    if let recent = friend.recent, !recent.isEmpty { recentSection(recent, friend: friend) }
                }
                .padding(.bottom, 24)
            } else if let errorMessage {
                EmptyState(systemImage: "person.crop.circle.badge.exclamationmark", title: "Profil indisponible", message: errorMessage)
                    .padding(.top, 80)
            } else {
                ProgressView().tint(.white).frame(maxWidth: .infinity).padding(.top, 120)
            }
        }
        .scrollIndicators(.hidden)
        .background(Tone.background)
        .navigationBarTitleDisplayMode(.inline)
        .refreshable { await load() }
        .task { blend = try? await APIClient.shared.blend(with: accountId) }
        .task {
            while !Task.isCancelled {
                await load()
                try? await Task.sleep(for: .seconds(20))
            }
        }
    }

    private func header(_ friend: Friend) -> some View {
        VStack(spacing: 10) {
            FriendAvatar(friend: friend, size: 110)
            Text(friend.name).font(.system(size: 26, weight: .bold)).foregroundStyle(Tone.primary)
            Text("@\(friend.username)").font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
        }
        .frame(maxWidth: .infinity)
        .padding(.top, 12)
    }

    private func nowPlaying(_ playing: FriendNowPlaying, friend: Friend) -> some View {
        Button {
            if !playing.track.sourceId.isEmpty { player.play(playing.track, context: [playing.track], name: friend.name) }
        } label: {
            HStack(spacing: 14) {
                Artwork(url: playing.track.coverURL, cornerRadius: 10).frame(width: 64, height: 64)
                VStack(alignment: .leading, spacing: 3) {
                    HStack(spacing: 6) {
                        EqualizerBars(isAnimating: true).frame(width: 12, height: 11)
                        Text("EN TRAIN D'ÉCOUTER").font(Typo.caption).tracking(1.2).foregroundStyle(Tone.secondary)
                    }
                    Text(playing.track.title).font(Typo.headline).foregroundStyle(Tone.primary).lineLimit(1)
                    Text(playing.track.artist).font(Typo.rowSubtitle).foregroundStyle(Tone.secondary).lineLimit(1)
                }
                Spacer()
                Image(systemName: "play.circle.fill").font(.system(size: 32)).foregroundStyle(Tone.primary)
            }
            .padding(14)
            .background(RoundedRectangle(cornerRadius: 18, style: .continuous).fill(Tone.surfaceStrong))
        }
        .buttonStyle(.pressable(scale: 0.98))
        .padding(.horizontal, 20)
    }

    private func taste(_ friend: Friend) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionHeader(title: "Vos goûts")
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                if let score = friend.compatibility {
                    Text("\(score) %").font(.system(size: 40, weight: .bold)).foregroundStyle(Tone.primary)
                    Text(verdict(score)).font(Typo.body).foregroundStyle(Tone.secondary)
                } else {
                    Text("Pas encore assez d'écoutes pour comparer.").font(Typo.body).foregroundStyle(Tone.secondary)
                }
            }
            if let shared = friend.sharedArtists, !shared.isEmpty {
                Text("En commun : " + shared.prefix(8).joined(separator: ", "))
                    .font(Typo.rowSubtitle)
                    .foregroundStyle(Tone.secondary)
            }
        }
        .padding(.horizontal, 20)
    }

    /// Blend : la playlist du jour qui mélange vos deux goûts.
    private func blendCard(_ blend: Blend) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: -12) {
                Image(systemName: "person.fill")
                    .font(.system(size: 20, weight: .bold)).foregroundStyle(.white)
                    .frame(width: 46, height: 46)
                    .background(Circle().fill(Color.white.opacity(0.25)))
                Artwork(url: blend.friendAvatarURL, cornerRadius: 23, symbol: "person.fill")
                    .frame(width: 46, height: 46)
                    .overlay(Circle().stroke(Color.black.opacity(0.2), lineWidth: 2))
                Spacer()
                Text("BLEND").font(Typo.caption).tracking(2).foregroundStyle(.white.opacity(0.8))
            }
            VStack(alignment: .leading, spacing: 4) {
                Text(blend.title).font(.system(size: 22, weight: .heavy)).foregroundStyle(.white).lineLimit(1)
                Text(blendSubtitle(blend)).font(Typo.rowSubtitle).foregroundStyle(.white.opacity(0.8)).lineLimit(2)
            }
            VStack(spacing: 6) {
                ForEach(blend.tracks.prefix(3)) { track in
                    HStack(spacing: 10) {
                        Artwork(url: track.coverURL, cornerRadius: 5).frame(width: 34, height: 34)
                        VStack(alignment: .leading, spacing: 1) {
                            Text(track.title).font(Typo.rowTitle).foregroundStyle(.white).lineLimit(1)
                            Text(track.artist).font(Typo.caption).foregroundStyle(.white.opacity(0.7)).lineLimit(1)
                        }
                        Spacer()
                    }
                }
            }
            HStack(spacing: 10) {
                Button {
                    if let first = blend.tracks.first { player.play(first, context: blend.tracks, name: blend.title) }
                } label: {
                    Label("Écouter", systemImage: "play.fill")
                        .font(Typo.headline).foregroundStyle(.black)
                        .frame(maxWidth: .infinity).frame(height: 46)
                        .background(Capsule().fill(.white))
                }
                .buttonStyle(.pressable(scale: 0.97))
                Button {
                    player.playShuffled(blend.tracks, name: blend.title)
                } label: {
                    Image(systemName: "shuffle")
                        .font(Typo.headline).foregroundStyle(.white)
                        .frame(width: 54, height: 46)
                        .background(Capsule().fill(Color.white.opacity(0.2)))
                }
                .buttonStyle(.pressable(scale: 0.95))
            }
        }
        .padding(18)
        .background(
            RoundedRectangle(cornerRadius: 24, style: .continuous)
                .fill(LinearGradient(colors: [Color(red: 0.95, green: 0.35, blue: 0.55), Color(red: 0.45, green: 0.2, blue: 0.95)],
                                     startPoint: .topLeading, endPoint: .bottomTrailing))
        )
        .padding(.horizontal, 20)
    }

    private func blendSubtitle(_ blend: Blend) -> String {
        var parts = ["\(blend.tracks.count) titres, renouvelés chaque jour"]
        if blend.sharedTracks > 0 {
            parts.append("\(blend.sharedTracks) que vous écoutez tous les deux")
        }
        return parts.joined(separator: " · ")
    }

    private func verdict(_ score: Int) -> String {
        switch score {
        case 80...: "d'affinité, vous êtes faits pour vous entendre"
        case 50..<80: "d'affinité, pas mal du tout"
        case 20..<50: "d'affinité, quelques points communs"
        default: "d'affinité, des univers bien différents"
        }
    }

    private func playlistSection(_ playlists: [UserPlaylist]) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionHeader(title: "Ses playlists").padding(.horizontal, 20)
            Carousel(items: playlists) { playlist in
                Button { path.append(Route.userPlaylist(id: playlist.id)) } label: {
                    VStack(alignment: .leading, spacing: 8) {
                        PlaylistCover(playlist: playlist).frame(width: 150, height: 150)
                        Text(playlist.name).font(Typo.rowTitle).foregroundStyle(Tone.primary).lineLimit(1)
                        Text(playlist.visibility == "collaborative" ? "À plusieurs" : playlist.trackCountLabel)
                            .font(Typo.rowSubtitle).foregroundStyle(Tone.secondary).lineLimit(1)
                    }
                    .frame(width: 150, alignment: .leading)
                }
                .buttonStyle(.pressable)
            }
        }
    }

    private func ranked(_ title: String, _ items: [FriendRanked], isArtist: Bool) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(title: title)
            ForEach(Array(items.prefix(5).enumerated()), id: \.element.id) { index, item in
                Button {
                    guard let source = item.source, let id = item.sourceId, !source.isEmpty else { return }
                    if isArtist {
                        path.append(Route.artist(source: source, id: id))
                    } else {
                        let track = Track(source: source, sourceId: id, title: item.name, artist: item.subtitle ?? "",
                                          album: nil, year: nil, durationSeconds: nil, coverURL: item.coverURL,
                                          artistSourceId: nil, albumSourceId: nil)
                        player.play(track, context: [track])
                    }
                } label: {
                    HStack(spacing: 12) {
                        Text("\(index + 1)").font(Typo.body).foregroundStyle(Tone.tertiary).monospacedDigit().frame(width: 20)
                        Artwork(url: item.coverURL, cornerRadius: isArtist ? 22 : 6, symbol: isArtist ? "person.fill" : "music.note")
                            .frame(width: 44, height: 44)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(item.name).font(Typo.rowTitle).foregroundStyle(Tone.primary).lineLimit(1)
                            if let subtitle = item.subtitle {
                                Text(subtitle).font(Typo.rowSubtitle).foregroundStyle(Tone.secondary).lineLimit(1)
                            }
                        }
                        Spacer()
                        Text("\(item.plays)").font(Typo.mono).foregroundStyle(Tone.tertiary)
                    }
                }
                .buttonStyle(.pressable(scale: 0.98))
            }
        }
        .padding(.horizontal, 20)
    }

    private func recentSection(_ plays: [FriendPlay], friend: Friend) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(title: "Écoutes récentes")
            ForEach(plays.prefix(10)) { play in
                if let track = play.track {
                    TrackRow(track: track, isCurrent: player.current?.id == track.id, isPlaying: player.isPlaying) {
                        let tracks = plays.compactMap(\.track)
                        player.play(track, context: tracks, name: "Écoutes de \(friend.name)")
                    }
                } else {
                    HStack(spacing: 14) {
                        Artwork(url: play.coverURL, cornerRadius: 6).frame(width: 50, height: 50)
                        VStack(alignment: .leading, spacing: 3) {
                            Text(play.title).font(Typo.rowTitle).foregroundStyle(Tone.primary).lineLimit(1)
                            Text(play.artist).font(Typo.rowSubtitle).foregroundStyle(Tone.secondary).lineLimit(1)
                        }
                        Spacer()
                        Text(relative(play.playedAt)).font(Typo.caption).foregroundStyle(Tone.tertiary)
                    }
                    .padding(.vertical, 6)
                }
            }
        }
        .padding(.horizontal, 20)
    }

    private func load() async {
        do {
            friend = try await APIClient.shared.friend(id: accountId)
            errorMessage = nil
        } catch {
            if friend == nil { errorMessage = error.localizedDescription }
        }
    }
}
