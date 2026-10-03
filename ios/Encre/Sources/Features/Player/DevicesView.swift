import SwiftUI

/// « Appareils » : tes PC (et autres appareils Sona) enregistrés sur le
/// compte. Ajoutés une fois, ils restent dans la liste même éteints ;
/// allumés, un appui suffit pour les piloter — d'où que tu sois, via Sona
/// Connect (sans QR code ni Wi-Fi commun).
struct DevicesView: View {
    /// Appareil choisi : le lecteur devient sa télécommande.
    var onControl: () -> Void
    @ObservedObject private var connect = ConnectManager.shared
    @Environment(\.dismiss) private var dismiss
    @State private var error: String?
    @State private var forgetting: SavedDevice?

    var body: some View {
        NavigationStack {
            List {
                Section {
                    if connect.saved.isEmpty {
                        Text("Aucun appareil enregistré pour l'instant.")
                            .font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
                    }
                    ForEach(connect.saved) { saved in
                        let live = liveDevice(saved.id)
                        Button {
                            pick(live, name: saved.name)
                        } label: {
                            row(name: live?.name ?? saved.name, kind: saved.kind, live: live, seen: saved.seenSeconds)
                        }
                        .swipeActions {
                            Button("Oublier", role: .destructive) { forgetting = saved }
                        }
                        .contextMenu {
                            Button("Oublier", systemImage: "trash", role: .destructive) { forgetting = saved }
                        }
                    }
                } header: {
                    Text("Mes appareils")
                } footer: {
                    if !connect.saved.isEmpty {
                        Text("Touche un appareil allumé pour le piloter. Glisse vers la gauche pour l'oublier.")
                    }
                }

                let others = connect.devices.filter { device in
                    !device.isMe && !connect.saved.contains { $0.id == device.id }
                }
                if !others.isEmpty {
                    Section("Allumés en ce moment") {
                        ForEach(others) { device in
                            HStack {
                                Button {
                                    pick(device, name: device.name)
                                } label: {
                                    row(name: device.name, kind: device.kind, live: device, seen: nil)
                                }
                                Button {
                                    Task { await save(device) }
                                } label: {
                                    Label("Ajouter", systemImage: "plus")
                                        .font(Typo.caption).foregroundStyle(.black)
                                        .padding(.horizontal, 12).frame(height: 30)
                                        .background(Capsule().fill(.white))
                                }
                                .buttonStyle(.borderless)
                            }
                        }
                    }
                }

                Section {
                    Label {
                        Text("Ouvre **Sona pour Windows** sur ton PC, connecté avec ce compte : il apparaît ici. Touche **Ajouter** pour le garder.")
                            .font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
                    } icon: {
                        Image(systemName: "laptopcomputer").foregroundStyle(Color.accentColor)
                    }
                }
            }
            .navigationTitle("Appareils")
            .navigationBarTitleDisplayMode(.large)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("OK") { dismiss() } } }
            .refreshable {
                await connect.refreshSaved()
                await connect.sync()
            }
            .task {
                await connect.refreshSaved()
                await connect.sync()
            }
            .alert("Appareils", isPresented: Binding(get: { error != nil }, set: { if !$0 { error = nil } })) {
                Button("OK", role: .cancel) {}
            } message: {
                Text(error ?? "")
            }
            .confirmationDialog(
                "Oublier \(forgetting?.name ?? "cet appareil") ?",
                isPresented: Binding(get: { forgetting != nil }, set: { if !$0 { forgetting = nil } }),
                titleVisibility: .visible
            ) {
                Button("Oublier", role: .destructive) {
                    if let id = forgetting?.id { Task { await connect.forget(id) } }
                }
            } message: {
                Text("Tu pourras l'ajouter de nouveau quand il sera allumé.")
            }
        }
    }

    /// L'appareil enregistré, s'il est allumé en ce moment.
    private func liveDevice(_ id: String) -> ConnectDevice? {
        connect.devices.first { $0.id == id && !$0.isMe }
    }

    private func pick(_ device: ConnectDevice?, name: String) {
        guard let device else {
            error = "\(name) est éteint : ouvre Sona dessus pour le piloter."
            return
        }
        connect.control(device)
        dismiss()
        onControl()
    }

    private func save(_ device: ConnectDevice) async {
        do {
            try await connect.save(device)
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func row(name: String, kind: String, live: ConnectDevice?, seen: Double?) -> some View {
        let chosen = live != nil && connect.controlId == live?.id
        let now = live.map { connect.now(on: $0) }
        return HStack(spacing: 14) {
            Image(systemName: kind == "iphone" ? "iphone" : "laptopcomputer")
                .font(.system(size: 19, weight: .semibold))
                .foregroundStyle(chosen ? .white : live == nil ? Tone.tertiary : Tone.secondary)
                .frame(width: 42, height: 42)
                .background(RoundedRectangle(cornerRadius: 11, style: .continuous)
                    .fill(chosen ? Color.accentColor : Tone.surfaceStrong))
            VStack(alignment: .leading, spacing: 2) {
                Text(name).font(Typo.rowTitle).foregroundStyle(live == nil ? Tone.secondary : Tone.primary).lineLimit(1)
                if let now, let track = now.track, !now.paused {
                    HStack(spacing: 6) {
                        EqualizerBars(isAnimating: true).frame(width: 12, height: 10)
                        Text(track.title).lineLimit(1)
                    }
                    .font(Typo.caption).foregroundStyle(Color.accentColor)
                } else {
                    Text(status(now: now, online: live != nil, seen: seen))
                        .font(Typo.caption).foregroundStyle(Tone.secondary).lineLimit(1)
                }
            }
            Spacer(minLength: 4)
            if chosen {
                Label("Piloté", systemImage: "checkmark").font(Typo.caption).foregroundStyle(Color.accentColor)
            } else if live != nil {
                Text("Piloter").font(Typo.caption).foregroundStyle(Color.accentColor)
            }
        }
        .contentShape(Rectangle())
    }

    private func status(now: ConnectManager.RemoteNow?, online: Bool, seen: Double?) -> String {
        guard online else {
            guard let seen else { return "Éteint" }
            let date = Date().addingTimeInterval(-seen)
            return "Éteint · vu \(date.formatted(.relative(presentation: .named)))"
        }
        if let track = now?.track { return "En pause · \(track.title)" }
        return "Allumé · rien en lecture"
    }
}
