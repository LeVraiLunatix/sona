import SwiftUI

/// Réglages : compte Last.fm, scrobbling, administration (admins), serveur.
struct SettingsView: View {
    @EnvironmentObject private var auth: AuthManager
    @ObservedObject private var config = APIConfig.shared
    @State private var scrobble = true
    @State private var shareListening = true
    @State private var smartDownloads = SmartDownloads.shared.enabled
    @State private var lovedImport: LovedImportStatus?
    @ObservedObject private var downloads = DownloadManager.shared
    @State private var pendingCount = 0
    /// Commit déployé sur le serveur : pour vérifier qu'une mise à jour est passée.
    @State private var serverVersion: String?
    @State private var errorMessage: String?
    @ObservedObject private var notifications = NotificationManager.shared

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
                        Text("Chaque morceau écouté au moins à moitié est aussi ajouté à ton profil Last.fm (et donc visible sur Sonar). Un titre ajouté à ta bibliothèque devient un titre aimé ♥ sur Last.fm.")
                    }
                }

                if account.id != nil {
                    Section {
                        Toggle("Partager mon écoute avec mes amis", isOn: $shareListening)
                            .onChange(of: shareListening) { _, value in
                                guard value != (account.shareListening ?? true) else { return }
                                Task { await setSharing(value) }
                            }
                        Button {
                            Task { await startLovedImport() }
                        } label: {
                            HStack {
                                Label("Importer mes titres aimés Last.fm", systemImage: "heart")
                                Spacer()
                                if lovedImport?.running == true { ProgressView() }
                            }
                        }
                        .disabled(lovedImport?.running == true)
                    } footer: {
                        if let status = lovedImport {
                            if let error = status.error {
                                Text(error).foregroundStyle(Tone.danger)
                            } else if status.running {
                                Text("Import en cours… \(status.done) / \(status.total)")
                            } else if status.total > 0 {
                                Text(lovedSummary(status))
                            }
                        } else {
                            Text("Tes amis voient ce que tu écoutes en direct et tes dernières écoutes.")
                        }
                    }
                }

                Section {
                    Toggle("Récaps de la semaine et du mois", isOn: $notifications.recaps)
                    Toggle("Rappel du défi du jour", isOn: $notifications.dailyChallenge)
                    Toggle("Parties lancées par mes amis", isOn: $notifications.friends)
                    Toggle("Nouvelles sorties de mes artistes", isOn: $notifications.releases)
                } header: {
                    Text("Notifications")
                } footer: {
                    Text("Récaps le lundi et le 1er du mois à 10 h, défi du jour à 18 h 30. Les parties des amis (blind test en direct, écoute ensemble) sont signalées quand l'app tourne, même en arrière-plan pendant la lecture.")
                }

                Section {
                    Toggle("Télécharger en Wi-Fi uniquement", isOn: Binding(
                        get: { downloads.wifiOnly }, set: { downloads.wifiOnly = $0 }
                    ))
                    Toggle("Téléchargements intelligents", isOn: $smartDownloads)
                        .onChange(of: smartDownloads) { _, value in
                            SmartDownloads.shared.enabled = value
                            if value { SmartDownloads.shared.schedule() }
                        }
                } header: {
                    Text("Téléchargements")
                } footer: {
                    Text(downloadsSummary + "\nIntelligents : la nuit (Wi-Fi, en charge) et à l'ouverture en Wi-Fi, ton Mix du jour, « En boucle » et tes playlists hors ligne sont téléchargés d'avance.")
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
                HStack {
                    Text("Version du serveur")
                    Spacer()
                    Text(serverVersion ?? "…")
                        .font(Typo.mono)
                        .foregroundStyle(Tone.secondary)
                }
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
        .onAppear {
            scrobble = auth.account?.scrobbleToLastfm ?? true
            shareListening = auth.account?.shareListening ?? true
        }
        .task { await loadPendingCount() }
        .task {
            let health = try? await APIClient.shared.health()
            serverVersion = health?.version ?? (health == nil ? "injoignable" : "ancienne")
        }
        .task {
            // État d'un import déjà lancé, puis suivi tant qu'il tourne.
            lovedImport = try? await APIClient.shared.lovedImportStatus()
            if lovedImport?.total == 0 && lovedImport?.running == false { lovedImport = nil }
            while lovedImport?.running == true {
                try? await Task.sleep(for: .seconds(2))
                guard !Task.isCancelled else { return }
                lovedImport = try? await APIClient.shared.lovedImportStatus()
            }
        }
    }

    private var downloadsSummary: String {
        let count = downloads.items.count
        let titles = count == 1 ? "1 titre" : "\(count) titres"
        return "\(titles) sur l'iPhone · \(downloads.totalBytes.byteLabel)"
    }

    private func lovedSummary(_ status: LovedImportStatus) -> String {
        let added = status.added == 1 ? "1 titre ajouté" : "\(status.added) titres ajoutés"
        var text = "\(added) à ta bibliothèque"
        if status.missing > 0 {
            text += status.missing == 1 ? ", 1 introuvable" : ", \(status.missing) introuvables"
        }
        return text + "."
    }

    private func setSharing(_ value: Bool) async {
        do {
            auth.update(try await APIClient.shared.updateMe(shareListening: value))
        } catch {
            errorMessage = error.localizedDescription
            shareListening = !value
        }
    }

    private func startLovedImport() async {
        do {
            lovedImport = try await APIClient.shared.startLovedImport()
            while lovedImport?.running == true {
                try? await Task.sleep(for: .seconds(2))
                lovedImport = try? await APIClient.shared.lovedImportStatus()
            }
        } catch {
            errorMessage = error.localizedDescription
        }
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
