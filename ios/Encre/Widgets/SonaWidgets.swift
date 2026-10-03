import ActivityKit
import AppIntents
import SwiftUI
import WidgetKit

/// Widgets de Sona : raccourcis (écran d'accueil), accès rapide (écran
/// verrouillé), Live Activities de l'écoute ensemble et des paroles.
///
/// Les widgets n'affichent pas le titre en cours : il faudrait partager des
/// données avec l'app (« App Group »), ce que l'installation sans compte
/// développeur ne permet pas. La Live Activity, elle, reçoit ses données
/// directement de l'app.
@main
struct SonaWidgetBundle: WidgetBundle {
    var body: some Widget {
        ShortcutsWidget()
        RemotePCWidget()
        LockScreenWidget()
        RemoteToggleControl()
        RemoteNextControl()
        PartyLiveActivity()
        LyricsLiveActivity()
    }
}

// MARK: - Logo

/// Le « S » en barres de forme d'onde (même géométrie que l'icône).
struct LogoShape: Shape {
    func path(in rect: CGRect) -> Path {
        let side = min(rect.width, rect.height)
        let width = SonaLogoGeometry.barWidth * side
        var path = Path()
        for bar in SonaLogoGeometry.bars {
            let frame = CGRect(
                x: rect.minX + bar.x * side - width / 2, y: rect.minY + bar.top * side,
                width: width, height: max(width, (bar.bottom - bar.top) * side)
            )
            path.addRoundedRect(in: frame, cornerSize: CGSize(width: width / 2, height: width / 2))
        }
        return path
    }
}

// MARK: - Raccourcis

private struct StaticEntry: TimelineEntry {
    let date: Date
}

private struct StaticProvider: TimelineProvider {
    func placeholder(in context: Context) -> StaticEntry { StaticEntry(date: .now) }
    func getSnapshot(in context: Context, completion: @escaping (StaticEntry) -> Void) { completion(StaticEntry(date: .now)) }
    func getTimeline(in context: Context, completion: @escaping (Timeline<StaticEntry>) -> Void) {
        // Change de jour à minuit : « défi du jour » toujours d'actualité.
        let midnight = Calendar.current.startOfDay(for: .now.addingTimeInterval(86_400))
        completion(Timeline(entries: [StaticEntry(date: .now)], policy: .after(midnight)))
    }
}

private let sonaGradient = LinearGradient(
    colors: [Color(red: 0.45, green: 0.2, blue: 0.95), Color(red: 0.12, green: 0.05, blue: 0.3)],
    startPoint: .topLeading, endPoint: .bottomTrailing
)

struct ShortcutsWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "sona.shortcuts", provider: StaticProvider()) { _ in
            ShortcutsView()
                .containerBackground(for: .widget) { sonaGradient }
        }
        .configurationDisplayName("Raccourcis Sona")
        .description("Le blind test du jour, ton récap, l'écoute ensemble et la radio DJ en un geste.")
        .supportedFamilies([.systemSmall, .systemMedium])
    }
}

private struct ShortcutsView: View {
    @Environment(\.widgetFamily) private var family

    var body: some View {
        if family == .systemSmall {
            VStack(alignment: .leading, spacing: 6) {
                LogoShape().fill(.white).frame(width: 34, height: 34)
                Spacer(minLength: 0)
                Text("Défi du jour").font(.system(size: 15, weight: .bold)).foregroundStyle(.white)
                Text("Blind test · classement entre amis")
                    .font(.system(size: 11, weight: .medium)).foregroundStyle(.white.opacity(0.75)).lineLimit(2)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .widgetURL(URL(string: "encre://blindtest"))
        } else {
            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 8) {
                    LogoShape().fill(.white).frame(width: 22, height: 22)
                    Text("Sona").font(.system(size: 16, weight: .heavy)).foregroundStyle(.white)
                }
                HStack(spacing: 8) {
                    shortcut("Blind test", "waveform.badge.magnifyingglass", "encre://blindtest")
                    shortcut("Radio DJ", "dial.medium", "encre://djradio")
                    shortcut("Ensemble", "person.2.wave.2.fill", "encre://party")
                    shortcut("Récap", "sparkles", "encre://recap")
                }
            }
        }
    }

    private func shortcut(_ title: String, _ icon: String, _ url: String) -> some View {
        Link(destination: URL(string: url)!) {
            VStack(spacing: 6) {
                Image(systemName: icon).font(.system(size: 20, weight: .semibold))
                Text(title).font(.system(size: 11, weight: .semibold)).lineLimit(1).minimumScaleFactor(0.8)
            }
            .foregroundStyle(.white)
            .frame(maxWidth: .infinity, minHeight: 64)
            .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(.white.opacity(0.15)))
        }
    }
}

// MARK: - Mon PC (Sona Connect)

/// Lecture/pause, précédent et suivant sur le PC piloté, sans ouvrir l'app.
/// Le widget ne connaît pas le titre en cours (voir plus haut) : juste les
/// commandes, exécutées par l'app.
struct RemotePCWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "sona.remote", provider: StaticProvider()) { _ in
            RemotePCView()
                .containerBackground(for: .widget) { sonaGradient }
        }
        .configurationDisplayName("Mon PC")
        .description("Lecture, pause, suivant et précédent sur le PC piloté dans « Appareils ».")
        .supportedFamilies([.systemSmall, .systemMedium])
    }
}

private struct RemotePCView: View {
    @Environment(\.widgetFamily) private var family

    var body: some View {
        VStack(alignment: .leading, spacing: family == .systemSmall ? 8 : 12) {
            HStack(spacing: 8) {
                Image(systemName: "laptopcomputer").font(.system(size: 15, weight: .semibold))
                Text("Mon PC").font(.system(size: 15, weight: .heavy))
                Spacer(minLength: 0)
                LogoShape().fill(.white.opacity(0.8)).frame(width: 16, height: 16)
            }
            .foregroundStyle(.white)
            Spacer(minLength: 0)
            HStack(spacing: family == .systemSmall ? 6 : 10) {
                button("backward.fill", "previous", size: 17)
                button("playpause.fill", "toggle", size: 22)
                button("forward.fill", "next", size: 17)
            }
        }
        .widgetURL(URL(string: "encre://devices"))
    }

    private func button(_ icon: String, _ command: String, size: CGFloat) -> some View {
        Button(intent: PCRemoteButtonIntent(command)) {
            Image(systemName: icon)
                .font(.system(size: size, weight: .bold))
                .foregroundStyle(.white)
                .frame(maxWidth: .infinity, minHeight: family == .systemSmall ? 46 : 56)
                .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(.white.opacity(0.16)))
        }
        .buttonStyle(.plain)
    }
}

/// Centre de contrôle (et bouton Action) : lecture/pause sur le PC piloté.
struct RemoteToggleControl: ControlWidget {
    var body: some ControlWidgetConfiguration {
        StaticControlConfiguration(kind: "sona.control.pc.toggle") {
            ControlWidgetButton(action: PCRemoteButtonIntent("toggle")) {
                Label("Lecture/pause sur mon PC", systemImage: "playpause.fill")
            }
        }
        .displayName("Lecture/pause sur mon PC")
        .description("Sona Connect : le PC choisi dans « Appareils ».")
    }
}

/// Centre de contrôle : titre suivant sur le PC piloté.
struct RemoteNextControl: ControlWidget {
    var body: some ControlWidgetConfiguration {
        StaticControlConfiguration(kind: "sona.control.pc.next") {
            ControlWidgetButton(action: PCRemoteButtonIntent("next")) {
                Label("Suivant sur mon PC", systemImage: "forward.fill")
            }
        }
        .displayName("Suivant sur mon PC")
        .description("Sona Connect : le PC choisi dans « Appareils ».")
    }
}

// MARK: - Écran verrouillé

struct LockScreenWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: "sona.lockscreen", provider: StaticProvider()) { _ in
            LockScreenView()
                .containerBackground(for: .widget) { Color.clear }
        }
        .configurationDisplayName("Sona")
        .description("Ouvre Sona ou le défi du jour depuis l'écran verrouillé.")
        .supportedFamilies([.accessoryCircular, .accessoryRectangular])
    }
}

private struct LockScreenView: View {
    @Environment(\.widgetFamily) private var family

    var body: some View {
        if family == .accessoryCircular {
            ZStack {
                AccessoryWidgetBackground()
                LogoShape().fill(.white).padding(10)
            }
            .widgetURL(URL(string: "encre://player"))
        } else {
            HStack(spacing: 8) {
                LogoShape().fill(.white).frame(width: 26, height: 26)
                VStack(alignment: .leading, spacing: 1) {
                    Text("Défi du jour").font(.system(size: 14, weight: .bold))
                    Text("Blind test Sona").font(.system(size: 12)).opacity(0.8)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .widgetURL(URL(string: "encre://blindtest"))
        }
    }
}

// MARK: - Live Activity : écoute ensemble

struct PartyLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: PartyActivityAttributes.self) { context in
            PartyLockScreenView(context: context)
                .activityBackgroundTint(Color(red: 0.12, green: 0.05, blue: 0.3))
                .activitySystemActionForegroundColor(.white)
                .widgetURL(URL(string: "encre://party"))
        } dynamicIsland: { context in
            DynamicIsland {
                DynamicIslandExpandedRegion(.leading) {
                    Label("\(context.state.listeners)", systemImage: "person.2.fill")
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundStyle(.white)
                }
                DynamicIslandExpandedRegion(.trailing) {
                    Text(context.attributes.code)
                        .font(.system(size: 14, weight: .heavy, design: .rounded))
                        .foregroundStyle(.white.opacity(0.8))
                }
                DynamicIslandExpandedRegion(.center) {
                    VStack(spacing: 2) {
                        Text(context.state.title ?? "En attente d'un titre").font(.system(size: 15, weight: .bold)).lineLimit(1)
                        if let artist = context.state.artist {
                            Text(artist).font(.system(size: 13)).foregroundStyle(.secondary).lineLimit(1)
                        }
                    }
                }
                DynamicIslandExpandedRegion(.bottom) {
                    PartyProgress(state: context.state)
                }
            } compactLeading: {
                Image(systemName: context.state.paused ? "pause.fill" : "person.2.wave.2.fill")
                    .foregroundStyle(Color(red: 0.7, green: 0.55, blue: 1))
            } compactTrailing: {
                if let reaction = context.state.lastReaction {
                    Text(reaction)
                } else {
                    Text("\(context.state.listeners)").font(.system(size: 14, weight: .bold))
                }
            } minimal: {
                Image(systemName: "person.2.wave.2.fill").foregroundStyle(Color(red: 0.7, green: 0.55, blue: 1))
            }
            .widgetURL(URL(string: "encre://party"))
        }
    }
}

private struct PartyLockScreenView: View {
    let context: ActivityViewContext<PartyActivityAttributes>

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                LogoShape().fill(.white).frame(width: 20, height: 20)
                Text(context.attributes.isHost ? "Ta session d'écoute" : "Avec \(context.attributes.hostName)")
                    .font(.system(size: 13, weight: .semibold)).foregroundStyle(.white.opacity(0.8))
                Spacer()
                Label("\(context.state.listeners)", systemImage: "person.2.fill")
                    .font(.system(size: 13, weight: .semibold)).foregroundStyle(.white.opacity(0.8))
                if let reaction = context.state.lastReaction {
                    Text(reaction).font(.system(size: 18))
                }
            }
            VStack(alignment: .leading, spacing: 2) {
                Text(context.state.title ?? "En attente d'un titre")
                    .font(.system(size: 17, weight: .bold)).foregroundStyle(.white).lineLimit(1)
                if let artist = context.state.artist {
                    Text(artist).font(.system(size: 14)).foregroundStyle(.white.opacity(0.75)).lineLimit(1)
                }
            }
            PartyProgress(state: context.state)
        }
        .padding(16)
    }
}

private struct PartyProgress: View {
    let state: PartyActivityAttributes.ContentState

    var body: some View {
        if let start = state.startedAt, let duration = state.duration, duration > 0, !state.paused,
           start.addingTimeInterval(duration) > .now {
            ProgressView(timerInterval: start...start.addingTimeInterval(duration), countsDown: false) {
                EmptyView()
            } currentValueLabel: {
                EmptyView()
            }
            .tint(.white)
        } else if state.paused {
            Label("En pause", systemImage: "pause.fill").font(.system(size: 12, weight: .semibold)).foregroundStyle(.white.opacity(0.7))
        }
    }
}

// MARK: - Live Activity : paroles

private let lyricsAccent = Color(red: 0.7, green: 0.55, blue: 1)

struct LyricsLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: LyricsActivityAttributes.self) { context in
            LyricsLockScreenView(state: context.state)
                .activityBackgroundTint(Color(red: 0.08, green: 0.04, blue: 0.2))
                .activitySystemActionForegroundColor(.white)
                .widgetURL(URL(string: "encre://player"))
        } dynamicIsland: { context in
            DynamicIsland {
                DynamicIslandExpandedRegion(.leading) {
                    LogoShape().fill(lyricsAccent).frame(width: 22, height: 22).padding(.leading, 4)
                }
                DynamicIslandExpandedRegion(.trailing) {
                    Image(systemName: context.state.paused ? "pause.fill" : "quote.bubble.fill")
                        .foregroundStyle(lyricsAccent).padding(.trailing, 4)
                }
                DynamicIslandExpandedRegion(.center) {
                    Text("\(context.state.title) · \(context.state.artist)")
                        .font(.system(size: 12, weight: .semibold)).foregroundStyle(.secondary).lineLimit(1)
                }
                DynamicIslandExpandedRegion(.bottom) {
                    VStack(spacing: 4) {
                        Text(context.state.line ?? context.state.title)
                            .font(.system(size: 17, weight: .bold)).foregroundStyle(.white)
                            .multilineTextAlignment(.center).lineLimit(2).minimumScaleFactor(0.8)
                        if let next = context.state.nextLine {
                            Text(next).font(.system(size: 13, weight: .medium)).foregroundStyle(.white.opacity(0.45)).lineLimit(1)
                        }
                    }
                    .frame(maxWidth: .infinity)
                    .contentTransition(.opacity)
                }
            } compactLeading: {
                Image(systemName: "quote.bubble.fill").foregroundStyle(lyricsAccent)
            } compactTrailing: {
                Text(context.state.line ?? context.state.title)
                    .font(.system(size: 12, weight: .semibold)).lineLimit(1)
                    .frame(maxWidth: 110)
            } minimal: {
                Image(systemName: "quote.bubble.fill").foregroundStyle(lyricsAccent)
            }
            .widgetURL(URL(string: "encre://player"))
        }
    }
}

private struct LyricsLockScreenView: View {
    let state: LyricsActivityAttributes.ContentState

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                LogoShape().fill(.white).frame(width: 18, height: 18)
                Text("\(state.title) · \(state.artist)")
                    .font(.system(size: 13, weight: .semibold)).foregroundStyle(.white.opacity(0.75)).lineLimit(1)
                Spacer()
                if state.paused {
                    Image(systemName: "pause.fill").font(.system(size: 12)).foregroundStyle(.white.opacity(0.7))
                }
            }
            VStack(alignment: .leading, spacing: 4) {
                Text(state.line ?? "Paroles indisponibles pour ce titre")
                    .font(.system(size: state.line == nil ? 15 : 21, weight: .heavy))
                    .foregroundStyle(state.line == nil ? .white.opacity(0.6) : .white)
                    .lineLimit(2).minimumScaleFactor(0.75)
                if let next = state.nextLine {
                    Text(next).font(.system(size: 15, weight: .semibold)).foregroundStyle(.white.opacity(0.4)).lineLimit(1)
                }
            }
            .contentTransition(.opacity)
            if let start = state.startedAt, let duration = state.duration, duration > 0, !state.paused,
               start.addingTimeInterval(duration) > .now {
                ProgressView(timerInterval: start...start.addingTimeInterval(duration), countsDown: false) {
                    EmptyView()
                } currentValueLabel: {
                    EmptyView()
                }
                .tint(.white)
            }
        }
        .padding(16)
    }
}
