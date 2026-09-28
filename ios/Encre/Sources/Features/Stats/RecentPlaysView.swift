import SwiftUI

/// Journal des écoutes (les « scrobbles »), du plus récent au plus ancien,
/// regroupées par jour.
struct RecentPlaysView: View {
    @EnvironmentObject private var player: PlayerManager
    @State private var plays: [RecentPlay] = []
    @State private var isLoading = true
    @State private var errorMessage: String?

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 22, pinnedViews: [.sectionHeaders]) {
                if isLoading && plays.isEmpty {
                    ProgressView().tint(.white).frame(maxWidth: .infinity).padding(.top, 80)
                } else if plays.isEmpty {
                    EmptyState(systemImage: "clock", title: "Aucune écoute pour l'instant",
                               message: errorMessage ?? "Les morceaux écoutés au moins à moitié apparaîtront ici.")
                }
                ForEach(groups, id: \.day) { group in
                    Section {
                        ForEach(group.plays) { play in row(play) }
                    } header: {
                        Text(group.day)
                            .font(Typo.caption)
                            .tracking(1.2)
                            .foregroundStyle(Tone.secondary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.vertical, 8)
                            .background(Tone.background)
                    }
                }
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 24)
        }
        .scrollIndicators(.hidden)
        .background(Tone.background)
        .navigationTitle("Historique")
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
        .refreshable { await load() }
    }

    private func row(_ play: RecentPlay) -> some View {
        HStack(spacing: 14) {
            Artwork(url: play.coverURL, cornerRadius: 6).frame(width: 46, height: 46)
            VStack(alignment: .leading, spacing: 3) {
                Text(play.title).font(Typo.rowTitle).foregroundStyle(Tone.primary).lineLimit(1)
                Text(play.artist).font(Typo.rowSubtitle).foregroundStyle(Tone.secondary).lineLimit(1)
            }
            Spacer(minLength: 8)
            VStack(alignment: .trailing, spacing: 3) {
                Text(Self.time(play.playedAt)).font(Typo.mono).foregroundStyle(Tone.tertiary)
                if play.origin == "lastfm" {
                    Text("Last.fm").font(.system(size: 10, weight: .semibold)).foregroundStyle(Tone.tertiary)
                }
            }
        }
        .contentShape(Rectangle())
        .onTapGesture {
            guard let source = play.source, let id = play.sourceId else { return }
            Task {
                if let track = try? await APIClient.shared.track(source: source, id: id) { player.play(track) }
            }
        }
    }

    private struct DayGroup {
        let day: String
        let plays: [RecentPlay]
    }

    private var groups: [DayGroup] {
        var result: [DayGroup] = []
        for play in plays {
            let day = Self.day(play.playedAt)
            if let last = result.last, last.day == day {
                result[result.count - 1] = DayGroup(day: day, plays: last.plays + [play])
            } else {
                result.append(DayGroup(day: day, plays: [play]))
            }
        }
        return result
    }

    private func load() async {
        isLoading = true
        do {
            plays = try await APIClient.shared.recentPlays(limit: 200)
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
        isLoading = false
    }

    private static let parser: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter
    }()

    private static func date(_ iso: String) -> Date? { parser.date(from: iso) }

    static func time(_ iso: String) -> String {
        guard let date = date(iso) else { return "" }
        return date.formatted(date: .omitted, time: .shortened)
    }

    static func day(_ iso: String) -> String {
        guard let date = date(iso) else { return "" }
        let calendar = Calendar.current
        if calendar.isDateInToday(date) { return "AUJOURD'HUI" }
        if calendar.isDateInYesterday(date) { return "HIER" }
        return date.formatted(.dateTime.weekday(.wide).day().month(.wide)).uppercased()
    }
}
