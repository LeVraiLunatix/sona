import CoreMotion
import MapKit
import SwiftUI

// MARK: - Nouvelles sorties

/// Accueil : albums, EP et singles sortis ces 3 dernières semaines chez tes
/// artistes les plus écoutés.
struct ReleasesSection: View {
    let releases: [Release]
    let onOpen: (Release) -> Void

    var body: some View {
        Carousel(items: releases) { release in
            Button { onOpen(release) } label: {
                VStack(alignment: .leading, spacing: 6) {
                    Artwork(url: release.coverURL, cornerRadius: 10)
                        .frame(width: 150, height: 150)
                        .overlay(alignment: .topLeading) {
                            Text(release.kind.uppercased())
                                .font(.system(size: 10, weight: .heavy))
                                .foregroundStyle(.black)
                                .padding(.horizontal, 7).padding(.vertical, 3)
                                .background(Capsule().fill(.white))
                                .padding(8)
                        }
                    Text(release.title).font(Typo.rowTitle).foregroundStyle(Tone.primary).lineLimit(1)
                    Text("\(release.artist) · \(release.ageLabel)").font(Typo.rowSubtitle).foregroundStyle(Tone.secondary).lineLimit(1)
                }
                .frame(width: 150, alignment: .leading)
            }
            .buttonStyle(.pressable)
        }
    }
}

// MARK: - Il y a un an

/// Accueil : ce que tu écoutais le même jour les années passées.
struct MemoriesCard: View {
    let memories: [Memory]
    @EnvironmentObject private var player: PlayerManager

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            ForEach(memories) { memory in
                Button {
                    if let first = memory.tracks.first {
                        player.play(first, context: memory.tracks, name: "\(memory.label) · \(memory.dateLabel)")
                    }
                } label: {
                    HStack(spacing: 14) {
                        ZStack {
                            ForEach(Array(memory.tracks.prefix(3).enumerated().reversed()), id: \.offset) { index, track in
                                Artwork(url: track.coverURL, cornerRadius: 8)
                                    .frame(width: 64, height: 64)
                                    .rotationEffect(.degrees(Double(index) * 7 - 7))
                                    .offset(x: CGFloat(index) * 6)
                            }
                        }
                        .frame(width: 84, height: 72)
                        VStack(alignment: .leading, spacing: 3) {
                            Text("🕰️ \(memory.label)").font(Typo.headline).foregroundStyle(Tone.primary)
                            Text(memory.dateLabel).font(Typo.caption).foregroundStyle(Tone.secondary)
                            Text(memory.tracks.prefix(3).map(\.title).joined(separator: " · "))
                                .font(Typo.rowSubtitle).foregroundStyle(Tone.secondary).lineLimit(1)
                        }
                        Spacer()
                        Image(systemName: "play.circle.fill").font(.system(size: 30)).foregroundStyle(Tone.primary)
                    }
                    .padding(14)
                    .background(
                        RoundedRectangle(cornerRadius: 20, style: .continuous)
                            .fill(Tone.surface)
                    )
                }
                .buttonStyle(.pressable(scale: 0.98))
            }
        }
    }
}

// MARK: - Carte des écoutes

struct ListeningMapView: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject private var player: PlayerManager
    @ObservedObject private var location = LocationProvider.shared
    @AppStorage("encre.mapPlays") private var recordPlaces = true
    @State private var places: [ListeningPlace] = []
    @State private var selected: ListeningPlace?
    @State private var loading = true

    var body: some View {
        NavigationStack {
            ZStack(alignment: .bottom) {
                Map(selection: Binding(get: { selected?.id }, set: { id in selected = places.first { $0.id == id } })) {
                    ForEach(places) { place in
                        Annotation(place.topArtist ?? "", coordinate: CLLocationCoordinate2D(latitude: place.lat, longitude: place.lon)) {
                            Artwork(url: place.coverURL, cornerRadius: 10)
                                .frame(width: size(place), height: size(place))
                                .overlay(RoundedRectangle(cornerRadius: 10).stroke(.white, lineWidth: 2))
                                .shadow(radius: 6)
                                .onTapGesture { withAnimation(Motion.snappy) { selected = place } }
                        }
                        .tag(place.id)
                    }
                }
                .mapStyle(.standard(elevation: .realistic, pointsOfInterest: .excludingAll))
                .ignoresSafeArea(edges: .bottom)

                if let selected {
                    placeCard(selected).padding(16).transition(.move(edge: .bottom).combined(with: .opacity))
                } else if !loading && places.isEmpty {
                    VStack(spacing: 8) {
                        Text("Ta carte se remplit au fil de tes écoutes.").font(Typo.headline).foregroundStyle(Tone.primary)
                        Text(location.status == .authorizedWhenInUse || location.status == .authorizedAlways
                             ? "Chaque écoute garde un lieu approximatif (à 1 km près)."
                             : "Autorise la localisation pour que tes écoutes soient placées sur la carte.")
                            .font(Typo.rowSubtitle).foregroundStyle(Tone.secondary).multilineTextAlignment(.center)
                        if location.status == .notDetermined {
                            PillButton(title: "Autoriser", systemImage: "location.fill") { location.request() }
                        }
                    }
                    .padding(18)
                    .background(RoundedRectangle(cornerRadius: 20, style: .continuous).fill(.ultraThinMaterial))
                    .padding(16)
                }
            }
            .navigationTitle("Carte de tes écoutes")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Fermer") { dismiss() } }
                ToolbarItem(placement: .primaryAction) {
                    Toggle(isOn: $recordPlaces) { Image(systemName: "location") }.toggleStyle(.button)
                }
            }
        }
        .task {
            location.request()
            places = (try? await APIClient.shared.listeningPlaces()) ?? []
            loading = false
        }
    }

    private func size(_ place: ListeningPlace) -> CGFloat {
        let most = Double(places.map(\.plays).max() ?? 1)
        return 34 + 30 * CGFloat(sqrt(Double(place.plays) / most))
    }

    private func placeCard(_ place: ListeningPlace) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("\(place.plays) écoute\(place.plays > 1 ? "s" : "") ici").font(Typo.headline).foregroundStyle(Tone.primary)
                Spacer()
                Button { withAnimation { selected = nil } } label: { Image(systemName: "xmark.circle.fill").foregroundStyle(Tone.secondary) }
            }
            ForEach(Array(place.topTracks.prefix(3).enumerated()), id: \.offset) { index, top in
                Text("\(index + 1). \(top.title) — \(top.artist ?? "") · \(top.plays)")
                    .font(Typo.rowSubtitle).foregroundStyle(Tone.secondary).lineLimit(1)
            }
            if let track = place.track {
                PillButton(title: "Réécouter", systemImage: "play.fill", kind: .secondary) {
                    player.play(track, context: [track], name: "Carte des écoutes")
                }
            }
        }
        .padding(16)
        .background(RoundedRectangle(cornerRadius: 20, style: .continuous).fill(.ultraThinMaterial))
    }
}

// MARK: - Défis et badges

/// Défis entre amis : un classement par défi de la semaine.
struct FriendsBoardsSection: View {
    let friends: Challenges.Friends

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Entre amis cette semaine").font(Typo.title).foregroundStyle(Tone.primary)
            if let champion = friends.champion {
                Label("\(champion.me ? "Tu es" : "\(champion.name) est") champion de la semaine dernière · \(champion.minutes) min",
                      systemImage: "trophy.fill")
                    .font(Typo.rowSubtitle).foregroundStyle(Tone.primary)
                    .padding(12).frame(maxWidth: .infinity, alignment: .leading)
                    .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Color.orange.opacity(0.18)))
            }
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(alignment: .top, spacing: 12) {
                    ForEach(friends.boards) { board in
                        VStack(alignment: .leading, spacing: 8) {
                            Label(board.title, systemImage: board.icon).font(Typo.rowTitle).foregroundStyle(Tone.primary).lineLimit(1)
                            ForEach(Array(board.ranking.enumerated()), id: \.offset) { index, entry in
                                HStack(spacing: 8) {
                                    Text(index < 3 ? ["🥇", "🥈", "🥉"][index] : "\(index + 1).").frame(width: 24)
                                    Text(entry.me ? "Toi" : entry.name).font(Typo.rowSubtitle)
                                        .foregroundStyle(entry.me ? Color.accentColor : Tone.primary).lineLimit(1)
                                    Spacer(minLength: 6)
                                    Text("\(entry.value) \(board.unit)").font(Typo.caption).foregroundStyle(Tone.secondary).monospacedDigit()
                                }
                            }
                        }
                        .padding(14).frame(width: 250, alignment: .topLeading)
                        .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(Tone.surfaceStrong))
                    }
                }
            }
        }
    }
}

struct ChallengesSection: View {
    let challenges: Challenges
    @State private var showingBadges = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .firstTextBaseline) {
                Text("Défis de la semaine").font(Typo.title).foregroundStyle(Tone.primary)
                Spacer()
                Text(challenges.endsInDays == 0 ? "Dernier jour" : "Encore \(challenges.endsInDays) j")
                    .font(Typo.caption).foregroundStyle(Tone.secondary)
            }
            ForEach(challenges.challenges) { challenge in
                HStack(spacing: 12) {
                    Image(systemName: challenge.done ? "checkmark.seal.fill" : challenge.icon)
                        .font(.system(size: 18, weight: .semibold))
                        .foregroundStyle(challenge.done ? Color.green : Tone.primary)
                        .frame(width: 36, height: 36)
                        .background(Circle().fill(Tone.surfaceStrong))
                    VStack(alignment: .leading, spacing: 5) {
                        HStack {
                            Text(challenge.title).font(Typo.rowTitle).foregroundStyle(Tone.primary).lineLimit(1)
                            Spacer()
                            Text("\(challenge.value)/\(challenge.goal)").font(Typo.caption).foregroundStyle(Tone.secondary).monospacedDigit()
                        }
                        ProgressView(value: Double(challenge.value), total: Double(max(challenge.goal, 1)))
                            .tint(challenge.done ? .green : .white)
                    }
                }
            }
            Button { showingBadges = true } label: {
                HStack {
                    Label("Badges : \(challenges.badges.filter(\.earned).count) / \(challenges.badges.count)", systemImage: "rosette")
                        .font(Typo.rowTitle)
                    Spacer()
                    Image(systemName: "chevron.right")
                }
                .foregroundStyle(Tone.primary)
                .padding(.top, 4)
            }
        }
        .padding(16)
        .background(RoundedRectangle(cornerRadius: 20, style: .continuous).fill(Tone.surface))
        .sheet(isPresented: $showingBadges) { BadgesView(badges: challenges.badges) }
    }
}

struct BadgesView: View {
    let badges: [Challenges.Badge]
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible()), GridItem(.flexible())], spacing: 18) {
                    ForEach(badges) { badge in
                        VStack(spacing: 8) {
                            Image(systemName: badge.icon)
                                .font(.system(size: 28, weight: .bold))
                                .foregroundStyle(badge.earned ? Color.black : Tone.tertiary)
                                .frame(width: 70, height: 70)
                                .background(Circle().fill(badge.earned
                                    ? AnyShapeStyle(LinearGradient(colors: [.yellow, .orange], startPoint: .top, endPoint: .bottom))
                                    : AnyShapeStyle(Tone.surfaceStrong)))
                            Text(badge.title).font(Typo.rowTitle).foregroundStyle(badge.earned ? Tone.primary : Tone.tertiary)
                            Text(badge.description).font(Typo.caption).foregroundStyle(Tone.secondary).multilineTextAlignment(.center)
                        }
                    }
                }
                .padding(20)
            }
            .background(Tone.background)
            .navigationTitle("Badges")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("OK") { dismiss() } } }
        }
    }
}
