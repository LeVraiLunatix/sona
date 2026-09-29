import SwiftUI

/// Onglet Amis : qui écoute quoi en ce moment (mis à jour toutes les 15 s),
/// et la dernière écoute des autres.
struct FriendsView: View {
    @Binding var path: NavigationPath
    @EnvironmentObject private var player: PlayerManager
    @State private var friends: [Friend] = []
    @State private var isLoading = true
    @State private var errorMessage: String?
    @State private var showingParty = false
    @State private var showingBlindTest = false
    @State private var parties: [PartySummary] = []
    @ObservedObject private var party = PartyManager.shared

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 12) {
                activities
                    .padding(.bottom, 10)

                if isLoading && friends.isEmpty {
                    ProgressView().tint(.white).frame(maxWidth: .infinity).padding(.top, 80)
                } else if friends.isEmpty {
                    EmptyState(
                        systemImage: "person.2",
                        title: "Personne pour l'instant",
                        message: errorMessage ?? "Dès que d'autres comptes seront acceptés sur l'app, tu verras ici ce qu'ils écoutent en direct."
                    )
                    .padding(.top, 40)
                } else {
                    ForEach(Array(friends.enumerated()), id: \.element.id) { index, friend in
                        FriendCard(friend: friend) {
                            path.append(Route.friend(accountId: friend.accountId))
                        } onPlay: { track in
                            player.play(track, context: [track], name: friend.name)
                        }
                        .reveal(index)
                    }
                }
            }
            .padding(.horizontal, 20)
            .padding(.top, 8)
            .padding(.bottom, 24)
            .animation(Motion.smooth, value: friends)
        }
        .scrollIndicators(.hidden)
        .background(Tone.background)
        .navigationTitle("Amis")
        .navigationBarTitleDisplayMode(.large)
        .refreshable { await load() }
        .task {
            while !Task.isCancelled {
                await load()
                try? await Task.sleep(for: .seconds(15))
            }
        }
        .sheet(isPresented: $showingParty) {
            PartyView().environmentObject(player)
        }
        .fullScreenCover(isPresented: $showingBlindTest) {
            BlindTestView()
        }
    }

    /// Écoute ensemble et blind test, et les sessions des amis à rejoindre.
    @ViewBuilder
    private var activities: some View {
        if let state = party.state {
            Button { showingParty = true } label: {
                HStack(spacing: 12) {
                    EqualizerBars(isAnimating: !state.paused).frame(width: 16, height: 14)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(state.isHost ? "Ta session \(state.code) est en cours" : "Tu écoutes avec \(state.hostName ?? "l'hôte")")
                            .font(Typo.rowTitle).foregroundStyle(.black)
                        Text("\(state.members.count) à l'écoute · touche pour ouvrir").font(Typo.caption).foregroundStyle(.black.opacity(0.6))
                    }
                    Spacer()
                    Image(systemName: "chevron.right").foregroundStyle(.black)
                }
                .padding(14)
                .background(RoundedRectangle(cornerRadius: 18, style: .continuous).fill(.white))
            }
            .buttonStyle(.pressable(scale: 0.98))
        }
        HStack(spacing: 12) {
            activityCard(
                title: "Écoute ensemble", subtitle: "Le même son, au même moment",
                icon: "person.2.wave.2.fill",
                colors: [Color(red: 0.4, green: 0.25, blue: 0.95), Color(red: 0.15, green: 0.1, blue: 0.4)]
            ) { showingParty = true }
            activityCard(
                title: "Blind test", subtitle: "Défi du jour et classement",
                icon: "waveform.badge.magnifyingglass",
                colors: [Color(red: 0.95, green: 0.35, blue: 0.45), Color(red: 0.4, green: 0.08, blue: 0.2)]
            ) { showingBlindTest = true }
        }
        if party.state == nil {
            ForEach(parties.filter { !$0.joined }) { summary in
                PartySummaryRow(summary: summary) {
                    Task {
                        await party.join(code: summary.code)
                        showingParty = true
                    }
                }
            }
        }
    }

    private func activityCard(title: String, subtitle: String, icon: String, colors: [Color], action: @escaping () -> Void) -> some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 10) {
                Image(systemName: icon).font(.system(size: 24, weight: .semibold)).foregroundStyle(.white)
                Spacer(minLength: 6)
                Text(title).font(Typo.headline).foregroundStyle(.white)
                Text(subtitle).font(Typo.caption).foregroundStyle(.white.opacity(0.75)).lineLimit(2)
            }
            .frame(maxWidth: .infinity, minHeight: 130, alignment: .leading)
            .padding(16)
            .background(
                RoundedRectangle(cornerRadius: 22, style: .continuous)
                    .fill(LinearGradient(colors: colors, startPoint: .topLeading, endPoint: .bottomTrailing))
            )
        }
        .buttonStyle(.pressable(scale: 0.96))
    }

    private func load() async {
        parties = (try? await APIClient.shared.activeParties()) ?? parties
        do {
            friends = try await APIClient.shared.friends()
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
        isLoading = false
    }
}

/// Carte d'un ami : avatar, nom, ce qu'il écoute (égaliseur animé) ou sa
/// dernière écoute, affinité, et lecture du même titre d'un tap.
struct FriendCard: View {
    let friend: Friend
    var action: () -> Void
    var onPlay: (Track) -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 14) {
                FriendAvatar(friend: friend, size: 52)
                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 6) {
                        Text(friend.name).font(Typo.headline).foregroundStyle(Tone.primary).lineLimit(1)
                        if let score = friend.compatibility {
                            Text("\(score) %")
                                .font(Typo.caption)
                                .foregroundStyle(Tone.secondary)
                                .padding(.horizontal, 6)
                                .padding(.vertical, 2)
                                .background(Capsule().fill(Tone.surfaceStrong))
                        }
                    }
                    if let playing = friend.nowPlaying {
                        HStack(spacing: 6) {
                            EqualizerBars(isAnimating: true).frame(width: 12, height: 11)
                            Text("\(playing.track.title) · \(playing.track.artist)")
                                .font(Typo.rowSubtitle)
                                .foregroundStyle(Tone.primary.opacity(0.9))
                                .lineLimit(1)
                        }
                    } else if let last = friend.lastPlay {
                        Text("\(last.title) · \(last.artist)")
                            .font(Typo.rowSubtitle)
                            .foregroundStyle(Tone.secondary)
                            .lineLimit(1)
                        Text(relative(last.playedAt))
                            .font(Typo.caption)
                            .foregroundStyle(Tone.tertiary)
                    } else {
                        Text("Pas encore d'écoute").font(Typo.rowSubtitle).foregroundStyle(Tone.tertiary)
                    }
                }
                Spacer(minLength: 4)
                if let track = playableTrack {
                    ZStack {
                        Artwork(url: track.coverURL, cornerRadius: 8)
                        Color.black.opacity(0.35).clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                        Button { onPlay(track) } label: {
                            Image(systemName: "play.fill")
                                .font(.system(size: 15, weight: .bold))
                                .foregroundStyle(.white)
                                .frame(width: 48, height: 48)
                        }
                        .buttonStyle(.pressable(scale: 0.85))
                    }
                    .frame(width: 48, height: 48)
                }
            }
            .padding(12)
            .background(
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .fill(friend.nowPlaying != nil ? Tone.surfaceStrong : Tone.surface)
            )
        }
        .buttonStyle(.pressable(scale: 0.98))
    }

    private var playableTrack: Track? {
        if let playing = friend.nowPlaying, !playing.track.source.isEmpty, !playing.track.sourceId.isEmpty {
            return playing.track
        }
        return friend.lastPlay?.track
    }
}

struct FriendAvatar: View {
    let friend: Friend
    var size: CGFloat

    var body: some View {
        ZStack(alignment: .bottomTrailing) {
            Group {
                if let url = friend.avatarURL {
                    Artwork(url: url, cornerRadius: size / 2, symbol: "person.fill")
                } else {
                    Circle()
                        .fill(Tone.surfaceStrong)
                        .overlay(
                            Text(String(friend.name.prefix(1)).uppercased())
                                .font(.system(size: size * 0.42, weight: .bold))
                                .foregroundStyle(Tone.primary)
                        )
                }
            }
            .frame(width: size, height: size)
            if friend.nowPlaying != nil {
                Circle()
                    .fill(Color.green)
                    .frame(width: size * 0.26, height: size * 0.26)
                    .overlay(Circle().stroke(Color.black, lineWidth: 2))
            }
        }
    }
}

/// « il y a 3 min », « hier »...
func relative(_ iso: String) -> String {
    let parser = ISO8601DateFormatter()
    guard let date = parser.date(from: iso) else { return "" }
    let formatter = RelativeDateTimeFormatter()
    formatter.locale = Locale(identifier: "fr_FR")
    formatter.unitsStyle = .full
    return formatter.localizedString(for: date, relativeTo: Date())
}
