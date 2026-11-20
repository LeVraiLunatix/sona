import Combine
import CoreText
import SwiftUI
import UIKit

// MARK: - Détection

/// Thème « GTA VI » (Vice City, Leonida) : mêmes règles que `isGtaArtist`, `isGtaAlbum` et
/// `isGtaTrack` du site (`web/app.js`). Seuls comptent la fiche officielle de Grand Theft Auto VI
/// et les sorties qui portent le marqueur « GTAVI: » ou « Grand Theft Auto VI: » ; les morceaux
/// « GTA VI » d'autres artistes n'allument rien.
enum GtaVI {
    /// Fiches artiste officielles : Deezer et YouTube Music.
    static let artistIds: Set<String> = ["deezer:237278551", "youtube:UCJ97ksybdciBBv7xsFSK6HA"]

    /// « (from GTAVI: The Album) », « [From GTAVI: Original Score] », « Grand Theft Auto VI: The Album » —
    /// mais pas « GTA VI » de n'importe quel rappeur : il faut les deux-points du titre officiel.
    private static let marker = try! NSRegularExpression(pattern: "(?:\\bgtavi|grand theft auto vi)\\s*:", options: [.caseInsensitive])

    /// Minuscules, sans accents ni ponctuation, mots séparés d'une espace.
    private static func words(_ text: String?) -> String {
        guard let text else { return "" }
        return text.folding(options: [.diacriticInsensitive, .caseInsensitive], locale: nil)
            .split { !$0.isLetter && !$0.isNumber }
            .joined(separator: " ")
            .lowercased()
    }

    private static func isName(_ name: String?) -> Bool { words(name) == "grand theft auto vi" }

    private static func hasMarker(_ text: String?) -> Bool {
        guard let text, !text.isEmpty else { return false }
        return marker.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)) != nil
    }

    /// Identifiant d'une fiche artiste (source + identifiant) : connu avant même de la charger.
    static func isArtistId(source: String, id: String) -> Bool { artistIds.contains("\(source):\(id)") }

    static func isArtist(_ artist: Artist) -> Bool {
        isArtistId(source: artist.source, id: artist.sourceId) || isName(artist.name)
    }

    static func isAlbum(_ album: Album) -> Bool {
        isName(album.artist) || hasMarker(album.title)
            || isArtistId(source: album.source, id: album.artistSourceId ?? "")
    }

    static func isTrack(_ track: Track?) -> Bool {
        guard let track else { return false }
        return isName(track.artist)
            || isArtistId(source: track.artistRouteSource, id: track.artistSourceId ?? "")
            || hasMarker(track.album) || hasMarker(track.title)
            || (track.artists ?? []).contains { isName($0.name) }
    }
}

// MARK: - État du thème

/// Allume ou éteint le thème partout dans l'app : une page GTA VI est à l'écran (fiche artiste,
/// album), ou le titre en cours en fait partie (sur cet iPhone ou sur l'appareil qu'il pilote) —
/// et le réglage Apparence › Thème GTA VI est activé.
@MainActor
final class GtaTheme: ObservableObject {
    static let shared = GtaTheme()

    /// Thème actif en ce moment.
    @Published private(set) var on = false
    /// Pages GTA VI actuellement affichées (une clé par page : une fiche masquée par une autre se retire).
    private var pages: Set<String> = []
    private var cancellables = Set<AnyCancellable>()

    private init() {
        GtaFont.register()
        // Le titre change (ici ou sur l'appareil piloté) : on revérifie. `$current` publie avant
        // l'écriture de la valeur ; `receive(on:)` repousse la lecture au tour suivant.
        PlayerManager.shared.$current
            .map { _ in () }
            .merge(with: ConnectManager.shared.objectWillChange.map { _ in () }.throttle(for: .milliseconds(400), scheduler: RunLoop.main, latest: true),
                   RemoteFlag.shared.objectWillChange.map { _ in () })
            .receive(on: DispatchQueue.main)
            .sink { [weak self] _ in self?.refresh() }
            .store(in: &cancellables)
    }

    /// Le titre qu'on entend : celui de l'iPhone, ou celui de l'appareil piloté à distance.
    private var currentTrack: Track? {
        RemoteFlag.shared.isRemote ? ConnectManager.shared.remoteTarget?.track : PlayerManager.shared.current
    }

    /// Une page de la clé `key` est (ou n'est plus) une page GTA VI affichée.
    func setPage(_ key: String, active: Bool) {
        if active { pages.insert(key) } else { pages.remove(key) }
        refresh()
    }

    /// À rappeler quand le réglage change.
    func refresh() {
        let enabled = UserDefaults.standard.object(forKey: Look.gtaKey) as? Bool ?? true
        let want = enabled && (!pages.isEmpty || GtaVI.isTrack(currentTrack))
        guard want != on else { return }
        withAnimation(.easeInOut(duration: 0.5)) { on = want }
    }
}

// MARK: - Couleurs et police

enum GtaColor {
    static let night = Color(hex: 0x0D0220)
    static let pink = Color(hex: 0xFF4FA3)
    static let hotPink = Color(hex: 0xFF2E97)
    static let cyan = Color(hex: 0x25E8FF)
    static let blue = Color(hex: 0x6F7BFF)
    static let violet = Color(hex: 0xA45BFF)
    static let onAccent = Color(hex: 0x1A0230)

    /// Dégradé des titres : blanc bleuté, bleu-violet, violet, rose.
    static let title = LinearGradient(
        stops: [
            .init(color: Color(hex: 0xF2F7FF), location: 0),
            .init(color: Color(hex: 0x9CC0FF), location: 0.34),
            .init(color: violet, location: 0.66),
            .init(color: pink, location: 1),
        ],
        startPoint: .top, endPoint: .bottom
    )
}

/// Pricedown Black, la police des titres de GTA (fichier `Resources/Fonts/Pricedown.otf`, voir
/// docs/GUIDE.md pour la licence). Sans le fichier, retombe sur le système en très gras italique.
enum GtaFont {
    static let name = "Pricedown-Black"

    /// Enregistre la police pour toute l'app (sans passer par Info.plist).
    static func register() {
        _ = registered
    }

    private static let registered: Void = {
        if let url = Bundle.main.url(forResource: "Pricedown", withExtension: "otf") {
            CTFontManagerRegisterFontsForURL(url as CFURL, .process, nil)
        }
    }()

    static func title(_ size: CGFloat) -> Font {
        register()
        if UIFont(name: name, size: size) != nil { return .custom(name, fixedSize: size) }
        return .system(size: size, weight: .black).italic()
    }
}

// MARK: - Modificateurs

/// Titre en lettres de façade de Vice City : Pricedown en majuscules, dégradé et halo néon.
/// Thème éteint : le texte reste tel que l'écran l'a dessiné.
private struct GtaTitleStyle: ViewModifier {
    @ObservedObject private var gta = GtaTheme.shared
    let size: CGFloat

    @ViewBuilder
    func body(content: Content) -> some View {
        if gta.on {
            content
                .font(GtaFont.title(size))
                .textCase(.uppercase)
                .foregroundStyle(GtaColor.title)
                .shadow(color: GtaColor.hotPink.opacity(0.55), radius: 9)
        } else {
            content
        }
    }
}

/// Fond de page : noir, ou le coucher de soleil de Vice City quand le thème est actif.
private struct PageBackground: ViewModifier {
    @ObservedObject private var gta = GtaTheme.shared

    func body(content: Content) -> some View {
        content.background {
            ZStack {
                Tone.background.ignoresSafeArea()
                if gta.on { GtaBackdrop().transition(.opacity) }
            }
        }
    }
}

/// Déclare qu'une page affichée est (ou n'est plus) une page GTA VI.
private struct GtaPageModifier: ViewModifier {
    let key: String
    let active: Bool

    func body(content: Content) -> some View {
        content
            .onAppear { GtaTheme.shared.setPage(key, active: active) }
            .onChange(of: active) { _, value in GtaTheme.shared.setPage(key, active: value) }
            .onDisappear { GtaTheme.shared.setPage(key, active: false) }
    }
}

extension View {
    func gtaTitle(size: CGFloat) -> some View { modifier(GtaTitleStyle(size: size)) }
    func pageBackground() -> some View { modifier(PageBackground()) }
    func gtaPage(_ key: String, active: Bool) -> some View { modifier(GtaPageModifier(key: key, active: active)) }
}

// MARK: - Décor

/// Le décor : ciel violet qui vire au rose, soleil rayé, grille qui fuit vers l'horizon, deux palmiers
/// en ombre chinoise. `veil` assombrit le tout pour garder le texte lisible.
struct GtaBackdrop: View {
    var veil: Double = 0.55

    var body: some View {
        GeometryReader { geo in
            let size = geo.size
            ZStack {
                LinearGradient(
                    stops: [
                        .init(color: Color(hex: 0x080224), location: 0),
                        .init(color: Color(hex: 0x170A58), location: 0.30),
                        .init(color: Color(hex: 0x3A1790), location: 0.48),
                        .init(color: Color(hex: 0x7A24B8), location: 0.60),
                        .init(color: Color(hex: 0xC52FB0), location: 0.72),
                        .init(color: Color(hex: 0xFF5FA8), location: 0.84),
                        .init(color: Color(hex: 0xFF9CCF), location: 1),
                    ],
                    startPoint: .top, endPoint: .bottom
                )
                sun(in: size)
                floor(in: size)
                palms(in: size)
                GtaColor.night.opacity(veil)
            }
            .frame(width: size.width, height: size.height)
        }
        .ignoresSafeArea()
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }

    /// Soleil rayé : dégradé rose → bleu-violet, coupé de bandes de plus en plus épaisses vers le bas.
    private func sun(in size: CGSize) -> some View {
        let d = min(min(size.width, size.height) * 0.54, 480)
        let k = d / 200
        let centerY = (size.height - d) * 0.62 + d / 2
        let bands: [(top: CGFloat, height: CGFloat)] = [(112, 4), (132, 7), (154, 10), (177, 14)]
        return Circle()
            .fill(LinearGradient(colors: [Color(hex: 0xFFA6DC), GtaColor.pink, Color(hex: 0x6F5CFF)], startPoint: .top, endPoint: .bottom))
            .frame(width: d, height: d)
            .mask {
                ZStack(alignment: .top) {
                    Rectangle().fill(.white)
                    ForEach(Array(bands.enumerated()), id: \.offset) { _, band in
                        Rectangle().fill(.black)
                            .frame(height: band.height * k)
                            .offset(y: band.top * k)
                            .blendMode(.destinationOut)
                    }
                }
                .compositingGroup()
            }
            .position(x: size.width / 2, y: centerY)
    }

    /// Grille en perspective : fuyantes cyan, traverses roses, fondue à l'horizon.
    private func floor(in size: CGSize) -> some View {
        let horizon = size.height * 0.66
        return ZStack {
            LinearGradient(colors: [GtaColor.night.opacity(0.94), Color(hex: 0x46085A).opacity(0.72)], startPoint: .top, endPoint: .bottom)
            Canvas { context, canvas in
                let depth = canvas.height - horizon
                let vanishing = CGPoint(x: canvas.width / 2, y: horizon)
                var vertical = Path()
                let step = max(canvas.width / 5, 60)
                for index in -10...10 {
                    vertical.move(to: vanishing)
                    vertical.addLine(to: CGPoint(x: vanishing.x + CGFloat(index) * step, y: canvas.height))
                }
                context.stroke(vertical, with: .color(GtaColor.cyan.opacity(0.55)), lineWidth: 1)
                var rows = Path()
                let count = 14
                for line in 1...count {
                    let y = horizon + depth * pow(CGFloat(line) / CGFloat(count), 2.2)
                    rows.move(to: CGPoint(x: 0, y: y))
                    rows.addLine(to: CGPoint(x: canvas.width, y: y))
                }
                context.stroke(rows, with: .color(GtaColor.hotPink.opacity(0.6)), lineWidth: 1)
            }
        }
        .frame(width: size.width, height: size.height - horizon)
        .mask(LinearGradient(stops: [.init(color: .clear, location: 0), .init(color: .black, location: 0.22), .init(color: .black, location: 1)], startPoint: .top, endPoint: .bottom))
        .opacity(0.72)
        .position(x: size.width / 2, y: horizon + (size.height - horizon) / 2)
    }

    /// Deux palmiers noirs, un petit à gauche et un grand à droite, qui dépassent du bas de l'écran.
    private func palms(in size: CGSize) -> some View {
        Canvas { context, canvas in
            let vmin = min(canvas.width, canvas.height)
            let color = GraphicsContext.Shading.color(Color(hex: 0x0A0118))
            let leftHeight = min(canvas.height * 0.5, 560)
            Palm.draw(in: &context, shading: color, origin: CGPoint(x: -0.02 * vmin, y: canvas.height * 1.04 - leftHeight), height: leftHeight)
            let rightHeight = min(canvas.height * 0.62, 700)
            Palm.draw(in: &context, shading: color, origin: CGPoint(x: canvas.width - rightHeight / 2 + 0.04 * vmin, y: canvas.height * 1.1 - rightHeight), height: rightHeight)
        }
    }
}

/// Un palmier en ombre chinoise : tronc courbe et sept palmes, dessinés dans une boîte de 200 × 400.
private enum Palm {
    /// Chaque palme : départ (118, 140), deux courbes de Bézier (contrôle 1, contrôle 2, arrivée) × 2.
    private static let fronds: [[CGFloat]] = [
        [90, 110, 50, 105, 12, 130, 52, 118, 90, 125, 118, 140],
        [95, 100, 70, 75, 30, 70, 70, 78, 98, 100, 118, 140],
        [130, 95, 150, 70, 185, 62, 156, 80, 138, 100, 118, 140],
        [150, 118, 185, 118, 198, 140, 176, 130, 146, 132, 118, 140],
        [112, 100, 112, 70, 100, 40, 122, 70, 124, 100, 118, 140],
        [100, 150, 70, 165, 40, 195, 78, 172, 100, 160, 118, 140],
        [140, 152, 166, 168, 178, 198, 156, 176, 134, 160, 118, 140],
    ]

    static func draw(in context: inout GraphicsContext, shading: GraphicsContext.Shading, origin: CGPoint, height: CGFloat) {
        let s = height / 400
        func point(_ x: CGFloat, _ y: CGFloat) -> CGPoint { CGPoint(x: origin.x + x * s, y: origin.y + y * s) }
        var trunk = Path()
        trunk.move(to: point(96, 400))
        trunk.addCurve(to: point(118, 140), control1: point(100, 300), control2: point(104, 220))
        context.stroke(trunk, with: shading, style: StrokeStyle(lineWidth: 9 * s, lineCap: .round))
        for v in fronds {
            var frond = Path()
            frond.move(to: point(118, 140))
            frond.addCurve(to: point(v[4], v[5]), control1: point(v[0], v[1]), control2: point(v[2], v[3]))
            frond.addCurve(to: point(v[10], v[11]), control1: point(v[6], v[7]), control2: point(v[8], v[9]))
            frond.closeSubpath()
            context.fill(frond, with: shading)
        }
    }
}
