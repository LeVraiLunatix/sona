import SwiftUI

/// Artistes en featuring des titres joués : les résultats de recherche ne
/// donnent que l'artiste principal, on va chercher les invités à la lecture.
@MainActor
final class TrackArtistsCache: ObservableObject {
    static let shared = TrackArtistsCache()

    @Published private(set) var byId: [String: [TrackArtist]] = [:]
    private var requested: Set<String> = []

    func load(_ track: Track) async {
        guard track.artists?.isEmpty != false,
              ["deezer", "spotify"].contains(track.source),
              requested.insert(track.id).inserted else { return }
        if let credits = try? await APIClient.shared.credits(for: track, details: false), !credits.artists.isEmpty {
            byId[track.id] = credits.artists
        }
    }

    func line(for track: Track) -> String {
        track.artistLine(extra: byId[track.id])
    }
}

/// Feuille « Crédits du titre » : artistes, compositeurs, producteurs, label…
struct CreditsView: View {
    let track: Track
    @State private var credits: TrackCredits?
    @State private var failed = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    Text(track.title)
                        .font(.system(size: 22, weight: .bold))
                        .foregroundStyle(Tone.primary)
                        .padding(.bottom, 14)
                    if let credits {
                        ForEach(rows(credits), id: \.0) { row in
                            VStack(alignment: .leading, spacing: 3) {
                                Text(row.0).font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
                                Text(row.1).font(Typo.rowTitle).foregroundStyle(Tone.primary)
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.vertical, 10)
                            Divider().overlay(Tone.separator)
                        }
                        if credits.credits.isEmpty {
                            Text("Compositeurs et producteurs : pas encore connus pour ce titre.")
                                .font(Typo.rowSubtitle).foregroundStyle(Tone.tertiary).padding(.top, 14)
                        }
                    } else if failed {
                        Text("Crédits indisponibles pour le moment.").foregroundStyle(Tone.secondary)
                    } else {
                        ProgressView().tint(.white).frame(maxWidth: .infinity).padding(.top, 40)
                    }
                }
                .padding(20)
            }
            .background(Tone.background)
            .navigationBarTitleDisplayMode(.inline)
        }
        .presentationDetents([.medium, .large])
        .task {
            do { credits = try await APIClient.shared.credits(for: track) } catch { failed = true }
        }
    }

    private func rows(_ c: TrackCredits) -> [(String, String)] {
        let main = c.artists.filter { $0.role != "featured" }.map(\.name)
        let feats = c.artists.filter { $0.role == "featured" }.map(\.name)
        var rows: [(String, String)] = []
        rows.append((main.count > 1 ? "Artistes" : "Artiste", (main.isEmpty ? [track.artist] : main).joined(separator: ", ")))
        if !feats.isEmpty { rows.append(("Featuring", feats.joined(separator: ", "))) }
        for group in c.credits { rows.append((group.role, group.names.joined(separator: ", "))) }
        var album = [c.album ?? track.album].compactMap { $0 }
        if let disc = c.discNumber, let n = c.trackNumber { album.append("Disque \(disc) · piste \(n)") }
        if !album.isEmpty { rows.append(("Album", album.joined(separator: " · "))) }
        if let label = c.label { rows.append(("Label", label)) }
        if let date = Self.dateLabel(c.releaseDate) { rows.append(("Sortie", date)) }
        if !c.genres.isEmpty { rows.append(("Genres", c.genres.joined(separator: ", "))) }
        if let s = c.durationSeconds { rows.append(("Durée", String(format: "%d:%02d", s / 60, s % 60))) }
        if let isrc = c.isrc { rows.append(("ISRC", isrc)) }
        return rows
    }

    private static func dateLabel(_ iso: String?) -> String? {
        guard let iso, !iso.isEmpty else { return nil }
        let parser = DateFormatter()
        parser.locale = Locale(identifier: "en_US_POSIX")
        parser.dateFormat = "yyyy-MM-dd"
        guard let date = parser.date(from: iso) else { return iso }
        let out = DateFormatter()
        out.locale = Locale(identifier: "fr_FR")
        out.dateStyle = .long
        return out.string(from: date)
    }
}
