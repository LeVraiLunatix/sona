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

    static var tintEnabled: Bool {
        UserDefaults.standard.object(forKey: tintKey) as? Bool ?? true
    }
}

struct AppearanceView: View {
    @AppStorage(Look.accentKey) private var accent = LookAccent.neutre.rawValue
    @AppStorage(Look.tintKey) private var tint = true

    var body: some View {
        Form {
            Section {
                Toggle("Teinte de la pochette", isOn: $tint)
            } footer: {
                Text("Les pages d'album et le lecteur plein écran prennent la couleur de la pochette. Désactivée : fond noir uni.")
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
    }
}
