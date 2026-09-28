import Foundation
import Combine
import Security

/// Adresse du serveur Sona et jeton API, réglables depuis l'onglet Réglages
/// (voir `Features/Settings`) — usage strictement personnel, comme l'API
/// elle-même (voir README du dépôt, section « API ») : pas de compte, un
/// jeton fixe partagé entre l'app et le serveur.
final class APIConfig: ObservableObject {
    static let shared = APIConfig()

    @Published var baseURLString: String {
        didSet { UserDefaults.standard.set(baseURLString, forKey: Keys.baseURL) }
    }
    /// Ancien jeton unique (API_TOKEN du serveur), réservé à l'administrateur
    /// — facultatif depuis la connexion Last.fm.
    @Published var token: String {
        didSet { Keychain.set(token, forKey: Keys.token) }
    }
    /// Session ouverte avec « Se connecter avec Last.fm ».
    @Published var sessionToken: String {
        didSet { Keychain.set(sessionToken, forKey: Keys.session) }
    }

    var baseURL: URL? { URL(string: baseURLString) }
    var hasCredentials: Bool { !sessionToken.isEmpty || !token.isEmpty }
    var isConfigured: Bool { baseURL != nil && hasCredentials }
    /// Session Last.fm en priorité, sinon l'ancien jeton.
    var bearer: String { sessionToken.isEmpty ? token : sessionToken }

    private enum Keys {
        static let baseURL = "encre.api.baseURL"
        static let token = "encre.api.token"
        static let session = "encre.api.session"
    }

    private init() {
        // Le jeton ne doit jamais figurer en clair dans ce fichier (il finirait
        // dans l'historique Git et dans l'IPA distribué) : `BuildSecrets` est
        // réécrit par la CI à partir d'un secret GitHub Actions chiffré juste
        // avant de compiler (voir `.github/workflows/ios.yml`), jamais commité
        // avec une vraie valeur. `Keychain` prend le relais ensuite : il
        // survit en pratique à une désinstallation/réinstallation de l'app
        // (contrairement à `UserDefaults`, purgé à chaque reinstall via
        // Sideloadly/AltStore), pour garder un jeton changé depuis Réglages.
        baseURLString = UserDefaults.standard.string(forKey: Keys.baseURL)
            ?? (BuildSecrets.apiBaseURL.isEmpty ? "http://127.0.0.1:8000" : BuildSecrets.apiBaseURL)
        token = Keychain.get(Keys.token) ?? BuildSecrets.apiToken
        sessionToken = Keychain.get(Keys.session) ?? ""
    }
}

/// Enveloppe minimale autour de l'API Keychain de Sécurité — juste de quoi
/// stocker/lire une chaîne, en `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`
/// (accessible dès le premier déverrouillage après redémarrage, jamais
/// synchronisé sur iCloud : ce jeton n'a rien à faire sur un autre appareil).
private enum Keychain {
    static func set(_ value: String, forKey key: String) {
        let data = Data(value.utf8)
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: key,
        ]
        SecItemDelete(query as CFDictionary)
        guard !value.isEmpty else { return }
        var attributes = query
        attributes[kSecValueData as String] = data
        attributes[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemAdd(attributes as CFDictionary, nil)
    }

    static func get(_ key: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: key,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var result: AnyObject?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }
}
