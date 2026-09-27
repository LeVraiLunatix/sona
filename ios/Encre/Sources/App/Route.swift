import Foundation

/// Destinations poussées dans la pile de navigation d'un onglet (voir
/// `RootTabView`) : une fiche album ou artiste, identifiée comme partout
/// ailleurs dans l'API par sa source et son identifiant chez cette source.
enum Route: Hashable {
    case album(source: String, id: String)
    case artist(source: String, id: String)
}
