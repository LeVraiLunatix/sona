import Foundation
import Combine

/// Adresse du serveur Sona et jeton API, réglables depuis l'onglet Réglages
/// (voir `Features/Settings`) — usage strictement personnel, comme l'API
/// elle-même (voir README du dépôt, section « API ») : pas de compte, un
/// jeton fixe partagé entre l'app et le serveur.
final class APIConfig: ObservableObject {
    static let shared = APIConfig()

    @Published var baseURLString: String {
        didSet { UserDefaults.standard.set(baseURLString, forKey: Keys.baseURL) }
    }
    @Published var token: String {
        didSet { UserDefaults.standard.set(token, forKey: Keys.token) }
    }

    var baseURL: URL? { URL(string: baseURLString) }
    var isConfigured: Bool { baseURL != nil && !token.isEmpty }

    private enum Keys {
        static let baseURL = "encre.api.baseURL"
        static let token = "encre.api.token"
    }

    private init() {
        // 127.0.0.1 par défaut : ne marche que dans le simulateur, sur le
        // même Mac que `run_api.py`. Sur un iPhone physique, renseigner
        // l'adresse locale du serveur (ex: http://192.168.1.x:8000).
        baseURLString = UserDefaults.standard.string(forKey: Keys.baseURL) ?? "http://127.0.0.1:8000"
        token = UserDefaults.standard.string(forKey: Keys.token) ?? ""
    }
}
