import CoreImage
import SwiftUI
import UIKit

/// Pochette (morceau, album, artiste, radio) : l'image distante en fondu
/// dès qu'elle arrive, sinon un aplat sombre discret avec une note — jamais
/// de couleur criarde en attendant.
struct Artwork: View {
    let url: String?
    var cornerRadius: CGFloat = 8
    var symbol: String = "music.note"

    var body: some View {
        GeometryReader { proxy in
            ZStack {
                placeholder(size: proxy.size)
                if let url, let imageURL = URL(string: url) {
                    AsyncImage(url: imageURL, transaction: Transaction(animation: .easeOut(duration: 0.35))) { phase in
                        if case .success(let image) = phase {
                            image.resizable().scaledToFill().transition(.opacity)
                        }
                    }
                }
            }
            .frame(width: proxy.size.width, height: proxy.size.height)
        }
        .clipShape(RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
        .overlay(
            // Filet presque invisible : détache une pochette noire du fond noir.
            RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                .strokeBorder(Color.white.opacity(0.06), lineWidth: 0.5)
        )
    }

    private func placeholder(size: CGSize) -> some View {
        ZStack {
            LinearGradient(
                colors: [Color.white.opacity(0.10), Color.white.opacity(0.04)],
                startPoint: .topLeading, endPoint: .bottomTrailing
            )
            Image(systemName: symbol)
                .font(.system(size: max(12, min(size.width, size.height) * 0.3), weight: .light))
                .foregroundStyle(Tone.tertiary)
        }
    }
}

/// Couleurs d'une pochette, pour teinter le lecteur plein écran et les
/// fiches : quatre moyennes par quart d'image (les coins d'un dégradé
/// maillé) plutôt qu'une seule moyenne grisâtre. Assombries et saturées
/// juste ce qu'il faut pour que le texte blanc reste lisible dessus.
@MainActor
enum ArtworkPalette {
    private static var cache: [String: [Color]] = [:]
    private static let context = CIContext(options: [.workingColorSpace: NSNull()])

    static let fallback: [Color] = [
        Color(hex: 0x1C1C22), Color(hex: 0x121216), Color(hex: 0x0C0C10), Color(hex: 0x18181D),
    ]

    static func colors(for urlString: String?) async -> [Color] {
        guard let urlString, let url = URL(string: urlString) else { return fallback }
        if let cached = cache[urlString] { return cached }
        guard let (data, _) = try? await URLSession.shared.data(from: url),
              let image = UIImage(data: data), let ciImage = CIImage(image: image)
        else { return fallback }

        let extent = ciImage.extent
        let half = CGSize(width: extent.width / 2, height: extent.height / 2)
        // Core Image a l'origine en bas à gauche : l'ordre ci-dessous donne
        // haut-gauche, haut-droite, bas-gauche, bas-droite à l'écran.
        let regions = [
            CGRect(x: extent.minX, y: extent.minY + half.height, width: half.width, height: half.height),
            CGRect(x: extent.minX + half.width, y: extent.minY + half.height, width: half.width, height: half.height),
            CGRect(x: extent.minX, y: extent.minY, width: half.width, height: half.height),
            CGRect(x: extent.minX + half.width, y: extent.minY, width: half.width, height: half.height),
        ]
        let colors = regions.map { average(of: ciImage, in: $0) }
        cache[urlString] = colors
        return colors
    }

    private static func average(of image: CIImage, in rect: CGRect) -> Color {
        guard let filter = CIFilter(name: "CIAreaAverage", parameters: [
            kCIInputImageKey: image, kCIInputExtentKey: CIVector(cgRect: rect),
        ]), let output = filter.outputImage else { return fallback[0] }
        var pixel = [UInt8](repeating: 0, count: 4)
        context.render(
            output, toBitmap: &pixel, rowBytes: 4, bounds: CGRect(x: 0, y: 0, width: 1, height: 1),
            format: .RGBA8, colorSpace: nil
        )
        var hue: CGFloat = 0, saturation: CGFloat = 0, brightness: CGFloat = 0, alpha: CGFloat = 0
        _ = UIColor(
            red: CGFloat(pixel[0]) / 255, green: CGFloat(pixel[1]) / 255, blue: CGFloat(pixel[2]) / 255, alpha: 1
        ).getHue(&hue, saturation: &saturation, brightness: &brightness, alpha: &alpha)
        // Plafond de luminosité : une pochette blanche donnerait sinon un fond
        // blanc sous un texte blanc.
        return Color(hue: Double(hue), saturation: Double(min(1, saturation * 1.15)), brightness: Double(min(brightness, 0.62)))
    }
}

/// Dégradé maillé animé (iOS 18) aux couleurs de la pochette : les points
/// intérieurs dérivent lentement, le fond « respire » en continu comme celui
/// du lecteur de Musique.
struct LivingBackground: View {
    let colors: [Color]
    var animated = true

    var body: some View {
        TimelineView(.animation(minimumInterval: 1 / 30, paused: !animated)) { timeline in
            let t = Float(timeline.date.timeIntervalSinceReferenceDate)
            MeshGradient(
                width: 3, height: 3,
                points: [
                    SIMD2<Float>(0, 0), SIMD2<Float>(0.5, 0), SIMD2<Float>(1, 0),
                    SIMD2<Float>(0, 0.5 + 0.12 * sin(t * 0.35)),
                    SIMD2<Float>(0.5 + 0.18 * sin(t * 0.42), 0.5 + 0.16 * cos(t * 0.31)),
                    SIMD2<Float>(1, 0.5 + 0.12 * cos(t * 0.27)),
                    SIMD2<Float>(0, 1), SIMD2<Float>(0.5 + 0.15 * cos(t * 0.38), 1), SIMD2<Float>(1, 1),
                ],
                colors: meshColors
            )
        }
        .overlay(Color.black.opacity(0.28))
        .ignoresSafeArea()
    }

    /// 9 couleurs du maillage à partir des 4 coins, le centre et les bords
    /// reprenant les coins en diagonale pour mélanger les teintes.
    private var meshColors: [Color] {
        let c = colors.count >= 4 ? colors : ArtworkPalette.fallback
        return [
            c[0], c[1], c[1],
            c[2], c[3], c[0],
            c[2], c[3], c[3],
        ]
    }
}
