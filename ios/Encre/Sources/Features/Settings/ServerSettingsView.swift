import SwiftUI

/// Adresse du serveur Sona et jeton API — voir `APIConfig`. Usage personnel :
/// pas de compte, juste ces deux valeurs à faire correspondre à `.env` côté
/// serveur (`API_TOKEN`) et à l'adresse où tourne `run_api.py`.
struct ServerSettingsView: View {
    @ObservedObject var config = APIConfig.shared
    @State private var testResult: String?
    @State private var testing = false

    var body: some View {
        Form {
            Section("Serveur Sona") {
                TextField("http://192.168.1.x:8000", text: $config.baseURLString)
                    .keyboardType(.URL)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
                SecureField("Jeton API (API_TOKEN)", text: $config.token)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
            }
            Section {
                Button(testing ? "Test en cours…" : "Tester la connexion") {
                    Task { await test() }
                }
                .disabled(testing || !config.isConfigured)
                if let testResult {
                    Text(testResult).font(.footnote)
                }
            } footer: {
                Text("L'adresse et le jeton doivent correspondre à ceux de `run_api.py` (voir la section « API » du README de Sona). Sur un iPhone physique, utilise l'adresse locale du Mac (ex: http://192.168.1.42:8000), pas 127.0.0.1.")
            }
        }
        .navigationTitle("Réglages")
    }

    private func test() async {
        testing = true
        testResult = nil
        do {
            let settings = try await APIClient.shared.getSettings()
            testResult = "Connecté — qualité « \(settings.quality) », format « \(settings.format) »."
        } catch {
            testResult = error.localizedDescription
        }
        testing = false
    }
}
