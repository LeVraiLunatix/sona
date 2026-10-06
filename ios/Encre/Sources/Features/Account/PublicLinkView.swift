import SwiftUI

/// Page publique « J'écoute » : un lien à mettre sur un profil (Discord,
/// Instagram…) qui montre en direct ce que tu écoutes, sinon ta dernière
/// écoute. Rien n'y apparaît quand « Partager mon écoute » est coupé.
struct PublicLinkView: View {
    @State private var token: String?
    @State private var loaded = false
    @State private var busy = false
    @State private var error: String?
    @State private var confirmingDelete = false

    private var url: URL? { token.flatMap { APIClient.shared.publicPageURL($0) } }

    var body: some View {
        Form {
            Section {
                if !loaded {
                    HStack { Spacer(); ProgressView(); Spacer() }
                } else if let url {
                    ShareLink(item: url, subject: Text("J'écoute sur Sona")) {
                        Label("Partager le lien", systemImage: "square.and.arrow.up")
                    }
                    Link(destination: url) {
                        Label("Ouvrir la page", systemImage: "safari")
                    }
                    Button {
                        UIPasteboard.general.url = url
                        UINotificationFeedbackGenerator().notificationOccurred(.success)
                    } label: {
                        Label("Copier le lien", systemImage: "doc.on.doc")
                    }
                } else {
                    Button {
                        Task { await create() }
                    } label: {
                        Label("Créer ma page", systemImage: "globe")
                    }
                    .disabled(busy)
                }
            } footer: {
                if let url {
                    Text(url.absoluteString).textSelection(.enabled)
                } else {
                    Text("Toute personne qui a le lien voit ce que tu écoutes, en direct (titre, pochette, progression), sinon ta dernière écoute. Idéal sur ton profil Discord ou Instagram.")
                }
            }

            if token != nil {
                Section {
                    Button("Changer de lien") { Task { await create() } }.disabled(busy)
                    Button("Supprimer la page", role: .destructive) { confirmingDelete = true }.disabled(busy)
                } footer: {
                    Text("Changer de lien ou supprimer la page : l'ancien lien ne marche plus. Rien n'apparaît quand « Partager mon écoute » est coupé.")
                }
            }
        }
        .navigationTitle("Page « J'écoute »")
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
        .confirmationDialog("Supprimer ta page « J'écoute » ?", isPresented: $confirmingDelete, titleVisibility: .visible) {
            Button("Supprimer", role: .destructive) { Task { await remove() } }
        }
        .alert("Page « J'écoute »", isPresented: Binding(get: { error != nil }, set: { if !$0 { error = nil } })) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(error ?? "")
        }
    }

    private func load() async {
        do {
            token = try await APIClient.shared.publicLink().token
        } catch {
            self.error = error.localizedDescription
        }
        loaded = true
    }

    private func create() async {
        busy = true
        defer { busy = false }
        do {
            token = try await APIClient.shared.createPublicLink().token
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func remove() async {
        busy = true
        defer { busy = false }
        do {
            try await APIClient.shared.deletePublicLink()
            token = nil
        } catch {
            self.error = error.localizedDescription
        }
    }
}
