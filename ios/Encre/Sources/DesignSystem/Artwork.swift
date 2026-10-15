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

    private static var meshCache: [String: [Color]] = [:]

    /// 16 couleurs (grille 4 × 4, ligne par ligne depuis le haut à gauche)
    /// pour le fond vivant du lecteur : la composition de la pochette est
    /// gardée (le ciel en haut, le sujet au centre…) plutôt que quatre
    /// moyennes. Chaque case est un peu rapprochée de la couleur la plus
    /// vive de l'image, pour un fond lumineux plutôt que boueux.
    static func meshColors(for urlString: String?) async -> [Color] {
        guard let urlString, let url = URL(string: urlString) else { return fallback }
        if let cached = meshCache[urlString] { return cached }
        guard let (data, _) = try? await URLSession.shared.data(from: url),
              let image = UIImage(data: data), let ciImage = CIImage(image: image)
        else { return fallback }

        let extent = ciImage.extent
        let cell = CGSize(width: extent.width / 4, height: extent.height / 4)
        var cells: [(hue: Double, saturation: Double, brightness: Double)] = []
        for row in 0..<4 {
            for column in 0..<4 {
                // Core Image a l'origine en bas à gauche : la ligne 0 est en haut.
                let rect = CGRect(
                    x: extent.minX + CGFloat(column) * cell.width,
                    y: extent.minY + CGFloat(3 - row) * cell.height,
                    width: cell.width, height: cell.height
                )
                cells.append(hsb(of: ciImage, in: rect))
            }
        }
        let vivid = cells.max { $0.saturation * $0.brightness < $1.saturation * $1.brightness }
        let colors = cells.map { cell -> Color in
            var saturation = min(1, cell.saturation * 1.2)
            var hue = cell.hue
            if let vivid, cell.saturation < 0.25, vivid.saturation > 0.35 {
                // Case grise : teintée par la couleur vive de la pochette.
                hue = vivid.hue
                saturation = max(saturation, vivid.saturation * 0.45)
            }
            return Color(hue: hue, saturation: saturation, brightness: min(max(cell.brightness, 0.14), 0.62))
        }
        meshCache[urlString] = colors
        return colors
    }

    private static func hsb(of image: CIImage, in rect: CGRect) -> (hue: Double, saturation: Double, brightness: Double) {
        guard let filter = CIFilter(name: "CIAreaAverage", parameters: [
            kCIInputImageKey: image, kCIInputExtentKey: CIVector(cgRect: rect),
        ]), let output = filter.outputImage else { return (0, 0, 0.1) }
        var pixel = [UInt8](repeating: 0, count: 4)
        context.render(
            output, toBitmap: &pixel, rowBytes: 4, bounds: CGRect(x: 0, y: 0, width: 1, height: 1),
            format: .RGBA8, colorSpace: nil
        )
        var hue: CGFloat = 0, saturation: CGFloat = 0, brightness: CGFloat = 0, alpha: CGFloat = 0
        _ = UIColor(
            red: CGFloat(pixel[0]) / 255, green: CGFloat(pixel[1]) / 255, blue: CGFloat(pixel[2]) / 255, alpha: 1
        ).getHue(&hue, saturation: &saturation, brightness: &brightness, alpha: &alpha)
        return (Double(hue), Double(saturation), Double(brightness))
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

/// Fond vivant aux couleurs de la pochette (dégradé maillé 4 × 4) : les
/// points intérieurs dérivent lentement, ceux des bords glissent le long
/// des bords, comme le lecteur de Musique.
///
/// Avec `reactive`, il bat avec la musique : les basses mesurées par le fil
/// audio quand il les mesure (visualiseur, égaliseur, « Fond qui bat au
/// son »), sinon une respiration douce sur le tempo du titre.
///
/// Sobre : immobile avec « Réduire les animations », arrêté hors écran et
/// quand l'app passe en arrière-plan, 60 images/s au plus (20 en mode
/// économie d'énergie, sans réaction au son).
struct LivingBackground: View {
    /// 16 couleurs (grille 4 × 4, voir `ArtworkPalette.meshColors`) ou 4
    /// (les coins, mélangés en diagonale).
    let colors: [Color]
    var animated = true
    var reactive = false
    /// Tempo du titre (BPM), pour respirer sur le temps sans mesurer le son.
    var tempo: Double? = nil

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.scenePhase) private var scenePhase
    @State private var pulse = PulseFollower()

    var body: some View {
        let running = animated && !reduceMotion && scenePhase == .active
        let lowPower = ProcessInfo.processInfo.isLowPowerModeEnabled
        let beats = reactive && !lowPower
        TimelineView(.animation(minimumInterval: lowPower ? 1 / 20 : (beats ? 1 / 60 : 1 / 30), paused: !running)) { timeline in
            // Immobile (« Réduire les animations ») : toujours la même image.
            let t = reduceMotion ? 0 : timeline.date.timeIntervalSinceReferenceDate
            let energy = running && beats ? pulse.energy(at: t, tempo: tempo) : 0
            ZStack {
                MeshGradient(width: 4, height: 4, points: Self.points(t: Float(t), energy: Float(energy)), colors: meshColors)
                    .scaleEffect(1 + 0.03 * energy)
                // Voile sombre pour la lisibilité du texte blanc, un peu
                // levé sur les temps forts : le fond « s'allume » au son.
                Color.black.opacity(0.3 - 0.1 * energy)
            }
        }
        .ignoresSafeArea()
    }

    /// Grille 4 × 4 : coins fixes, bords qui glissent le long des bords,
    /// intérieur qui dérive en 2D — chaque point à sa propre vitesse. Assez
    /// peu (moins d'un demi-espacement) pour que deux points ne se croisent
    /// jamais, un peu plus quand la musique tape.
    static func points(t: Float, energy: Float) -> [SIMD2<Float>] {
        let amplitude: Float = 0.085 + 0.06 * energy
        var result: [SIMD2<Float>] = []
        result.reserveCapacity(16)
        for row in 0..<4 {
            for column in 0..<4 {
                let seed = Float(row * 4 + column)
                var x = Float(column) / 3
                var y = Float(row) / 3
                if column != 0 && column != 3 { x += amplitude * sin(t * (0.21 + 0.031 * seed) + seed * 1.7) }
                if row != 0 && row != 3 { y += amplitude * cos(t * (0.17 + 0.027 * seed) + seed * 2.3) }
                result.append(SIMD2<Float>(x, y))
            }
        }
        return result
    }

    private var meshColors: [Color] {
        if colors.count >= 16 { return Array(colors.prefix(16)) }
        let c = colors.count >= 4 ? colors : ArtworkPalette.fallback
        // 4 coins → 16 : chaque ligne reprend les coins en diagonale pour
        // mélanger les teintes plutôt que des bandes nettes.
        return [
            c[0], c[0], c[1], c[1],
            c[2], c[3], c[0], c[1],
            c[2], c[1], c[3], c[0],
            c[2], c[2], c[3], c[3],
        ]
    }
}

/// Énergie lissée (0…1) qui fait battre `LivingBackground`.
final class PulseFollower {
    private var smoothed: Double = 0
    private var lastTime: Double = 0
    private var lastHeard: Double = -10

    func energy(at time: Double, tempo: Double?) -> Double {
        let elapsed = min(0.1, max(0, time - lastTime))
        lastTime = time
        let bass = Double(max(AudioEffects.level(0), AudioEffects.level(1)))
        let body = Double(AudioEffects.level(3))
        if bass + body > 0.002 { lastHeard = time }
        let target: Double
        if time - lastHeard < 1 {
            // Le fil audio mesure le son : les basses mènent la danse.
            target = min(1, bass * 1.35 + body * 0.35)
        } else if let tempo, tempo > 40 {
            // Pas de mesure : une respiration sur le temps, assez douce pour
            // ne pas sembler à contretemps (on ne connaît pas le premier temps).
            let beat = (time * tempo / 60).truncatingRemainder(dividingBy: 1)
            target = 0.22 * (0.5 + 0.5 * cos(2 * .pi * beat))
        } else {
            target = 0
        }
        // Attaque rapide, retombée lente : un battement, pas un clignotement.
        let rate = target > smoothed ? 16.0 : 3.5
        smoothed += (target - smoothed) * min(1, rate * elapsed)
        return smoothed
    }
}
