import SwiftUI

// MARK: - Connecter un appareil (TV…)

/// Autoriser un appareil (la TV, par exemple) à se connecter à ton compte : on saisit le code
/// affiché sur son écran (ou on colle le lien du QR code), on vérifie le nom de l'appareil, puis
/// on autorise — ou on refuse si ce n'est pas toi qui as lancé la connexion.
struct DeviceLinkView: View {
    @State private var input = ""
    @State private var info: DeviceLinkInfo?
    @State private var message: String?
    @State private var isError = false
    @State private var isWorking = false
    @State private var done = false

    var body: some View {
        Form {
            if !done {
                Section {
                    TextField("Code affiché sur l'appareil", text: $input)
                        .textInputAutocapitalization(.characters)
                        .autocorrectionDisabled()
                        .onSubmit { Task { await lookUp() } }
                    Button {
                        Task { await lookUp() }
                    } label: {
                        HStack { Text("Continuer"); Spacer(); if isWorking && info == nil { ProgressView() } }
                    }
                    .disabled(code.isEmpty || isWorking)
                } footer: {
                    Text("Sur la TV, lance la connexion : un code (et un QR code) s'affiche. Tu peux aussi coller ici le lien du QR code.")
                }
            }

            if let info, !done {
                Section {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("« \(info.name) » demande l'accès à ton compte Sona.").font(Typo.headline)
                        Text("Le code affiché sur son écran doit être \(info.userCode). Si ce n'est pas le cas, refuse.")
                            .font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
                    }
                    Button("Autoriser") { Task { await answer(approve: true) } }.disabled(isWorking)
                    Button("Refuser", role: .destructive) { Task { await answer(approve: false) } }.disabled(isWorking)
                }
            }

            if let message {
                Section { Text(message).foregroundStyle(isError ? Tone.danger : Tone.primary) }
            }
        }
        .navigationTitle("Connecter un appareil")
        .navigationBarTitleDisplayMode(.inline)
    }

    /// Le code seul, qu'on ait saisi « AB12 » ou collé « https://…/#/link/AB12 » ou « …?link=AB12 ».
    private var code: String {
        let tokens = input.uppercased().components(separatedBy: CharacterSet.alphanumerics.inverted).filter { !$0.isEmpty }
        return tokens.last ?? ""
    }

    private func lookUp() async {
        guard !code.isEmpty else { return }
        isWorking = true
        message = nil
        defer { isWorking = false }
        do {
            info = try await APIClient.shared.deviceLinkInfo(code: code)
        } catch {
            info = nil
            isError = true
            message = error.localizedDescription
        }
    }

    private func answer(approve: Bool) async {
        guard let info else { return }
        isWorking = true
        defer { isWorking = false }
        do {
            try await APIClient.shared.answerDeviceLink(code: info.userCode, approve: approve)
            done = true
            isError = false
            message = approve ? "\(info.name) est connecté à ton compte." : "Connexion refusée."
        } catch {
            isError = true
            message = error.localizedDescription
        }
    }
}

// MARK: - Diagnostic de lecture (admin)

/// Ce que le serveur trouve pour un titre et pourquoi il écarte chaque source ; de quoi comprendre
/// un titre qui ne se lance pas, et choisir une source à la main (lien YouTube ou SoundCloud).
struct DiagnoseSheet: View {
    let track: Track
    @Environment(\.dismiss) private var dismiss
    @State private var report: DiagnoseReport?
    @State private var errorMessage: String?
    @State private var isRunning = false
    @State private var url = ""
    @State private var isWorking = false

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Text("« \(track.title) » — \(track.artist)").font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
                }
                if isRunning {
                    Section {
                        HStack(spacing: 10) {
                            ProgressView()
                            Text("Le serveur cherche et télécharge le titre… (jusqu'à une minute)")
                                .font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
                        }
                    }
                }
                if let errorMessage {
                    Section { Text(errorMessage).foregroundStyle(Tone.danger) }
                }
                if let report { content(report) }
            }
            .navigationTitle("Diagnostic de lecture")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("OK") { dismiss() } } }
            .task { await run() }
        }
    }

    @ViewBuilder
    private func content(_ report: DiagnoseReport) -> some View {
        Section {
            HStack {
                Text(report.ready == true ? "Prêt" : "Échec")
                    .font(.system(size: 13, weight: .bold))
                    .padding(.horizontal, 8).padding(.vertical, 3)
                    .background(Capsule().fill(report.ready == true ? Color.green.opacity(0.25) : Tone.danger.opacity(0.25)))
                Text(report.message ?? report.result ?? "").font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
            }
            if let ref = report.track {
                Text(Self.referenceLine(ref))
                    .font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
            }
        }
        if let excluded = report.excluded, excluded > 0 {
            Section {
                Text("\(excluded) source\(excluded > 1 ? "s" : "") écartée\(excluded > 1 ? "s" : "") avec « Mauvaise version ? » pour ce titre.")
                    .font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
                Button("Réautoriser et réessayer") {
                    Task { await act { try await APIClient.shared.unrejectSources(source: track.source, id: track.sourceId) } }
                }.disabled(isWorking)
            }
        }
        if report.tried != nil {
            Section {
                TextField("https://soundcloud.com/… ou https://youtu.be/…", text: $url)
                    .keyboardType(.URL)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                Button("Essayer ce lien") {
                    let link = url.trimmingCharacters(in: .whitespacesAndNewlines)
                    guard !link.isEmpty else { return }
                    Task { await act { try await APIClient.shared.useSource(source: track.source, id: track.sourceId, url: link) } }
                }.disabled(isWorking || url.trimmingCharacters(in: .whitespaces).isEmpty)
            } header: {
                Text("Choisir une source à la main")
            } footer: {
                Text("Aucune bonne version ? Colle un lien : il sera essayé en premier, et comparé à l'extrait officiel avant d'être accepté.")
            }
            candidates("Sources essayées", report.tried ?? [], empty: "Aucun résultat n'a passé le tri ci-dessous") { c in
                "\(c.artist ?? "?") — \(c.outcome ?? "?")"
            }
            candidates("Résultats des recherches", report.found ?? [], empty: "YouTube et SoundCloud n'ont rien renvoyé") { c in
                "\(c.artist ?? "?") — " + (c.rejected.map { "écarté : \($0)" } ?? "acceptable")
            }
        }
    }

    private func candidates(
        _ title: String, _ list: [DiagnoseReport.Candidate], empty: String,
        detail: @escaping (DiagnoseReport.Candidate) -> String
    ) -> some View {
        Section(title) {
            if list.isEmpty {
                Text(empty).font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
            }
            ForEach(list) { c in
                VStack(alignment: .leading, spacing: 2) {
                    Text(Self.candidateLine(c))
                        .font(Typo.rowTitle)
                    Text(detail(c)).font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
                }
            }
        }
    }

    private static func duration(_ seconds: Int) -> String { String(format: "%d:%02d", seconds / 60, seconds % 60) }

    // Phrases construites pas à pas : une seule grosse expression de `+` fait expirer le compilateur.
    private static func referenceLine(_ ref: DiagnoseReport.Reference) -> String {
        var parts: [String] = ["Référence : " + (ref.title ?? "?") + " — " + (ref.artist ?? "?")]
        if let album = ref.album { parts.append(album) }
        if let seconds = ref.durationSeconds { parts.append(duration(seconds)) }
        return parts.joined(separator: " · ")
    }

    private static func candidateLine(_ c: DiagnoseReport.Candidate) -> String {
        var parts: [String] = [c.title ?? "?", c.platform ?? "?"]
        if let seconds = c.durationSeconds { parts.append(duration(seconds)) }
        if let score = c.score { parts.append("score " + String(Int(score))) }
        return parts.joined(separator: " · ")
    }

    private func run() async {
        isRunning = true
        errorMessage = nil
        defer { isRunning = false }
        do { report = try await APIClient.shared.diagnose(source: track.source, id: track.sourceId) }
        catch { errorMessage = error.localizedDescription }
    }

    private func act(_ work: () async throws -> Void) async {
        isWorking = true
        defer { isWorking = false }
        do {
            try await work()
            await run()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
