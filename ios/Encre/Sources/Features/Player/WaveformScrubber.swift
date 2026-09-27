import SwiftUI

/// Défilement façon forme d'onde (Encre.dc.html : `bars`/`wfDown`/`wfMove`) :
/// Sona n'a pas d'empreinte audio réelle à afficher (elle sert uniquement à
/// vérifier le fichier téléchargé côté serveur, jamais exposée par l'API),
/// donc les barres sont un motif déterministe tiré de l'identifiant du
/// morceau — décoratif, mais stable d'une lecture à l'autre.
struct WaveformScrubber: View {
    let trackId: String
    let progress: Double // 0...1
    var onSeek: (Double) -> Void

    private var heights: [CGFloat] {
        var generator = SeededGenerator(seed: trackId.hashValue)
        return (0..<48).map { i in
            let base = 0.35 + 0.55 * abs(sin(Double(i) * 0.6 + Double(generator.next() % 100) / 140))
            return CGFloat(base)
        }
    }

    var body: some View {
        let bars = heights
        return GeometryReader { proxy in
            HStack(alignment: .bottom, spacing: 3) {
                ForEach(0..<bars.count, id: \.self) { i in
                    let played = Double(i) / Double(bars.count) <= progress
                    Capsule()
                        .fill(played ? EncreColor.text : EncreColor.neutral300)
                        .frame(height: proxy.size.height * bars[i])
                }
            }
            .frame(maxHeight: .infinity, alignment: .bottom)
            .contentShape(Rectangle())
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { value in
                        let fraction = Double(value.location.x / proxy.size.width)
                        onSeek(min(1, max(0, fraction)))
                    }
            )
        }
    }
}

/// Générateur pseudo-aléatoire déterministe (même graine -> même suite) :
/// `Int.random` dépend de l'aléa système, ce qui redessinerait les barres à
/// chaque rendu de la vue.
private struct SeededGenerator {
    private var state: UInt64
    init(seed: Int) { state = UInt64(bitPattern: Int64(seed)) &+ 0x9E3779B97F4A7C15 }
    mutating func next() -> Int {
        state ^= state << 13
        state ^= state >> 7
        state ^= state << 17
        return Int(state % 1000)
    }
}
