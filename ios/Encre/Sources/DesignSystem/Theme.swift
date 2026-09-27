import SwiftUI

/// Jetons du design "Encre" (voir le handoff Claude Design :
/// `_ds/broadsheet-.../styles.css`) — thème imprimerie/CMJN : papier crème,
/// encre presque noire, cyan et magenta en accents, jaune process réservé
/// aux seuls effets d'impression (jamais à l'UI).
enum EncreColor {
    static let bg = Color(hex: 0xF3F2F2)
    static let surface = Color(hex: 0xEAE9E9)
    static let text = Color(hex: 0x201E1D)
    static let accent = Color(hex: 0x0088B0) // cyan
    static let accent2 = Color(hex: 0xD6006C) // magenta
    static let processYellow = Color(hex: 0xEDBB00)

    static let neutral100 = Color(hex: 0xF8F4F4)
    static let neutral200 = Color(hex: 0xEAE7E7)
    static let neutral300 = Color(hex: 0xD7D3D3)
    static let neutral400 = Color(hex: 0xBAB6B6)
    static let neutral500 = Color(hex: 0x9B9797)
    static let neutral600 = Color(hex: 0x7D7979)
    static let neutral700 = Color(hex: 0x605D5D)
    static let neutral800 = Color(hex: 0x444141)
    static let neutral900 = Color(hex: 0x2D2B2B)

    static let accent700 = Color(hex: 0x006786)
    static let accent800 = Color(hex: 0x004961)
    static let accent2_700 = Color(hex: 0xAA0B56)
    static let accent2_800 = Color(hex: 0x790E3D)

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
