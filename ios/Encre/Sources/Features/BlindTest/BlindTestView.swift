import AVFoundation
import SwiftUI

/// Blind test : un extrait, quatre propositions, 15 s. Plus on répond vite,
/// plus on marque (et une série de bonnes réponses rapporte un bonus).
/// Défi du jour identique pour tout le monde, avec classement ; parties
/// libres à la carte : tes titres, le top, un artiste, une radio ou une de
/// tes playlists, 5 à 20 extraits, titre ou artiste à trouver, mode expert.
/// « Complète les paroles » : le titre joue jusqu'à une ligne, à toi de
/// trouver comment elle finit.
struct BlindTestView: View {
    @Environment(\.dismiss) private var dismiss

    private enum Phase: Equatable { case menu, loading, playing, finished }

    @State private var phase: Phase = .menu
    @State private var mode = "daily"
    @State private var round: BlindRound?
    @State private var index = 0
    @State private var picked: Int?
    @State private var score = 0
    @State private var correct = 0
    @State private var streak = 0
    @State private var remaining: Double = BlindTestView.questionSeconds
    @State private var leaderboard: [BlindScore] = []
    @State private var dailyPlayed = false
    @State private var errorMessage: String?
    @State private var audio: AVPlayer?
    @State private var timer: Task<Void, Never>?
    @State private var resumeMainPlayer = false
    @State private var lastGain = 0
    // Partie à la carte
    @State private var ref: String?
    @State private var refLabel: String?
    @AppStorage("blindtest.count") private var count = 10
    @AppStorage("blindtest.guess") private var guess = "title"
    @AppStorage("blindtest.expert") private var expert = false
    @State private var picking: BlindSourcePicker.Kind?
    /// Réglages de la partie en cours (le défi du jour a les siens).
    @State private var playingGuess = "title"
    @State private var playingExpert = false
    @State private var audioCut: Task<Void, Never>?
    /// Paroles : l'extrait joue encore, le chrono n'a pas démarré.
    @State private var listening = false
    // En direct entre amis
    @State private var live: LiveLaunch?
    @State private var liveRooms: [LiveSummary] = []
    @State private var askingCode = false
    @State private var typedCode = ""

    static let questionSeconds: Double = 15
    /// Mode expert : l'extrait s'arrête au bout de 5 s.
    static let expertListenSeconds: Double = 5

    var body: some View {
        NavigationStack {
            ZStack {
                LinearGradient(
                    colors: [Color(red: 0.12, green: 0.06, blue: 0.3), Tone.background],
                    startPoint: .top, endPoint: .bottom
                )
                .ignoresSafeArea()

                switch phase {
                case .menu: menu
                case .loading: ProgressView("Préparation des extraits…").tint(.white).foregroundStyle(Tone.secondary)
                case .playing: question
                case .finished: results
                }
            }
            .navigationTitle("Blind test")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Fermer") { stopAudio(); dismiss() }
                }
            }
        }
        .task { await loadLeaderboard() }
        .task {
            while !Task.isCancelled {
                liveRooms = (try? await APIClient.shared.activeLive()) ?? liveRooms
                try? await Task.sleep(for: .seconds(10))
            }
        }
        .onDisappear { stopAudio() }
        .fullScreenCover(item: $live) { launch in
            BlindLiveView(joinCode: launch.code)
        }
        .alert("Rejoindre une partie", isPresented: $askingCode) {
            TextField("Code (5 lettres)", text: $typedCode)
                .textInputAutocapitalization(.characters)
                .autocorrectionDisabled()
            Button("Annuler", role: .cancel) {}
            Button("Rejoindre") {
                let code = typedCode.trimmingCharacters(in: .whitespaces).uppercased()
                if !code.isEmpty { live = LiveLaunch(code: code) }
            }
        }
        .sheet(item: $picking) { kind in
            BlindSourcePicker(kind: kind) { id, label in
                picking = nil
                start(kind.mode, ref: id, label: label)
            }
            .presentationDetents([.medium, .large])
        }
    }

    // MARK: - Menu

    private var menu: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                VStack(alignment: .leading, spacing: 8) {
                    Image(systemName: "waveform.badge.magnifyingglass")
                        .font(.system(size: 44, weight: .semibold))
                        .foregroundStyle(Tone.primary)
                        .symbolEffect(.bounce, options: .repeating.speed(0.3))
                    Text("Blind test").font(.system(size: 30, weight: .heavy)).foregroundStyle(Tone.primary)
                    Text("Un extrait, quatre propositions, 15 secondes. Plus tu es rapide, plus tu marques.")
                        .font(Typo.body)
                        .foregroundStyle(Tone.secondary)
                }

                modeCard(
                    title: "Défi du jour",
                    subtitle: dailyPlayed ? "Déjà joué aujourd'hui : rejoue pour le plaisir (ne compte plus)" : "10 extraits de vos écoutes, les mêmes pour tout le monde · classement",
                    icon: "calendar", highlighted: true
                ) { start("daily") }

                if let errorMessage {
                    Text(errorMessage).font(Typo.rowSubtitle).foregroundStyle(Tone.danger)
                }

                liveSection

                VStack(alignment: .leading, spacing: 12) {
                    Text("Partie libre").font(Typo.headline).foregroundStyle(Tone.primary)
                    options
                    LazyVGrid(columns: [GridItem(.flexible(), spacing: 12), GridItem(.flexible(), spacing: 12)], spacing: 12) {
                        sourceTile("Tes titres", "Toi et tes amis", "person.2.fill", [.pink, .purple]) { start("solo") }
                        sourceTile("Top du moment", "Les hits Deezer", "chart.line.uptrend.xyaxis", [.orange, .red]) { start("chart") }
                        sourceTile("Un artiste", "Ses tubes et ses proches", "music.mic", [.blue, .cyan]) { picking = .artist }
                        sourceTile("Une radio", "Rap FR, 2000s, rock…", "dot.radiowaves.left.and.right", [.green, .teal]) { picking = .radio }
                        sourceTile("Une playlist", "Une de tes playlists", "music.note.list", [.indigo, .blue]) { picking = .playlist }
                        sourceTile("Surprise", "Un thème au hasard", "dice.fill", [.yellow, .orange]) { surprise() }
                    }
                }

                if !leaderboard.isEmpty { leaderboardView(title: "Classement du jour") }
            }
            .padding(20)
        }
    }

    /// En direct : créer une partie, rejoindre celle d'un ami ou un code.
    private var liveSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("En direct avec tes amis").font(Typo.headline).foregroundStyle(Tone.primary)
            ForEach(liveRooms.filter { !$0.joined }) { room in
                LiveSummaryRow(summary: room) { live = LiveLaunch(code: room.code) }
            }
            HStack(spacing: 12) {
                Button { live = LiveLaunch(code: nil) } label: {
                    Label("Créer une partie", systemImage: "person.3.fill")
                        .font(Typo.headline)
                        .foregroundStyle(.black)
                        .frame(maxWidth: .infinity)
                        .frame(height: 52)
                        .background(Capsule().fill(.white))
                }
                .buttonStyle(.pressable(scale: 0.97))
                Button {
                    typedCode = ""
                    askingCode = true
                } label: {
                    Label("Code", systemImage: "number")
                        .font(Typo.headline)
                        .foregroundStyle(Tone.primary)
                        .padding(.horizontal, 18)
                        .frame(height: 52)
                        .background(Capsule().fill(Tone.surfaceStrong))
                }
                .buttonStyle(.pressable(scale: 0.97))
            }
            Text("Le même extrait pour tout le monde au même moment, classement en direct.")
                .font(Typo.caption).foregroundStyle(Tone.tertiary)
        }
    }

    private var options: some View {
        VStack(spacing: 12) {
            Picker("Extraits", selection: $count) {
                Text("5 extraits").tag(5)
                Text("10 extraits").tag(10)
                Text("20 extraits").tag(20)
            }
            .pickerStyle(.segmented)
            Picker("À trouver", selection: $guess) {
                Text("Trouver le titre").tag("title")
                Text("Trouver l'artiste").tag("artist")
                Text("Paroles").tag("lyrics")
            }
            .pickerStyle(.segmented)
            Toggle(isOn: $expert) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Mode expert").font(Typo.rowTitle).foregroundStyle(Tone.primary)
                    Text("5 s d'écoute seulement · points ×1,5").font(Typo.caption).foregroundStyle(Tone.secondary)
                }
            }
            .tint(.purple)
        }
        .padding(14)
        .background(RoundedRectangle(cornerRadius: 20, style: .continuous).fill(Tone.surface))
    }

    private func sourceTile(_ title: String, _ subtitle: String, _ icon: String, _ colors: [Color], action: @escaping () -> Void) -> some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 10) {
                Image(systemName: icon)
                    .font(.system(size: 22, weight: .bold))
                    .foregroundStyle(.white)
                Spacer(minLength: 0)
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).font(Typo.headline).foregroundStyle(.white).lineLimit(1)
                    Text(subtitle).font(Typo.caption).foregroundStyle(.white.opacity(0.8)).lineLimit(1)
                }
            }
            .padding(14)
            .frame(maxWidth: .infinity, minHeight: 110, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: 20, style: .continuous)
                    .fill(LinearGradient(colors: colors.map { $0.opacity(0.85) }, startPoint: .topLeading, endPoint: .bottomTrailing))
            )
        }
        .buttonStyle(.pressable(scale: 0.96))
    }

    /// Une radio thématique au hasard.
    private func surprise() {
        phase = .loading
        Task {
            if let radio = (try? await APIClient.shared.radioGroups())?.flatMap(\.radios).randomElement() {
                start("radio", ref: radio.id, label: radio.title)
            } else {
                start("chart")
            }
        }
    }

    private func modeCard(title: String, subtitle: String, icon: String, highlighted: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 14) {
                Image(systemName: icon)
                    .font(.system(size: 22, weight: .semibold))
                    .foregroundStyle(highlighted ? .black : Tone.primary)
                    .frame(width: 48, height: 48)
                    .background(Circle().fill(highlighted ? Color.white : Tone.surfaceStrong))
                VStack(alignment: .leading, spacing: 3) {
                    Text(title).font(Typo.headline).foregroundStyle(Tone.primary)
                    Text(subtitle).font(Typo.rowSubtitle).foregroundStyle(Tone.secondary).multilineTextAlignment(.leading)
                }
                Spacer()
                Image(systemName: "play.fill").foregroundStyle(Tone.primary)
            }
            .padding(16)
            .background(RoundedRectangle(cornerRadius: 20, style: .continuous).fill(Tone.surface))
        }
        .buttonStyle(.pressable(scale: 0.97))
    }

    private func leaderboardView(title: String) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title).font(Typo.headline).foregroundStyle(Tone.primary)
            ForEach(Array(leaderboard.enumerated()), id: \.element.id) { rank, entry in
                HStack(spacing: 12) {
                    Text(rank < 3 ? ["🥇", "🥈", "🥉"][rank] : "\(rank + 1)")
                        .font(.system(size: rank < 3 ? 22 : 15, weight: .bold))
                        .foregroundStyle(Tone.secondary)
                        .frame(width: 30)
                    Artwork(url: entry.avatarURL, cornerRadius: 18, symbol: "person.fill").frame(width: 36, height: 36)
                    Text(entry.name).font(Typo.rowTitle).foregroundStyle(entry.isMe ? Tone.primary : Tone.secondary)
                    Spacer()
                    Text("\(entry.correct)/\(entry.total)").font(Typo.caption).foregroundStyle(Tone.tertiary)
                    Text("\(entry.score)").font(.system(size: 17, weight: .bold)).foregroundStyle(Tone.primary).monospacedDigit()
                }
                .padding(.vertical, 4)
            }
        }
        .padding(16)
        .background(RoundedRectangle(cornerRadius: 20, style: .continuous).fill(Tone.surface))
    }

    // MARK: - Question

    @ViewBuilder
    private var question: some View {
        if let round, round.questions.indices.contains(index) {
            let q = round.questions[index]
            VStack(spacing: 22) {
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("\(index + 1) / \(round.questions.count)").font(Typo.caption).foregroundStyle(Tone.secondary)
                        Text(q.isLyrics ? "Complète les paroles" : (playingGuess == "artist" ? "Quel artiste ?" : "Quel titre ?"))
                            .font(Typo.caption).foregroundStyle(Tone.tertiary)
                    }
                    if playingExpert {
                        Label("Expert", systemImage: "bolt.fill").font(Typo.caption).foregroundStyle(.purple)
                    }
                    Spacer()
                    if streak >= 3 {
                        Label("Série ×\(streak)", systemImage: "flame.fill")
                            .font(Typo.caption)
                            .foregroundStyle(.orange)
                            .transition(.scale.combined(with: .opacity))
                    }
                    Text("\(score) pts").font(.system(size: 17, weight: .bold)).foregroundStyle(Tone.primary)
                        .contentTransition(.numericText(value: Double(score)))
                }

                if q.isLyrics {
                    lyricsCard(q)
                } else {
                ZStack {
                    Circle().stroke(Color.white.opacity(0.12), lineWidth: 10)
                    Circle()
                        .trim(from: 0, to: remaining / Self.questionSeconds)
                        .stroke(timerColor, style: StrokeStyle(lineWidth: 10, lineCap: .round))
                        .rotationEffect(.degrees(-90))
                        .animation(.linear(duration: 0.1), value: remaining)
                    if picked != nil {
                        Artwork(url: q.coverURL, cornerRadius: 80)
                            .frame(width: 150, height: 150)
                            .transition(.scale.combined(with: .opacity))
                    } else {
                        VStack(spacing: 4) {
                            EqualizerBars(isAnimating: true).frame(width: 46, height: 40)
                            Text("\(Int(remaining.rounded(.up)))").font(.system(size: 30, weight: .heavy)).foregroundStyle(Tone.primary)
                                .monospacedDigit()
                        }
                    }
                }
                .frame(width: 180, height: 180)
                .animation(Motion.bouncy, value: picked)
                }

                if picked != nil {
                    VStack(spacing: 2) {
                        Text(q.track.title).font(Typo.headline).foregroundStyle(Tone.primary).lineLimit(1)
                        Text(q.track.artist).font(Typo.rowSubtitle).foregroundStyle(Tone.secondary).lineLimit(1)
                    }
                    .transition(.opacity)
                }

                if let picked, lastGain > 0, picked == q.answer {
                    Text("+\(lastGain)").font(.system(size: 22, weight: .heavy)).foregroundStyle(.green)
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                }

                VStack(spacing: 10) {
                    ForEach(Array(q.choices.enumerated()), id: \.offset) { choiceIndex, choice in
                        Button { answer(choiceIndex, question: q) } label: {
                            VStack(alignment: .leading, spacing: 2) {
                                if choice.title.isEmpty {
                                    Text(choice.artist).font(Typo.headline).lineLimit(1)
                                } else {
                                    Text(choice.title).font(Typo.headline).lineLimit(q.isLyrics ? 2 : 1)
                                    if !choice.artist.isEmpty {
                                        Text(choice.artist).font(Typo.rowSubtitle).opacity(0.75).lineLimit(1)
                                    }
                                }
                            }
                            .foregroundStyle(choiceForeground(choiceIndex, q))
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.horizontal, 16)
                            .frame(height: 62)
                            .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(choiceBackground(choiceIndex, q)))
                        }
                        .buttonStyle(.pressable(scale: 0.97))
                        .disabled(picked != nil)
                    }
                }
                Spacer(minLength: 0)
            }
            .padding(20)
            .sensoryFeedback(trigger: picked) { _, new in
                guard let new else { return nil }
                return new == q.answer ? .success : .error
            }
        }
    }

    /// Paroles : les lignes d'avant, puis celle à compléter ; chrono en
    /// barre une fois l'extrait arrivé à la ligne.
    private func lyricsCard(_ q: BlindQuestion) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            ForEach(Array((q.before ?? []).enumerated()), id: \.offset) { _, line in
                Text(line).font(.system(size: 17, weight: .semibold)).foregroundStyle(Tone.tertiary)
            }
            Text(q.prompt ?? "…")
                .font(.system(size: 24, weight: .heavy))
                .foregroundStyle(Tone.primary)
                .fixedSize(horizontal: false, vertical: true)
            if picked != nil {
                HStack(spacing: 10) {
                    Artwork(url: q.coverURL ?? q.track.coverURL, cornerRadius: 6).frame(width: 40, height: 40)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(q.track.title).font(Typo.rowTitle).foregroundStyle(Tone.primary).lineLimit(1)
                        Text(q.track.artist).font(Typo.caption).foregroundStyle(Tone.secondary).lineLimit(1)
                    }
                }
                .transition(.opacity)
            } else if listening {
                HStack(spacing: 8) {
                    EqualizerBars(isAnimating: true).frame(width: 22, height: 18)
                    Text("Écoute bien…").font(Typo.caption).foregroundStyle(Tone.secondary)
                }
            } else {
                ProgressView(value: remaining, total: Self.questionSeconds)
                    .tint(timerColor)
                    .animation(.linear(duration: 0.1), value: remaining)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(18)
        .background(RoundedRectangle(cornerRadius: 22, style: .continuous).fill(Tone.surface))
        .animation(Motion.smooth, value: listening)
        .animation(Motion.smooth, value: picked)
    }

    private var timerColor: Color {
        remaining > 8 ? .white : (remaining > 4 ? .orange : .red)
    }

    private func choiceBackground(_ index: Int, _ q: BlindQuestion) -> Color {
        guard let picked else { return Tone.surfaceStrong }
        if index == q.answer { return Color.green.opacity(0.85) }
        if index == picked { return Color.red.opacity(0.8) }
        return Tone.surface
    }

    private func choiceForeground(_ index: Int, _ q: BlindQuestion) -> Color {
        guard picked != nil else { return Tone.primary }
        return index == q.answer || index == picked ? .white : Tone.tertiary
    }

    // MARK: - Résultats

    private var results: some View {
        ScrollView {
            VStack(spacing: 20) {
                Text(verdict).font(.system(size: 50))
                Text("\(score) points").font(.system(size: 40, weight: .heavy)).foregroundStyle(Tone.primary)
                Text("\(correct) bonne\(correct > 1 ? "s" : "") réponse\(correct > 1 ? "s" : "") sur \(round?.questions.count ?? 0)")
                    .font(Typo.body).foregroundStyle(Tone.secondary)
                if let refLabel, mode != "daily" {
                    Text(refLabel).font(Typo.caption).foregroundStyle(Tone.tertiary)
                }
                PillButton(title: "Menu", systemImage: "square.grid.2x2", kind: .secondary) {
                    withAnimation(Motion.smooth) { phase = .menu }
                }

                HStack(spacing: 12) {
                    PillButton(title: "Rejouer", systemImage: "arrow.clockwise") {
                        if mode == "daily" { start("solo") } else { start(mode, ref: ref, label: refLabel) }
                    }
                    PillButton(title: "Écouter", systemImage: "music.note.list", kind: .secondary) {
                        if let tracks = round?.questions.map(\.track), let first = tracks.first {
                            PlayerManager.shared.play(first, context: tracks, name: "Blind test")
                            dismiss()
                        }
                    }
                }

                if !leaderboard.isEmpty { leaderboardView(title: mode == "daily" ? "Classement du jour" : "Défi du jour") }
            }
            .padding(20)
        }
    }

    private var verdict: String {
        let total = max(1, round?.questions.count ?? 1)
        switch Double(correct) / Double(total) {
        case 0.9...: return "🏆"
        case 0.6..<0.9: return "🔥"
        case 0.3..<0.6: return "🙂"
        default: return "🙈"
        }
    }

    // MARK: - Déroulé

    private func start(_ newMode: String, ref newRef: String? = nil, label: String? = nil) {
        mode = newMode
        ref = newRef
        refLabel = label
        phase = .loading
        errorMessage = nil
        let daily = newMode == "daily"
        playingGuess = daily ? "title" : guess
        playingExpert = daily ? false : expert
        Task {
            do {
                let fresh = try await APIClient.shared.blindRound(
                    mode: newMode, ref: newRef, count: daily ? 10 : count, guess: playingGuess
                )
                playingGuess = fresh.guess ?? playingGuess
                guard fresh.questions.count >= 3 else {
                    errorMessage = playingGuess == "lyrics"
                        ? "Pas assez de titres avec paroles synchronisées pour ce thème : essaie-en un autre."
                        : newMode == "solo" || daily
                        ? "Pas assez de titres avec extrait pour l'instant : écoute encore un peu de musique !"
                        : "Pas assez de titres avec extrait pour ce thème : essaie-en un autre."
                    phase = .menu
                    return
                }
                if let first = fresh.questions.first, first.isLyrics {
                    // Le titre complet doit être prêt côté serveur : le premier
                    // tout de suite, les suivants pendant la partie.
                    try? await APIClient.shared.prepareStream(source: first.track.source, id: first.track.sourceId)
                    let rest = fresh.questions.dropFirst().map(\.track)
                    Task {
                        for track in rest {
                            try? await APIClient.shared.prepareStream(source: track.source, id: track.sourceId)
                        }
                    }
                }
                round = fresh
                dailyPlayed = fresh.alreadyPlayed
                score = 0
                correct = 0
                streak = 0
                index = 0
                resumeMainPlayer = PlayerManager.shared.isPlaying
                PlayerManager.shared.pause()
                phase = .playing
                ask()
            } catch {
                errorMessage = error.localizedDescription
                phase = .menu
            }
        }
    }

    private func ask() {
        guard let round, round.questions.indices.contains(index) else { return finish() }
        picked = nil
        lastGain = 0
        remaining = Self.questionSeconds
        let q = round.questions[index]
        audioCut?.cancel()
        timer?.cancel()
        if q.isLyrics {
            playLyricsClip(q)
            return
        }
        listening = false
        if let url = URL(string: q.previewURL) {
            try? AVAudioSession.sharedInstance().setActive(true)
            let item = AVPlayerItem(url: url)
            if audio == nil { audio = AVPlayer() }
            audio?.replaceCurrentItem(with: item)
            // Un point de départ au hasard dans l'extrait : moins prévisible.
            audio?.seek(to: CMTime(seconds: Double.random(in: 0...8), preferredTimescale: 600))
            audio?.play()
        }
        if playingExpert {
            audioCut = Task {
                try? await Task.sleep(for: .seconds(Self.expertListenSeconds))
                guard !Task.isCancelled else { return }
                audio?.pause()
            }
        }
        startTimer(q)
    }

    /// Paroles : le titre complet joue ~10 s avant la ligne, s'arrête pile
    /// dessus, et le chrono démarre.
    private func playLyricsClip(_ q: BlindQuestion) {
        listening = true
        let lineTime = q.lineTime ?? 0
        if let request = try? APIClient.shared.streamRequest(source: q.track.source, id: q.track.sourceId) {
            try? AVAudioSession.sharedInstance().setActive(true)
            let asset = AVURLAsset(url: request.url, options: ["AVURLAssetHTTPHeaderFieldsKey": request.headers])
            if audio == nil { audio = AVPlayer() }
            audio?.replaceCurrentItem(with: AVPlayerItem(asset: asset))
            audio?.seek(to: CMTime(seconds: max(0, q.clipStart ?? 0), preferredTimescale: 600),
                        toleranceBefore: .zero, toleranceAfter: .zero)
            audio?.play()
        }
        audioCut = Task {
            let started = Date()
            while !Task.isCancelled {
                try? await Task.sleep(for: .milliseconds(80))
                let position = audio?.currentTime().seconds ?? 0
                // Garde-fou : un titre qui ne charge pas ne bloque pas la partie.
                if position >= lineTime - 0.05 || Date().timeIntervalSince(started) > 25 { break }
            }
            guard !Task.isCancelled else { return }
            listening = false
            guard picked == nil else { return }
            audio?.pause()
            startTimer(q)
        }
    }

    private func startTimer(_ q: BlindQuestion) {
        timer?.cancel()
        timer = Task {
            let start = Date()
            while !Task.isCancelled {
                try? await Task.sleep(for: .milliseconds(100))
                let left = max(0, Self.questionSeconds - Date().timeIntervalSince(start))
                remaining = left
                if left <= 0 {
                    answer(-1, question: q)
                    return
                }
            }
        }
    }

    private func answer(_ choice: Int, question q: BlindQuestion) {
        guard picked == nil else { return }
        timer?.cancel()
        withAnimation(Motion.snappy) {
            picked = choice
            if choice == q.answer {
                correct += 1
                streak += 1
                let base = 100 + Int(remaining * 10) + (streak >= 3 ? 50 : 0)
                lastGain = playingExpert ? base * 3 / 2 : base
                score += lastGain
            } else {
                streak = 0
            }
        }
        var pause = 1.6
        if q.isLyrics, let lineTime = q.lineTime {
            // La vraie fin de la ligne, chantée.
            audioCut?.cancel()
            listening = false
            audio?.seek(to: CMTime(seconds: max(0, lineTime - 0.3), preferredTimescale: 600),
                        toleranceBefore: .zero, toleranceAfter: .zero)
            audio?.play()
            pause = min(6, max(2.5, (q.revealEnd ?? lineTime + 3) - lineTime + 0.6))
        }
        Task {
            try? await Task.sleep(for: .seconds(pause))
            index += 1
            if let round, index < round.questions.count {
                withAnimation(Motion.smooth) { ask() }
            } else {
                finish()
            }
        }
    }

    private func finish() {
        stopAudio()
        withAnimation(Motion.smooth) { phase = .finished }
        let total = round?.questions.count ?? 0
        Task {
            try? await APIClient.shared.submitBlindScore(mode: mode, score: score, correct: correct, total: total)
            if mode == "daily" { dailyPlayed = true }
            await loadLeaderboard()
        }
    }

    private func stopAudio() {
        timer?.cancel()
        audioCut?.cancel()
        audio?.pause()
        audio = nil
        if resumeMainPlayer {
            resumeMainPlayer = false
            PlayerManager.shared.resume()
        }
    }

    private func loadLeaderboard() async {
        leaderboard = (try? await APIClient.shared.blindLeaderboard()) ?? leaderboard
    }
}

/// Choix du thème d'une partie : un artiste (recherche), une radio Deezer
/// ou une de tes playlists.
struct BlindSourcePicker: View {
    enum Kind: String, Identifiable {
        case artist, radio, playlist
        var id: String { rawValue }
        var mode: String { rawValue }
        var title: String {
            switch self {
            case .artist: "Choisis un artiste"
            case .radio: "Choisis une radio"
            case .playlist: "Choisis une playlist"
            }
        }
    }

    let kind: Kind
    let onPick: (String, String) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var query = ""
    @State private var artists: [Artist] = []
    @State private var radios: [RadioGroup] = []
    @State private var playlists: [UserPlaylist] = []
    @State private var loading = true

    var body: some View {
        NavigationStack {
            List {
                switch kind {
                case .artist:
                    ForEach(artists) { artist in
                        row(artist.name, subtitle: artist.fans.map { "\($0.formatted()) fans" }, image: artist.pictureURL, round: true) {
                            onPick(artist.sourceId, artist.name)
                        }
                    }
                case .radio:
                    ForEach(radios) { group in
                        Section(group.title) {
                            ForEach(group.radios) { radio in
                                row(radio.title, subtitle: nil, image: radio.pictureURL, round: false) {
                                    onPick(radio.id, radio.title)
                                }
                            }
                        }
                    }
                case .playlist:
                    ForEach(playlists.filter { $0.trackCount >= 4 }) { playlist in
                        row(playlist.name, subtitle: "\(playlist.trackCount) titres", image: playlist.coverURL ?? playlist.covers.first, round: false) {
                            onPick(String(playlist.id), playlist.name)
                        }
                    }
                }
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
            .background(Tone.background)
            .overlay {
                if loading && isEmpty {
                    ProgressView().tint(.white)
                } else if isEmpty && (kind != .artist || !query.isEmpty) {
                    Text(kind == .playlist ? "Aucune playlist d'au moins 4 titres." : "Rien trouvé.")
                        .font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
                }
            }
            .navigationTitle(kind.title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Annuler") { dismiss() } }
            }
            .modifier(ArtistSearch(enabled: kind == .artist, query: $query))
        }
        .task { await loadInitial() }
        .task(id: query) {
            guard kind == .artist, !query.trimmingCharacters(in: .whitespaces).isEmpty else { return }
            try? await Task.sleep(for: .milliseconds(300))
            guard !Task.isCancelled else { return }
            loading = true
            if let found = try? await APIClient.shared.searchArtists(query: query, limit: 15) {
                artists = found.filter { $0.source == "deezer" }
            }
            loading = false
        }
    }

    private var isEmpty: Bool {
        switch kind {
        case .artist: artists.isEmpty
        case .radio: radios.isEmpty
        case .playlist: playlists.isEmpty
        }
    }

    private func row(_ title: String, subtitle: String?, image: String?, round: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Artwork(url: image, cornerRadius: round ? 24 : 8, symbol: round ? "music.mic" : "music.note.list")
                    .frame(width: 48, height: 48)
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).font(Typo.rowTitle).foregroundStyle(Tone.primary).lineLimit(1)
                    if let subtitle {
                        Text(subtitle).font(Typo.rowSubtitle).foregroundStyle(Tone.secondary).lineLimit(1)
                    }
                }
                Spacer()
                Image(systemName: "play.circle.fill").font(.system(size: 22)).foregroundStyle(Tone.secondary)
            }
        }
        .listRowBackground(Color.clear)
    }

    private func loadInitial() async {
        switch kind {
        case .artist:
            break
        case .radio:
            radios = (try? await APIClient.shared.radioGroups()) ?? []
        case .playlist:
            playlists = (try? await APIClient.shared.playlists()) ?? []
        }
        loading = false
    }
}

/// Barre de recherche, seulement pour le choix d'un artiste.
private struct ArtistSearch: ViewModifier {
    let enabled: Bool
    @Binding var query: String

    @ViewBuilder
    func body(content: Content) -> some View {
        if enabled {
            content.searchable(text: $query, placement: .navigationBarDrawer(displayMode: .always), prompt: "Artiste")
        } else {
            content
        }
    }
}
