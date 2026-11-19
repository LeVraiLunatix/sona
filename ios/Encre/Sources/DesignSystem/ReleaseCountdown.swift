import SwiftUI

/// Dates de sortie des albums annoncés : lecture de l'instant donné par le
/// serveur (minuit à Paris) et libellés.
enum ReleaseClock {
    static func parse(_ iso: String) -> Date? {
        ISO8601DateFormatter().date(from: iso)
    }

    private static let dayFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "fr_FR")
        formatter.timeZone = TimeZone(identifier: "Europe/Paris")
        formatter.dateFormat = "EEEE d MMMM"
        return formatter
    }()

    private static let shortFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "fr_FR")
        formatter.timeZone = TimeZone(identifier: "Europe/Paris")
        formatter.dateFormat = "d MMM"
        return formatter
    }()

    /// « Vendredi 5 décembre ».
    static func dayLabel(_ date: Date) -> String {
        dayFormatter.string(from: date).capitalized(with: Locale(identifier: "fr_FR"))
    }

    /// « 5 déc. » (pour un titre pas encore sorti, à partir de `releaseDate`).
    static func shortLabel(isoDay: String?) -> String? {
        guard let isoDay, isoDay.count >= 10 else { return nil }
        let parser = DateFormatter()
        parser.locale = Locale(identifier: "en_US_POSIX")
        parser.timeZone = TimeZone(identifier: "Europe/Paris")
        parser.dateFormat = "yyyy-MM-dd"
        return parser.date(from: String(isoDay.prefix(10))).map { shortFormatter.string(from: $0) }
    }
}

/// Compte à rebours en quatre tuiles (jours, heures, minutes, secondes) jusqu'à
/// la sortie. `onReached` part une fois l'heure atteinte (la page se recharge).
struct CountdownTiles: View {
    let target: Date
    var onReached: () -> Void = {}

    var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { context in
            let left = max(0, Int(target.timeIntervalSince(context.date).rounded(.up)))
            HStack(spacing: 10) {
                tile(left / 86_400, "jours")
                tile(left % 86_400 / 3_600, "heures")
                tile(left % 3_600 / 60, "minutes")
                tile(left % 60, "secondes")
            }
            .animation(.snappy, value: left)
            .onChange(of: left == 0) { _, reached in
                if reached { onReached() }
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(Self.spoken(left))
        }
    }

    private func tile(_ value: Int, _ label: String) -> some View {
        VStack(spacing: 4) {
            Text(String(format: "%02d", value))
                .font(.system(size: 30, weight: .bold, design: .rounded))
                .monospacedDigit()
                .contentTransition(.numericText(countsDown: true))
                .foregroundStyle(Tone.primary)
            Text(label)
                .font(.system(size: 11, weight: .semibold))
                .textCase(.uppercase)
                .foregroundStyle(Tone.secondary)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 12)
        .glassRounded(18)
    }

    private static func spoken(_ seconds: Int) -> String {
        let days = seconds / 86_400, hours = seconds % 86_400 / 3_600, minutes = seconds % 3_600 / 60
        return "Sortie dans \(days) jour\(days > 1 ? "s" : ""), \(hours) heure\(hours > 1 ? "s" : ""), \(minutes) minute\(minutes > 1 ? "s" : "")"
    }
}

/// Pastille compacte : « J-12 » à plus d'un jour, sinon « 03:22:10 » qui défile.
struct CountdownChip: View {
    let target: Date

    var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { context in
            let left = max(0, Int(target.timeIntervalSince(context.date).rounded(.up)))
            let days = left / 86_400
            HStack(spacing: 5) {
                Image(systemName: "clock")
                    .font(.system(size: 11, weight: .bold))
                Text(days >= 1
                     ? "J-\(days)"
                     : String(format: "%02d:%02d:%02d", left / 3_600, left % 3_600 / 60, left % 60))
                    .font(.system(size: 13, weight: .bold, design: .rounded))
                    .monospacedDigit()
                    .contentTransition(.numericText(countsDown: true))
            }
            .foregroundStyle(Tone.primary)
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(Capsule(style: .continuous).fill(Color.white.opacity(0.14)))
            .animation(.snappy, value: left)
        }
    }
}
