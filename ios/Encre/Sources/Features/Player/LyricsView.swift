import SwiftUI

/// Paroles du morceau en cours (LRCLIB côté serveur). Synchronisées : la
/// ligne chantée en blanc plein, les autres estompées et floutées d'autant
/// plus qu'elles sont loin — l'effet de profondeur de Musique —, recentrage
/// fluide à chaque changement de ligne, et un tap sur une ligne y ramène la
/// lecture.
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
                        let distance = abs(index - (active ?? -1))
                        let isActive = index == active
                        Text(line.text.isEmpty ? "♪" : line.text)
                            .font(.system(size: 28, weight: .bold))
                            .foregroundStyle(Color.white.opacity(isActive ? 1 : (index < (active ?? 0) ? 0.3 : 0.4)))
                            .blur(radius: isActive ? 0 : min(3.5, Double(distance) * 0.9))
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
