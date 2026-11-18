import AVFoundation
import NaturalLanguage
import SwiftUI
import Translation

/// Retard de la sortie audio (Bluetooth surtout) : les paroles s'allument un peu plus tôt pour
/// tomber au moment où on entend le mot, pas quand il est décodé.
enum LyricsTiming {
    static var latency: Double { min(0.4, max(0, AVAudioSession.sharedInstance().outputLatency)) }
}

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
    /// Décalage des paroles du titre en cours, en secondes (positif : les
    /// paroles arrivent plus tôt). Gardé par titre sur l'iPhone.
    @Published private(set) var offset: Double = 0
    /// Réglage du décalage affiché sous les paroles.
    @Published var showsOffset = false
    private var trackID: String?

    func load(for track: Track) {
        trackID = track.id
        offset = Self.storedOffset(for: track.id)
        showsOffset = false
    }

    func setOffset(_ value: Double) {
        let clamped = (min(10, max(-10, value)) * 10).rounded() / 10
        offset = clamped
        guard let trackID else { return }
        if clamped == 0 {
            UserDefaults.standard.removeObject(forKey: Self.offsetKey(trackID))
        } else {
            UserDefaults.standard.set(clamped, forKey: Self.offsetKey(trackID))
        }
    }

    /// Décalage gardé pour un titre (aussi lu par l'activité en direct).
    nonisolated static func storedOffset(for trackID: String) -> Double {
        UserDefaults.standard.double(forKey: offsetKey(trackID))
    }

    private nonisolated static func offsetKey(_ id: String) -> String { "encre.lyricsOffset.\(id)" }
}

struct LyricsView: View {
    @ObservedObject var player: PlayerManager
    let track: Track
    @ObservedObject private var options = LyricsOptions.shared

    private enum LoadState: Equatable {
        case loading, loaded(Lyrics), unavailable(String)
    }
    @State private var state: LoadState = .loading
    @State private var freeScroll = false
    // Traduction en français (sur l'iPhone, hors ligne une fois la langue
    // téléchargée) des paroles dans une autre langue.
    @State private var translations: [String: String] = [:]
    @State private var translationConfig: TranslationSession.Configuration?
    // Changement de ligne « en vague », comme sur le site (voir `LyricsWave`).
    @State private var wave = LyricsWave()
    @State private var waveRunning = false
    @State private var waveTask: Task<Void, Never>?
    @State private var scrollPosition = ScrollPosition()
    @State private var layout = LyricsLayout()
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

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
                    synced(lyrics)
                        .translationTask(translationConfig) { session in
                            await translate(lyrics.lines, with: session)
                        }
                } else {
                    plain(lyrics)
                }
            }
        }
        .overlay(alignment: .bottom) {
            if options.showsOffset && options.synced {
                LyricsOffsetBar(options: options)
                    .padding(.bottom, 14)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
        }
        .animation(Motion.snappy, value: options.showsOffset)
        .task(id: track.id) {
            options.load(for: track)
            await load()
        }
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
    /// Marge au-dessus de la première ligne et sous la dernière.
    private static let verticalInset: CGFloat = 120
    private static let rowSpacing: CGFloat = 22

    private func synced(_ lyrics: Lyrics) -> some View {
        let lines = lyrics.lines
        let offset = options.offset
        // Légère avance : la ligne s'allume quand elle est chantée, pas un
        // demi-temps après (le lecteur ne publie sa position que 2 fois/s).
        let position = player.positionSeconds + 0.25 + LyricsTiming.latency + offset
        let active = lines.lastIndex(where: { ($0.time ?? 0) <= position })
        return ScrollViewReader { proxy in
            ScrollView(showsIndicators: false) {
                // L'horloge ne tourne que pendant la vague d'un changement de ligne.
                TimelineView(.animation(paused: !waveRunning)) { context in
                    VStack(alignment: .leading, spacing: Self.rowSpacing) {
                        // Longue intro : les trois points d'attente avant la
                        // première ligne.
                        if active == nil, let first = lines.first?.time, first > 4 {
                            InterludeDots(start: 0, end: first, offset: offset, player: player, active: true)
                                .id(-1)
                        }
                        ForEach(Array(lines.enumerated()), id: \.offset) { index, line in
                            let translated = options.translating
                                ? translations[line.text].flatMap { (text: String) -> String? in text != line.text ? text : nil } : nil
                            LyricRow(
                                line: line,
                                next: lines.dropFirst(index + 1).first?.time,
                                // Avant la première ligne (intro, ou lecture pas
                                // encore lancée) : tout net et estompé, rien de flou.
                                distance: active.map { abs(index - $0) },
                                offset: offset,
                                isPlaying: player.isPlaying,
                                translation: translated,
                                player: player
                            )
                            .equatable()
                            .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { layout.heights[index] = $0 }
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .contentShape(Rectangle())
                            .onTapGesture {
                                if let time = line.time { player.seek(toSeconds: max(0, time - offset)) }
                            }
                            .id(index)
                            // En dernier : la vague décale la ligne sans rien animer d'autre.
                            .offset(y: wave.offset(index, at: context.date))
                        }
                        footer(lyrics)
                    }
                    .padding(.vertical, Self.verticalInset)
                    // La marge est à l'intérieur de la zone qui défile : le flou
                    // des lignes déborde dans la marge au lieu d'être coupé net
                    // au bord (la zone s'étend jusqu'aux bords de l'écran).
                    .padding(.horizontal, Self.sideInset)
                }
            }
            .scrollPosition($scrollPosition)
            .onScrollGeometryChange(for: LyricsScrollMetrics.self) { geometry in
                LyricsScrollMetrics(
                    offset: geometry.contentOffset.y,
                    viewport: geometry.containerSize.height,
                    maxOffset: max(0, geometry.contentSize.height - geometry.containerSize.height)
                )
            } action: { _, new in
                layout.metrics = new
            }
            .padding(.horizontal, -Self.sideInset)
            .mask { EdgeFade() }
            // Mode libre : un doigt qui fait défiler les paroles les laisse tranquilles, sans les
            // ramener de force à la ligne en cours ; une pastille propose d'y revenir.
            .simultaneousGesture(DragGesture(minimumDistance: 10).onChanged { _ in
                if !freeScroll {
                    freeScroll = true
                    stopWave()
                }
            })
            .overlay(alignment: .bottom) {
                if freeScroll, let active {
                    Button {
                        freeScroll = false
                        withAnimation(Motion.smooth) { proxy.scrollTo(active, anchor: UnitPoint(x: 0.5, y: 0.35)) }
                    } label: {
                        Label("Revenir à la ligne en cours", systemImage: "arrow.down.to.line")
                            .font(.system(size: 14, weight: .semibold))
                            .foregroundStyle(.white)
                            .padding(.horizontal, 14)
                            .padding(.vertical, 9)
                            .background(Capsule().fill(Color.white.opacity(0.18)))
                    }
                    .buttonStyle(.pressable)
                    .padding(.bottom, 18)
                    .transition(.opacity.combined(with: .move(edge: .bottom)))
                }
            }
            .animation(Motion.snappy, value: freeScroll)
            .onAppear {
                if let active { proxy.scrollTo(active, anchor: UnitPoint(x: 0.5, y: 0.35)) }
            }
            .onChange(of: active) { old, new in
                guard let new, !freeScroll else { return }
                follow(line: new, from: old, count: lines.count, proxy: proxy)
            }
            .onChange(of: player.current?.id) { _, _ in
                freeScroll = false
                stopWave()
            }
        }
    }

    // MARK: - Vague

    /// Haut d'une ligne dans la zone qui défile (les lignes sont mesurées ; pas
    /// de points d'intro quand une ligne est en cours).
    private func top(of index: Int) -> CGFloat {
        (0..<index).reduce(Self.verticalInset) { $0 + (layout.heights[$1] ?? 0) + Self.rowSpacing }
    }

    private func stopWave() {
        waveTask?.cancel()
        wave = LyricsWave()
        waveRunning = false
    }

    /// Recentre sur la ligne `index` comme sur le site : le défilement se fait
    /// d'un coup, puis chaque ligne visible revient à sa place en glissant, celles
    /// du dessous un peu après celles du dessus (voir `LyricsWave`). Une vague déjà
    /// en cours n'est pas coupée : chaque ligne repart d'où elle est.
    private func follow(line index: Int, from previous: Int?, count: Int, proxy: ScrollViewProxy) {
        let metrics = layout.metrics
        let measured = (0..<count).allSatisfy { layout.heights[$0] != nil }
        guard previous != nil, measured, metrics.viewport > 0 else {
            // Pas encore mesuré (ou venue de l'intro) : défilement doux d'un bloc.
            withAnimation(Motion.smooth) { proxy.scrollTo(index, anchor: UnitPoint(x: 0.5, y: 0.35)) }
            return
        }
        // Une ligne très longue est alignée plus haut pour qu'elle tienne.
        let anchor = (layout.heights[index] ?? 0) > metrics.viewport * 0.4 ? 0.16 : 0.36
        let target = min(max(0, top(of: index) - metrics.viewport * anchor), metrics.maxOffset)
        let delta = target - metrics.offset
        guard abs(delta) >= 1 else { return }
        guard !reduceMotion else {
            scrollPosition.scrollTo(y: target)
            return
        }
        guard abs(delta) <= metrics.viewport * 1.1 else {
            // Grand saut (retour en arrière dans le titre) : glissement d'un bloc.
            stopWave()
            withAnimation(Motion.smooth) { scrollPosition.scrollTo(y: target) }
            return
        }
        let now = Date()
        var from: [Int: CGFloat] = [:]
        var delay: [Int: Double] = [:]
        for row in 0..<count {
            let y = top(of: row) - metrics.offset
            // Hors de l'écran : pas animée.
            if y + (layout.heights[row] ?? 0) < -metrics.viewport * 0.35 || y > metrics.viewport * 1.35 { continue }
            from[row] = wave.offset(row, at: now) + delta
            delay[row] = row > index ? Double(min(row - index, 6)) * 0.034 : 0
        }
        wave = LyricsWave(start: now, from: from, delay: delay)
        waveRunning = true
        scrollPosition.scrollTo(y: target)
        waveTask?.cancel()
        let total = wave.total
        waveTask = Task {
            try? await Task.sleep(for: .seconds(total + 0.1))
            guard !Task.isCancelled else { return }
            wave = LyricsWave()
            waveRunning = false
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

    private func plain(_ lyrics: Lyrics) -> some View {
        ScrollView(showsIndicators: false) {
            VStack(alignment: .leading, spacing: 0) {
                Text(lyrics.lines.map(\.text).joined(separator: "\n"))
                    .font(.system(size: 22, weight: .semibold))
                    .lineSpacing(8)
                    .foregroundStyle(Tone.primary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                footer(lyrics)
                    .padding(.top, 18)
            }
            .padding(.vertical, 30)
        }
        .mask { EdgeFade() }
    }

    /// Sous les paroles : leur source et leur précision.
    private func footer(_ lyrics: Lyrics) -> some View {
        Group {
            if let name = lyrics.sourceName {
                Text(Self.sourceLine(lyrics, name: name))
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(Color.white.opacity(0.4))
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.top, 8)
    }

    static func sourceLine(_ name: String, sync: String?) -> String {
        switch sync {
        case "word": "Paroles : \(name) · mot par mot"
        case "line": "Paroles : \(name) · ligne par ligne"
        default: "Paroles : \(name)"
        }
    }

    static func sourceLine(_ lyrics: Lyrics, name: String) -> String {
        sourceLine(name, sync: lyrics.sync) + (lyrics.approximate == true ? " · synchro approximative" : "")
    }

    /// Tout se fait tout seul : le serveur recherche de nouveau les paroles
    /// absentes et en cherche de meilleures en arrière-plan ; ici, une
    /// erreur (réseau, source injoignable) est réessayée sans rien demander,
    /// et des paroles moins précises que « mot par mot » sont redemandées
    /// une fois, le temps que le serveur ait peut-être trouvé mieux.
    private func load() async {
        state = .loading
        for (attempt, delay) in [0, 3, 10, 30].enumerated() {
            if delay > 0 {
                try? await Task.sleep(for: .seconds(delay))
            }
            guard !Task.isCancelled else { return }
            do {
                if let lyrics = try await APIClient.shared.lyrics(for: track) {
                    show(lyrics)
                    if lyrics.sync != "word" && !lyrics.instrumental {
                        await lookForBetter(than: lyrics)
                    }
                } else {
                    state = .unavailable("Pas encore de paroles pour ce morceau. Sona les recherche de nouveau d'elle-même, régulièrement.")
                }
                return
            } catch {
                guard !Task.isCancelled else { return }
                if attempt == 0 {
                    // Première erreur : on le dit, et on réessaie en silence.
                    state = .unavailable("Les paroles n'ont pas pu être chargées. Nouvel essai en cours…")
                }
            }
        }
        state = .unavailable("Les paroles n'ont pas pu être chargées. Sona réessaiera au prochain titre.")
    }

    private func lookForBetter(than current: Lyrics) async {
        try? await Task.sleep(for: .seconds(20))
        guard !Task.isCancelled, let better = try? await APIClient.shared.lyrics(for: track) else { return }
        let rank = ["word": 2, "line": 1]
        if rank[better.sync ?? "", default: 0] > rank[current.sync ?? "", default: 0] {
            withAnimation(Motion.smooth) { show(better) }
        }
    }

    private func show(_ lyrics: Lyrics) {
        layout.heights = [:]
        stopWave()
        translations = [:]
        options.translating = false
        translationConfig = nil
        if let language = lyrics.language {
            options.foreign = language != "fr"
        } else {
            let recognizer = NLLanguageRecognizer()
            recognizer.processString(lyrics.lines.map(\.text).joined(separator: "\n"))
            options.foreign = recognizer.dominantLanguage.map { $0 != .french } ?? false
        }
        state = .loaded(lyrics)
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
                circle("timer", on: options.showsOffset, label: "Décalage des paroles") {
                    options.showsOffset.toggle()
                }
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

/// Une ligne de paroles. Toutes les lignes (chantée ou non) sont faites des
/// mêmes boîtes posées par la même mise en page : quand la ligne s'allume,
/// aucun mot ne bouge ni ne change de rang. Distance à la ligne chantée → flou
/// et transparence, mêmes valeurs que le site (`data-d`).
private struct LyricRow: View, Equatable {
    let line: Lyrics.Line
    let next: Double?
    /// Écart avec la ligne chantée (0 = elle) ; `nil` avant la première ligne.
    let distance: Int?
    let offset: Double
    let isPlaying: Bool
    let translation: String?
    let player: PlayerManager

    static func == (a: Self, b: Self) -> Bool {
        a.line == b.line && a.next == b.next && a.distance == b.distance && a.offset == b.offset
            && a.isPlaying == b.isPlaying && a.translation == b.translation
    }

    private var blur: Double {
        switch distance {
        case nil, 0: 0
        case 1: 0.5
        case 2: 1.1
        case 3: 1.6
        default: 2
        }
    }

    private var dimming: Double {
        switch distance {
        case nil, 0: 1
        case 1: 0.82
        case 2: 0.62
        case 3: 0.48
        default: 0.38
        }
    }

    var body: some View {
        let isActive = distance == 0
        VStack(alignment: .leading, spacing: 0) {
            if line.text.isEmpty {
                // Pause instrumentale (ligne vide du LRC).
                InterludeDots(
                    start: line.time ?? 0, end: next ?? (line.time ?? 0) + 4,
                    offset: offset, player: player, active: isActive
                )
            } else {
                KaraokeLine(
                    words: KaraokeLine.timedWords(line, next: next),
                    player: player, offset: offset, active: isActive, isPlaying: isPlaying
                )
            }
            if let translation {
                Text(translation)
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(Color.white.opacity(isActive ? 0.75 : 0.35))
                    .padding(.top, 4)
            }
        }
        .font(.system(size: 28, weight: .bold))
        .blur(radius: blur)
        .opacity(dimming)
        // Les lignes inactives sont un peu plus petites (comme sur le site).
        .scaleEffect(isActive ? 1 : 0.94, anchor: .leading)
        .animation(.timingCurve(0.2, 0.8, 0.2, 1, duration: 0.8), value: distance.map { min($0, 4) })
    }
}

/// Glissement des lignes au changement de ligne, sur le modèle du site
/// (`lyricsWave`) : le défilement est fait d'un coup, puis chaque ligne
/// visible revient à sa place — `from` : décalage de départ —, les lignes du
/// dessous avec un léger retard, en 0,82 s sur la même courbe.
private struct LyricsWave {
    static let duration = 0.82
    private static let curve = UnitCurve.bezier(
        startControlPoint: UnitPoint(x: 0.22, y: 0.9), endControlPoint: UnitPoint(x: 0.26, y: 1)
    )

    var start = Date.distantPast
    var from: [Int: CGFloat] = [:]
    var delay: [Int: Double] = [:]

    var total: Double { Self.duration + (delay.values.max() ?? 0) }

    /// Décalage de la ligne à cet instant (0 hors vague).
    func offset(_ index: Int, at date: Date) -> CGFloat {
        guard let origin = from[index] else { return 0 }
        let elapsed = date.timeIntervalSince(start) - (delay[index] ?? 0)
        if elapsed >= Self.duration { return 0 }
        if elapsed <= 0 { return origin }
        return origin * (1 - CGFloat(Self.curve.value(at: elapsed / Self.duration)))
    }
}

private struct LyricsScrollMetrics: Equatable {
    var offset: CGFloat
    var viewport: CGFloat
    var maxOffset: CGFloat
}

/// Mesures gardées hors de l'état SwiftUI : les lire ou les mettre à jour ne
/// redessine rien.
private final class LyricsLayout {
    var heights: [Int: CGFloat] = [:]
    var metrics = LyricsScrollMetrics(offset: 0, viewport: 0, maxOffset: 0)
}

/// Ligne chantée : allumée mot par mot au rythme de la lecture. Les temps
/// viennent de la source quand elle les donne (LRC enrichi), sinon chaque mot
/// reçoit une part de la ligne proportionnelle à sa longueur. Hors `active`,
/// les mêmes mots, éteints et immobiles.
struct KaraokeLine: View {
    struct TimedWord: Hashable {
        var start: Double
        var end: Double
        var text: String
    }

    let words: [TimedWord]
    /// Pas observé : seule la ligne chantée lit sa position, à chaque image.
    let player: PlayerManager
    /// Décalage réglé pour ce titre (voir `LyricsOptions.offset`).
    var offset: Double = 0
    var active = true
    var isPlaying = true
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        TimelineView(.animation(minimumInterval: 1 / 60, paused: !active || !isPlaying)) { _ in
            let now: Double? = active ? player.exactPositionSeconds + 0.05 + LyricsTiming.latency + offset : nil
            // Un mot = une vue : il peut monter, grossir et s'illuminer seul.
            WordFlowLayout {
                ForEach(Array(words.enumerated()), id: \.offset) { _, word in
                    KaraokeWord(word: word, now: now, still: reduceMotion)
                }
            }
        }
    }

    static func timedWords(_ line: Lyrics.Line, next: Double?) -> [TimedWord] {
        let start = line.time ?? 0
        if let words = line.words, !words.isEmpty {
            return words.enumerated().map { index, word in
                let following = word.end
                    ?? (index + 1 < words.count ? words[index + 1].time : min(next ?? word.time + 1, word.time + 1.2))
                // Fin devinée (pas donnée par la source) et longue pause
                // derrière : on plafonne à une durée de chant plausible. Une
                // fin donnée est respectée, sinon une note tenue serait
                // raccourcie.
                let sung = 0.5 + 0.12 * Double(word.text.trimmingCharacters(in: .whitespaces).count)
                let end = word.end == nil && following - word.time > 1.5 ? min(following, word.time + sung) : following
                return TimedWord(start: word.time, end: max(word.time + 0.05, end), text: word.text)
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

/// Un mot de la ligne, façon Musique : il s'allume au fil de sa durée, monte
/// d'un rien, et s'il est tenu longtemps il grossit et rayonne avant de
/// retomber en douceur. `now == nil` : ligne à l'arrêt (mot éteint, mêmes
/// dimensions). Immobile avec « Réduire les animations ».
private struct KaraokeWord: View {
    let word: KaraokeLine.TimedWord
    let now: Double?
    let still: Bool

    /// Éteint : gris du site (0,5) ; chanté : de 0,4 à blanc plein.
    private func level(_ progress: Double, lit: Bool) -> Double { lit ? 0.4 + 0.6 * progress : 0.5 }

    var body: some View {
        let lit = now != nil
        let time = now ?? word.start - 10
        let duration = max(0.05, word.end - word.start)
        let progress = min(1, max(0, (time - word.start) / duration))
        let rise = min(1, max(0, (time - word.start) / min(0.35, duration * 0.6)))
        let fall = time > word.end ? min(1, max(0, 1 - (time - word.end) / 0.4)) : 1
        let lift = rise * rise * (3 - 2 * rise) * fall
        // Seuls les mots tenus (≥ 0,6 s, plein effet à 1,6 s) grossissent.
        let held = lift * min(1, max(0, (duration - 0.5) / 0.6))
        let hasGap = word.text.last?.isWhitespace == true
        let body = word.text.trimmingCharacters(in: .whitespaces)
        let isHeldNote = duration >= 0.9 && body.count >= 3
        // La marge suit le grossissement : le mot pousse ses voisins au lieu de
        // passer dessus (voir `WordFlowLayout`, qui ne s'en sert pas pour les
        // retours à la ligne : un mot qui grossit ne fait sauter aucun mot).
        let push: CGFloat = isHeldNote && !still ? 0.62 * Double(body.count) * held : 0
        Group {
            if isHeldNote {
                // Note tenue (« frontièèères ») : les lettres s'allument l'une
                // après l'autre sur toute la note.
                let letters = Array(body)
                let count = Double(letters.count)
                HStack(spacing: 0) {
                    ForEach(Array(letters.enumerated()), id: \.offset) { index, letter in
                        let p = min(1, max(0, progress * count - Double(index)))
                        Text(String(letter))
                            .foregroundStyle(Color.white.opacity(level(p, lit: lit)))
                    }
                }
            } else {
                Text(body)
                    .foregroundStyle(Color.white.opacity(level(progress, lit: lit)))
            }
        }
        .scaleEffect(still ? 1 : 1 + 0.08 * held, anchor: .center)
        .shadow(color: .white.opacity(still ? 0 : 0.8 * held), radius: 10 * held)
        .layoutValue(key: WordGapKey.self, value: hasGap)
        .layoutValue(key: WordPushKey.self, value: push)
    }
}

private struct WordGapKey: LayoutValueKey {
    static let defaultValue = true
}

/// Place prise en plus de chaque côté par un mot qui grossit.
private struct WordPushKey: LayoutValueKey {
    static let defaultValue: CGFloat = 0
}

/// Mots posés l'un après l'autre, retour à la ligne à la largeur proposée.
/// L'espace entre deux mots n'existe que si la source en met un (les
/// syllabes d'un même mot se touchent). Les retours à la ligne se décident sur
/// les largeurs au repos : un mot qui grossit décale ses voisins de sa ligne
/// sans en renvoyer aucun à la ligne suivante.
private struct WordFlowLayout: Layout {
    private let space: CGFloat = 8

    private func rows(_ subviews: Subviews, width: CGFloat) -> (frames: [CGRect], size: CGSize) {
        var frames: [CGRect] = []
        var x: CGFloat = 0, rest: CGFloat = 0, y: CGFloat = 0, rowHeight: CGFloat = 0, maxX: CGFloat = 0
        for sub in subviews {
            let size = sub.sizeThatFits(.unspecified)
            let push = sub[WordPushKey.self]
            if rest > 0, rest + size.width > width {
                x = 0
                rest = 0
                y += rowHeight + 2
                rowHeight = 0
            }
            frames.append(CGRect(origin: CGPoint(x: x + push, y: y), size: size))
            let gap = sub[WordGapKey.self] ? space : 0
            x += size.width + 2 * push + gap
            rest += size.width + gap
            rowHeight = max(rowHeight, size.height)
            maxX = max(maxX, rest)
        }
        return (frames, CGSize(width: min(width, maxX), height: y + rowHeight))
    }

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        rows(subviews, width: proposal.width ?? .infinity).size
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let layout = rows(subviews, width: bounds.width)
        for (sub, frame) in zip(subviews, layout.frames) {
            sub.place(at: CGPoint(x: bounds.minX + frame.minX, y: bounds.minY + frame.minY), proposal: ProposedViewSize(frame.size))
        }
    }
}

/// Pause instrumentale (intro, pont, ligne vide du LRC) : trois points qui
/// respirent et s'allument l'un après l'autre au fil de la pause, comme
/// dans Musique. Estompés quand ce n'est pas la ligne en cours.
struct InterludeDots: View {
    let start: Double
    let end: Double
    var offset: Double = 0
    @ObservedObject var player: PlayerManager
    var active: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        TimelineView(.animation(minimumInterval: 1 / 30, paused: !active || !player.isPlaying)) { timeline in
            let now = player.exactPositionSeconds + offset
            let progress = end > start ? min(1, max(0, (now - start) / (end - start))) : 0
            let breath = reduceMotion ? 1 : 1 + 0.1 * sin(timeline.date.timeIntervalSinceReferenceDate * 2.4)
            HStack(spacing: 10) {
                ForEach(0..<3, id: \.self) { dot in
                    let lit = min(1, max(0, progress * 3 - Double(dot)))
                    Circle()
                        .fill(Color.white.opacity(active ? 0.3 + 0.7 * lit : 0.22))
                        .frame(width: 11, height: 11)
                }
            }
            .scaleEffect(active ? breath : 0.85, anchor: .leading)
            .frame(height: 30, alignment: .leading)
        }
        .accessibilityHidden(true)
    }
}

/// Réglage du décalage des paroles : ± 0,5 s par appui, gardé pour ce
/// titre ; un appui sur la valeur la remet à zéro.
struct LyricsOffsetBar: View {
    @ObservedObject var options: LyricsOptions

    var body: some View {
        HStack(spacing: 6) {
            step("minus", by: -0.5, label: "Paroles plus tard")
            Button {
                options.setOffset(0)
            } label: {
                VStack(spacing: 1) {
                    Text(valueLabel)
                        .font(.system(size: 15, weight: .semibold).monospacedDigit())
                        .contentTransition(.numericText(value: options.offset))
                    Text(options.offset == 0 ? "Décalage" : "Remettre à zéro")
                        .font(.system(size: 10, weight: .medium))
                        .opacity(0.6)
                }
                .foregroundStyle(.white)
                .frame(minWidth: 96)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Décalage des paroles : \(valueLabel)")
            .accessibilityHint("Remet le décalage à zéro")
            step("plus", by: 0.5, label: "Paroles plus tôt")
        }
        .padding(6)
        .background(Capsule().fill(.ultraThinMaterial))
        .environment(\.colorScheme, .dark)
        .animation(Motion.snappy, value: options.offset)
        .sensoryFeedback(.selection, trigger: options.offset)
    }

    private var valueLabel: String {
        let value = options.offset
        let sign = value > 0 ? "+" : value < 0 ? "−" : ""
        return sign + String(format: "%.1f s", abs(value)).replacingOccurrences(of: ".", with: ",")
    }

    private func step(_ icon: String, by delta: Double, label: String) -> some View {
        Button {
            options.setOffset(options.offset + delta)
        } label: {
            Image(systemName: icon)
                .font(.system(size: 15, weight: .bold))
                .foregroundStyle(.white)
                .frame(width: 40, height: 40)
                .background(Circle().fill(Color.white.opacity(0.14)))
        }
        .buttonStyle(.pressable(scale: 0.88))
        .accessibilityLabel(label)
    }
}
