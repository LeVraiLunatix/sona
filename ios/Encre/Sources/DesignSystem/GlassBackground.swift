import SwiftUI

/// Vrai Liquid Glass système (iOS 26, `glassEffect(_:in:)`) plutôt que
/// l'ancienne reproduction maison au `.ultraThinMaterial` + dégradés blancs :
/// le rendu (réfraction, reflets spéculaires, ombre de contact) est fourni
/// par le système et réagit correctement au fond qui défile dessous, chose
/// qu'un flou statique ne pouvait pas simuler.
struct GlassBackground: ViewModifier {
    var shape: AnyShape
    var tint: Color?
    var interactive: Bool

    func body(content: Content) -> some View {
        var glass = Glass.regular
        if let tint { glass = glass.tint(tint) }
        if interactive { glass = glass.interactive() }
        return content.glassEffect(glass, in: shape)
    }
}

extension View {
    /// Fond "verre liquide" derrière une forme quelconque (capsule, cercle,
    /// rectangle arrondi...). `interactive` ajoute la réaction tactile
    /// système (léger allumage/ondulation au toucher) — à réserver aux
    /// éléments qu'on presse vraiment (boutons de transport, onglets), pas
    /// aux conteneurs purement décoratifs.
    func glassBackground<S: Shape>(_ shape: S, tint: Color? = nil, interactive: Bool = false) -> some View {
        modifier(GlassBackground(shape: AnyShape(shape), tint: tint, interactive: interactive))
    }

    func glassCapsule(tint: Color? = nil, interactive: Bool = false) -> some View {
        glassBackground(Capsule(), tint: tint, interactive: interactive)
    }
    func glassCircle(tint: Color? = nil, interactive: Bool = false) -> some View {
        glassBackground(Circle(), tint: tint, interactive: interactive)
    }
    func glassRounded(_ radius: CGFloat = 24, tint: Color? = nil, interactive: Bool = false) -> some View {
        glassBackground(RoundedRectangle(cornerRadius: radius, style: .continuous), tint: tint, interactive: interactive)
    }
}
