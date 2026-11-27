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
        /// Compte banni ou suspendu par la modération.
        case sanctioned(APIError.Sanction)
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
            await loadSupabaseConfig()
            return
        }
        // Démarrage instantané : compte déjà accepté la dernière fois → on
        // entre tout de suite, la vérification se fait en arrière-plan (un
        // accès révoqué entre-temps est pris en compte dès sa réponse).
        if state == .checking, let cached = Self.cachedAccount, cached.status == "approved" {
            state = .approved(cached)
        }
        await loadSupabaseConfig()
        if setAsideLegacySession() { return }
        await adoptOldAccount()
        do {
            apply(try await APIClient.shared.me())
        } catch APIError.sanctioned(let sanction) {
            // Le serveur relit le statut à CHAQUE requête : un bannissement ou une suspension s'applique tout de suite.
            state = .sanctioned(sanction)
        } catch APIError.server(let status, _) where status == 401 {
            // Session expirée ou révoquée : on retombe sur l'ancien jeton s'il
            // y en a un, sinon retour à l'écran de connexion.
            if SupabaseAuth.shared.hasSession {
                // Session de compte Sona révoquée ou expirée pour de bon : retour à la connexion (ou à l'ancien jeton).
                await SupabaseAuth.shared.signOut()
                if !APIConfig.shared.token.isEmpty {
                    await refresh()
                    return
                }
            } else if !APIConfig.shared.sessionToken.isEmpty {
                APIConfig.shared.sessionToken = ""
                if !APIConfig.shared.token.isEmpty {
                    await refresh()
                    return
                }
            } else {
                APIConfig.shared.token = ""
            }
            Self.cachedAccount = nil
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

    /// Adresse du projet Supabase et clé publique, fournies par le serveur (rien n'est écrit en dur dans l'app).
    @Published private(set) var supabaseEnabled = false

    func loadSupabaseConfig() async {
        guard APIConfig.shared.baseURL != nil, let config = try? await APIClient.shared.authConfig() else { return }
        SupabaseAuth.shared.configure(url: config.supabaseURL, anonKey: config.supabaseAnonKey)
        supabaseEnabled = SupabaseAuth.shared.config != nil
    }

    // MARK: Ancien compte (connexion Last.fm d'avant les comptes Sona)

    private static let legacyKey = "encre.legacy.session"
    /// Un ancien compte attend d'être rattaché : l'écran de connexion l'annonce.
    var hasLegacyAccount: Bool { Keychain.get(Self.legacyKey) != nil }

    /// Une ancienne session (jeton sans point, contrairement à un jeton Supabase) est mise de côté, et on repasse par
    /// la connexion : elle servira de preuve pour rattacher l'ancien compte.
    private func setAsideLegacySession() -> Bool {
        let old = APIConfig.shared.sessionToken
        guard supabaseEnabled, !SupabaseAuth.shared.hasSession, !old.isEmpty, !old.contains(".") else { return false }
        Keychain.set(old, forKey: Self.legacyKey)
        APIConfig.shared.sessionToken = ""
        Self.cachedAccount = nil
        state = .signedOut
        return true
    }

    private func adoptOldAccount() async {
        guard SupabaseAuth.shared.hasSession, let old = Keychain.get(Self.legacyKey) else { return }
        do {
            try await APIClient.shared.linkLegacy(sessionToken: old)
        } catch APIError.server(let status, _) where [403, 404, 409].contains(status) {
            // Définitif : il n'y a rien à reprendre.
        } catch {
            return // réseau ou serveur en panne : on réessaiera
        }
        Keychain.set("", forKey: Self.legacyKey)
    }

    /// Compte Sona : e-mail + mot de passe.
    func signIn(email: String, password: String, captcha: String) async {
        await runSupabase { try await SupabaseAuth.shared.signIn(email: email, password: password, captcha: captcha) }
    }

    /// Compte Sona : code par e-mail (connexion ou création). Vrai si le code est parti.
    func sendCode(email: String, captcha: String) async -> Bool {
        await runSupabase { try await SupabaseAuth.shared.sendCode(email: email, captcha: captcha) }
        return errorMessage == nil
    }

    func verifyCode(email: String, code: String) async {
        await runSupabase { try await SupabaseAuth.shared.verifyCode(email: email, code: code) }
    }

    /// Compte Sona : Google, Discord ou GitHub (PKCE, feuille système).
    func signIn(provider: String, using session: WebAuthenticationSession) async {
        await runSupabase { try await SupabaseAuth.shared.signIn(provider: provider, using: session) }
    }

    private func runSupabase(_ action: () async throws -> Void) async {
        isWorking = true
        errorMessage = nil
        defer { isWorking = false }
        do {
            await loadSupabaseConfig()
            try await action()
            await refresh()
        } catch SupabaseAuth.AuthError.cancelled {
            // Feuille fermée : rien à signaler.
        } catch {
            errorMessage = error.localizedDescription
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
        if SupabaseAuth.shared.hasSession {
            await SupabaseAuth.shared.signOut()
        } else if !APIConfig.shared.sessionToken.isEmpty {
            try? await APIClient.shared.logout()
        }
        APIConfig.shared.sessionToken = ""
        APIConfig.shared.token = ""
        Self.cachedAccount = nil
        state = .signedOut
    }

    func update(_ account: AppAccount) {
        apply(account)
    }

    private static let cacheKey = "encre.lastAccount"

    private static var cachedAccount: AppAccount? {
        get {
            guard let data = UserDefaults.standard.data(forKey: cacheKey) else { return nil }
            return try? JSONDecoder().decode(AppAccount.self, from: data)
        }
        set {
            if let newValue, let data = try? JSONEncoder().encode(newValue) {
                UserDefaults.standard.set(data, forKey: cacheKey)
            } else {
                UserDefaults.standard.removeObject(forKey: cacheKey)
            }
        }
    }

    private func apply(_ account: AppAccount) {
        offline = false
        Self.cachedAccount = account
        switch account.status {
        case "approved": state = .approved(account)
        case "rejected": state = .rejected(account)
        default: state = .pending(account)
        }
    }
}
