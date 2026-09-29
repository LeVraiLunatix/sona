import AVFoundation
import SwiftUI

/// Blind test en direct entre amis : tout le monde entend le même extrait au
/// même moment et répond sur son téléphone ; classement en direct.
/// Le serveur mène le déroulé (voir `app/services/blindlive.py`), l'app
/// relit l'état chaque seconde et cale son horloge sur la sienne.
struct BlindLiveView: View {
    /// Code d'une partie à rejoindre ; `nil` : on en crée une.
    let joinCode: String?

    @Environment(\.dismiss) private var dismiss
    @State private var state: LiveState?
    @State private var errorMessage: String?
    @State private var ended = false
    /// Heure serveur − heure du téléphone.
    @State private var clockOffset: Double = 0
    @State private var audio = AVPlayer()
    @State private var loadedIndex: Int?
    @State private var playTask: Task<Void, Never>?
    @State private var resumeMainPlayer = false
    @State private var picking: BlindSourcePicker.Kind?
    @State private var confirmingLeave = false
    @State private var isStarting = false
    @State private var pendingChoice: Int?
    /// Paroles : question dont la fin de ligne a déjà été rejouée.
    @State private var revealedIndex: Int?

    var body: some View {
        NavigationStack {
            ZStack {
                LinearGradient(
                    colors: [Color(red: 0.3, green: 0.05, blue: 0.2), Tone.background],
                    startPoint: .top, endPoint: .bottom
                )
                .ignoresSafeArea()

                if let state {
                    content(state)
                } else if ended || errorMessage != nil {
                    VStack(spacing: 16) {
                        EmptyState(
                            systemImage: "flag.checkered",
                            title: ended ? "Partie terminée" : "Impossible de rejoindre",
                            message: errorMessage ?? "L'hôte a fermé la partie."
                        )
                        PillButton(title: "Fermer", systemImage: "xmark") { close() }
                    }
                    .padding(24)
                } else {
                    ProgressView().tint(.white)
                }
            }
            .navigationTitle("Blind test en direct")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(state?.isHost == true ? "Terminer" : "Quitter") {
                        if state?.isHost == true && state?.players.count ?? 0 > 1 {
                            confirmingLeave = true
                        } else {
                            Task { await leave() }
                        }
                    }
                }
            }
            .confirmationDialog("Terminer la partie pour tout le monde ?", isPresented: $confirmingLeave, titleVisibility: .visible) {
                Button("Terminer", role: .destructive) { Task { await leave() } }
            }
        }
        .sheet(item: $picking) { kind in
            BlindSourcePicker(kind: kind) { id, label in
                picking = nil
                Task { await configure(mode: kind.mode, ref: id, label: label) }
            }
            .presentationDetents([.medium, .large])
        }
        .task { await run() }
        .onDisappear { stopAudio() }
    }

    // MARK: - Écrans

    @ViewBuilder
    private func content(_ state: LiveState) -> some View {
        switch state.phase {
        case "question", "reveal":
            if let question = state.question {
                questionView(state, question)
            }
        case "finished":
            finishedView(state)
        default:
            lobby(state)
        }
    }

    private func lobby(_ state: LiveState) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                VStack(spacing: 6) {
                    Text("Code de la partie").font(Typo.caption).foregroundStyle(Tone.secondary)
                    Text(state.code)
                        .font(.system(size: 46, weight: .heavy, design: .rounded))
                        .tracking(8)
                        .foregroundStyle(Tone.primary)
                    ShareLink(item: "Rejoins mon blind test sur Sona : code \(state.code)") {
                        Label("Inviter", systemImage: "square.and.arrow.up").font(Typo.rowTitle)
                    }
                    .tint(.white)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 18)
                .background(RoundedRectangle(cornerRadius: 24, style: .continuous).fill(Tone.surface))

                playersGrid(state)

                themeSummary(state)

                if state.isHost {
                    hostSettings(state)
                    PillButton(
                        title: state.players.count > 1 ? "Lancer la partie" : "Lancer (seul pour l'instant)",
                        systemImage: "play.fill", isLoading: isStarting
                    ) {
                        Task { await start() }
                    }
                    .frame(maxWidth: .infinity)
                } else {
                    HStack(spacing: 10) {
                        ProgressView().tint(.white)
                        Text("\(state.hostName ?? "L'hôte") choisit le thème et lance la partie…")
                            .font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
                    }
                    .frame(maxWidth: .infinity)
                }

                if let errorMessage {
                    Text(errorMessage).font(Typo.rowSubtitle).foregroundStyle(Tone.danger)
                }
            }
            .padding(20)
        }
    }

    private func playersGrid(_ state: LiveState) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(state.players.count == 1 ? "1 joueur" : "\(state.players.count) joueurs")
                .font(Typo.headline).foregroundStyle(Tone.primary)
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 10), count: 4), spacing: 14) {
                ForEach(state.players) { player in
                    VStack(spacing: 6) {
                        Artwork(url: player.avatarURL, cornerRadius: 28, symbol: "person.fill")
                            .frame(width: 56, height: 56)
                            .overlay(alignment: .bottomTrailing) {
                                if player.isHost {
                                    Image(systemName: "crown.fill")
                                        .font(.system(size: 12))
                                        .foregroundStyle(.yellow)
                                        .padding(4)
                                        .background(Circle().fill(.black))
                                }
                            }
                        Text(player.isMe ? "Toi" : player.name)
                            .font(Typo.caption).foregroundStyle(Tone.secondary).lineLimit(1)
                    }
                    .transition(.scale.combined(with: .opacity))
                }
            }
            .animation(Motion.bouncy, value: state.players.map(\.name))
        }
    }

    private func themeSummary(_ state: LiveState) -> some View {
        HStack(spacing: 12) {
            Image(systemName: icon(for: state.mode))
                .font(.system(size: 20, weight: .bold))
                .foregroundStyle(.white)
                .frame(width: 44, height: 44)
                .background(Circle().fill(Tone.surfaceStrong))
            VStack(alignment: .leading, spacing: 2) {
                Text(state.label ?? themeName(state.mode)).font(Typo.headline).foregroundStyle(Tone.primary).lineLimit(1)
                Text("\(state.count) extraits · \(guessLabel(state.guess))")
                    .font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
            }
            Spacer()
        }
        .padding(14)
        .background(RoundedRectangle(cornerRadius: 20, style: .continuous).fill(Tone.surface))
    }

    private func hostSettings(_ state: LiveState) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Thème").font(Typo.headline).foregroundStyle(Tone.primary)
            ScrollView(.horizontal) {
                HStack(spacing: 10) {
                    themeChip("Vos titres", "person.3.fill", selected: state.mode == "solo") {
                        Task { await configure(mode: "solo", ref: nil, label: "Vos titres") }
                    }
                    themeChip("Top du moment", "chart.line.uptrend.xyaxis", selected: state.mode == "chart") {
                        Task { await configure(mode: "chart", ref: nil, label: "Top du moment") }
                    }
                    themeChip("Un artiste", "music.mic", selected: state.mode == "artist") { picking = .artist }
                    themeChip("Une radio", "dot.radiowaves.left.and.right", selected: state.mode == "radio") { picking = .radio }
                    themeChip("Une playlist", "music.note.list", selected: state.mode == "playlist") { picking = .playlist }
                    themeChip("Surprise", "dice.fill", selected: false) { Task { await surprise() } }
                }
            }
            .scrollIndicators(.hidden)
            Picker("Extraits", selection: Binding(
                get: { state.count },
                set: { value in Task { await configure(count: value) } }
            )) {
                Text("5").tag(5)
                Text("10").tag(10)
                Text("15").tag(15)
                Text("20").tag(20)
            }
            .pickerStyle(.segmented)
            Picker("À trouver", selection: Binding(
                get: { state.guess },
                set: { value in Task { await configure(guess: value) } }
            )) {
                Text("Le titre").tag("title")
                Text("L'artiste").tag("artist")
                Text("Paroles").tag("lyrics")
            }
            .pickerStyle(.segmented)
        }
    }

    private func guessLabel(_ guess: String) -> String {
        switch guess {
        case "artist": "trouver l'artiste"
        case "lyrics": "compléter les paroles"
        default: "trouver le titre"
        }
    }

    private func themeChip(_ title: String, _ icon: String, selected: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Label(title, systemImage: icon)
                .font(Typo.rowTitle)
                .foregroundStyle(selected ? .black : Tone.primary)
                .padding(.horizontal, 14)
                .padding(.vertical, 10)
                .background(Capsule().fill(selected ? Color.white : Tone.surfaceStrong))
        }
        .buttonStyle(.pressable(scale: 0.95))
    }

    // MARK: Question

    private func questionView(_ state: LiveState, _ question: LiveQuestion) -> some View {
        let reveal = state.phase == "reveal"
        return VStack(spacing: 18) {
            HStack {
                Text("\(question.index + 1) / \(state.total)").font(Typo.caption).foregroundStyle(Tone.secondary)
                Spacer()
                if let me = state.players.first(where: \.isMe) {
                    if me.streak >= 3 {
                        Label("×\(me.streak)", systemImage: "flame.fill").font(Typo.caption).foregroundStyle(.orange)
                    }
                    Text("\(me.score) pts").font(.system(size: 17, weight: .bold)).foregroundStyle(Tone.primary)
                        .contentTransition(.numericText(value: Double(me.score)))
                }
            }

            TimelineView(.periodic(from: .now, by: 0.1)) { context in
                let now = context.date.timeIntervalSince1970 + clockOffset
                timerRing(state: state, question: question, now: now, reveal: reveal)
            }
            .frame(width: question.isLyrics ? 110 : 170, height: question.isLyrics ? 110 : 170)

            if question.isLyrics {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(Array((question.before ?? []).enumerated()), id: \.offset) { _, line in
                        Text(line).font(.system(size: 16, weight: .semibold)).foregroundStyle(Tone.tertiary)
                    }
                    Text(question.prompt ?? "…")
                        .font(.system(size: 22, weight: .heavy))
                        .foregroundStyle(Tone.primary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(16)
                .background(RoundedRectangle(cornerRadius: 20, style: .continuous).fill(Tone.surface))
            }

            if reveal, let track = question.track {
                VStack(spacing: 2) {
                    Text(track.title).font(Typo.headline).foregroundStyle(Tone.primary).lineLimit(1)
                    Text(track.artist).font(Typo.rowSubtitle).foregroundStyle(Tone.secondary).lineLimit(1)
                }
                .transition(.opacity)
            }

            VStack(spacing: 10) {
                ForEach(Array(question.choices.enumerated()), id: \.offset) { index, choice in
                    Button { Task { await answer(index, question: question) } } label: {
                        VStack(alignment: .leading, spacing: 2) {
                            if choice.title.isEmpty {
                                Text(choice.artist).font(Typo.headline).lineLimit(1)
                            } else {
                                Text(choice.title).font(Typo.headline).lineLimit(question.isLyrics ? 2 : 1)
                                if !choice.artist.isEmpty {
                                    Text(choice.artist).font(Typo.rowSubtitle).opacity(0.75).lineLimit(1)
                                }
                            }
                        }
                        .foregroundStyle(choiceForeground(index, question))
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal, 16)
                        .frame(height: 58)
                        .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(choiceBackground(index, question)))
                    }
                    .buttonStyle(.pressable(scale: 0.97))
                    .disabled(reveal || question.myChoice != nil || pendingChoice != nil)
                }
            }

            liveRanking(state, reveal: reveal)
            Spacer(minLength: 0)
        }
        .padding(20)
        .animation(Motion.smooth, value: reveal)
        .sensoryFeedback(trigger: reveal) { _, isReveal in
            guard isReveal, let mine = question.myChoice, let answer = question.answer else { return nil }
            return mine == answer ? .success : .error
        }
    }

    @ViewBuilder
    private func timerRing(state: LiveState, question: LiveQuestion, now: Double, reveal: Bool) -> some View {
        let startsAt = state.startsAt ?? now
        let deadline = state.deadline ?? now
        let total = max(1, deadline - startsAt)
        let remaining = max(0, min(total, deadline - now))
        ZStack {
            Circle().stroke(Color.white.opacity(0.12), lineWidth: 10)
            if !reveal {
                Circle()
                    .trim(from: 0, to: now < startsAt ? 1 : remaining / total)
                    .stroke(remaining > 8 ? Color.white : (remaining > 4 ? .orange : .red),
                            style: StrokeStyle(lineWidth: 10, lineCap: .round))
                    .rotationEffect(.degrees(-90))
            }
            if reveal {
                Artwork(url: question.coverURL, cornerRadius: 75)
                    .frame(width: 140, height: 140)
                    .transition(.scale.combined(with: .opacity))
            } else if now < startsAt {
                VStack(spacing: 2) {
                    Text("Prêt ?").font(Typo.caption).foregroundStyle(Tone.secondary)
                    Text("\(Int((startsAt - now).rounded(.up)))")
                        .font(.system(size: 48, weight: .heavy)).foregroundStyle(Tone.primary).monospacedDigit()
                }
            } else if question.myChoice != nil || pendingChoice != nil {
                VStack(spacing: 4) {
                    Image(systemName: "checkmark.circle.fill").font(.system(size: 34)).foregroundStyle(.white)
                    Text("\(question.answered)/\(state.players.count) ont répondu")
                        .font(Typo.caption).foregroundStyle(Tone.secondary)
                }
            } else {
                VStack(spacing: 4) {
                    EqualizerBars(isAnimating: true).frame(width: 46, height: 40)
                    Text("\(Int(remaining.rounded(.up)))")
                        .font(.system(size: 30, weight: .heavy)).foregroundStyle(Tone.primary).monospacedDigit()
                }
            }
        }
    }

    private func liveRanking(_ state: LiveState, reveal: Bool) -> some View {
        VStack(spacing: 6) {
            ForEach(Array(state.players.prefix(6).enumerated()), id: \.element.id) { rank, player in
                HStack(spacing: 10) {
                    Text("\(rank + 1)").font(Typo.caption).foregroundStyle(Tone.tertiary).frame(width: 18)
                    Artwork(url: player.avatarURL, cornerRadius: 13, symbol: "person.fill").frame(width: 26, height: 26)
                    Text(player.isMe ? "Toi" : player.name)
                        .font(Typo.rowSubtitle).foregroundStyle(player.isMe ? Tone.primary : Tone.secondary).lineLimit(1)
                    Spacer()
                    if reveal, let gained = player.gained, gained > 0 {
                        Text("+\(gained)").font(Typo.caption).foregroundStyle(.green)
                            .transition(.move(edge: .trailing).combined(with: .opacity))
                    } else if reveal, player.wasRight == false || player.gained == nil {
                        Image(systemName: "xmark").font(Typo.caption).foregroundStyle(Tone.danger)
                    } else if player.answered {
                        Image(systemName: "checkmark").font(Typo.caption).foregroundStyle(Tone.secondary)
                    }
                    Text("\(player.score)").font(.system(size: 15, weight: .bold)).foregroundStyle(Tone.primary)
                        .monospacedDigit()
                        .contentTransition(.numericText(value: Double(player.score)))
                }
            }
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(Tone.surface))
        .animation(Motion.snappy, value: state.players)
    }

    private func choiceBackground(_ index: Int, _ question: LiveQuestion) -> Color {
        let mine = question.myChoice ?? pendingChoice
        if let answer = question.answer {
            if index == answer { return Color.green.opacity(0.85) }
            if index == mine { return Color.red.opacity(0.8) }
            return Tone.surface
        }
        if let mine { return index == mine ? Color.white.opacity(0.3) : Tone.surface }
        return Tone.surfaceStrong
    }

    private func choiceForeground(_ index: Int, _ question: LiveQuestion) -> Color {
        let mine = question.myChoice ?? pendingChoice
        guard question.answer != nil || mine != nil else { return Tone.primary }
        return index == question.answer || index == mine ? .white : Tone.tertiary
    }

    // MARK: Fin

    private func finishedView(_ state: LiveState) -> some View {
        ScrollView {
            VStack(spacing: 22) {
                podium(Array(state.players.prefix(3)))
                    .padding(.top, 10)

                VStack(spacing: 8) {
                    ForEach(Array(state.players.enumerated()), id: \.element.id) { rank, player in
                        HStack(spacing: 12) {
                            Text("\(rank + 1)").font(.system(size: 15, weight: .bold)).foregroundStyle(Tone.secondary).frame(width: 24)
                            Artwork(url: player.avatarURL, cornerRadius: 18, symbol: "person.fill").frame(width: 36, height: 36)
                            Text(player.isMe ? "Toi" : player.name).font(Typo.rowTitle).foregroundStyle(Tone.primary)
                            Spacer()
                            Text("\(player.correct)/\(state.total)").font(Typo.caption).foregroundStyle(Tone.tertiary)
                            Text("\(player.score)").font(.system(size: 17, weight: .bold)).foregroundStyle(Tone.primary).monospacedDigit()
                        }
                    }
                }
                .padding(16)
                .background(RoundedRectangle(cornerRadius: 20, style: .continuous).fill(Tone.surface))

                if state.isHost {
                    PillButton(title: "Revanche", systemImage: "arrow.clockwise", isLoading: isStarting) {
                        Task { await start() }
                    }
                    hostSettings(state)
                } else {
                    Text("\(state.hostName ?? "L'hôte") peut lancer une revanche.")
                        .font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
                }
                if !state.tracks.isEmpty {
                    PillButton(title: "Écouter les titres", systemImage: "music.note.list", kind: .secondary) {
                        PlayerManager.shared.play(state.tracks[0], context: state.tracks, name: "Blind test")
                        resumeMainPlayer = false
                        Task { await leave() }
                    }
                }
                if let errorMessage {
                    Text(errorMessage).font(Typo.rowSubtitle).foregroundStyle(Tone.danger)
                }
            }
            .padding(20)
        }
    }

    private func podium(_ top: [LivePlayer]) -> some View {
        let order = top.count == 3 ? [1, 0, 2] : Array(top.indices)
        return HStack(alignment: .bottom, spacing: 12) {
            ForEach(order, id: \.self) { rank in
                let player = top[rank]
                VStack(spacing: 8) {
                    Text(["🥇", "🥈", "🥉"][rank]).font(.system(size: rank == 0 ? 40 : 30))
                    Artwork(url: player.avatarURL, cornerRadius: rank == 0 ? 36 : 28, symbol: "person.fill")
                        .frame(width: rank == 0 ? 72 : 56, height: rank == 0 ? 72 : 56)
                    Text(player.isMe ? "Toi" : player.name).font(Typo.rowTitle).foregroundStyle(Tone.primary).lineLimit(1)
                    Text("\(player.score) pts").font(Typo.caption).foregroundStyle(Tone.secondary)
                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                        .fill(Color.white.opacity(rank == 0 ? 0.25 : 0.12))
                        .frame(height: CGFloat([110, 80, 60][rank]))
                }
                .frame(maxWidth: .infinity)
            }
        }
    }

    // MARK: - Déroulé

    private func run() async {
        resumeMainPlayer = PlayerManager.shared.isPlaying
        PlayerManager.shared.pause()
        do {
            let first: LiveState
            if let joinCode {
                first = try await APIClient.shared.joinLive(code: joinCode)
            } else {
                first = try await APIClient.shared.createLive()
            }
            apply(first, sentAt: Date())
        } catch {
            errorMessage = error.localizedDescription
            return
        }
        while !Task.isCancelled, let code = state?.code {
            try? await Task.sleep(for: .milliseconds(state?.phase == "lobby" ? 1500 : 800))
            guard !Task.isCancelled else { return }
            let sentAt = Date()
            do {
                apply(try await APIClient.shared.liveState(code: code), sentAt: sentAt)
            } catch APIError.server(let status, _) where status == 404 || status == 403 {
                stopAudio()
                state = nil
                ended = true
                return
            } catch {
                // Réseau capricieux : on réessaie au tour suivant.
            }
        }
    }

    private func apply(_ fresh: LiveState, sentAt: Date) {
        // Heure serveur au milieu de l'aller-retour.
        let received = Date()
        let midpoint = (sentAt.timeIntervalSince1970 + received.timeIntervalSince1970) / 2
        let offset = fresh.serverTime - midpoint
        clockOffset = state == nil ? offset : clockOffset * 0.7 + offset * 0.3
        if fresh.question?.index != state?.question?.index || fresh.phase != state?.phase {
            pendingChoice = nil
        }
        withAnimation(Motion.smooth) { state = fresh }
        syncAudio(fresh)
    }

    /// Charge l'extrait dès qu'il est connu et le lance à l'heure prévue.
    private func syncAudio(_ state: LiveState) {
        if state.phase == "reveal", let question = state.question, question.isLyrics {
            revealLyrics(question)
            return
        }
        guard state.phase == "question", let question = state.question, let startsAt = state.startsAt else {
            if state.phase == "lobby" || state.phase == "finished" { audio.pause() }
            return
        }
        guard loadedIndex != question.index else { return }
        let item: AVPlayerItem
        if question.isLyrics, let stream = question.stream,
           let request = try? APIClient.shared.streamRequest(source: stream.source, id: stream.sourceId) {
            // Paroles : le titre complet, de `clipStart` jusqu'à la ligne.
            Task { try? await APIClient.shared.prepareStream(source: stream.source, id: stream.sourceId) }
            item = AVPlayerItem(asset: AVURLAsset(url: request.url, options: ["AVURLAssetHTTPHeaderFieldsKey": request.headers]))
        } else if let url = URL(string: question.previewURL) {
            item = AVPlayerItem(url: url)
        } else {
            return
        }
        loadedIndex = question.index
        try? AVAudioSession.sharedInstance().setActive(true)
        audio.pause()
        audio.replaceCurrentItem(with: item)
        playTask?.cancel()
        let offset = clockOffset
        let clipStart = question.isLyrics ? max(0, question.clipStart ?? 0) : 0
        let lineTime = question.isLyrics ? question.lineTime : nil
        playTask = Task {
            let delay = startsAt - (Date().timeIntervalSince1970 + offset)
            if delay > 0 { try? await Task.sleep(for: .seconds(delay)) }
            guard !Task.isCancelled else { return }
            // En retard (rejoint en cours) : on se cale sur les autres.
            let late = max(0, -delay)
            if late > 0.3 || clipStart > 0 {
                _ = await audio.seek(to: CMTime(seconds: clipStart + late, preferredTimescale: 600),
                                     toleranceBefore: .zero, toleranceAfter: .zero)
            }
            audio.play()
            guard let lineTime else { return }
            // Arrêt pile sur la ligne à compléter.
            while !Task.isCancelled {
                try? await Task.sleep(for: .milliseconds(80))
                if audio.currentTime().seconds >= lineTime - 0.05 { break }
            }
            guard !Task.isCancelled else { return }
            audio.pause()
        }
    }

    /// Correction d'une question de paroles : la vraie fin de la ligne.
    private func revealLyrics(_ question: LiveQuestion) {
        guard revealedIndex != question.index, let lineTime = question.lineTime else { return }
        revealedIndex = question.index
        playTask?.cancel()
        let end = question.revealEnd ?? lineTime + 4
        playTask = Task {
            _ = await audio.seek(to: CMTime(seconds: max(0, lineTime - 0.3), preferredTimescale: 600),
                                 toleranceBefore: .zero, toleranceAfter: .zero)
            guard !Task.isCancelled else { return }
            audio.play()
            try? await Task.sleep(for: .seconds(min(5, max(1.5, end - lineTime + 0.5))))
            guard !Task.isCancelled else { return }
            audio.pause()
        }
    }

    private func answer(_ choice: Int, question: LiveQuestion) async {
        guard let code = state?.code, pendingChoice == nil else { return }
        pendingChoice = choice
        do {
            let fresh = try await APIClient.shared.answerLive(code: code, index: question.index, choice: choice)
            apply(fresh, sentAt: Date())
        } catch {
            // Trop tard (la correction est tombée entre-temps) : rien à faire.
        }
    }

    private func configure(mode: String? = nil, ref: String? = nil, label: String? = nil, count: Int? = nil, guess: String? = nil) async {
        guard let current = state else { return }
        let newMode = mode ?? current.mode
        do {
            let fresh = try await APIClient.shared.configureLive(
                code: current.code,
                mode: newMode,
                ref: mode == nil ? current.ref : ref,
                label: mode == nil ? current.label : label,
                count: count ?? current.count,
                guess: guess ?? current.guess
            )
            errorMessage = nil
            apply(fresh, sentAt: Date())
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func surprise() async {
        if let radio = (try? await APIClient.shared.radioGroups())?.flatMap(\.radios).randomElement() {
            await configure(mode: "radio", ref: radio.id, label: radio.title)
        } else {
            await configure(mode: "chart", ref: nil, label: "Top du moment")
        }
    }

    private func start() async {
        guard let code = state?.code else { return }
        isStarting = true
        defer { isStarting = false }
        do {
            loadedIndex = nil
            apply(try await APIClient.shared.startLive(code: code), sentAt: Date())
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func leave() async {
        if let code = state?.code {
            try? await APIClient.shared.leaveLive(code: code)
        }
        close()
    }

    private func close() {
        stopAudio()
        dismiss()
    }

    private func stopAudio() {
        playTask?.cancel()
        audio.pause()
        if resumeMainPlayer {
            resumeMainPlayer = false
            PlayerManager.shared.resume()
        }
    }

    private func themeName(_ mode: String) -> String {
        switch mode {
        case "chart": "Top du moment"
        case "artist": "Un artiste"
        case "radio": "Une radio"
        case "playlist": "Une playlist"
        default: "Vos titres"
        }
    }

    private func icon(for mode: String) -> String {
        switch mode {
        case "chart": "chart.line.uptrend.xyaxis"
        case "artist": "music.mic"
        case "radio": "dot.radiowaves.left.and.right"
        case "playlist": "music.note.list"
        default: "person.3.fill"
        }
    }
}

/// Ouverture d'une partie en direct : création (`code == nil`) ou code.
struct LiveLaunch: Identifiable {
    let id = UUID()
    let code: String?
}

/// Partie d'un ami à rejoindre (onglet Amis, menu du blind test).
struct LiveSummaryRow: View {
    let summary: LiveSummary
    let onJoin: () -> Void

    var body: some View {
        Button(action: onJoin) {
            HStack(spacing: 12) {
                Artwork(url: summary.hostAvatarURL, cornerRadius: 22, symbol: "person.fill")
                    .frame(width: 44, height: 44)
                VStack(alignment: .leading, spacing: 2) {
                    Text("\(summary.hostName ?? "Un ami") lance un blind test")
                        .font(Typo.rowTitle).foregroundStyle(Tone.primary).lineLimit(1)
                    Text([summary.label, "\(summary.players) joueur\(summary.players > 1 ? "s" : "")",
                          summary.phase == "lobby" ? "en attente" : "en cours"]
                        .compactMap { $0 }.joined(separator: " · "))
                        .font(Typo.caption).foregroundStyle(Tone.secondary).lineLimit(1)
                }
                Spacer()
                Text("Rejoindre")
                    .font(Typo.caption)
                    .foregroundStyle(.black)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 7)
                    .background(Capsule().fill(.white))
            }
            .padding(12)
            .background(RoundedRectangle(cornerRadius: 18, style: .continuous).fill(Tone.surface))
        }
        .buttonStyle(.pressable(scale: 0.98))
    }
}
