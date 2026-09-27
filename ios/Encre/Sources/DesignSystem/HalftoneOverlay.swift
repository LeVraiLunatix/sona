import SwiftUI

/// Trame de points façon impression offset (`.halftone` dans
/// `_ds/.../styles.css`, et le calque de points de `Cover.dc.html`) : une
/// grille de petits points multipliés sur l'image, dessinée avec `Canvas`
/// plutôt qu'une pile de vues (des centaines de points par pochette, répétés
/// sur chaque vignette d'une liste — `Canvas` dessine ça en un seul passage
/// Core Graphics au lieu de créer autant de vues SwiftUI).
struct HalftoneOverlay: View {
    var spacing: CGFloat = 4
    var dotRadius: CGFloat = 0.6
    var opacity: Double = 0.16

    var body: some View {
        Canvas { context, size in
            let color = GraphicsContext.Shading.color(.black.opacity(opacity))
            var x: CGFloat = spacing / 2
            while x < size.width {
                var y: CGFloat = spacing / 2
                while y < size.height {
                    let rect = CGRect(x: x - dotRadius, y: y - dotRadius, width: dotRadius * 2, height: dotRadius * 2)
                    context.fill(Path(ellipseIn: rect), with: color)
                    y += spacing
                }
                x += spacing
            }
        }
        .blendMode(.multiply)
        .allowsHitTesting(false)
    }
}

extension View {
    func halftone() -> some View {
        overlay(HalftoneOverlay())
    }
}
