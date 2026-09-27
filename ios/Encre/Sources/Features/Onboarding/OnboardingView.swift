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
            EncreColor.bg.ignoresSafeArea()
            Group {
                switch step {
                case 0: welcomeStep
                default: setupStep
                }
            }
            .transition(.asymmetric(insertion: .move(edge: .trailing), removal: .move(edge: .leading)).combined(with: .opacity))
        }
        .animation(.easeInOut(duration: 0.35), value: step)
    }

    private var welcomeStep: some View {
        VStack(alignment: .leading, spacing: 14) {
            Spacer()
            Text("BIENVENUE")
                .font(EncreFont.heading(12))
                .tracking(2)
                .foregroundStyle(EncreColor.accent2_700)
            Text("Encre")
                .font(EncreFont.heading(88))
                .foregroundStyle(EncreColor.text)
                .lineLimit(1)
                .minimumScaleFactor(0.5)
            Text("Vos titres préférés, imprimés en couleur et posés sous verre.")
                .font(EncreFont.bodyItalic(21))
                .foregroundStyle(EncreColor.neutral800)

            Button {
                step = 1
            } label: {
                Text("Commencer")
                    .font(EncreFont.heading(19))
                    .foregroundStyle(EncreColor.text)
                    .frame(maxWidth: .infinity)
                    .frame(height: 60)
            }
            .buttonStyle(.plain)
            .glassCapsule()
            .padding(.top, 14)

            Spacer().frame(height: 20)
        }
        .padding(.horizontal, 28)
        .padding(.bottom, 60)
    }

    private var setupStep: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("DERNIÈRE ÉTAPE")
                .font(EncreFont.heading(12))
                .tracking(2)
                .foregroundStyle(EncreColor.accent2_700)
                .padding(.top, 100)
            Text("Trouvons votre serveur")
                .font(EncreFont.heading(36))
                .foregroundStyle(EncreColor.text)
            Text("L'adresse et le jeton de ton serveur Sona (`run_api.py`) — usage personnel, pas de compte à créer. Détails dans le README du dépôt, section « API ».")
                .font(EncreFont.body(16))
                .foregroundStyle(EncreColor.neutral700)

            VStack(spacing: 12) {
                TextField("http://192.168.1.x:8000", text: $config.baseURLString)
                    .keyboardType(.URL)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
                    .padding(.horizontal, 16)
                    .frame(height: 48)
                    .glassRounded(14)
                SecureField("Jeton API", text: $config.token)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
                    .padding(.horizontal, 16)
                    .frame(height: 48)
                    .glassRounded(14)
            }
            .padding(.top, 8)

            if let testResult {
                Text(testResult)
                    .font(EncreFont.body(14))
                    .foregroundStyle(EncreColor.accent2_700)
            }

            Spacer()

            Button {
                Task { await finish() }
            } label: {
                Text(testing ? "Vérification…" : "Ouvrir Encre")
                    .font(EncreFont.heading(19))
                    .foregroundStyle(EncreColor.bg)
                    .frame(maxWidth: .infinity)
                    .frame(height: 60)
            }
            .buttonStyle(.plain)
            .background(Capsule().fill(config.isConfigured ? EncreColor.spot : EncreColor.neutral300))
            .disabled(testing || !config.isConfigured)
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
