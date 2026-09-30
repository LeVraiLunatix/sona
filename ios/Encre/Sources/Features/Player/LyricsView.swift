import NaturalLanguage
import SwiftUI
import Translation

/// Paroles du morceau en cours (LRCLIB côté serveur). Synchronisées : la
/// ligne chantée en blanc plein, les autres estompées et floutées d'autant
/// plus qu'elles sont loin — l'effet de profondeur de Musique —, recentrage
/// fluide à chaque changement de ligne, et un tap sur une ligne y ramène la
/// lecture. La ligne en cours s'allume mot par mot (karaoké), et le mode
/// « chante » baisse la voix du titre.
/// Options des paroles partagées avec l'en-tête du lecteur, où sont leurs
/// boutons (« Chante », « Traduire »).
@MainActor
final class LyricsOptions: ObservableObject {
    static let shared = LyricsOptions()
    /// Paroles synchronisées affichées (le mode « chante » a un sens).
    @Published var synced = false
    /// Paroles dans une autre langue que le français.
    @Published var foreign = false
    @Published var translating = false
}

struct LyricsView: View {
    @ObservedObject var player: PlayerManager
    let track: Track
    @ObservedObject private var options = LyricsOptions.shared

    private enum LoadState: Equatable {
        case loading, loaded(Lyrics), unavailable(String)
    }
    @State private var state: LoadState = .loading
    // Traduction en français (sur l'iPhone, hors ligne une fois la langue
    // téléchargée) des paroles dans une autre langue.
    @State private var translations: [String: String] = [:]
    @State private var translationConfig: TranslationSession.Configuration?

    var body: some View {
        Group {
            switch state {
            case .loading:
                ProgressView().tint(.white).frame(maxWidth: .infinity, maxHeight: .infinity)
            case .unavailable(let message):
                EmptyState(systemImage: "quote.bubble", title: "Paroles indisponibles", message: message)
                    .frame(maxHeight: .infinity)
            case .loaded(let lyrics):
                if lyrics.instrumental {
                    EmptyState(systemImage: "pianokeys", title: "Instrumental", message: "Pas de paroles, juste la musique.")
                        .frame(maxHeight: .infinity)
                } else if lyrics.synced {
                    synced(lyrics.lines)
                        .translationTask(translationConfig) { session in
                            await translate(lyrics.lines, with: session)
                        }
                } else {
                    plain(lyrics.lines)
                }
            }
        }
        .task(id: track.id) { await load() }
        // Boutons dans l'en-tête du lecteur (`LyricsHeaderButtons`).
        .onChange(of: options.translating) { _, on in
            if on && translations.isEmpty {
                translationConfig = TranslationSession.Configuration(target: Locale.Language(identifier: "fr"))
            }
        }
        .onChange(of: state) { _, new in
            if case .loaded(let lyrics) = new { options.synced = lyrics.synced && !lyrics.instrumental } else { options.synced = false }
        }
        .onDisappear { options.synced = false }
    }

    /// Marge du lecteur plein écran (voir `FullPlayerView`).
    private static let sideInset: CGFloat = 26

    private func synced(_ lines: [Lyrics.Line]) -> some View {
        // Légère avance : la ligne s'allume quand elle est chantée, pas un
        // demi-temps après (le lecteur ne publie sa position que 2 fois/s).
        let position = player.positionSeconds + 0.35
        let active = lines.lastIndex(where: { ($0.time ?? 0) <= position })
        return ScrollViewReader { proxy in
            ScrollView(showsIndicators: false) {
                VStack(alignment: .leading, spacing: 22) {
                    ForEach(Array(lines.enumerated()), id: \.offset) { index, line in
                        let isActive = index == active
                        // Avant la première ligne (intro, ou lecture pas
                        // encore lancée) : tout net et estompé, rien de flou.
                        let blur = active.map { isActive ? 0 : min(3.5, Double(abs(index - $0)) * 0.9) } ?? 0
                        VStack(alignment: .leading, spacing: 0) {
                            if isActive && !line.text.isEmpty {
                                KaraokeLine(
                                    words: KaraokeLine.timedWords(line, next: lines.dropFirst(index + 1).first?.time),
                                    player: player
                                )
                            } else {
                                Text(line.text.isEmpty ? "♪" : line.text)
                                    .foregroundStyle(Color.white.opacity(index < (active ?? 0) ? 0.3 : 0.45))
                            }
                            if options.translating, let translated = translations[line.text], translated != line.text {
                                Text(translated)
                                    .font(.system(size: 17, weight: .semibold))
                                    .foregroundStyle(Color.white.opacity(isActive ? 0.75 : 0.35))
                                    .padding(.top, 4)
                            }
                        }
                            .font(.system(size: 28, weight: .bold))
                            .blur(radius: blur)
                            .scaleEffect(isActive ? 1 : 0.97, anchor: .leading)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .contentShape(Rectangle())
                            .onTapGesture {
                                if let time = line.time { player.seek(toSeconds: time) }
                            }
                            .id(index)
                    }
                }
                .padding(.vertical, 120)
                // La marge est à l'intérieur de la zone qui défile : le flou
                // des lignes déborde dans la marge au lieu d'être coupé net
                // au bord (la zone s'étend jusqu'aux bords de l'écran).
                .padding(.horizontal, Self.sideInset)
                .animation(Motion.smooth, value: active)
            }
            .padding(.horizontal, -Self.sideInset)
            .mask { EdgeFade() }
            .onAppear {
                if let active { proxy.scrollTo(active, anchor: UnitPoint(x: 0.5, y: 0.35)) }
            }
            .onChange(of: active) { _, newValue in
                guard let newValue else { return }
                withAnimation(Motion.smooth) { proxy.scrollTo(newValue, anchor: UnitPoint(x: 0.5, y: 0.35)) }
            }
        }
    }

    private func translate(_ lines: [Lyrics.Line], with session: TranslationSession) async {
        let texts = Array(Set(lines.map(\.text).filter { !$0.isEmpty }))
        let requests = texts.enumerated().map { index, text in
            TranslationSession.Request(sourceText: text, clientIdentifier: "\(index)")
        }
        guard let responses = try? await session.translations(from: requests) else { return }
        var result: [String: String] = [:]
        for response in responses {
            if let id = response.clientIdentifier.flatMap(Int.init), texts.indices.contains(id) {
                result[texts[id]] = response.targetText
            }
        }
        withAnimation(Motion.smooth) { translations = result }
    }

    private func plain(_ lines: [Lyrics.Line]) -> some View {
        ScrollView(showsIndicators: false) {
            Text(lines.map(\.text).joined(separator: "\n"))
                .font(.system(size: 22, weight: .semibold))
                .lineSpacing(8)
                .foregroundStyle(Tone.primary)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.vertical, 30)
        }
        .mask { EdgeFade() }
    }

    private func load() async {
        state = .loading
        do {
            if let lyrics = try await APIClient.shared.lyrics(for: track) {
                translations = [:]
                options.translating = false
                translationConfig = nil
                let recognizer = NLLanguageRecognizer()
                recognizer.processString(lyrics.lines.map(\.text).joined(separator: "\n"))
                options.foreign = recognizer.dominantLanguage.map { $0 != .french } ?? false
                state = .loaded(lyrics)
            } else {
                state = .unavailable("Pas de paroles connues pour ce morceau.")
            }
        } catch {
            guard !Task.isCancelled else { return }
            state = .unavailable("Les paroles n'ont pas pu être chargées.")
        }
    }
}

/// « Traduire » et « Chante », en ronds dans l'en-tête du lecteur quand
/// les paroles sont affichées (à côté du titre, sans cacher le texte).
struct LyricsHeaderButtons: View {
    @ObservedObject var player: PlayerManager
    @ObservedObject private var options = LyricsOptions.shared

    var body: some View {
        HStack(spacing: 10) {
            if options.foreign {
                circle("character.bubble", on: options.translating, label: "Traduire") {
                    options.translating.toggle()
                }
            }
            if options.synced {
                SingButton(player: player)
                    .transition(.scale.combined(with: .opacity))
            }
        }
        .animation(Motion.smooth, value: options.synced)
        .animation(Motion.smooth, value: options.foreign)
    }

    private func circle(_ icon: String, on: Bool, label: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: icon)
                .font(.system(size: 16, weight: .semibold))
                .foregroundStyle(on ? .black : .white)
                .contentTransition(.symbolEffect(.replace))
                .frame(width: 38, height: 38)
                .background(Circle().fill(on ? Color.white : Color.white.opacity(0.15)))
        }
        .buttonStyle(.pressable(scale: 0.88))
        .accessibilityLabel(label)
        .transition(.scale.combined(with: .opacity))
    }
}

/// Bouton « Chante » : un appui active ou coupe le mode chant ; un appui
/// long (ou un glissé vertical) ouvre le curseur « Voix », qu'on règle
/// dans la foulée sans lever le doigt — comme le volume dans le Centre de
/// contrôle.
struct SingButton: View {
    @ObservedObject var player: PlayerManager
    @State private var showsSlider = false
    @State private var pressing = false
    @State private var dragged = false
    @State private var dragStart: Double?
    @State private var longPressTask: Task<Void, Never>?
    @State private var hideTask: Task<Void, Never>?

    /// Valeur montrée : 100 % quand le mode chant est coupé (titre normal).
    private var shownLevel: Double { player.singAlong ? player.vocalLevel : 1 }

    var body: some View {
        Image(systemName: player.singAlong ? "mic.fill" : "mic")
            .font(.system(size: 16, weight: .semibold))
            .foregroundStyle(player.singAlong ? .black : .white)
            .contentTransition(.symbolEffect(.replace))
            .symbolEffect(.pulse, isActive: player.singSource == .searching)
            .frame(width: 38, height: 38)
            .background(Circle().fill(player.singAlong ? Color.white : Color.white.opacity(0.15)))
            .scaleEffect(pressing ? 0.88 : 1)
            .animation(Motion.snappy, value: pressing)
            .contentShape(Circle())
            .gesture(press)
            .overlay(alignment: .topTrailing) {
                // Le panneau s'ouvre sous le bouton, vers la gauche (le
                // bouton est au bord droit de l'en-tête).
                if showsSlider {
                    KaraokePanel(
                        player: player, level: shownLevel, onChange: adjust,
                        onInteract: scheduleHide, onClose: { showsSlider = false }
                    )
                    .offset(y: 48)
                    .transition(.scale(scale: 0.7, anchor: .topTrailing).combined(with: .opacity))
                }
            }
            .animation(Motion.snappy, value: showsSlider)
            .sensoryFeedback(.selection, trigger: player.singAlong)
            .sensoryFeedback(.impact(weight: .medium), trigger: showsSlider) { _, shown in shown }
            .accessibilityElement()
            .accessibilityLabel("Chante")
            .accessibilityValue(player.singAlong ? "Voix \(Int((player.vocalLevel * 100).rounded())) %" : "Désactivé")
            .accessibilityHint("Touche deux fois pour activer ou couper. Balaie vers le haut ou le bas pour régler la voix.")
            .accessibilityAddTraits(.isButton)
            .accessibilityAction { player.setSingAlong(!player.singAlong) }
            .accessibilityAdjustableAction { direction in
                switch direction {
                case .increment: player.setVocalLevel(shownLevel + 0.1)
                case .decrement: player.setVocalLevel(shownLevel - 0.1)
                @unknown default: break
                }
            }
    }

    /// Un seul geste pour tout : appui court, appui long, glissé.
    private var press: some Gesture {
        DragGesture(minimumDistance: 0)
            .onChanged { value in
                if !pressing {
                    pressing = true
                    dragged = false
                    dragStart = nil
                    hideTask?.cancel()
                    longPressTask = Task {
                        try? await Task.sleep(for: .milliseconds(350))
                        guard !Task.isCancelled else { return }
                        openSlider()
                    }
                }
                if abs(value.translation.height) > 8 { dragged = true }
                guard dragged || showsSlider else { return }
                longPressTask?.cancel()
                if !showsSlider { openSlider() }
                // Glisser vers le haut monte la voix (hauteur du curseur =
                // de 0 à 100 %).
                let start = dragStart ?? shownLevel
                if dragStart == nil { dragStart = start }
                adjust(start - value.translation.height / KaraokePanel.height)
            }
            .onEnded { _ in
                longPressTask?.cancel()
                let wasTap = !dragged && !showsSlider
                pressing = false
                if wasTap {
                    player.setSingAlong(!player.singAlong)
                } else {
                    scheduleHide()
                }
            }
    }

    private func openSlider() {
        guard !showsSlider else { return }
        showsSlider = true
        dragStart = shownLevel
    }

    private func adjust(_ level: Double) {
        hideTask?.cancel()
        let clamped = min(1, max(0, level))
        // Petits paliers : le curseur « accroche » 0 et 100 %.
        let snapped = clamped < 0.02 ? 0 : (clamped > 0.98 ? 1 : clamped)
        player.setVocalLevel(snapped)
    }

    /// Le panneau se referme seul après quelques secondes sans y toucher.
    private func scheduleHide() {
        hideTask?.cancel()
        hideTask = Task {
            try? await Task.sleep(for: .seconds(6))
            guard !Task.isCancelled else { return }
            showsSlider = false
        }
    }
}

/// Menu karaoké, ouvert par un appui long (ou un glissé) sur « Chante » :
/// le curseur « Voix » façon volume d'iOS (rempli depuis le bas), trois
/// raccourcis, ce qui joue en ce moment, l'avancement de la séparation par
/// IA et la file d'attente du serveur, qu'on peut vider.
struct KaraokePanel: View {
    @ObservedObject var player: PlayerManager
    let level: Double
    let onChange: (Double) -> Void
    /// Toute action dans le panneau repousse sa fermeture automatique.
    let onInteract: () -> Void
    let onClose: () -> Void

    @State private var clearing = false
    @State private var clearedCount: Int?

    static let height: CGFloat = 188
    private let sliderWidth: CGFloat = 56
    private let columnWidth: CGFloat = 196

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            slider
            VStack(alignment: .leading, spacing: 12) {
                header
                presets
                sourceLine
                if let status = statusText {
                    statusView(status)
                        .transition(.opacity)
                }
                Spacer(minLength: 0)
                queueLine
            }
            .frame(width: columnWidth, height: Self.height, alignment: .topLeading)
        }
        .padding(14)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 26, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 26, style: .continuous).strokeBorder(Color.white.opacity(0.08)))
        .environment(\.colorScheme, .dark)
        .shadow(color: .black.opacity(0.4), radius: 22, y: 10)
        .animation(Motion.smooth, value: statusText)
        .animation(Motion.smooth, value: player.singSource)
        .fixedSize()
        // État de la file du serveur, tant que le panneau est ouvert.
        .task {
            while !Task.isCancelled {
                await player.refreshKaraokeQueue()
                try? await Task.sleep(for: .seconds(5))
            }
        }
    }

    // MARK: Curseur

    private var slider: some View {
        ZStack(alignment: .bottom) {
            Capsule().fill(Color.white.opacity(0.14))
            Rectangle()
                .fill(Color.white)
                .frame(height: Self.height * level)
            Image(systemName: level < 0.01 ? "music.note" : "music.mic")
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(level > 0.12 ? Color.black : Color.white)
                .contentTransition(.symbolEffect(.replace))
                .padding(.bottom, 14)
        }
        .frame(width: sliderWidth, height: Self.height)
        .clipShape(Capsule())
        .contentShape(Capsule())
        .gesture(
            DragGesture(minimumDistance: 0)
                .onChanged { value in onChange(1 - value.location.y / Self.height) }
                .onEnded { _ in onInteract() }
        )
        .accessibilityElement()
        .accessibilityLabel("Voix")
        .accessibilityValue("\(Int((level * 100).rounded())) %")
        .accessibilityAdjustableAction { direction in
            switch direction {
            case .increment: onChange(level + 0.1)
            case .decrement: onChange(level - 0.1)
            @unknown default: break
            }
            onInteract()
        }
    }

    // MARK: Colonne

    private var header: some View {
        HStack(alignment: .firstTextBaseline) {
            Text("Voix")
                .font(.system(size: 17, weight: .bold))
                .foregroundStyle(Tone.primary)
            Text("\(Int((level * 100).rounded())) %")
                .font(.system(size: 17, weight: .semibold).monospacedDigit())
                .foregroundStyle(Tone.secondary)
                .contentTransition(.numericText())
                .animation(Motion.snappy, value: level)
            Spacer(minLength: 0)
            Button(action: onClose) {
                Image(systemName: "xmark")
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(Tone.secondary)
                    .frame(width: 26, height: 26)
                    .background(Circle().fill(Color.white.opacity(0.12)))
            }
            .buttonStyle(.pressable(scale: 0.85))
            .accessibilityLabel("Fermer")
        }
    }

    /// Raccourcis : karaoké complet, voix en fond pour suivre, titre normal.
    private var presets: some View {
        HStack(spacing: 6) {
            preset("Instru", value: 0)
            preset("En fond", value: 0.35)
            preset("Normal", value: 1)
        }
    }

    private func preset(_ title: String, value: Double) -> some View {
        let isOn = abs(level - value) < 0.03
        return Button {
            onChange(value)
            onInteract()
        } label: {
            Text(title)
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(isOn ? Color.black : Tone.primary)
                .lineLimit(1)
                .frame(maxWidth: .infinity)
                .frame(height: 30)
                .background(Capsule().fill(isOn ? Color.white : Color.white.opacity(0.12)))
        }
        .buttonStyle(.pressable(scale: 0.92))
        .sensoryFeedback(.selection, trigger: isOn)
    }

    /// Ce qui joue en ce moment.
    private var sourceLine: some View {
        let (icon, text): (String, String) = switch player.singSource {
        case .off: ("waveform", "Titre original")
        case .searching: ("hourglass", "Préparation du karaoké…")
        case .instrumental: ("music.note", "Instru YouTube en attendant")
        case .reduced: ("dial.low", "Voix baissée en attendant")
        case .separated:
            ("sparkles", player.stemsQuality == "hq" ? "Voix séparée par IA · haute qualité" : "Voix séparée par IA · version rapide")
        }
        return Label {
            Text(text).fixedSize(horizontal: false, vertical: true)
        } icon: {
            Image(systemName: icon).frame(width: 16)
        }
        .font(.system(size: 12, weight: .medium))
        .foregroundStyle(player.singSource == .separated ? Tone.primary : Tone.secondary)
    }

    private struct Status: Equatable {
        var text: String
        var progress: Double?
        var isError = false
    }

    /// Avancement de la séparation par IA du titre en cours.
    private var statusText: Status? {
        guard player.singAlong else { return nil }
        switch player.separation {
        case .idle, .ready:
            return nil
        case .waiting(let ahead):
            return Status(text: ahead > 0 ? "En file d'attente (\(ahead) avant)" : "Séparation par IA…")
        case .running(let progress):
            return Status(text: "Séparation par IA… \(Int((progress * 100).rounded())) %", progress: progress)
        case .downloading:
            return Status(text: "Chargement des pistes…")
        case .improving(let progress):
            return Status(text: "Version haute qualité… \(Int((progress * 100).rounded())) %", progress: progress)
        case .failed(let message):
            return Status(text: message, isError: true)
        }
    }

    private func statusView(_ status: Status) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(status.text)
                .font(.system(size: 11, weight: .medium).monospacedDigit())
                .foregroundStyle(status.isError ? Tone.danger : Tone.secondary)
                .fixedSize(horizontal: false, vertical: true)
            if let progress = status.progress {
                ProgressView(value: min(1, max(0, progress)))
                    .tint(.white)
                    .animation(Motion.smooth, value: progress)
            }
        }
    }

    /// File des séparations du serveur, avec « Vider ».
    @ViewBuilder
    private var queueLine: some View {
        let queue = player.karaokeQueue
        let waiting = queue?.queued ?? 0
        HStack(spacing: 8) {
            Image(systemName: "list.bullet")
                .font(.system(size: 11, weight: .semibold))
            Text(queueText(waiting: waiting, running: queue?.running != nil))
                .font(.system(size: 11, weight: .medium))
                .lineLimit(2)
            Spacer(minLength: 0)
            if waiting > 0 || queue?.running != nil {
                Button {
                    onInteract()
                    clearing = true
                    Task {
                        clearedCount = await player.clearKaraokeQueue()
                        clearing = false
                    }
                } label: {
                    Group {
                        if clearing {
                            ProgressView().controlSize(.mini).tint(.white)
                        } else {
                            Text("Vider")
                        }
                    }
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(Tone.primary)
                    .padding(.horizontal, 10)
                    .frame(height: 24)
                    .background(Capsule().fill(Color.white.opacity(0.14)))
                }
                .buttonStyle(.pressable(scale: 0.9))
                .disabled(clearing)
                .accessibilityLabel("Vider la file d'attente de séparation")
            }
        }
        .foregroundStyle(Tone.tertiary)
    }

    private func queueText(waiting: Int, running: Bool) -> String {
        if let cleared = clearedCount, waiting == 0 {
            return cleared > 0 ? "File vidée (\(cleared))" : "File déjà vide"
        }
        switch (waiting, running) {
        case (0, false): return "File du serveur vide"
        case (0, true): return "1 séparation en cours"
        case (1, _): return "1 titre en attente"
        default: return "\(waiting) titres en attente"
        }
    }
}

/// Ligne en cours, allumée mot par mot au rythme de la lecture. Les temps
/// viennent de la source quand elle les donne (LRC enrichi), sinon chaque mot
/// reçoit une part de la ligne proportionnelle à sa longueur.
struct KaraokeLine: View {
    struct TimedWord: Hashable {
        var start: Double
        var end: Double
        var text: String
    }

    let words: [TimedWord]
    @ObservedObject var player: PlayerManager

    var body: some View {
        TimelineView(.animation(minimumInterval: 1 / 30, paused: !player.isPlaying)) { _ in
            let now = player.exactPositionSeconds + 0.1
            words.reduce(Text("")) { text, word in
                let progress = word.end > word.start ? min(1, max(0, (now - word.start) / (word.end - word.start))) : 1
                return text + Text(word.text).foregroundStyle(Color.white.opacity(0.4 + 0.6 * progress))
            }
        }
    }

    static func timedWords(_ line: Lyrics.Line, next: Double?) -> [TimedWord] {
        let start = line.time ?? 0
        if let words = line.words, !words.isEmpty {
            return words.enumerated().map { index, word in
                let following = index + 1 < words.count ? words[index + 1].time : min(next ?? word.time + 1, word.time + 1.2)
                return TimedWord(start: word.time, end: max(word.time + 0.05, following), text: word.text)
            }
        }
        let tokens = line.text.split(separator: " ", omittingEmptySubsequences: true).map(String.init)
        guard !tokens.isEmpty else { return [] }
        let letters = Double(tokens.reduce(0) { $0 + $1.count })
        // Chanté à peu près à ce rythme ; une longue pause avant la ligne
        // suivante ne doit pas étirer la ligne.
        let natural = letters * 0.085 + 0.8
        let available = (next ?? start + natural) - start - 0.15
        let duration = max(0.6, min(natural, available))
        let weights = tokens.map { Double($0.count) + 2 }
        let total = weights.reduce(0, +)
        var cursor = start
        return tokens.enumerated().map { index, token in
            let length = duration * weights[index] / total
            defer { cursor += length }
            return TimedWord(start: cursor, end: cursor + length, text: index + 1 < tokens.count ? token + " " : token)
        }
    }
}
