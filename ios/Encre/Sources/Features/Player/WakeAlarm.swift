import AlarmKit
import AppIntents
import Combine
import SwiftUI

/// Réveil musical : une vraie alarme iOS (AlarmKit — elle sonne même en
/// mode silencieux et sur l'écran verrouillé), avec un bouton « Écouter »
/// qui lance ton mix du jour, le son montant doucement.
struct SonaAlarmMetadata: AlarmMetadata {}

@MainActor
final class WakeAlarm: ObservableObject {
    static let shared = WakeAlarm()

    @Published var enabled = UserDefaults.standard.bool(forKey: "encre.wake.enabled")
    @Published var hour = UserDefaults.standard.object(forKey: "encre.wake.hour") as? Int ?? 7
    @Published var minute = UserDefaults.standard.object(forKey: "encre.wake.minute") as? Int ?? 30
    /// Jours de la semaine (1 = dimanche … 7 = samedi, comme `Calendar`) ; vide : une seule fois.
    @Published var days: Set<Int> = Set(UserDefaults.standard.array(forKey: "encre.wake.days") as? [Int] ?? [2, 3, 4, 5, 6])
    @Published private(set) var message: String?

    private var alarmId: UUID? {
        get { UserDefaults.standard.string(forKey: "encre.wake.id").flatMap(UUID.init) }
        set { UserDefaults.standard.set(newValue?.uuidString, forKey: "encre.wake.id") }
    }

    private init() {}

    /// Enregistre les réglages et (re)programme l'alarme.
    func apply() async {
        let defaults = UserDefaults.standard
        defaults.set(enabled, forKey: "encre.wake.enabled")
        defaults.set(hour, forKey: "encre.wake.hour")
        defaults.set(minute, forKey: "encre.wake.minute")
        defaults.set(Array(days), forKey: "encre.wake.days")
        if let id = alarmId {
            try? AlarmManager.shared.cancel(id: id)
            alarmId = nil
        }
        message = nil
        guard enabled else { return }
        do {
            let state = try await AlarmManager.shared.requestAuthorization()
            guard state == .authorized else {
                message = "Autorise les alarmes pour Sona dans Réglages › Sona."
                enabled = false
                defaults.set(false, forKey: "encre.wake.enabled")
                return
            }
            let id = UUID()
            try await AlarmManager.shared.schedule(id: id, configuration: configuration())
            alarmId = id
        } catch {
            message = "Impossible de programmer le réveil : \(error.localizedDescription)"
        }
    }

    private func configuration() -> AlarmManager.AlarmConfiguration<SonaAlarmMetadata> {
        let weekdays: [Locale.Weekday] = days.sorted().compactMap { Self.weekday($0) }
        let schedule = Alarm.Schedule.relative(.init(
            time: .init(hour: hour, minute: minute),
            repeats: weekdays.isEmpty ? .never : .weekly(weekdays)
        ))
        let alert = AlarmPresentation.Alert(
            title: "Réveil Sona",
            stopButton: AlarmButton(text: "Arrêter", textColor: .white, systemImageName: "stop.circle"),
            secondaryButton: AlarmButton(text: "Écouter", textColor: .white, systemImageName: "play.fill"),
            secondaryButtonBehavior: .custom
        )
        let attributes = AlarmAttributes<SonaAlarmMetadata>(
            presentation: AlarmPresentation(alert: alert), metadata: SonaAlarmMetadata(), tintColor: .pink
        )
        return AlarmManager.AlarmConfiguration<SonaAlarmMetadata>(
            schedule: schedule, attributes: attributes, secondaryIntent: WakeUpMusicIntent()
        )
    }

    private static func weekday(_ value: Int) -> Locale.Weekday? {
        [1: .sunday, 2: .monday, 3: .tuesday, 4: .wednesday, 5: .thursday, 6: .friday, 7: .saturday][value]
    }

    /// « Écouter » : le mix du jour (sinon « En boucle »), le son qui monte
    /// en une minute — sur l'iPhone, même s'il pilotait le PC la veille.
    func startMusic() async {
        ConnectManager.shared.setControl(nil)
        var tracks = (try? await APIClient.shared.mixes())?.first(where: { !$0.tracks.isEmpty })?.tracks ?? []
        var name = "Mix du jour"
        if tracks.isEmpty {
            tracks = (try? await APIClient.shared.smartPlaylist("on_repeat")) ?? []
            name = "En boucle"
        }
        guard let first = tracks.first else { return }
        let target = max(0.3, SystemVolume.current)
        SystemVolume.set(0.1)
        PlayerManager.shared.play(first, context: tracks, name: name)
        for step in 1...20 {
            try? await Task.sleep(for: .seconds(3))
            SystemVolume.set(0.1 + (target - 0.1) * Double(step) / 20)
        }
    }
}

/// Bouton « Écouter » de l'alarme : exécuté par l'app.
struct WakeUpMusicIntent: LiveActivityIntent {
    static let title: LocalizedStringResource = "Écouter le réveil Sona"
    static let isDiscoverable = false

    @MainActor
    func perform() async throws -> some IntentResult {
        Task { await WakeAlarm.shared.startMusic() }
        return .result()
    }
}

/// Réglages du réveil (Réglages › Réveil musical).
struct WakeAlarmView: View {
    @ObservedObject private var alarm = WakeAlarm.shared

    private let dayLabels: [(Int, String)] = [(2, "L"), (3, "M"), (4, "M"), (5, "J"), (6, "V"), (7, "S"), (1, "D")]

    var body: some View {
        Form {
            Section {
                Toggle("Réveil musical", isOn: $alarm.enabled)
                DatePicker("Heure", selection: Binding(
                    get: { Calendar.current.date(from: DateComponents(hour: alarm.hour, minute: alarm.minute)) ?? .now },
                    set: { date in
                        let parts = Calendar.current.dateComponents([.hour, .minute], from: date)
                        alarm.hour = parts.hour ?? 7
                        alarm.minute = parts.minute ?? 30
                    }
                ), displayedComponents: .hourAndMinute)
                HStack(spacing: 6) {
                    ForEach(dayLabels, id: \.0) { day, label in
                        let on = alarm.days.contains(day)
                        Button {
                            if on { alarm.days.remove(day) } else { alarm.days.insert(day) }
                        } label: {
                            Text(label)
                                .font(Typo.rowTitle)
                                .foregroundStyle(on ? .black : Tone.primary)
                                .frame(maxWidth: .infinity, minHeight: 36)
                                .background(Circle().fill(on ? Color.white : Tone.surfaceStrong))
                        }
                        .buttonStyle(.plain)
                    }
                }
            } footer: {
                Text(alarm.days.isEmpty
                     ? "Une seule fois, à la prochaine occurrence de cette heure."
                     : "Une vraie alarme : elle sonne même en mode silencieux. Touche « Écouter » : ton mix du jour démarre, le son monte doucement.")
            }
            if let message = alarm.message {
                Section { Text(message).foregroundStyle(Tone.danger) }
            }
        }
        .navigationTitle("Réveil musical")
        .onChange(of: alarm.enabled) { _, _ in Task { await alarm.apply() } }
        .onChange(of: alarm.hour) { _, _ in Task { await alarm.apply() } }
        .onChange(of: alarm.minute) { _, _ in Task { await alarm.apply() } }
        .onChange(of: alarm.days) { _, _ in Task { await alarm.apply() } }
    }
}
