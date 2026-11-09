import SwiftUI

/// Le logo de Sona : « Orbite » — un anneau incliné autour d'une sphère de verre, avec une petite
/// lune. Même dessin que l'icône de l'app et que le logo du site (espace 64 × 64, voir `LOGOS.orbite`
/// dans le site). À l'apparition, l'anneau se trace, la sphère se pose, puis la lune se met à
/// tourner sur l'anneau — passant derrière la sphère, puis devant.
struct SonaLogo: View {
    var size: CGFloat = 64
    var live = true

    var body: some View {
        OrbitLogo(size: size, live: live, drawIn: 1.2)
    }
}

struct OrbitLogo: View {
    var size: CGFloat = 64
    /// La lune tourne sans fin.
    var live = true
    /// Durée du tracé d'apparition, en secondes (0 : déjà dessiné).
    var drawIn: Double = 1.3
    @State private var start = Date()

    var body: some View {
        TimelineView(.animation(minimumInterval: 1 / 60)) { timeline in
            let t = timeline.date.timeIntervalSince(start)
            Canvas { context, canvasSize in
                OrbitLogo.draw(&context, side: min(canvasSize.width, canvasSize.height), t: t, drawIn: drawIn, live: live)
            }
        }
        .frame(width: size, height: size)
        .onAppear { start = Date() }
        .accessibilityHidden(true)
    }

    // MARK: Dessin (espace 64 × 64)

    private static let center = CGPoint(x: 32, y: 32)
    private static let radius: CGFloat = 12.5
    private static let tilt = -22.0 * Double.pi / 180

    /// Point de l'ellipse de l'anneau (28 × 10, inclinée de −22°) à l'angle donné.
    private static func ringPoint(_ angle: Double) -> CGPoint {
        let x = 28 * cos(angle)
        let y = 10 * sin(angle)
        let rx = x * cos(tilt) - y * sin(tilt)
        let ry = x * sin(tilt) + y * cos(tilt)
        return CGPoint(x: 32 + rx, y: 32 + ry)
    }

    /// Une moitié de l'anneau, tracée sur la part `fraction` de sa longueur.
    /// Arrière : par le haut (gauche → droite) ; avant : par le bas.
    private static func halfRing(back: Bool, fraction: Double) -> Path {
        let steps = 90
        let count = max(1, Int(Double(steps) * min(1, max(0, fraction))))
        var path = Path()
        for index in 0...count {
            let u = Double(index) / Double(steps)
            let angle = back ? Double.pi + u * Double.pi : Double.pi - u * Double.pi
            let point = ringPoint(angle)
            if index == 0 { path.move(to: point) } else { path.addLine(to: point) }
        }
        return path
    }

    private static func circle(_ r: CGFloat, at p: CGPoint = center) -> Path {
        Path(ellipseIn: CGRect(x: p.x - r, y: p.y - r, width: r * 2, height: r * 2))
    }

    private static func glass(center p: CGPoint, radius r: CGFloat) -> GraphicsContext.Shading {
        .radialGradient(
            Gradient(stops: [
                .init(color: Color(white: 0.86), location: 0),
                .init(color: Color(white: 0.46), location: 0.5),
                .init(color: Color(white: 0.2), location: 1),
            ]),
            center: CGPoint(x: p.x - r * 0.3, y: p.y - r * 0.35), startRadius: 0, endRadius: r * 1.5
        )
    }

    private static var ringShading: GraphicsContext.Shading {
        .linearGradient(
            Gradient(stops: [
                .init(color: Color.white.opacity(0.95), location: 0),
                .init(color: Color.white.opacity(0.5), location: 0.3),
                .init(color: Color.white.opacity(0.34), location: 0.62),
                .init(color: Color.white.opacity(0.9), location: 1),
            ]),
            startPoint: CGPoint(x: 4, y: 26), endPoint: CGPoint(x: 60, y: 38)
        )
    }

    private static var rimShading: GraphicsContext.Shading {
        .linearGradient(
            Gradient(colors: [Color.white.opacity(0.7), Color.white.opacity(0.12)]),
            startPoint: CGPoint(x: 20, y: 18), endPoint: CGPoint(x: 44, y: 46)
        )
    }

    static func draw(_ context: inout GraphicsContext, side: CGFloat, t: Double, drawIn: Double, live: Bool) {
        let k = side / 64
        context.scaleBy(x: k, y: k)

        let appear = drawIn > 0 ? min(1, max(0, t / drawIn)) : 1
        let ease = 1 - pow(1 - appear, 3)
        let ringStyle = StrokeStyle(lineWidth: 2.1, lineCap: .round, lineJoin: .round)

        // La lune : posée à gauche de l'anneau (comme sur l'icône), puis en orbite.
        let moonAngle = 2.52 - (live ? max(0, t - drawIn) * 0.85 : 0)
        let moonIsFront = sin(moonAngle) > 0
        let moonOpacity = min(1, max(0, (appear - 0.6) / 0.4))

        // Lueur derrière la sphère.
        context.drawLayer { layer in
            layer.addFilter(.blur(radius: 2.8))
            layer.opacity = ease
            layer.fill(circle(radius), with: .color(Color.white.opacity(0.1)))
        }

        // Arrière de l'anneau, coupé derrière la sphère (rien ne transparaît à travers).
        context.drawLayer { layer in
            layer.clip(to: circle(radius + 0.6), options: .inverse)
            layer.stroke(halfRing(back: true, fraction: min(1, ease * 2)), with: ringShading, style: ringStyle)
        }

        if !moonIsFront { drawMoon(&context, angle: moonAngle, opacity: moonOpacity) }

        // Sphère de verre : pose en grossissant.
        context.drawLayer { layer in
            layer.translateBy(x: 32, y: 32)
            let scale = 0.55 + 0.45 * ease
            layer.scaleBy(x: scale, y: scale)
            layer.translateBy(x: -32, y: -32)
            layer.opacity = ease

            layer.fill(circle(radius), with: glass(center: center, radius: radius))

            // Ombre portée de l'anneau sur la sphère.
            layer.drawLayer { shade in
                shade.clip(to: circle(radius))
                shade.addFilter(.blur(radius: 1.5))
                shade.translateBy(x: 0, y: 2.2)
                shade.stroke(halfRing(back: false, fraction: 1), with: .color(Color.black.opacity(0.42)),
                             style: StrokeStyle(lineWidth: 5, lineCap: .round))
            }

            layer.stroke(circle(radius), with: rimShading, lineWidth: 1.3)

            // Reflet.
            layer.drawLayer { shine in
                shine.addFilter(.blur(radius: 0.9))
                shine.translateBy(x: 27.6, y: 26.8)
                shine.rotate(by: .degrees(-34))
                shine.fill(Path(ellipseIn: CGRect(x: -4.8, y: -2.5, width: 9.6, height: 5)),
                           with: .color(Color.white.opacity(0.72)))
            }
        }

        // Avant de l'anneau, par-dessus la sphère (même épaisseur et même dégradé : pas de couture).
        context.stroke(halfRing(back: false, fraction: max(0, ease * 2 - 1)), with: ringShading, style: ringStyle)

        if moonIsFront { drawMoon(&context, angle: moonAngle, opacity: moonOpacity) }
    }

    private static func drawMoon(_ context: inout GraphicsContext, angle: Double, opacity: Double) {
        let p = ringPoint(angle)
        context.drawLayer { layer in
            layer.opacity = opacity
            layer.fill(circle(2.2, at: p), with: glass(center: p, radius: 2.2))
            layer.fill(circle(2.2, at: p), with: .color(Color.white.opacity(0.3)))
            layer.stroke(circle(2.2, at: p), with: .color(Color.white.opacity(0.6)), lineWidth: 0.8)
        }
    }
}
