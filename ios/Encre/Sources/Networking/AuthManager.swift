import AuthenticationServices
import Foundation
import SwiftUI

/// État de connexion de l'app : pas connecté, en attente de validation par
/// un admin, refusé, ou accepté (accès à l'app).
@MainActor
final class AuthManager: ObservableObject {
    static let shared = AuthManager()

    enum State: Equatable {
        case checking
        case signedOut
        /// Session enregistrée mais serveur injoignable : on ne déconnecte
        /// pas pour autant, on réessaie.
        case unreachable(String)
        case pending(AppAccount)
        case rejected(AppAccount)
        case approved(AppAccount)
    }

    @Published private(set) var state: State = .checking
    @Published var errorMessage: String?
    @Published private(set) var isWorking = false
    /// Serveur injoignable, mais l'utilisateur a choisi d'entrer quand même
    /// pour écouter ses téléchargements.
    @Published var offline = false

    var account: AppAccount? {
        switch state {
        case .pending(let a), .rejected(let a), .approved(let a): a
        default: nil
        }
    }

    private init() {}

    /// Relit l'état du compte auprès du serveur (au lancement, et pendant
    /// l'attente de validation).
    func refresh() async {
        guard APIConfig.shared.isConfigured else {
            state = .signedOut
            return
        }
        do {
            apply(try await APIClient.shared.me())
        } catch APIError.server(let status, _) where status == 401 {
            // Session expirée ou révoquée : on retombe sur l'ancien jeton s'il
            // y en a un, sinon retour à l'écran de connexion.
            if !APIConfig.shared.sessionToken.isEmpty {
                APIConfig.shared.sessionToken = ""
                if !APIConfig.shared.token.isEmpty {
                    await refresh()
                    return
                }
            } else {
                APIConfig.shared.token = ""
            }
            state = .signedOut
        } catch {
            // Serveur injoignable ou en panne : jamais une raison de renvoyer
            // à l'écran de connexion (la session reste valable). On garde
            // l'état connu, sinon on affiche l'écran « serveur injoignable ».
            switch state {
            case .checking, .unreachable, .signedOut:
                state = .unreachable(error.localizedDescription)
            default:
                break
            }
        }
    }

    /// « Se connecter avec Last.fm » : page Last.fm dans une feuille système,
    /// retour sur `encre://lastfm?token=…`, puis échange côté serveur.
    func signInWithLastfm(using session: WebAuthenticationSession) async {
        isWorking = true
        errorMessage = nil
        defer { isWorking = false }
        do {
            let config = try await APIClient.shared.authConfig()
            guard config.lastfmEnabled, let url = Self.loginURL(config) else {
                errorMessage = "La connexion Last.fm n'est pas configurée sur le serveur (LASTFM_API_KEY et LASTFM_API_SECRET)."
                return
            }
            let callback = try await session.authenticate(using: url, callbackURLScheme: "encre")
            guard let token = URLComponents(url: callback, resolvingAgainstBaseURL: false)?
                .queryItems?.first(where: { $0.name == "token" })?.value else {
                errorMessage = "Last.fm n'a pas renvoyé d'autorisation."
                return
            }
            let login = try await APIClient.shared.loginWithLastfm(token: token)
            APIConfig.shared.sessionToken = login.sessionToken
            apply(login.account)
        } catch let error as ASWebAuthenticationSessionError where error.code == .canceledLogin {
            // Fenêtre Last.fm fermée : rien à signaler.
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    /// Page d'autorisation Last.fm, avec pour retour
    /// `<serveur>/auth/lastfm/callback` — Last.fm refuse `encre://` ; c'est
    /// le serveur qui renvoie ensuite vers l'app.
    private static func loginURL(_ config: AuthConfig) -> URL? {
        guard let apiKey = config.apiKey, let base = APIConfig.shared.baseURL else {
            return config.authURL.flatMap(URL.init(string:))
        }
        var components = URLComponents(string: "https://www.last.fm/api/auth/")
        components?.queryItems = [
            URLQueryItem(name: "api_key", value: apiKey),
            URLQueryItem(name: "cb", value: base.appendingPathComponent("auth/lastfm/callback").absoluteString),
        ]
        return components?.url
    }

    func signOut() async {
        if !APIConfig.shared.sessionToken.isEmpty {
            try? await APIClient.shared.logout()
        }
        APIConfig.shared.sessionToken = ""
        APIConfig.shared.token = ""
        state = .signedOut
    }

    func update(_ account: AppAccount) {
        apply(account)
    }

    private func apply(_ account: AppAccount) {
        offline = false
        switch account.status {
        case "approved": state = .approved(account)
        case "rejected": state = .rejected(account)
        default: state = .pending(account)
        }
    }
}
