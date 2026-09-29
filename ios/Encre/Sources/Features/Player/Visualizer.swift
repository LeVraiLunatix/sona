import SwiftUI

/// Visualiseur du lecteur : des barres qui dansent sur le son réel (niveau
/// par bande de fréquence mesuré par `AudioEffects`), des basses à gauche
/// aux aigus à droite, en miroir autour du centre.
struct VisualizerBars: View {
    var isPlaying: Bool
    var color: Color = .white

    var body: some View {
        TimelineView(.animation(minimumInterval: 1 / 30, paused: !isPlaying)) { timeline in
            // L'heure de l'image, lue dans le dessin : sans elle, le Canvas
            // ne se redessine pas (rien d'autre ne change à ses yeux).
            let frame = timeline.date.timeIntervalSinceReferenceDate
            Canvas { context, size in
                _ = frame
                let bands = AudioEffects.levelBands
                // Basses au centre, aigus vers les bords.
                let order = Array((0..<bands).reversed()) + Array(0..<bands)
                let count = order.count
                let gap: CGFloat = 4
                let width = max(2, (size.width - gap * CGFloat(count - 1)) / CGFloat(count))
                for (slot, band) in order.enumerated() {
                    let level = isPlaying ? CGFloat(AudioEffects.level(band)) : 0
                    let height = max(width, level * size.height)
                    let rect = CGRect(
                        x: CGFloat(slot) * (width + gap), y: (size.height - height) / 2,
                        width: width, height: height
                    )
                    context.fill(
                        Path(roundedRect: rect, cornerRadius: width / 2),
                        with: .color(color.opacity(0.45 + 0.55 * Double(level)))
                    )
                }
            }
        }
        .accessibilityHidden(true)
    }
}
