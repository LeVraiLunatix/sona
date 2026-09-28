import SwiftUI

/// Jetons du design "Encre" — variante sombre et sobre : fond quasi noir,
/// texte presque blanc, cyan et magenta gardés comme seuls accents (un peu
/// éclaircis pour rester lisibles sur fond sombre), jaune process réservé aux
/// seuls effets d'impression (jamais à l'UI). Les noms `neutral100...900`
/// restent croissants de clair à sombre comme avant l'inversion, pour ne pas
/// avoir à retoucher tous les appels existants (`neutral700` reste "texte
/// secondaire", `neutral300` reste "à peine visible", etc.).
enum EncreColor {
    static let bg = Color(hex: 0x121112)
    static let surface = Color(hex: 0x1C1B1C)
    static let text = Color(hex: 0xF4F1EF)
    static let accent = Color(hex: 0x28B8E0) // cyan, éclairci pour le fond sombre
    static let accent2 = Color(hex: 0xFF4FA0) // magenta, éclairci pour le fond sombre
    static let processYellow = Color(hex: 0xEDBB00)

    static let neutral100 = Color(hex: 0x232224)
    static let neutral200 = Color(hex: 0x2C2B2D)
    static let neutral300 = Color(hex: 0x3A383B)
    static let neutral400 = Color(hex: 0x504E51)
    static let neutral500 = Color(hex: 0x6E6B6E)
    static let neutral600 = Color(hex: 0x8F8C8F)
    static let neutral700 = Color(hex: 0xAFACAE)
    static let neutral800 = Color(hex: 0xD2CFD0)
    static let neutral900 = Color(hex: 0xF4F1EF)

    static let accent700 = Color(hex: 0x6CD3F0)
    static let accent800 = Color(hex: 0x9FE2F6)
    static let accent2_700 = Color(hex: 0xFF8AC0)
    static let accent2_800 = Color(hex: 0xFFB6D8)

    /// Couleur d'accent "spot" active : cyan par défaut (le prototype permet
    /// de basculer sur magenta — pas encore exposé côté app).
    static let spot = accent
    static let spotDeep = accent700
}

enum EncreFont {
    // Source Serif 4, embarquée (voir Resources/Fonts) : les noms PostScript
    // exacts, à défaut desquels SwiftUI retombe silencieusement sur le
    // système — vérifiés avec fonttools sur les .ttf embarquées.
    private static let regular = "SourceSerif4-Regular"
    private static let semibold = "SourceSerif4-SemiBold"
    private static let italic = "SourceSerif4-Italic"

    static func heading(_ size: CGFloat) -> Font { .custom(semibold, size: size) }
    static func body(_ size: CGFloat) -> Font { .custom(regular, size: size) }
    static func bodyItalic(_ size: CGFloat) -> Font { .custom(italic, size: size) }
}

extension Color {
    init(hex: UInt32) {
        let r = Double((hex >> 16) & 0xFF) / 255
        let g = Double((hex >> 8) & 0xFF) / 255
        let b = Double(hex & 0xFF) / 255
        self.init(red: r, green: g, blue: b)
    }
}

enum EncreShadow {
    static let sm = Shadow(radius: 2, y: 1, opacity: 0.14)
    static let md = Shadow(radius: 10, y: 3, opacity: 0.16)
    static let lg = Shadow(radius: 32, y: 12, opacity: 0.22)

    struct Shadow {
        let radius: CGFloat
        let y: CGFloat
        let opacity: Double
    }
}

extension View {
    func encreShadow(_ shadow: EncreShadow.Shadow) -> some View {
        self.shadow(color: EncreColor.neutral900.opacity(shadow.opacity), radius: shadow.radius, x: 0, y: shadow.y)
    }
}
