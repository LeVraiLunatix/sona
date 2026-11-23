import SwiftUI

/// Le logo de Sona : un « S » plein, gris clair (#D2D1D8) sur noir — même dessin que l'icône de l'app, le
/// site et l'app Windows (pack « Fin »). Chemin généré à partir du SVG du pack (arcs convertis en courbes),
/// ramené dans un carré, glyphe centré et agrandi au maximum. Partagé avec les widgets.
struct SonaMark: Shape {
    static let color = Color(red: 210 / 255, green: 209 / 255, blue: 216 / 255)

    func path(in rect: CGRect) -> Path {
        let side = min(rect.width, rect.height)
        let origin = CGPoint(x: rect.midX - side / 2, y: rect.midY - side / 2)
        func p(_ x: CGFloat, _ y: CGFloat) -> CGPoint { CGPoint(x: origin.x + x * side, y: origin.y + y * side) }
        var path = Path()
        path.move(to: p(0.93234, 0.01324))
        path.addLine(to: p(0.09127, 0.01324))
        path.addCurve(to: p(0.00000, 0.10450), control1: p(0.04086, 0.01324), control2: p(0.00000, 0.05410))
        path.addLine(to: p(0.00000, 0.17648))
        path.addCurve(to: p(0.01941, 0.23271), control1: p(0.00001, 0.19687), control2: p(0.00684, 0.21666))
        path.addLine(to: p(0.33806, 0.63988))
        path.addCurve(to: p(0.34686, 0.72328), control1: p(0.35670, 0.66371), control2: p(0.36011, 0.69608))
        path.addCurve(to: p(0.27575, 0.76772), control1: p(0.33361, 0.75047), control2: p(0.30600, 0.76772))
        path.addLine(to: p(0.09127, 0.76772))
        path.addCurve(to: p(0.00000, 0.85899), control1: p(0.04086, 0.76772), control2: p(0.00000, 0.80858))
        path.addLine(to: p(0.00000, 0.89550))
        path.addCurve(to: p(0.09127, 0.98676), control1: p(0.00000, 0.94590), control2: p(0.04086, 0.98676))
        path.addLine(to: p(0.86541, 0.98676))
        path.addCurve(to: p(0.94057, 0.94729), control1: p(0.89543, 0.98677), control2: p(0.92353, 0.97201))
        path.addCurve(to: p(0.95071, 0.86300), control1: p(0.95761, 0.92257), control2: p(0.96140, 0.89106))
        path.addLine(to: p(0.92193, 0.78743))
        path.addCurve(to: p(0.73009, 0.44871), control1: p(0.87547, 0.66548), control2: p(0.81079, 0.55127))
        path.addLine(to: p(0.66054, 0.36030))
        path.addCurve(to: p(0.65153, 0.27685), control1: p(0.64181, 0.33650), control2: p(0.63831, 0.30409))
        path.addCurve(to: p(0.72266, 0.23228), control1: p(0.66476, 0.24960), control2: p(0.69238, 0.23229))
        path.addLine(to: p(0.86382, 0.23228))
        path.addCurve(to: p(0.93976, 0.19164), control1: p(0.89434, 0.23228), control2: p(0.92283, 0.21703))
        path.addLine(to: p(0.98862, 0.11838))
        path.addCurve(to: p(0.99200, 0.04893), control1: p(1.00247, 0.09763), control2: p(1.00377, 0.07093))
        path.addCurve(to: p(0.93234, 0.01324), control1: p(0.98022, 0.02693), control2: p(0.95729, 0.01321))
        path.closeSubpath()
        return path
    }
}
