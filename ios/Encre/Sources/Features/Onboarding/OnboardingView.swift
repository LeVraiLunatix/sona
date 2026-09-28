import SwiftUI

/// Accueil au premier lancement — version honnête du 3-écrans du prototype
/// (masthead, "qui écoutez-vous ?", "c'est prêt") : Sona n'a ni compte ni
/// préférences d'artistes à collecter (voir README), la seule chose qui
/// manque vraiment avant de pouvoir ouvrir l'app est la connexion au
/// serveur — donc 2 écrans : bienvenue, puis adresse + jeton.
struct OnboardingView: View {
    @ObservedObject private var config = APIConfig.shared
    @State private var step = 0
    @State private var testing = false
    @State private var testResult: String?
    var onFinished: () -> Void

    var body: some View {
        ZStack {
            LivingBackground(colors: [
                Color(hex: 0x2A2340), Color(hex: 0x14121C), Color(hex: 0x0B0B10), Color(hex: 0x1D1A2B),
            ])
            Group {
                switch step {
                case 0: welcomeStep
                default: setupStep
                }
            }
            .transition(.asymmetric(
                insertion: .move(edge: .trailing).combined(with: .opacity),
                removal: .move(edge: .leading).combined(with: .opacity)
            ))
        }
        .animation(Motion.smooth, value: step)
    }

    private var welcomeStep: some View {
        VStack(alignment: .leading, spacing: 14) {
            Spacer()
            Image(systemName: "waveform")
                .font(.system(size: 44, weight: .semibold))
                .foregroundStyle(Tone.primary)
                .symbolEffect(.variableColor.iterative, options: .repeating)
                .reveal(0)
            Text("Encre")
                .font(.system(size: 64, weight: .bold))
                .foregroundStyle(Tone.primary)
                .reveal(1)
            Text("Ta musique, ton serveur. Rien d'autre.")
                .font(.system(size: 20, weight: .medium))
                .foregroundStyle(Tone.secondary)
                .reveal(2)
            Spacer().frame(height: 30)
            PillButton(title: "Commencer", systemImage: "arrow.right") { step = 1 }
                .reveal(3)
        }
        .padding(.horizontal, 28)
        .padding(.bottom, 50)
    }

    private var setupStep: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Connexion au serveur")
                .font(Typo.largeTitle)
                .foregroundStyle(Tone.primary)
                .padding(.top, 90)
            Text("L'adresse et le jeton de ton serveur Sona (`run_api.py`). Pas de compte à créer.")
                .font(Typo.body)
                .foregroundStyle(Tone.secondary)

            VStack(spacing: 12) {
                TextField("https://…", text: $config.baseURLString)
                    .keyboardType(.URL)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
                    .padding(.horizontal, 16)
                    .frame(height: 50)
                    .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Tone.surfaceStrong))
                SecureField("Jeton API", text: $config.token)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
                    .padding(.horizontal, 16)
                    .frame(height: 50)
                    .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Tone.surfaceStrong))
            }
            .padding(.top, 8)

            if let testResult {
                Text(testResult)
                    .font(Typo.rowSubtitle)
                    .foregroundStyle(Tone.danger)
                    .transition(.opacity)
            }

            Spacer()

            PillButton(title: testing ? "Vérification…" : "Ouvrir Encre", systemImage: "checkmark", isLoading: testing) {
                Task { await finish() }
            }
            .disabled(!config.isConfigured)
            .opacity(config.isConfigured ? 1 : 0.4)
        }
        .padding(.horizontal, 28)
        .padding(.bottom, 40)
    }

    private func finish() async {
        testing = true
        testResult = nil
        do {
            _ = try await APIClient.shared.getSettings()
            onFinished()
        } catch {
            testResult = "Connexion impossible : \(error.localizedDescription)"
        }
        testing = false
    }
}
