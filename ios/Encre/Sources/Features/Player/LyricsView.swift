import SwiftUI

/// Paroles du morceau en cours (LRCLIB côté serveur). Synchronisées : la
/// ligne chantée en blanc plein, les autres estompées et floutées d'autant
/// plus qu'elles sont loin — l'effet de profondeur de Musique —, recentrage
/// fluide à chaque changement de ligne, et un tap sur une ligne y ramène la
/// lecture. La ligne en cours s'allume mot par mot (karaoké), et le mode
/// « chante » baisse la voix du titre.
struct LyricsView: View {
    @ObservedObject var player: PlayerManager
    let track: Track

    private enum LoadState: Equatable {
        case loading, loaded(Lyrics), unavailable(String)
    }
    @State private var state: LoadState = .loading

    var body: some View {
        Group {
            switch state {
            case .loading:
                ProgressView().tint(.white).frame(maxWidth: .infinity, maxHeight: .infinity)
            case .unavailable(let message):
                EmptyState(systemImage: "quote.bubble", title: "Paroles indisponibles", message: message)
                    .frame(maxHeight: .infinity)
            case .loaded(let lyrics):
                if lyrics.instrumental {
                    EmptyState(systemImage: "pianokeys", title: "Instrumental", message: "Pas de paroles, juste la musique.")
                        .frame(maxHeight: .infinity)
                } else if lyrics.synced {
                    synced(lyrics.lines)
                        .overlay(alignment: .topTrailing) { singButton }
                } else {
                    plain(lyrics.lines)
                }
            }
        }
        .task(id: track.id) { await load() }
    }

    private func synced(_ lines: [Lyrics.Line]) -> some View {
        // Légère avance : la ligne s'allume quand elle est chantée, pas un
        // demi-temps après (le lecteur ne publie sa position que 2 fois/s).
        let position = player.positionSeconds + 0.35
        let active = lines.lastIndex(where: { ($0.time ?? 0) <= position })
        return ScrollViewReader { proxy in
            ScrollView(showsIndicators: false) {
                VStack(alignment: .leading, spacing: 22) {
                    ForEach(Array(lines.enumerated()), id: \.offset) { index, line in
                        let isActive = index == active
                        // Avant la première ligne (intro, ou lecture pas
                        // encore lancée) : tout net et estompé, rien de flou.
                        let blur = active.map { isActive ? 0 : min(3.5, Double(abs(index - $0)) * 0.9) } ?? 0
                        Group {
                            if isActive && !line.text.isEmpty {
                                KaraokeLine(
                                    words: KaraokeLine.timedWords(line, next: lines.dropFirst(index + 1).first?.time),
                                    player: player
                                )
                            } else {
                                Text(line.text.isEmpty ? "♪" : line.text)
                                    .foregroundStyle(Color.white.opacity(index < (active ?? 0) ? 0.3 : 0.45))
                            }
                        }
                            .font(.system(size: 28, weight: .bold))
                            .blur(radius: blur)
                            .scaleEffect(isActive ? 1 : 0.97, anchor: .leading)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .contentShape(Rectangle())
                            .onTapGesture {
                                if let time = line.time { player.seek(toSeconds: time) }
                            }
                            .id(index)
                    }
                }
                .padding(.vertical, 120)
                .animation(Motion.smooth, value: active)
            }
            .mask { EdgeFade() }
            .onAppear {
                if let active { proxy.scrollTo(active, anchor: UnitPoint(x: 0.5, y: 0.35)) }
            }
            .onChange(of: active) { _, newValue in
                guard let newValue else { return }
                withAnimation(Motion.smooth) { proxy.scrollTo(newValue, anchor: UnitPoint(x: 0.5, y: 0.35)) }
            }
        }
    }

    /// Mode « chante » : voix du titre baissée.
    private var singButton: some View {
        Button {
            player.setSingAlong(!player.singAlong)
        } label: {
            Label(player.singAlong ? "Voix coupée" : "Chante", systemImage: player.singAlong ? "mic.fill" : "mic")
                .font(Typo.caption)
                .foregroundStyle(player.singAlong ? .black : .white)
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(Capsule().fill(player.singAlong ? Color.white : Color.white.opacity(0.15)))
        }
        .buttonStyle(.pressable(scale: 0.95))
        .sensoryFeedback(.selection, trigger: player.singAlong)
        .padding(.top, 8)
    }

    private func plain(_ lines: [Lyrics.Line]) -> some View {
        ScrollView(showsIndicators: false) {
            Text(lines.map(\.text).joined(separator: "\n"))
                .font(.system(size: 22, weight: .semibold))
                .lineSpacing(8)
                .foregroundStyle(Tone.primary)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.vertical, 30)
        }
        .mask { EdgeFade() }
    }

    private func load() async {
        state = .loading
        do {
            if let lyrics = try await APIClient.shared.lyrics(for: track) {
                state = .loaded(lyrics)
            } else {
                state = .unavailable("Pas de paroles connues pour ce morceau.")
            }
        } catch {
            guard !Task.isCancelled else { return }
            state = .unavailable("Les paroles n'ont pas pu être chargées.")
        }
    }
}

/// Ligne en cours, allumée mot par mot au rythme de la lecture. Les temps
/// viennent de la source quand elle les donne (LRC enrichi), sinon chaque mot
/// reçoit une part de la ligne proportionnelle à sa longueur.
struct KaraokeLine: View {
    struct TimedWord: Hashable {
        var start: Double
        var end: Double
        var text: String
    }

    let words: [TimedWord]
    @ObservedObject var player: PlayerManager

    var body: some View {
        TimelineView(.animation(minimumInterval: 1 / 30, paused: !player.isPlaying)) { _ in
            let now = player.exactPositionSeconds + 0.1
            words.reduce(Text("")) { text, word in
                let progress = word.end > word.start ? min(1, max(0, (now - word.start) / (word.end - word.start))) : 1
                return text + Text(word.text).foregroundStyle(Color.white.opacity(0.4 + 0.6 * progress))
            }
        }
    }

    static func timedWords(_ line: Lyrics.Line, next: Double?) -> [TimedWord] {
        let start = line.time ?? 0
        if let words = line.words, !words.isEmpty {
            return words.enumerated().map { index, word in
                let following = index + 1 < words.count ? words[index + 1].time : min(next ?? word.time + 1, word.time + 1.2)
                return TimedWord(start: word.time, end: max(word.time + 0.05, following), text: word.text)
            }
        }
        let tokens = line.text.split(separator: " ", omittingEmptySubsequences: true).map(String.init)
        guard !tokens.isEmpty else { return [] }
        let letters = Double(tokens.reduce(0) { $0 + $1.count })
        // Chanté à peu près à ce rythme ; une longue pause avant la ligne
        // suivante ne doit pas étirer la ligne.
        let natural = letters * 0.085 + 0.8
        let available = (next ?? start + natural) - start - 0.15
        let duration = max(0.6, min(natural, available))
        let weights = tokens.map { Double($0.count) + 2 }
        let total = weights.reduce(0, +)
        var cursor = start
        return tokens.enumerated().map { index, token in
            let length = duration * weights[index] / total
            defer { cursor += length }
            return TimedWord(start: cursor, end: cursor + length, text: index + 1 < tokens.count ? token + " " : token)
        }
    }
}
