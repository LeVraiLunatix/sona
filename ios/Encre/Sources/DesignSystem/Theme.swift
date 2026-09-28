import SwiftUI

/// Direction artistique : noir profond, blanc, et des gris obtenus par
/// transparence du blanc — rien d'autre. La seule couleur de l'app vient des
/// pochettes elles-mêmes (fond du lecteur, halo des fiches album), comme
/// dans Musique.
enum Tone {
    static let background = Color.black
    /// Cartes, champs, boutons secondaires : à peine détachés du fond.
    static let surface = Color.white.opacity(0.07)
    static let surfaceStrong = Color.white.opacity(0.12)
    static let separator = Color.white.opacity(0.08)

    static let primary = Color.white
    static let secondary = Color.white.opacity(0.6)
    static let tertiary = Color.white.opacity(0.35)

    /// Réservé aux erreurs : un rouge doux, jamais une couleur d'interface.
    static let danger = Color(red: 1, green: 0.42, blue: 0.42)
}

/// Police système (SF Pro), graisses franches et interlettrage resserré
/// sur les grands titres — la typographie de Musique/Podcasts.
enum Typo {
    static let hero = Font.system(size: 40, weight: .bold)
    static let largeTitle = Font.system(size: 32, weight: .bold)
    static let title = Font.system(size: 22, weight: .bold)
    static let headline = Font.system(size: 17, weight: .semibold)
    static let body = Font.system(size: 16, weight: .regular)
    static let rowTitle = Font.system(size: 16, weight: .medium)
    static let rowSubtitle = Font.system(size: 14, weight: .regular)
    static let caption = Font.system(size: 12, weight: .semibold)
    static let mono = Font.system(size: 12, weight: .medium).monospacedDigit()
}

enum Motion {
    /// Ressort par défaut de l'app : vif, sans rebond appuyé.
    static let snappy = Animation.spring(response: 0.35, dampingFraction: 0.85)
    static let smooth = Animation.spring(response: 0.55, dampingFraction: 0.9)
    static let bouncy = Animation.spring(response: 0.45, dampingFraction: 0.68)
}

extension Color {
    init(hex: UInt32) {
        let r = Double((hex >> 16) & 0xFF) / 255
        let g = Double((hex >> 8) & 0xFF) / 255
        let b = Double(hex & 0xFF) / 255
        self.init(red: r, green: g, blue: b)
    }
}

// MARK: - Boutons

/// Enfoncement au toucher (léger rétrécissement + atténuation) pour tout ce
/// qui se tape : la réponse tactile qui donne à l'app sa sensation « native ».
struct PressableStyle: ButtonStyle {
    var scale: CGFloat = 0.96

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .contentShape(Rectangle())
            .scaleEffect(configuration.isPressed ? scale : 1)
            .opacity(configuration.isPressed ? 0.75 : 1)
            .animation(Motion.snappy, value: configuration.isPressed)
    }
}

extension ButtonStyle where Self == PressableStyle {
    static var pressable: PressableStyle { PressableStyle() }
    static func pressable(scale: CGFloat) -> PressableStyle { PressableStyle(scale: scale) }
}

/// Bouton plein (blanc sur noir) ou discret (verre fumé), pleine largeur —
/// les « Lecture » / « Aléatoire » des fiches.
struct PillButton: View {
    enum Kind { case primary, secondary }

    let title: String
    let systemImage: String
    var kind: Kind = .primary
    var isLoading = false
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 8) {
                if isLoading {
                    ProgressView().tint(kind == .primary ? .black : .white)
                } else {
                    Image(systemName: systemImage)
                }
                Text(title)
            }
            .font(Typo.headline)
            .foregroundStyle(kind == .primary ? Color.black : Tone.primary)
            .frame(maxWidth: .infinity)
            .frame(height: 50)
            .background(
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .fill(kind == .primary ? Color.white : Tone.surfaceStrong)
            )
        }
        .buttonStyle(.pressable)
        .disabled(isLoading)
    }
}

// MARK: - Apparition en cascade

/// Fondu + léger glissement vers le haut à la première apparition, décalé
/// par `index` : les sections d'un écran se posent l'une après l'autre au
/// lieu d'apparaître d'un bloc.
private struct RevealModifier: ViewModifier {
    let index: Int
    @State private var shown = false

    func body(content: Content) -> some View {
        content
            .opacity(shown ? 1 : 0)
            .offset(y: shown ? 0 : 18)
            .blur(radius: shown ? 0 : 6)
            .onAppear {
                guard !shown else { return }
                withAnimation(Motion.smooth.delay(Double(min(index, 8)) * 0.06)) { shown = true }
            }
    }
}

extension View {
    func reveal(_ index: Int = 0) -> some View {
        modifier(RevealModifier(index: index))
    }

    /// Les vignettes d'une rangée horizontale rétrécissent et s'estompent en
    /// sortant de l'écran : la rangée respire au défilement.
    func carouselItem() -> some View {
        scrollTransition(.interactive, axis: .horizontal) { content, phase in
            content
                .scaleEffect(phase.isIdentity ? 1 : 0.9)
                .opacity(phase.isIdentity ? 1 : 0.55)
        }
    }
}

// MARK: - Transition « zoom » vers les fiches

/// Espace de noms partagé par la vignette tapée et la fiche ouverte :
/// `.navigationTransition(.zoom)` fait alors grandir la pochette jusqu'à
/// devenir la page (et la rétrécit au retour, geste interactif compris),
/// exactement comme Photos ou Musique.
private struct ZoomNamespaceKey: EnvironmentKey {
    static let defaultValue: Namespace.ID? = nil
}

extension EnvironmentValues {
    var zoomNamespace: Namespace.ID? {
        get { self[ZoomNamespaceKey.self] }
        set { self[ZoomNamespaceKey.self] = newValue }
    }
}

private struct ZoomSourceModifier: ViewModifier {
    let route: Route
    @Environment(\.zoomNamespace) private var namespace

    @ViewBuilder
    func body(content: Content) -> some View {
        if let namespace {
            content.matchedTransitionSource(id: route, in: namespace)
        } else {
            content
        }
    }
}

private struct ZoomDestinationModifier: ViewModifier {
    let route: Route
    @Environment(\.zoomNamespace) private var namespace

    @ViewBuilder
    func body(content: Content) -> some View {
        if let namespace {
            content.navigationTransition(.zoom(sourceID: route, in: namespace))
        } else {
            content
        }
    }
}

extension View {
    func zoomSource(_ route: Route) -> some View { modifier(ZoomSourceModifier(route: route)) }
    func zoomDestination(_ route: Route) -> some View { modifier(ZoomDestinationModifier(route: route)) }
}
