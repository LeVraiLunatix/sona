import Foundation

/// Valeur de sélection des onglets de `RootTabView` — la barre elle-même est
/// maintenant la vraie `TabView` système (Liquid Glass natif depuis iOS 26),
/// plus une pastille "verre liquide" maison à reproduire.
enum AppTab: Int, CaseIterable {
    case home, library, search
}
