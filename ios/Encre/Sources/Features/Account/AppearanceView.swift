import SwiftUI

/// Réglages › Apparence : couleur d'accent et teinte des pochettes, comme dans
/// Sona sur le web et sur PC. Tout est gardé sur l'iPhone.
enum LookAccent: String, CaseIterable, Identifiable {
    case neutre, ciel, menthe, rose, ambre, violet

    var id: String { rawValue }

    var label: String {
        switch self {
        case .neutre: "Neutre"
        case .ciel: "Ciel"
        case .menthe: "Menthe"
        case .rose: "Rose"
        case .ambre: "Ambre"
        case .violet: "Violet"
        }
    }

    /// `nil` : la couleur par défaut de l'app (blanc).
    var color: Color? {
        switch self {
        case .neutre: nil
        case .ciel: Color(hex: 0x8CC8FF)
        case .menthe: Color(hex: 0x7EE0B0)
        case .rose: Color(hex: 0xFF9BB8)
        case .ambre: Color(hex: 0xFFC46B)
        case .violet: Color(hex: 0xB9A4FF)
        }
    }
}

enum Look {
    static let accentKey = "sona.look.accent"
    static let tintKey = "sona.look.tint"
    static let immersiveKey = "sona.look.immersive"
    static let gtaKey = "sona.look.gtavi"
    static let archiveKey = "sona.look.archive"

    static var tintEnabled: Bool {
        UserDefaults.standard.object(forKey: tintKey) as? Bool ?? true
    }
}

struct AppearanceView: View {
    @AppStorage(Look.accentKey) private var accent = LookAccent.neutre.rawValue
    @AppStorage(Look.tintKey) private var tint = true
    @AppStorage(Look.immersiveKey) private var immersive = true
    @AppStorage(Look.gtaKey) private var gta = true
    @AppStorage(Look.archiveKey) private var archive = true

    var body: some View {
        Form {
            Section {
                Toggle("Thème GTA VI", isOn: $gta)
            } footer: {
                Text("Sur la page de Grand Theft Auto VI, et dès qu'un titre de l'album joue, Sona devient Vice City : ciel violet, soleil rayé, rose néon.")
            }
            Section {
                Toggle("Thème archive", isOn: $archive)
            } footer: {
                Text("Quand un titre d'un artiste à identités (FEMTOGO…) joue, Sona prend l'esprit archive : monospace, noir, pochettes en noir et blanc et un seul accent doré.")
            }
            Section {
                Toggle("Teinte de la pochette", isOn: $tint)
            } footer: {
                Text("Les pages d'album, d'artiste et le lecteur plein écran prennent la couleur de la pochette. Désactivée : fond noir uni.")
            }
            Section {
                Toggle("Lecteur immersif", isOn: $immersive)
            } footer: {
                Text("La pochette occupe toute la largeur du lecteur, sous la barre d'état. Désactivé : pochette centrée.")
            }
            Section {
                ForEach(LookAccent.allCases) { option in
                    Button {
                        accent = option.rawValue
                    } label: {
                        HStack(spacing: 12) {
                            Circle()
                                .fill(option.color ?? Color.white)
                                .frame(width: 22, height: 22)
                                .overlay(Circle().strokeBorder(Color.white.opacity(0.25), lineWidth: 1))
                            Text(option.label).foregroundStyle(Tone.primary)
                            Spacer()
                            if accent == option.rawValue { Image(systemName: "checkmark").foregroundStyle(Tone.primary) }
                        }
                    }
                }
            } header: {
                Text("Couleur d'accent")
            } footer: {
                Text("Interrupteurs, boutons et liens de l'app.")
            }
        }
        .navigationTitle("Apparence")
        .navigationBarTitleDisplayMode(.inline)
        .onChange(of: gta) { _, _ in GtaTheme.shared.refresh() }
        .onChange(of: archive) { _, _ in ArchiveTheme.shared.refresh() }
    }
}
