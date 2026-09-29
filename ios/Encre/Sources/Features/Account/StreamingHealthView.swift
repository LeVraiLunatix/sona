import SwiftUI
import UniformTypeIdentifiers

/// Santé de la lecture (admins) : Sona arrive-t-il encore à lire YouTube ?
/// Cookies YouTube à renvoyer (fichier cookies.txt), mise à jour de yt-dlp,
/// essai de lecture — de quoi réparer sans toucher au serveur.
struct StreamingHealthView: View {
    @State private var status: StreamingStatus?
    @State private var errorMessage: String?
    @State private var result: String?
    @State private var resultIsBad = false
    @State private var working = false
    @State private var importing = false

    var body: some View {
        List {
            if let status {
                Section {
                    HStack(alignment: .top, spacing: 14) {
                        Circle().fill(color(status.health.state)).frame(width: 14, height: 14).padding(.top, 5)
                        VStack(alignment: .leading, spacing: 4) {
                            Text(title(status.health.state)).font(Typo.headline).foregroundStyle(Tone.primary)
                            Text(status.health.advice ?? subtitle(status.health.state))
                                .font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
                            Text("\(status.health.recentOk) titre(s) lancé(s), \(status.health.recentFailures) échec(s) sur 30 min")
                                .font(Typo.caption).foregroundStyle(Tone.tertiary)
                        }
                    }
                    .padding(.vertical, 4)
                }

                Section {
                    LabeledContent("État", value: cookieState(status.cookies))
                    if let updated = status.cookies.updatedAt {
                        LabeledContent("Envoyés", value: Date(timeIntervalSince1970: updated).formatted(.relative(presentation: .named)))
                    }
                    Button {
                        importing = true
                    } label: {
                        Label("Envoyer un fichier cookies.txt", systemImage: "square.and.arrow.up")
                    }
                    .disabled(working)
                } header: {
                    Text("Cookies YouTube")
                } footer: {
                    Text("Sur le PC : fenêtre de navigation privée, connexion à youtube.com, export avec l'extension « Get cookies.txt LOCALLY » (ce site uniquement), puis ferme la fenêtre privée. Envoie le fichier ici (via Fichiers ou AirDrop) ou depuis le site Sona.")
                }

                Section {
                    LabeledContent("Version", value: status.ytdlp.version ?? "?")
                    if let update = status.ytdlp.lastUpdate {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(update.message).font(Typo.rowSubtitle).foregroundStyle(Tone.primary)
                            Text(Date(timeIntervalSince1970: update.checkedAt).formatted(.relative(presentation: .named)))
                                .font(Typo.caption).foregroundStyle(Tone.tertiary)
                        }
                    }
                    Button {
                        run { try await APIClient.shared.updateYtdlp() }
                    } label: {
                        Label("Mettre à jour maintenant", systemImage: "arrow.down.circle")
                    }
                    Button {
                        run { try await APIClient.shared.streamingSelftest() }
                    } label: {
                        Label("Essai de lecture", systemImage: "play.circle")
                    }
                } header: {
                    Text("yt-dlp")
                } footer: {
                    Text("Mis à jour tout seul chaque nuit, avec un essai de lecture : si la nouvelle version casse quelque chose, Sona revient à l'ancienne.")
                }

                if let result {
                    Section {
                        Text(result).foregroundStyle(resultIsBad ? Tone.danger : Tone.primary)
                    }
                }
            } else if let errorMessage {
                Text(errorMessage).foregroundStyle(Tone.danger)
            } else {
                ProgressView().frame(maxWidth: .infinity)
            }
        }
        .navigationTitle("Santé de la lecture")
        .navigationBarTitleDisplayMode(.inline)
        .overlay { if working { ProgressView().controlSize(.large) } }
        .task { await load() }
        .refreshable { await load() }
        .fileImporter(isPresented: $importing, allowedContentTypes: [.plainText, .text, .data]) { picked in
            guard case .success(let url) = picked else { return }
            let access = url.startAccessingSecurityScopedResource()
            defer { if access { url.stopAccessingSecurityScopedResource() } }
            guard let content = try? String(contentsOf: url, encoding: .utf8) else {
                show("Fichier illisible.", bad: true)
                return
            }
            run { try await APIClient.shared.uploadYouTubeCookies(content) }
        }
    }

    private func load() async {
        do {
            status = try await APIClient.shared.streamingStatus()
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func run(_ action: @escaping () async throws -> AdminResult) {
        working = true
        Task {
            do {
                let got = try await action()
                let bad = got.ok == false || got.loggedIn == false
                show(got.message ?? (got.ok == true ? "YouTube répond." : "Terminé."), bad: bad)
            } catch {
                show(error.localizedDescription, bad: true)
            }
            working = false
            await load()
        }
    }

    private func show(_ text: String, bad: Bool) {
        result = text
        resultIsBad = bad
    }

    private func color(_ state: String) -> Color {
        switch state {
        case "down": .red
        case "degraded": .orange
        default: .green
        }
    }

    private func title(_ state: String) -> String {
        switch state {
        case "down": "Lecture en panne"
        case "degraded": "Lecture perturbée"
        default: "Tout fonctionne"
        }
    }

    private func subtitle(_ state: String) -> String {
        state == "ok" ? "La musique se lance normalement." : "Certains titres ne se lancent pas."
    }

    private func cookieState(_ cookies: StreamingStatus.Cookies) -> String {
        guard cookies.present else { return "Aucun fichier" }
        switch cookies.loggedIn {
        case .some(true): return "Connectés"
        case .some(false): return "Expirés"
        default: return "Pas encore vérifiés"
        }
    }
}
