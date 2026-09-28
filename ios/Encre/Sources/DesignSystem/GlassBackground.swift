import SwiftUI

/// Reproduit le "verre liquide" du prototype (`--g-bg`, `--g-bf`, `--g-bd`,
/// `--g-sh` dans Encre.dc.html) : un flou saturé, un reflet diagonal, une
/// bordure claire et une ombre à la fois interne (liseré lumineux) et externe.
/// Utilisé pour les pastilles flottantes — barre d'onglets, mini-lecteur,
/// boutons ronds sur pochette.
struct GlassBackground: ViewModifier {
    var shape: AnyShape

    func body(content: Content) -> some View {
        content
            .background {
                shape
                    .fill(.ultraThinMaterial)
                    .overlay {
                        // Opacités revues à la baisse pour le thème sombre :
                        // les mêmes reflets qu'en clair (0.5/0.45/0.72)
                        // paraissaient criards sur un fond quasi noir — un
                        // "verre" sobre a un reflet discret, pas un flash.
                        shape.fill(
                            LinearGradient(
                                colors: [.white.opacity(0.16), .white.opacity(0.04)],
                                startPoint: .topLeading, endPoint: .bottomTrailing
                            )
                        )
                    }
                    .overlay {
                        // Reflet diagonal (--g-sheen) : concentré en haut-gauche.
                        shape.fill(
                            RadialGradient(
                                colors: [.white.opacity(0.14), .clear],
                                center: UnitPoint(x: 0.25, y: 0),
                                startRadius: 0, endRadius: 220
                            )
                        )
                    }
                    .overlay {
                        // `.stroke` plutôt que `.strokeBorder` : `AnyShape`
                        // n'est pas `InsettableShape`, seul `.stroke` est
                        // disponible sur un `Shape` quelconque.
                        shape.stroke(Color.white.opacity(0.16), lineWidth: 1)
                    }
            }
            .encreShadow(EncreShadow.lg)
    }
}

extension View {
    /// Fond "verre liquide" derrière une forme quelconque (capsule, cercle,
    /// rectangle arrondi...).
    func glassBackground<S: Shape>(_ shape: S) -> some View {
        modifier(GlassBackground(shape: AnyShape(shape)))
    }

    func glassCapsule() -> some View { glassBackground(Capsule()) }
    func glassCircle() -> some View { glassBackground(Circle()) }
    func glassRounded(_ radius: CGFloat = 24) -> some View {
        glassBackground(RoundedRectangle(cornerRadius: radius, style: .continuous))
    }
}
