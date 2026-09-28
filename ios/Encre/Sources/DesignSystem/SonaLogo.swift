import SwiftUI

/// Le « S » de Sona : deux demi-cercles aux extrémités arrondies, d'un seul
/// trait — même tracé que l'icône (`Scripts/make_icon.py`). `progress` (0…1)
/// permet de le faire se dessiner.
struct SonaMark: Shape {
    var progress: CGFloat = 1

    var animatableData: CGFloat {
        get { progress }
        set { progress = newValue }
    }

    // Mêmes proportions que l'icône (unités du carré de dessin).
    static let radius: CGFloat = 0.205
    static let stroke: CGFloat = 0.115

    func path(in rect: CGRect) -> Path {
        let side = min(rect.width, rect.height)
        let origin = CGPoint(x: rect.midX - side / 2, y: rect.midY - side / 2)
        let r = Self.radius * side
        let cx = origin.x + side / 2
        let cy = origin.y + side / 2

        // Un seul tracé continu : de l'extrémité haute (arc du haut parcouru à
        // l'envers) jusqu'à l'extrémité basse, en passant par le centre.
        var points: [CGPoint] = []
        func arc(_ center: CGPoint, from start: Double, to end: Double) {
            let steps = 90
            for i in 0...steps {
                let a = (start + (end - start) * Double(i) / Double(steps)) * .pi / 180
                points.append(CGPoint(x: center.x + r * cos(a), y: center.y + r * sin(a)))
            }
        }
        arc(CGPoint(x: cx, y: cy - r), from: 330, to: 90)
        arc(CGPoint(x: cx, y: cy + r), from: 270, to: 510)

        var path = Path()
        path.addLines(points)
        return path.trimmedPath(from: 0, to: progress)
    }
}

/// Logo prêt à l'emploi, blanc, qui se dessine à son apparition.
struct SonaLogo: View {
    var size: CGFloat = 64
    var animated = true
    @State private var progress: CGFloat = 0

    var body: some View {
        SonaMark(progress: animated ? progress : 1)
            .stroke(Tone.primary, style: StrokeStyle(lineWidth: SonaMark.stroke * size, lineCap: .round, lineJoin: .round))
            .frame(width: size, height: size)
            .shadow(color: .white.opacity(0.25), radius: size * 0.08)
            .onAppear {
                guard animated, progress == 0 else { return }
                withAnimation(.easeInOut(duration: 1.1).delay(0.15)) { progress = 1 }
            }
    }
}
