import Foundation

/// Destinations poussées dans la pile de navigation d'un onglet (voir
/// `RootTabView`) : une fiche album ou artiste, identifiée comme partout
/// ailleurs dans l'API par sa source et son identifiant chez cette source.
enum Route: Hashable {
    case album(source: String, id: String)
    /// Chez Deezer, playlists et albums ont des numéros indépendants :
    /// ouvrir une playlist via `/albums/...` affichait un tout autre contenu.
    case playlist(source: String, id: String)
    case artist(source: String, id: String)
    /// Playlist de l'utilisateur (créée dans l'app ou importée).
    case userPlaylist(id: Int)
    /// Titres gardés sur l'iPhone.
    case downloads
    /// Mix « Faits pour toi » de l'accueil.
    case mix(id: String)
    /// Profil d'un ami.
    case friend(accountId: Int)
    /// Playlist intelligente (en boucle, oubliés, découvertes…).
    case smart(id: String, title: String)
    /// Titres inédits ajoutés à la main.
    case exclusives
    /// Sortie (album, EP, single) d'un artiste à identités.
    case release(source: String, id: String, persona: String, album: String)
}
