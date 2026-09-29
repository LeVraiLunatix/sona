import CoreMotion
import SwiftUI

// MARK: - AirPods : gestes de la tête

/// Avec des AirPods (Pro, 3e/4e génération, Max) : hocher la tête ajoute le
/// titre à ta bibliothèque, secouer la tête passe au suivant. Les capteurs de
/// mouvement des écouteurs sont lus via `CMHeadphoneMotionManager`.
@MainActor
final class HeadGestures: ObservableObject {
    static let shared = HeadGestures()

    @Published var enabled = UserDefaults.standard.bool(forKey: "encre.headGestures") {
        didSet {
            UserDefaults.standard.set(enabled, forKey: "encre.headGestures")
            enabled ? start() : stop()
        }
    }
    /// Dernier geste reconnu (affiché brièvement dans le lecteur).
    @Published private(set) var lastGesture: String?

    private let manager = CMHeadphoneMotionManager()
    private var samples: [(time: TimeInterval, pitch: Double, yaw: Double)] = []
    private var quietUntil: TimeInterval = 0

    var available: Bool { manager.isDeviceMotionAvailable }

    private init() {}

    func startIfEnabled() {
        if enabled { start() }
    }

    private func start() {
        guard manager.isDeviceMotionAvailable, !manager.isDeviceMotionActive else { return }
        manager.startDeviceMotionUpdates(to: .main) { [weak self] motion, _ in
            guard let motion else { return }
            let sample = (motion.timestamp, motion.attitude.pitch, motion.attitude.yaw)
            Task { @MainActor in self?.handle(sample) }
        }
    }

    private func stop() {
        manager.stopDeviceMotionUpdates()
        samples.removeAll()
    }

    private func handle(_ sample: (TimeInterval, Double, Double)) {
        samples.append((sample.0, sample.1, sample.2))
        samples.removeAll { sample.0 - $0.time > 1.0 }
        guard sample.0 > quietUntil, samples.count > 10, PlayerManager.shared.isPlaying else { return }
        let pitches = samples.map(\.pitch), yaws = samples.map(\.yaw)
        let pitchRange = (pitches.max() ?? 0) - (pitches.min() ?? 0)
        let yawRange = (yaws.max() ?? 0) - (yaws.min() ?? 0)
        let backToStart = abs((pitches.last ?? 0) - (pitches.first ?? 0)) < 0.12

        if pitchRange > 0.35, yawRange < 0.2, backToStart {
            recognized("♥ Ajouté à ta bibliothèque") { await self.likeCurrent() }
        } else if yawRange > 0.55, pitchRange < 0.25, directionChanges(yaws) >= 2 {
            recognized("Titre suivant") { PlayerManager.shared.next() }
        }
    }

    private func directionChanges(_ values: [Double]) -> Int {
        var changes = 0, lastSign = 0
        for (previous, value) in zip(values, values.dropFirst()) {
            let delta = value - previous
            guard abs(delta) > 0.01 else { continue }
            let sign = delta > 0 ? 1 : -1
            if lastSign != 0 && sign != lastSign { changes += 1 }
            lastSign = sign
        }
        return changes
    }

    private func recognized(_ label: String, action: @escaping () async -> Void) {
        quietUntil = (samples.last?.time ?? 0) + 1.5
        samples.removeAll()
        UINotificationFeedbackGenerator().notificationOccurred(.success)
        withAnimation(Motion.snappy) { lastGesture = label }
        Task {
            await action()
            try? await Task.sleep(for: .seconds(2))
            withAnimation(Motion.smooth) { if self.lastGesture == label { self.lastGesture = nil } }
        }
    }

    private func likeCurrent() async {
        guard let track = PlayerManager.shared.current else { return }
        try? await APIClient.shared.addToLibrary(kind: "track", source: track.source, sourceId: track.sourceId)
    }
}

// MARK: - Son : égaliseur et AirPods

struct SoundSettingsSheet: View {
    @ObservedObject var player: PlayerManager
    @ObservedObject private var gestures = HeadGestures.shared
    @Environment(\.dismiss) private var dismiss
    @State private var gains: [Float] = AudioEffects.eqGains
    @AppStorage("encre.autoResume") private var autoResume = true
    @AppStorage("encre.visualizer") private var visualizer = false
    @AppStorage("encre.djVoice") private var djVoice = false
    @AppStorage("encre.lyricsActivity") private var lyricsActivity = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    ScrollView(.horizontal) {
                        HStack(spacing: 8) {
                            ForEach(EQPreset.all) { preset in
                                Button(preset.name) { apply(preset.gains) }
                                    .font(Typo.rowTitle)
                                    .foregroundStyle(gains == preset.gains ? .black : Tone.primary)
                                    .padding(.horizontal, 12).padding(.vertical, 7)
                                    .background(Capsule().fill(gains == preset.gains ? Color.white : Tone.surfaceStrong))
                                    .buttonStyle(.plain)
                            }
                        }
                    }
                    .scrollIndicators(.hidden)
                    HStack(alignment: .bottom, spacing: 0) {
                        ForEach(0..<5, id: \.self) { band in
                            VStack(spacing: 8) {
                                Text(String(format: "%+.0f", gains[band])).font(Typo.caption).foregroundStyle(Tone.secondary).monospacedDigit()
                                Slider(value: Binding(
                                    get: { Double(gains[band]) },
                                    set: { value in
                                        gains[band] = Float(value.rounded())
                                        apply(gains)
                                    }
                                ), in: -12...12)
                                .rotationEffect(.degrees(-90))
                                .frame(width: 150, height: 30)
                                .frame(width: 44, height: 150)
                                .tint(.white)
                                Text(AudioEffects.bandLabels[band]).font(Typo.caption).foregroundStyle(Tone.primary)
                            }
                            .frame(maxWidth: .infinity)
                        }
                    }
                    .padding(.vertical, 6)
                } header: {
                    Text("Égaliseur")
                } footer: {
                    Text("Appliqué à tous les titres, téléchargés ou non.")
                }

                Section {
                    Toggle(isOn: $player.spatialAudio) {
                        Label("Audio spatial", systemImage: "airpods.gen3")
                    }
                    Toggle(isOn: $gestures.enabled) {
                        VStack(alignment: .leading, spacing: 2) {
                            Label("Gestes de la tête", systemImage: "person.fill.questionmark")
                            Text("Hoche la tête : ♥ ajouter · Secoue la tête : titre suivant")
                                .font(Typo.caption).foregroundStyle(Tone.secondary)
                        }
                    }
                    .disabled(!gestures.available && !gestures.enabled)
                    Toggle(isOn: $autoResume) {
                        VStack(alignment: .leading, spacing: 2) {
                            Label("Reprise automatique", systemImage: "play.circle")
                            Text("Écouteurs retirés : pause. Remis dans les 15 min : la musique repart.")
                                .font(Typo.caption).foregroundStyle(Tone.secondary)
                        }
                    }
                } header: {
                    Text("AirPods")
                } footer: {
                    Text(gestures.available
                         ? "Audio spatial : active aussi « Spatialiser la stéréo » et le suivi de la tête dans le Centre de contrôle (appui long sur le volume)."
                         : "Gestes de la tête : mets tes AirPods (Pro, 3e génération ou plus, Max) pour les activer.")
                }

                Section {
                    Toggle(isOn: $djVoice) {
                        VStack(alignment: .leading, spacing: 2) {
                            Label("DJ vocal", systemImage: "mic.and.signal.meter")
                            Text("Une voix annonce chaque titre, comme à la radio.")
                                .font(Typo.caption).foregroundStyle(Tone.secondary)
                        }
                    }
                    Toggle(isOn: $visualizer) {
                        VStack(alignment: .leading, spacing: 2) {
                            Label("Visualiseur", systemImage: "waveform")
                            Text("Des barres qui dansent sur le son, sous la pochette.")
                                .font(Typo.caption).foregroundStyle(Tone.secondary)
                        }
                    }
                    Toggle(isOn: $lyricsActivity) {
                        VStack(alignment: .leading, spacing: 2) {
                            Label("Paroles sur l'écran verrouillé", systemImage: "quote.bubble")
                            Text("La ligne chantée en direct sur l'écran verrouillé et dans la Dynamic Island.")
                                .font(Typo.caption).foregroundStyle(Tone.secondary)
                        }
                    }
                } header: {
                    Text("Ambiance")
                }
                .onChange(of: visualizer) { _, on in
                    AudioEffects.visualizerOn = on
                    player.audioEffectsChanged()
                }
                .onChange(of: djVoice) { _, on in
                    if !on { DJVoice.shared.stop() }
                }
                .onChange(of: lyricsActivity) { _, _ in
                    LyricsActivity.shared.settingChanged()
                }
            }
            .navigationTitle("Son")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("OK") { dismiss() } } }
        }
    }

    private func apply(_ values: [Float]) {
        gains = values
        AudioEffects.eqGains = values
        player.audioEffectsChanged()
    }
}

// MARK: - Moments (réactions sur la timeline)

/// Les réactions de tes amis (et les tiennes) apparaissent au moment précis
/// du titre où elles ont été postées.
struct MomentsOverlay: View {
    @ObservedObject var player: PlayerManager
    let moments: [TrackMoment]

    var body: some View {
        let position = player.positionSeconds
        let visible = moments.filter { position >= $0.position && position - $0.position < 4 }
        VStack(alignment: .leading, spacing: 6) {
            ForEach(visible) { moment in
                HStack(spacing: 8) {
                    Artwork(url: moment.avatarURL, cornerRadius: 12, symbol: "person.fill").frame(width: 24, height: 24)
                    Text(moment.emoji).font(.system(size: 20))
                    Text(moment.text.map { "\(moment.isMe ? "Toi" : moment.name) : \($0)" } ?? (moment.isMe ? "Toi" : moment.name))
                        .font(Typo.rowSubtitle).foregroundStyle(.white).lineLimit(1)
                }
                .padding(.horizontal, 10).padding(.vertical, 6)
                .background(Capsule().fill(.black.opacity(0.55)))
                .transition(.move(edge: .bottom).combined(with: .opacity))
            }
        }
        .animation(Motion.bouncy, value: visible.map(\.id))
    }
}

struct AddMomentSheet: View {
    let track: Track
    let position: Double
    let onPosted: () -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var emoji = "🔥"
    @State private var text = ""
    @State private var posting = false

    private let emojis = ["🔥", "😍", "🤯", "😭", "💀", "🎯", "👑", "🥶", "🙏", "💯"]

    var body: some View {
        NavigationStack {
            VStack(spacing: 20) {
                Text("Réagis à \(timeLabel) de « \(track.title) »").font(Typo.headline).foregroundStyle(Tone.primary)
                    .multilineTextAlignment(.center)
                LazyVGrid(columns: Array(repeating: GridItem(.flexible()), count: 5), spacing: 12) {
                    ForEach(emojis, id: \.self) { value in
                        Button { emoji = value } label: {
                            Text(value).font(.system(size: 32))
                                .frame(width: 54, height: 54)
                                .background(Circle().fill(emoji == value ? Color.white.opacity(0.25) : .clear))
                        }
                        .buttonStyle(.plain)
                    }
                }
                TextField("Un petit mot (facultatif)", text: $text)
                    .textFieldStyle(.roundedBorder)
                PillButton(title: "Publier", systemImage: "paperplane.fill", isLoading: posting) {
                    Task {
                        posting = true
                        try? await APIClient.shared.addMoment(for: track, position: position, emoji: emoji,
                                                              text: text.isEmpty ? nil : String(text.prefix(80)))
                        posting = false
                        onPosted()
                        dismiss()
                    }
                }
                Text("Tes amis verront ta réaction à cet instant quand ils écouteront le titre.")
                    .font(Typo.caption).foregroundStyle(Tone.secondary).multilineTextAlignment(.center)
            }
            .padding(20)
            .navigationTitle("Moment")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Annuler") { dismiss() } } }
        }
        .presentationDetents([.medium])
    }

    private var timeLabel: String {
        String(format: "%d:%02d", Int(position) / 60, Int(position) % 60)
    }
}

// MARK: - Carte story à partager

/// Carte 9:16 d'un titre (pochette, titre, une ligne de paroles au choix),
/// prête pour une story Instagram ou Snap.
struct StoryShareSheet: View {
    let track: Track
    @Environment(\.dismiss) private var dismiss
    @State private var lines: [String] = []
    @State private var chosen: String?
    @State private var cover: UIImage?
    @State private var image: UIImage?

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 18) {
                    if let image {
                        Image(uiImage: image).resizable().scaledToFit()
                            .frame(maxHeight: 420)
                            .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                            .shadow(radius: 16)
                        ShareLink(item: Image(uiImage: image), preview: SharePreview(track.title, image: Image(uiImage: image))) {
                            Label("Partager", systemImage: "square.and.arrow.up")
                                .font(Typo.headline).foregroundStyle(.black)
                                .padding(.horizontal, 24).padding(.vertical, 12)
                                .background(Capsule().fill(.white))
                        }
                    } else {
                        ProgressView().tint(.white).frame(height: 300)
                    }
                    if !lines.isEmpty {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("Choisis une ligne des paroles").font(Typo.headline).foregroundStyle(Tone.primary)
                            Button { choose(nil) } label: { lineRow("Sans paroles", selected: chosen == nil) }
                            ForEach(lines, id: \.self) { line in
                                Button { choose(line) } label: { lineRow(line, selected: chosen == line) }
                            }
                        }
                    }
                }
                .padding(20)
            }
            .background(Tone.background)
            .navigationTitle("Story")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("OK") { dismiss() } } }
        }
        .task { await load() }
    }

    private func lineRow(_ text: String, selected: Bool) -> some View {
        HStack {
            Text(text).font(Typo.rowSubtitle).foregroundStyle(selected ? .black : Tone.primary).multilineTextAlignment(.leading)
            Spacer()
        }
        .padding(10)
        .background(RoundedRectangle(cornerRadius: 10).fill(selected ? Color.white : Tone.surface))
    }

    private func load() async {
        if let url = track.coverURL.flatMap(URL.init(string:)),
           let downloaded = try? await URLSession.shared.data(from: url) {
            cover = UIImage(data: downloaded.0)
        }
        if let lyrics = try? await APIClient.shared.lyrics(for: track), !lyrics.instrumental {
            var seen = Set<String>()
            lines = lyrics.lines.map(\.text).filter { !$0.isEmpty && $0.count <= 90 && seen.insert($0).inserted }
        }
        render()
    }

    private func choose(_ line: String?) {
        chosen = line
        render()
    }

    @MainActor
    private func render() {
        let renderer = ImageRenderer(content: StoryCard(track: track, cover: cover, line: chosen))
        renderer.scale = 3
        image = renderer.uiImage
    }
}

private struct StoryCard: View {
    let track: Track
    let cover: UIImage?
    let line: String?

    var body: some View {
        ZStack {
            if let cover {
                Image(uiImage: cover).resizable().scaledToFill().blur(radius: 40).overlay(Color.black.opacity(0.35))
            } else {
                LinearGradient(colors: [.purple, .black], startPoint: .top, endPoint: .bottom)
            }
            VStack(spacing: 22) {
                Spacer()
                Group {
                    if let cover {
                        Image(uiImage: cover).resizable().scaledToFit()
                    } else {
                        Image(systemName: "music.note").font(.system(size: 80)).foregroundStyle(.white)
                    }
                }
                .frame(width: 240, height: 240)
                .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                .shadow(color: .black.opacity(0.5), radius: 20, y: 10)
                VStack(spacing: 4) {
                    Text(track.title).font(.system(size: 26, weight: .heavy)).foregroundStyle(.white).multilineTextAlignment(.center)
                    Text(track.artist).font(.system(size: 18, weight: .medium)).foregroundStyle(.white.opacity(0.8))
                }
                if let line {
                    Text("« \(line) »")
                        .font(.system(size: 22, weight: .bold, design: .serif))
                        .italic()
                        .foregroundStyle(.white)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 28)
                }
                Spacer()
                Text("Sona").font(.system(size: 16, weight: .black)).foregroundStyle(.white.opacity(0.8)).padding(.bottom, 30)
            }
            .padding(.horizontal, 24)
        }
        .frame(width: 360, height: 640)
        .clipped()
    }
}
