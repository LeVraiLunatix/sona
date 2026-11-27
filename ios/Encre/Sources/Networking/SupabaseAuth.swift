import AuthenticationServices
import CryptoKit
import Foundation
import Security
import SwiftUI

/// Connexion à un compte Sona (Supabase Auth) sans bibliothèque tierce : e-mail + mot de passe, ou Google / Discord / GitHub
/// avec PKCE dans une feuille système (`ASWebAuthenticationSession`, retour sur `sona://auth/callback`).
///
/// Le jeton d'accès (court) est envoyé au serveur musique, qui le fait vérifier par le service de comptes à chaque requête
/// (un compte banni ou suspendu est donc refusé tout de suite). Le jeton de renouvellement reste dans le Trousseau.
/// Aucune clé secrète ici : l'adresse du projet et la clé publique (« anon ») viennent de `GET /auth/config`.
@MainActor
final class SupabaseAuth {
    static let shared = SupabaseAuth()

    struct Session: Codable, Equatable {
        var accessToken: String
        var refreshToken: String
        /// Instant d'expiration du jeton d'accès (secondes depuis 1970).
        var expiresAt: TimeInterval
    }

    struct Config: Equatable {
        var url: URL
        var anonKey: String
    }

    enum AuthError: LocalizedError {
        case notConfigured
        case cancelled
        case server(String)
        case missingCode

        var errorDescription: String? {
            switch self {
            case .notConfigured: "La connexion par compte Sona n'est pas configurée sur ce serveur."
            case .cancelled: nil
            case .server(let message): message
            case .missingCode: "La connexion n'a pas abouti. Réessaie."
            }
        }
    }

    static let callbackScheme = "sona"
    static let callbackURL = "sona://auth/callback"
    /// Les fournisseurs proposés (pas de « Se connecter avec Apple » : choix assumé, voir docs/AUTH_SETUP.md).
    static let providers: [(id: String, name: String, icon: String)] = [
        ("google", "Google", "g.circle.fill"), ("discord", "Discord", "bubble.left.and.bubble.right.fill"), ("github", "GitHub", "chevron.left.forwardslash.chevron.right"),
    ]

    private(set) var config: Config?
    private var session: Session? {
        didSet { Self.store(session) }
    }
    private var refreshing: Task<Session?, Never>?

    private init() {
        session = Self.load()
    }

    var hasSession: Bool { session != nil }

    func configure(url: String?, anonKey: String?) {
        guard let url, let parsed = URL(string: url), let anonKey, !anonKey.isEmpty else { config = nil; return }
        config = Config(url: parsed, anonKey: anonKey)
    }

    // MARK: - Connexions

    func signIn(email: String, password: String) async throws {
        let body = ["email": email.trimmingCharacters(in: .whitespacesAndNewlines), "password": password]
        apply(try await token(grant: "password", body: body))
    }

    /// OAuth avec PKCE : le « verifier » ne quitte jamais l'appareil ; seul son empreinte part avec la demande.
    func signIn(provider: String, using web: WebAuthenticationSession) async throws {
        guard let config else { throw AuthError.notConfigured }
        let verifier = Self.randomVerifier()
        var components = URLComponents(url: config.url.appendingPathComponent("auth/v1/authorize"), resolvingAgainstBaseURL: false)
        components?.queryItems = [
            URLQueryItem(name: "provider", value: provider),
            URLQueryItem(name: "redirect_to", value: Self.callbackURL),
            URLQueryItem(name: "code_challenge", value: Self.challenge(for: verifier)),
            URLQueryItem(name: "code_challenge_method", value: "s256"),
        ]
        guard let url = components?.url else { throw AuthError.notConfigured }
        let callback: URL
        do {
            callback = try await web.authenticate(using: url, callbackURLScheme: Self.callbackScheme)
        } catch let error as ASWebAuthenticationSessionError where error.code == .canceledLogin {
            throw AuthError.cancelled
        }
        let items = URLComponents(url: callback, resolvingAgainstBaseURL: false)?.queryItems ?? []
        if let message = items.first(where: { $0.name == "error_description" })?.value { throw AuthError.server(message) }
        guard let code = items.first(where: { $0.name == "code" })?.value else { throw AuthError.missingCode }
        apply(try await token(grant: "pkce", body: ["auth_code": code, "code_verifier": verifier]))
    }

    func signOut() async {
        if let config, let session {
            var req = URLRequest(url: config.url.appendingPathComponent("auth/v1/logout"))
            req.httpMethod = "POST"
            req.setValue(config.anonKey, forHTTPHeaderField: "apikey")
            req.setValue("Bearer \(session.accessToken)", forHTTPHeaderField: "Authorization")
            _ = try? await URLSession.shared.data(for: req)
        }
        session = nil
        APIConfig.shared.sessionToken = ""
    }

    // MARK: - Jeton d'accès

    /// Jeton d'accès valable : renouvelé s'il expire dans moins d'une minute. Un seul renouvellement à la fois
    /// (le jeton de renouvellement de Supabase ne sert qu'une fois : deux demandes en parallèle ruineraient la session).
    func freshAccessToken() async -> String? {
        guard let current = session else { return nil }
        if current.expiresAt - Date().timeIntervalSince1970 > 60 { return current.accessToken }
        if let refreshing { return await refreshing.value?.accessToken }
        let task = Task { [weak self] () -> Session? in
            guard let self else { return nil }
            do {
                let renewed = try await self.token(grant: "refresh_token", body: ["refresh_token": current.refreshToken])
                self.apply(renewed)
                return renewed
            } catch AuthError.server(let message) where message.localizedCaseInsensitiveContains("refresh token") {
                // Jeton de renouvellement refusé (session révoquée) : on s'arrête là, l'app repasse par la connexion.
                self.session = nil
                APIConfig.shared.sessionToken = ""
                return nil
            } catch {
                return current // réseau coupé : on garde l'ancien jeton, le serveur dira s'il est expiré
            }
        }
        refreshing = task
        let result = await task.value
        refreshing = nil
        return result?.accessToken
    }

    // MARK: - Interne

    private func apply(_ new: Session) {
        session = new
        // Le serveur musique reçoit le jeton d'accès comme n'importe quelle session de l'app.
        APIConfig.shared.sessionToken = new.accessToken
    }

    private struct TokenResponse: Decodable {
        var accessToken: String
        var refreshToken: String
        var expiresIn: Double?
        var expiresAt: Double?

        enum CodingKeys: String, CodingKey {
            case accessToken = "access_token", refreshToken = "refresh_token", expiresIn = "expires_in", expiresAt = "expires_at"
        }
    }

    private func token(grant: String, body: [String: String]) async throws -> Session {
        guard let config else { throw AuthError.notConfigured }
        var components = URLComponents(url: config.url.appendingPathComponent("auth/v1/token"), resolvingAgainstBaseURL: false)
        components?.queryItems = [URLQueryItem(name: "grant_type", value: grant)]
        guard let url = components?.url else { throw AuthError.notConfigured }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue(config.anonKey, forHTTPHeaderField: "apikey")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, response) = try await URLSession.shared.data(for: req)
        guard let http = response as? HTTPURLResponse else { throw AuthError.server("Réponse invalide.") }
        guard (200..<300).contains(http.statusCode) else { throw AuthError.server(Self.message(from: data, status: http.statusCode)) }
        let parsed = try JSONDecoder().decode(TokenResponse.self, from: data)
        let expires = parsed.expiresAt ?? (Date().timeIntervalSince1970 + (parsed.expiresIn ?? 3600))
        return Session(accessToken: parsed.accessToken, refreshToken: parsed.refreshToken, expiresAt: expires)
    }

    private static func message(from data: Data, status: Int) -> String {
        let object = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
        let raw = (object?["error_description"] as? String) ?? (object?["msg"] as? String) ?? (object?["message"] as? String) ?? ""
        switch raw.lowercased() {
        case let m where m.contains("invalid login credentials"): return "E-mail ou mot de passe incorrect."
        case let m where m.contains("email not confirmed"): return "Confirme d'abord ton adresse e-mail (lien reçu par courriel)."
        case let m where m.contains("rate limit") || status == 429: return "Trop de tentatives. Réessaie dans quelques minutes."
        default: return raw.isEmpty ? "Connexion refusée (\(status))." : raw
        }
    }

    // MARK: PKCE

    static func randomVerifier() -> String {
        var bytes = [UInt8](repeating: 0, count: 32)
        let status = SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)
        precondition(status == errSecSuccess, "Générateur aléatoire indisponible")
        return base64URL(Data(bytes))
    }

    static func challenge(for verifier: String) -> String {
        base64URL(Data(SHA256.hash(data: Data(verifier.utf8))))
    }

    static func base64URL(_ data: Data) -> String {
        data.base64EncodedString().replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
    }

    // MARK: Trousseau

    private static let storeKey = "encre.supabase.session"

    private static func store(_ session: Session?) {
        guard let session, let data = try? JSONEncoder().encode(session), let text = String(data: data, encoding: .utf8) else {
            Keychain.set("", forKey: storeKey)
            return
        }
        Keychain.set(text, forKey: storeKey)
    }

    private static func load() -> Session? {
        guard let text = Keychain.get(storeKey), let data = text.data(using: .utf8) else { return nil }
        return try? JSONDecoder().decode(Session.self, from: data)
    }
}
