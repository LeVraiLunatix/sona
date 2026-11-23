import SwiftUI

/// Le logo de Sona : le « S » plein, gris clair sur noir (pack « Fin »), le même que l'icône de l'app, le
/// site et l'app Windows — voir `SonaMark` (SonaLogoGeometry.swift). À l'apparition, il se révèle de gauche à
/// droite en grossissant à peine ; ensuite, si `live`, un halo discret respire autour de lui.
struct SonaLogo: View {
    var size: CGFloat = 64
    /// Le halo respire sans fin.
    var live = true
    /// Durée de l'apparition, en secondes (0 : le logo est déjà là, comme sur l'écran de lancement).
    var drawIn: Double = 1.0
    @State private var start = Date()

    var body: some View {
        TimelineView(.animation(minimumInterval: 1 / 30)) { timeline in
            let t = timeline.date.timeIntervalSince(start)
            let appear = drawIn > 0 ? min(1, max(0, t / drawIn)) : 1
            let ease = 1 - pow(1 - appear, 3)
            let breathe = live ? 0.5 + 0.5 * sin(t * 1.8) : 0.5
            SonaMark()
                .fill(SonaMark.color)
                .frame(width: size, height: size)
                .mask(alignment: .leading) {
                    Rectangle().frame(width: size * min(1, ease * 1.15))
                }
                .scaleEffect(0.92 + 0.08 * ease)
                .opacity(min(1, ease * 2))
                .shadow(color: Color.white.opacity(0.16 + 0.12 * breathe), radius: size * (0.1 + 0.05 * breathe))
        }
        .frame(width: size, height: size)
        .onAppear { start = Date() }
        .accessibilityHidden(true)
    }
}
