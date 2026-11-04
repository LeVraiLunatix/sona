import SwiftUI

/// Surfaces sobres : un aplat gris très léger, sans verre, sans reflet ni
/// ombre. On garde les mêmes points d'entrée (`glassCapsule`, `glassCircle`,
/// `glassRounded`…) pour ne pas toucher les écrans, mais ils ne dessinent
/// plus qu'un fond plat. Les barres système (onglets, navigation) gardent
/// leur rendu natif iOS.
struct GlassBackground: ViewModifier {
    var shape: AnyShape
    var tint: Color?
    var interactive: Bool

    func body(content: Content) -> some View {
        content.background(shape.fill(tint?.opacity(0.18) ?? Tone.surfaceStrong))
    }
}

extension View {
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
