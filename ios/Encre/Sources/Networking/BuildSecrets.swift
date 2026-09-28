import Foundation

/// Valeurs par défaut injectées à la compilation par la CI (voir
/// `.github/workflows/ios.yml`, étape « Injecter la config serveur ») à
/// partir de secrets GitHub Actions chiffrés — jamais commités en clair.
///
/// Ce fichier reste suivi par Git avec des valeurs vides : un clonage local
/// compile tel quel (`APIConfig` retombe alors sur la saisie manuelle depuis
/// Réglages, comme avant), tandis que la CI réécrit ce même fichier dans son
/// propre checkout juste avant de compiler l'.ipa, pour que l'app installée
/// via Sideloadly/AltStore soit déjà connectée au serveur sans rien saisir.
enum BuildSecrets {
    static let apiBaseURL = ""
    static let apiToken = ""
}
