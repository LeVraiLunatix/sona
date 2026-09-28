import AuthenticationServices
import SwiftUI

/// Premier écran : se connecter avec Last.fm. L'adresse du serveur est
/// déjà renseignée dans l'app distribuée ; sinon, un champ la demande.
struct LoginView: View {
    @EnvironmentObject private var auth: AuthManager
    @ObservedObject private var config = APIConfig.shared
    @Environment(\.webAuthenticationSession) private var webAuthenticationSession
    @State private var showsServer = false
    @State private var showsToken = false

    var body: some View {
        ZStack {
            LivingBackground(colors: [
                Color(hex: 0x3A0D14), Color(hex: 0x14090C), Color(hex: 0x0B0B10), Color(hex: 0x24090F),
            ])
            VStack(alignment: .leading, spacing: 14) {
                Spacer()
                SonaLogo(size: 72)
                    .reveal(0)
                Text("Sona")
                    .font(.system(size: 64, weight: .bold))
                    .foregroundStyle(Tone.primary)
                    .reveal(1)
                Text("Ta musique, tes stats. Sur invitation.")
                    .font(.system(size: 20, weight: .medium))
                    .foregroundStyle(Tone.secondary)
                    .reveal(2)

                Spacer().frame(height: 24)

                if showsServer || config.baseURL == nil || config.baseURLString.isEmpty {
                    field("Adresse du serveur (https://…)", text: $config.baseURLString, secure: false)
                        .transition(.opacity.combined(with: .move(edge: .bottom)))
                }

                Button {
                    Task { await auth.signInWithLastfm(using: webAuthenticationSession) }
                } label: {
                    HStack(spacing: 10) {
                        if auth.isWorking {
                            ProgressView().tint(.white)
                        } else {
                            Image(systemName: "dot.radiowaves.left.and.right")
                        }
                        Text("Se connecter avec Last.fm")
                    }
                    .font(Typo.headline)
                    .foregroundStyle(.white)
                    .frame(maxWidth: .infinity)
                    .frame(height: 54)
                    .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(Color(hex: 0xD51007)))
                }
                .buttonStyle(.pressable)
                .disabled(auth.isWorking || config.baseURL == nil)
                .reveal(3)

                if let message = auth.errorMessage {
                    Text(message)
                        .font(Typo.rowSubtitle)
                        .foregroundStyle(Tone.danger)
                        .transition(.opacity)
                }

                if showsToken {
                    field("Jeton administrateur (API_TOKEN)", text: $config.token, secure: true)
                    PillButton(title: "Utiliser ce jeton", systemImage: "key.fill", kind: .secondary) {
                        Task { await auth.refresh() }
                    }
                    .disabled(config.token.isEmpty)
                }

                HStack {
                    Button(showsServer ? "Masquer le serveur" : "Changer de serveur") {
                        withAnimation(Motion.smooth) { showsServer.toggle() }
                    }
                    Spacer()
                    Button(showsToken ? "Annuler" : "J'ai un jeton") {
                        withAnimation(Motion.smooth) { showsToken.toggle() }
                    }
                }
                .font(Typo.rowSubtitle)
                .foregroundStyle(Tone.tertiary)
                .padding(.top, 6)
            }
            .padding(.horizontal, 28)
            .padding(.bottom, 40)
            .animation(Motion.smooth, value: auth.errorMessage)
        }
    }

    private func field(_ placeholder: String, text: Binding<String>, secure: Bool) -> some View {
        Group {
            if secure {
                SecureField(placeholder, text: text)
            } else {
                TextField(placeholder, text: text).keyboardType(.URL)
            }
        }
        .autocorrectionDisabled()
        .textInputAutocapitalization(.never)
        .padding(.horizontal, 16)
        .frame(height: 50)
        .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Tone.surfaceStrong))
    }
}

/// Connecté, mais l'accès n'est pas (ou plus) accordé : on attend un admin.
struct AccessPendingView: View {
    let account: AppAccount
    let rejected: Bool
    @EnvironmentObject private var auth: AuthManager
    @State private var pulse = false

    var body: some View {
        ZStack {
            Tone.background.ignoresSafeArea()
            VStack(spacing: 18) {
                Spacer()
                ZStack {
                    Circle()
                        .fill(Color.white.opacity(0.06))
                        .frame(width: 150, height: 150)
                        .scaleEffect(pulse ? 1.12 : 0.92)
                        .opacity(rejected ? 0 : 1)
                    Artwork(url: account.avatarURL, cornerRadius: 50, symbol: "person.fill")
                        .frame(width: 100, height: 100)
                }
                .animation(.easeInOut(duration: 1.6).repeatForever(autoreverses: true), value: pulse)
                Text(rejected ? "Accès refusé" : "Demande envoyée")
                    .font(Typo.largeTitle)
                    .foregroundStyle(Tone.primary)
                Text(rejected
                     ? "Un administrateur n'a pas accordé l'accès à \(account.name)."
                     : "Salut \(account.name) ! Un administrateur doit accepter ton compte avant que tu puisses entrer. Cet écran se met à jour tout seul.")
                    .font(Typo.body)
                    .foregroundStyle(Tone.secondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 32)
                Spacer()
                PillButton(title: "Se déconnecter", systemImage: "rectangle.portrait.and.arrow.right", kind: .secondary) {
                    Task { await auth.signOut() }
                }
                .padding(.horizontal, 28)
                .padding(.bottom, 40)
            }
        }
        .onAppear { pulse = true }
        .task(id: rejected) {
            guard !rejected else { return }
            // Vérifie régulièrement si l'accès a été accordé.
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(8))
                await auth.refresh()
            }
        }
    }
}


/// Session enregistrée, mais le serveur ne répond pas : réessai
/// automatique toutes les 5 s, sans repasser par la connexion.
struct ServerUnreachableView: View {
    let message: String
    @EnvironmentObject private var auth: AuthManager
    @State private var retrying = false

    var body: some View {
        ZStack {
            Tone.background.ignoresSafeArea()
            VStack(spacing: 18) {
                Spacer()
                Image(systemName: "wifi.exclamationmark")
                    .font(.system(size: 46, weight: .semibold))
                    .foregroundStyle(Tone.secondary)
                    .symbolEffect(.pulse, options: .repeating)
                Text("Serveur injoignable")
                    .font(Typo.largeTitle)
                    .foregroundStyle(Tone.primary)
                Text(message)
                    .font(Typo.body)
                    .foregroundStyle(Tone.secondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 32)
                Spacer()
                PillButton(title: "Réessayer", systemImage: "arrow.clockwise", isLoading: retrying) {
                    Task {
                        retrying = true
                        await auth.refresh()
                        retrying = false
                    }
                }
                .padding(.horizontal, 28)
                Button("Se déconnecter") { Task { await auth.signOut() } }
                    .font(Typo.rowSubtitle)
                    .foregroundStyle(Tone.tertiary)
                    .padding(.bottom, 40)
            }
        }
        .task {
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(5))
                await auth.refresh()
            }
        }
    }
}
