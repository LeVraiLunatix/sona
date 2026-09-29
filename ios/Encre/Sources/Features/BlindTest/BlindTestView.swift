import AVFoundation
import SwiftUI

/// Blind test : un extrait, quatre propositions, 15 s. Plus on répond vite,
/// plus on marque (et une série de bonnes réponses rapporte un bonus).
/// Défi du jour identique pour tout le monde, avec classement.
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

    static let questionSeconds: Double = 15

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
        .onDisappear { stopAudio() }
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
                    Text("Trouve le titre").font(.system(size: 30, weight: .heavy)).foregroundStyle(Tone.primary)
                    Text("10 extraits tirés de vos écoutes, à toi et tes amis. 15 secondes par titre : plus tu es rapide, plus tu marques.")
                        .font(Typo.body)
                        .foregroundStyle(Tone.secondary)
                }

                modeCard(
                    title: "Défi du jour",
                    subtitle: dailyPlayed ? "Déjà joué aujourd'hui : rejoue pour le plaisir (ne compte plus)" : "Les mêmes extraits pour tout le monde · classement",
                    icon: "calendar", highlighted: true
                ) { start("daily") }

                modeCard(title: "Partie libre", subtitle: "Un nouveau tirage à chaque fois", icon: "shuffle", highlighted: false) {
                    start("solo")
                }

                if !leaderboard.isEmpty { leaderboardView(title: "Classement du jour") }
                if let errorMessage {
                    Text(errorMessage).font(Typo.rowSubtitle).foregroundStyle(Tone.danger)
                }
            }
            .padding(20)
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
                    Text("\(index + 1) / \(round.questions.count)").font(Typo.caption).foregroundStyle(Tone.secondary)
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

                if let picked, lastGain > 0, picked == q.answer {
                    Text("+\(lastGain)").font(.system(size: 22, weight: .heavy)).foregroundStyle(.green)
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                }

                VStack(spacing: 10) {
                    ForEach(Array(q.choices.enumerated()), id: \.offset) { choiceIndex, choice in
                        Button { answer(choiceIndex, question: q) } label: {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(choice.title).font(Typo.headline).lineLimit(1)
                                Text(choice.artist).font(Typo.rowSubtitle).opacity(0.75).lineLimit(1)
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

                HStack(spacing: 12) {
                    PillButton(title: "Rejouer", systemImage: "arrow.clockwise") { start("solo") }
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

    private func start(_ newMode: String) {
        mode = newMode
        phase = .loading
        errorMessage = nil
        Task {
            do {
                let fresh = try await APIClient.shared.blindRound(mode: newMode)
                guard fresh.questions.count >= 3 else {
                    errorMessage = "Pas assez de titres avec extrait pour l'instant : écoute encore un peu de musique !"
                    phase = .menu
                    return
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
        if let url = URL(string: q.previewURL) {
            try? AVAudioSession.sharedInstance().setActive(true)
            let item = AVPlayerItem(url: url)
            if audio == nil { audio = AVPlayer() }
            audio?.replaceCurrentItem(with: item)
            // Un point de départ au hasard dans l'extrait : moins prévisible.
            audio?.seek(to: CMTime(seconds: Double.random(in: 0...8), preferredTimescale: 600))
            audio?.play()
        }
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
                lastGain = 100 + Int(remaining * 10) + (streak >= 3 ? 50 : 0)
                score += lastGain
            } else {
                streak = 0
            }
        }
        Task {
            try? await Task.sleep(for: .seconds(1.6))
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
