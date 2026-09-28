import SwiftUI

/// Le logo de Sona : un « S » dessiné par des barres de forme d'onde — même
/// géométrie que l'icône (`SonaLogoGeometry`, générée par
/// `Scripts/make_icon.py`). À l'apparition, les barres montent l'une après
/// l'autre ; ensuite, si `live`, elles ondulent doucement comme un égaliseur
/// (assez peu pour que le S reste lisible).
struct SonaLogo: View {
    var size: CGFloat = 64
    var live = true
    @State private var appeared = false

    var body: some View {
        TimelineView(.animation(minimumInterval: 1 / 30, paused: !live || !appeared)) { timeline in
            let t = timeline.date.timeIntervalSinceReferenceDate
            Canvas { context, canvas in
                let side = min(canvas.width, canvas.height)
                let width = SonaLogoGeometry.barWidth * side
                for (index, bar) in SonaLogoGeometry.bars.enumerated() {
                    let top = bar.top * side
                    let bottom = bar.bottom * side
                    let height = bottom - top
                    // Ondulation propre à chaque barre, déphasée le long du S.
                    let wobble = live ? 1 + 0.12 * sin(t * 3.1 + Double(index) * 0.7) : 1
                    let scaled = max(width, height * CGFloat(wobble))
                    let center = (top + bottom) / 2
                    let rect = CGRect(x: bar.x * side - width / 2, y: center - scaled / 2, width: width, height: scaled)
                    context.fill(Path(roundedRect: rect, cornerRadius: width / 2), with: .color(.white))
                }
            }
            .mask {
                // Apparition de gauche à droite.
                GeometryReader { proxy in
                    Rectangle()
                        .frame(width: appeared ? proxy.size.width : 0)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        }
        .frame(width: size, height: size)
        .shadow(color: .white.opacity(0.25), radius: size * 0.08)
        .onAppear {
            guard !appeared else { return }
            withAnimation(.easeOut(duration: 0.9).delay(0.15)) { appeared = true }
        }
    }
}
