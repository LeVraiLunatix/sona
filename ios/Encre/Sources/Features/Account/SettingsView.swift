import SwiftUI

/// Réglages : compte Last.fm, scrobbling, administration (admins), serveur.
struct SettingsView: View {
    @EnvironmentObject private var auth: AuthManager
    @ObservedObject private var config = APIConfig.shared
    @State private var scrobble = true
    @State private var pendingCount = 0
    @State private var errorMessage: String?

    var body: some View {
        Form {
            if let account = auth.account {
                Section {
                    HStack(spacing: 14) {
                        Artwork(url: account.avatarURL, cornerRadius: 28, symbol: "person.fill")
                            .frame(width: 56, height: 56)
                        VStack(alignment: .leading, spacing: 3) {
                            Text(account.name).font(Typo.headline)
                            Text(account.id == nil ? "Jeton administrateur" : "Last.fm · \(account.username)")
                                .font(Typo.rowSubtitle)
                                .foregroundStyle(Tone.secondary)
                        }
                        Spacer()
                        if account.isAdmin {
                            Text("ADMIN")
                                .font(Typo.caption)
                                .padding(.horizontal, 8)
                                .padding(.vertical, 4)
                                .background(Capsule().fill(Tone.surfaceStrong))
                        }
                    }
                    .padding(.vertical, 4)

                    if account.id != nil {
                        Toggle("Envoyer mes écoutes sur Last.fm", isOn: $scrobble)
                            .onChange(of: scrobble) { _, value in
                                guard value != account.scrobbleToLastfm else { return }
                                Task { await setScrobbling(value) }
                            }
                    }
                } footer: {
                    if account.id != nil {
                        Text("Chaque morceau écouté au moins à moitié est aussi ajouté à ton profil Last.fm (et donc visible sur Sonar).")
                    }
                }

                if account.isAdmin {
                    Section {
                        NavigationLink {
                            AdminView()
                        } label: {
                            HStack {
                                Label("Accès à l'app", systemImage: "person.badge.shield.checkmark")
                                Spacer()
                                if pendingCount > 0 {
                                    Text("\(pendingCount)")
                                        .font(Typo.caption)
                                        .foregroundStyle(.black)
                                        .padding(.horizontal, 8)
                                        .padding(.vertical, 3)
                                        .background(Capsule().fill(.white))
                                }
                            }
                        }
                    } header: {
                        Text("Administration")
                    }
                }
            }

            Section {
                TextField("https://…", text: $config.baseURLString)
                    .keyboardType(.URL)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
            } header: {
                Text("Serveur")
            }

            if let errorMessage {
                Section { Text(errorMessage).foregroundStyle(Tone.danger) }
            }

            Section {
                Button("Se déconnecter", role: .destructive) {
                    Task { await auth.signOut() }
                }
            }
        }
        .navigationTitle("Réglages")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear { scrobble = auth.account?.scrobbleToLastfm ?? true }
        .task { await loadPendingCount() }
    }

    private func setScrobbling(_ value: Bool) async {
        do {
            auth.update(try await APIClient.shared.updateMe(scrobbleToLastfm: value))
        } catch {
            errorMessage = error.localizedDescription
            scrobble = !value
        }
    }

    private func loadPendingCount() async {
        guard auth.account?.isAdmin == true, let accounts = try? await APIClient.shared.adminAccounts() else { return }
        pendingCount = accounts.filter { $0.status == "pending" }.count
    }
}

/// Panel d'admin : qui peut entrer dans l'app. Les demandes en attente en
/// premier, accepter/refuser d'un geste, révoquer ou nommer admin ensuite.
struct AdminView: View {
    @EnvironmentObject private var auth: AuthManager
    @State private var accounts: [AppAccount] = []
    @State private var isLoading = true
    @State private var errorMessage: String?
    @State private var busyId: Int?

    var body: some View {
        List {
            if let errorMessage {
                Text(errorMessage).foregroundStyle(Tone.danger)
            }
            section("En attente", status: "pending", empty: "Aucune demande pour l'instant.")
            section("Accès accordé", status: "approved", empty: nil)
            section("Refusés", status: "rejected", empty: nil)
        }
        .overlay {
            if isLoading && accounts.isEmpty { ProgressView().tint(.white) }
        }
        .navigationTitle("Accès à l'app")
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
        .refreshable { await load() }
        .animation(Motion.smooth, value: accounts)
    }

    @ViewBuilder
    private func section(_ title: String, status: String, empty: String?) -> some View {
        let list = accounts.filter { $0.status == status }
        if !list.isEmpty || empty != nil {
            Section(title) {
                if list.isEmpty, let empty {
                    Text(empty).foregroundStyle(Tone.secondary)
                }
                ForEach(list) { account in
                    row(account)
                }
            }
        }
    }

    private func row(_ account: AppAccount) -> some View {
        let isSelf = account.id != nil && account.id == auth.account?.id
        return HStack(spacing: 12) {
            Artwork(url: account.avatarURL, cornerRadius: 22, symbol: "person.fill")
                .frame(width: 44, height: 44)
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text(account.name).font(Typo.rowTitle)
                    if account.isAdmin {
                        Text("ADMIN").font(.system(size: 9, weight: .bold)).foregroundStyle(Tone.secondary)
                    }
                }
                Text("Last.fm · \(account.username)").font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
            }
            Spacer()
            if busyId == account.id {
                ProgressView().tint(.white)
            } else if account.status == "pending" {
                HStack(spacing: 8) {
                    decisionButton("xmark", filled: false) { await decide(account, "reject") }
                    decisionButton("checkmark", filled: true) { await decide(account, "approve") }
                }
            }
        }
        .padding(.vertical, 4)
        .swipeActions(edge: .trailing) {
            if !isSelf {
                if account.status == "approved" {
                    Button("Révoquer", role: .destructive) { Task { await decide(account, "reject") } }
                } else if account.status == "rejected" {
                    Button("Accepter") { Task { await decide(account, "approve") } }.tint(.green)
                }
            }
        }
        .contextMenu {
            if !isSelf && account.status == "approved" {
                Button(account.isAdmin ? "Retirer les droits d'admin" : "Nommer admin",
                       systemImage: "person.badge.key") {
                    Task { await decide(account, account.isAdmin ? "demote" : "promote") }
                }
            }
        }
    }

    private func decisionButton(_ icon: String, filled: Bool, action: @escaping () async -> Void) -> some View {
        Button {
            Task { await action() }
        } label: {
            Image(systemName: icon)
                .font(.system(size: 14, weight: .bold))
                .foregroundStyle(filled ? Color.black : Tone.primary)
                .frame(width: 36, height: 36)
                .background(Circle().fill(filled ? Color.white : Tone.surfaceStrong))
        }
        .buttonStyle(.pressable(scale: 0.85))
    }

    private func load() async {
        isLoading = true
        do {
            accounts = try await APIClient.shared.adminAccounts()
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
        isLoading = false
    }

    private func decide(_ account: AppAccount, _ action: String) async {
        guard let id = account.id else { return }
        busyId = id
        do {
            let updated = try await APIClient.shared.adminDecide(accountId: id, action: action)
            if let index = accounts.firstIndex(where: { $0.id == id }) { accounts[index] = updated }
        } catch {
            errorMessage = error.localizedDescription
        }
        busyId = nil
    }
}
