import SwiftUI

/// Lecteur plein écran, dans l'esprit de Musique : fond vivant aux
/// couleurs de la pochette, pochette qui se rétracte en pause, barre de
/// progression qui s'épaissit sous le doigt, paroles synchronisées floutées
/// autour de la ligne chantée. Passer aux paroles ou à la file fait glisser
/// la pochette en en-tête compact (même élément, animé d'une place à
/// l'autre).
struct FullPlayerView: View {
    @ObservedObject var player: PlayerManager
    /// Ferme le lecteur et ouvre une fiche dans l'onglet actif.
    var onOpenRoute: (Route) -> Void
    @Environment(\.dismiss) private var dismiss

    private enum Panel: Equatable { case artwork, lyrics, queue }
    @State private var panel: Panel = .artwork
    @State private var palette: [Color] = ArtworkPalette.fallback
    @State private var isLiked = false
    @State private var likeBounce = 0
    @State private var isStartingRadio = false
    @State private var playlistPick: PlaylistPickRequest?
    @State private var confirmingWrongVersion = false
    @State private var showingSound = false
    @State private var storyTrack: Track?
    @State private var momentRequest: MomentRequest?
    @State private var moments: [TrackMoment] = []
    @ObservedObject private var gestures = HeadGestures.shared
    /// Paroles : commandes du bas masquées après quelques secondes sans
    /// toucher l'écran (comme Musique) ; un tap les ramène.
    @State private var controlsHidden = false
    @State private var activity = 0
    @State private var scrubbing = false
    @Namespace private var hero

    private struct AutoHideKey: Equatable {
        var panel: Panel
        var activity: Int
        var playing: Bool
        var scrubbing: Bool
    }

    var body: some View {
        ZStack {
            LivingBackground(colors: palette, animated: player.isPlaying)
                .id(palette)
                .transition(.opacity)

            if let track = player.current {
                VStack(spacing: 0) {
                    topBar
                    Group {
                        switch panel {
                        case .artwork:
                            artworkPanel(track)
                                .overlay(alignment: .bottomLeading) {
                                    MomentsOverlay(player: player, moments: moments).padding(.bottom, 8)
                                }
                        case .lyrics:
                            compactPanel(track) {
                                LyricsView(player: player, track: track)
                                    .simultaneousGesture(TapGesture().onEnded { revealControls() })
                            }
                        case .queue: compactPanel(track) { queueList }
                        }
                    }
                    .frame(maxHeight: .infinity)

                    if !(controlsHidden && panel == .lyrics) {
                        controls(track)
                            .transition(.move(edge: .bottom).combined(with: .opacity))
                    }
                }
                .padding(.horizontal, 26)
                .padding(.bottom, 8)
            } else {
                EmptyState(systemImage: "music.note", title: "Rien en lecture")
            }
        }
        .animation(.easeInOut(duration: 0.9), value: palette)
        .task(id: player.current?.coverURL) {
            let colors = await ArtworkPalette.colors(for: player.current?.coverURL)
            palette = colors
        }
        .task(id: player.current?.id) { await refreshLikeState() }
        .task(id: player.current?.id) { await loadMoments() }
        .overlay(alignment: .top) {
            if let gesture = gestures.lastGesture {
                Label(gesture, systemImage: "airpods")
                    .font(Typo.rowTitle)
                    .foregroundStyle(.black)
                    .padding(.horizontal, 16).padding(.vertical, 10)
                    .background(Capsule().fill(.white))
                    .padding(.top, 60)
                    .transition(.move(edge: .top).combined(with: .opacity))
            }
        }
        .sheet(isPresented: $showingSound) { SoundSettingsSheet(player: player) }
        .sheet(item: $storyTrack) { track in StoryShareSheet(track: track) }
        .sheet(item: $momentRequest) { request in
            AddMomentSheet(track: request.track, position: request.position) {
                Task { await loadMoments() }
            }
        }
        .task(id: AutoHideKey(panel: panel, activity: activity, playing: player.isPlaying, scrubbing: scrubbing)) {
            guard panel == .lyrics, player.isPlaying, !scrubbing else {
                if controlsHidden { withAnimation(Motion.smooth) { controlsHidden = false } }
                return
            }
            try? await Task.sleep(for: .seconds(4))
            guard !Task.isCancelled else { return }
            withAnimation(.easeInOut(duration: 0.5)) { controlsHidden = true }
        }
        // Feuille à part : celle de `RootTabView` ne peut pas s'ouvrir par-dessus
        // ce plein écran.
        .sheet(item: $playlistPick) { request in
            AddToPlaylistSheet(tracks: request.tracks)
        }
        .confirmationDialog(
            "Ce n'est pas la bonne version ?", isPresented: $confirmingWrongVersion, titleVisibility: .visible
        ) {
            Button("Chercher une autre version") {
                if let track = player.current { Task { await reportWrongVersion(track) } }
            }
        } message: {
            Text("Clip avec bruitages, live, remix… Cette source sera écartée pour de bon et le titre relancé avec une autre.")
        }
        .onChange(of: player.current == nil) { _, isEmpty in
            if isEmpty { dismiss() }
        }
    }

    private func revealControls() {
        withAnimation(Motion.smooth) { controlsHidden = false }
        activity += 1
    }

    // MARK: - Haut

    private var topBar: some View {
        HStack {
            Button { dismiss() } label: {
                Image(systemName: "chevron.down")
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(Tone.primary)
                    .frame(width: 40, height: 40)
            }
            .buttonStyle(.pressable(scale: 0.85))
            Spacer()
            VStack(spacing: 6) {
                Capsule().fill(Color.white.opacity(0.35)).frame(width: 38, height: 5)
                sleepBadge
                if player.isMixing {
                    // Enchaînement AutoMix en cours (tempo calé si différent).
                    Label(
                        player.mixTempoRatio == 1
                            ? "AutoMix"
                            : String(format: "AutoMix · tempo %+.0f %%", (player.mixTempoRatio - 1) * 100),
                        systemImage: "arrow.triangle.merge"
                    )
                    .font(Typo.caption)
                    .foregroundStyle(Tone.primary)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 4)
                    .background(Capsule().fill(Color.white.opacity(0.15)))
                    .transition(.scale.combined(with: .opacity))
                }
            }
            .animation(Motion.smooth, value: player.isMixing)
            Spacer()
            actionsMenu
        }
        .padding(.top, 8)
    }

    /// Minuteur de sommeil en cours : compte à rebours (ou « fin du titre »).
    @ViewBuilder
    private var sleepBadge: some View {
        if let timer = player.sleepTimer {
            HStack(spacing: 4) {
                Image(systemName: "moon.zzz.fill")
                if timer == .endOfTrack {
                    Text("Fin du titre")
                } else if let deadline = player.sleepDeadline {
                    // Borne haute jamais avant la basse : une plage inversée plante.
                    let now = Date()
                    Text(timerInterval: now...max(deadline, now), countsDown: true)
                        .monospacedDigit()
                }
            }
            .font(Typo.caption)
            .foregroundStyle(Tone.secondary)
            .transition(.opacity)
        }
    }

    /// Menu « ⋯ » isolé dans sa propre vue, comparée par valeur : le lecteur
    /// se redessine deux fois par seconde (progression), et un menu ouvert
    /// reconstruit à chaque fois scintillait.
    private var actionsMenu: some View {
        PlayerActionsMenu(
            track: player.current,
            isLiked: isLiked,
            isDownloaded: player.current.map { DownloadManager.shared.isDownloaded($0) } ?? false,
            isStartingRadio: isStartingRadio,
            sleepTimer: player.sleepTimer,
            actions: PlayerActionsMenu.Actions(
                addToPlaylist: { track in playlistPick = PlaylistPickRequest(tracks: [track]) },
                setSleepTimer: { player.setSleepTimer($0) },
                openRoute: onOpenRoute,
                startRadio: { source, id in startArtistRadio(source: source, artistId: id) },
                startDJRadio: { track in startDJRadio(track) },
                toggleLike: { track in Task { await toggleLike(track) } },
                reportWrongVersion: { _ in confirmingWrongVersion = true },
                openSound: { showingSound = true },
                shareStory: { track in storyTrack = track },
                addMoment: { track in momentRequest = MomentRequest(track: track, position: player.positionSeconds) }
            )
        )
        .equatable()
    }

    // MARK: - Panneaux

    private func artworkPanel(_ track: Track) -> some View {
        VStack(spacing: 0) {
            Spacer(minLength: 16)
            GeometryReader { proxy in
                let side = min(proxy.size.width, proxy.size.height)
                Artwork(url: track.coverURL, cornerRadius: 14)
                    .matchedGeometryEffect(id: "artwork", in: hero)
                    .frame(width: side, height: side)
                    .scaleEffect(player.isPlaying || player.isLoading ? 1 : 0.8)
                    .shadow(color: .black.opacity(player.isPlaying ? 0.45 : 0.25), radius: player.isPlaying ? 30 : 14, y: player.isPlaying ? 18 : 8)
                    .animation(Motion.bouncy, value: player.isPlaying)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .id(track.id)
                    .transition(.asymmetric(
                        insertion: .scale(scale: 0.9).combined(with: .opacity),
                        removal: .opacity
                    ))
            }
            .aspectRatio(1, contentMode: .fit)
            .animation(Motion.smooth, value: track.id)
            Spacer(minLength: 24)
            titleRow(track, compact: false)
                .padding(.bottom, 18)
        }
    }

    private func compactPanel<Content: View>(_ track: Track, @ViewBuilder content: () -> Content) -> some View {
        VStack(spacing: 14) {
            HStack(spacing: 14) {
                Artwork(url: track.coverURL, cornerRadius: 8)
                    .matchedGeometryEffect(id: "artwork", in: hero)
                    .frame(width: 62, height: 62)
                    .shadow(color: .black.opacity(0.3), radius: 10, y: 5)
                    // Toucher la petite pochette : retour au lecteur (sans
                    // paroles ni file), comme dans Musique.
                    .contentShape(Rectangle())
                    .onTapGesture {
                        withAnimation(Motion.smooth) { panel = .artwork }
                    }
                    .sensoryFeedback(.impact(weight: .light), trigger: panel)
                titleRow(track, compact: true)
            }
            .padding(.top, 14)
            content()
                .frame(maxHeight: .infinity)
                .transition(.opacity.combined(with: .move(edge: .bottom)))
        }
    }

    private func titleRow(_ track: Track, compact: Bool) -> some View {
        HStack(alignment: .center, spacing: 12) {
            VStack(alignment: .leading, spacing: 3) {
                Text(track.title)
                    .font(.system(size: compact ? 17 : 22, weight: .bold))
                    .foregroundStyle(Tone.primary)
                    .lineLimit(1)
                Button {
                    if let artistId = track.artistSourceId {
                        onOpenRoute(.artist(source: track.source, id: artistId))
                    }
                } label: {
                    Text(track.artist)
                        .font(.system(size: compact ? 15 : 19, weight: .regular))
                        .foregroundStyle(Tone.secondary)
                        .lineLimit(1)
                }
                .buttonStyle(.pressable)
                .disabled(track.artistSourceId == nil)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .id(track.id)
            .transition(.opacity)

            Button {
                Task { await toggleLike(track) }
            } label: {
                Image(systemName: isLiked ? "heart.fill" : "heart")
                    .font(.system(size: compact ? 18 : 22, weight: .semibold))
                    .foregroundStyle(Tone.primary)
                    .symbolEffect(.bounce, value: likeBounce)
                    .contentTransition(.symbolEffect(.replace))
                    .frame(width: 40, height: 40)
            }
            .buttonStyle(.pressable(scale: 0.8))
            .sensoryFeedback(.success, trigger: likeBounce)
        }
    }

    /// File d'attente façon Musique : les quatre bascules (aléatoire,
    /// répétition, lecture automatique, fondu enchaîné), « Poursuivre la
    /// lecture » réordonnable, puis les titres similaires qui suivront.
    private var queueList: some View {
        VStack(alignment: .leading, spacing: 14) {
            QueueToggles(player: player)
                .padding(.top, 6)

            // En-têtes en lignes ordinaires plutôt qu'en `Section` : les
            // en-têtes d'une liste simple restent collés en haut, sur un fond
            // grisé qui jure avec le lecteur.
            List {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Poursuivre la lecture")
                        .font(Typo.headline)
                        .foregroundStyle(Tone.primary)
                    if let name = player.contextName {
                        Text("De \(name)")
                            .font(Typo.rowSubtitle)
                            .foregroundStyle(Tone.secondary)
                    }
                }
                .padding(.bottom, 4)
                .queueRowStyle()

                if player.queuedNext.isEmpty {
                    Text("Rien après ce morceau.")
                        .font(Typo.rowSubtitle)
                        .foregroundStyle(Tone.secondary)
                        .padding(.vertical, 10)
                        .queueRowStyle()
                }
                ForEach(player.queuedNext) { track in
                    QueueRow(track: track) { player.playFromUpNext(track) }
                        .queueRowStyle()
                        .swipeActions(edge: .trailing, allowsFullSwipe: true) {
                            Button(role: .destructive) {
                                withAnimation(Motion.smooth) { player.removeFromQueue(track) }
                            } label: {
                                Label("Retirer", systemImage: "minus.circle")
                            }
                        }
                }
                .onMove { source, destination in
                    player.moveQueued(from: source, to: destination)
                }

                if player.autoplayEnabled && !player.isStation {
                    VStack(alignment: .leading, spacing: 2) {
                        Label("Lecture automatique", systemImage: "infinity")
                            .font(Typo.headline)
                            .foregroundStyle(Tone.primary)
                        Text("Des morceaux similaires seront lus automatiquement.")
                            .font(Typo.rowSubtitle)
                            .foregroundStyle(Tone.secondary)
                    }
                    .padding(.top, 16)
                    .padding(.bottom, 4)
                    .queueRowStyle()

                    ForEach(player.autoplayNext) { track in
                        QueueRow(track: track, showsHandle: false) { player.playFromUpNext(track) }
                            .queueRowStyle()
                    }
                }
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
            .scrollIndicators(.hidden)
            .environment(\.defaultMinListRowHeight, 10)
            .mask { EdgeFade() }
        }
    }

    // MARK: - Commandes

    private func controls(_ track: Track) -> some View {
        VStack(spacing: 0) {
            PlayerScrubber(
                progress: player.progress,
                duration: player.durationSeconds > 0 ? player.durationSeconds : Double(track.durationSeconds ?? 0)
            ) { fraction in
                player.seek(toFraction: fraction)
            } onScrub: { active in
                scrubbing = active
                if !active { activity += 1 }
            }

            if let message = player.errorMessage {
                Text(message)
                    .font(Typo.rowSubtitle)
                    .foregroundStyle(Tone.danger)
                    .multilineTextAlignment(.center)
                    .padding(.top, 6)
                    .transition(.opacity)
            }

            TVCastBanner()
                .padding(.top, 10)

            TransportRow(player: player)
                .padding(.vertical, 22)

            HStack(spacing: 12) {
                Image(systemName: "speaker.fill").font(.system(size: 12)).foregroundStyle(Tone.tertiary)
                SystemVolumeView().frame(height: 30)
                Image(systemName: "speaker.wave.3.fill").font(.system(size: 12)).foregroundStyle(Tone.tertiary)
            }

            HStack {
                panelButton(.lyrics, icon: "quote.bubble")
                Spacer()
                AirPlayButton()
                Spacer()
                TVCastButton()
                Spacer()
                panelButton(.queue, icon: "list.bullet")
            }
            .padding(.horizontal, 30)
            .padding(.top, 16)
        }
    }

    private func panelButton(_ target: Panel, icon: String) -> some View {
        let active = panel == target
        return Button {
            withAnimation(Motion.smooth) { panel = active ? .artwork : target }
        } label: {
            Image(systemName: icon)
                .font(.system(size: 19, weight: .semibold))
                .foregroundStyle(active ? Color.black : Tone.secondary)
                .frame(width: 44, height: 36)
                .background(
                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                        .fill(active ? Color.white : Color.clear)
                )
        }
        .buttonStyle(.pressable(scale: 0.85))
        .sensoryFeedback(.selection, trigger: panel)
    }

    // MARK: - Actions

    private func reportWrongVersion(_ track: Track) async {
        do {
            try await APIClient.shared.reportWrongVersion(track)
            // Un téléchargement de ce titre est la même mauvaise version.
            DownloadManager.shared.remove(track)
            if player.current?.id == track.id { player.reloadCurrent() }
        } catch {
            player.errorMessage = error.localizedDescription
        }
    }

    private func startDJRadio(_ track: Track) {
        isStartingRadio = true
        Task {
            do {
                try await player.playDJRadio(from: track)
            } catch {
                player.errorMessage = error.localizedDescription
            }
            isStartingRadio = false
        }
    }

    private func startArtistRadio(source: String, artistId: String) {
        isStartingRadio = true
        Task {
            do {
                try await player.playStation(name: player.current.map { "Radio \($0.artist)" }) {
                    try await APIClient.shared.artistRadio(source: source, id: artistId)
                }
            } catch {
                player.errorMessage = error.localizedDescription
            }
            isStartingRadio = false
        }
    }

    private func loadMoments() async {
        guard let track = player.current else { return }
        moments = (try? await APIClient.shared.moments(for: track)) ?? []
    }

    private func refreshLikeState() async {
        guard let track = player.current else { return }
        if let page = try? await APIClient.shared.library(kind: "track", limit: 200) {
            isLiked = page.items.contains { $0.source == track.source && $0.sourceId == track.sourceId }
        }
    }

    private func toggleLike(_ track: Track) async {
        do {
            if isLiked {
                try await APIClient.shared.removeFromLibrary(kind: "track", source: track.source, sourceId: track.sourceId)
            } else {
                try await APIClient.shared.addToLibrary(kind: "track", source: track.source, sourceId: track.sourceId)
            }
            isLiked.toggle()
            likeBounce += 1
        } catch {
            player.errorMessage = error.localizedDescription
        }
    }
}

/// Précédent / lecture-pause / suivant : gros symboles nus, rebond et retour
/// haptique à chaque appui, comme Musique.
private struct TransportRow: View {
    @ObservedObject var player: PlayerManager
    @State private var backTaps = 0
    @State private var forwardTaps = 0

    var body: some View {
        HStack {
            Spacer()
            Button {
                backTaps += 1
                player.previous()
            } label: {
                Image(systemName: "backward.fill")
                    .font(.system(size: 30))
                    .symbolEffect(.bounce.byLayer, value: backTaps)
                    .frame(width: 70, height: 70)
            }
            .buttonStyle(.pressable(scale: 0.8))
            Spacer()
            Button {
                player.togglePlayPause()
            } label: {
                Group {
                    if player.isLoading {
                        ProgressView().tint(.white).scaleEffect(1.5)
                    } else {
                        Image(systemName: player.isPlaying ? "pause.fill" : "play.fill")
                            .font(.system(size: 46))
                            .contentTransition(.symbolEffect(.replace.downUp))
                    }
                }
                .frame(width: 84, height: 84)
            }
            .buttonStyle(.pressable(scale: 0.82))
            .sensoryFeedback(.impact(weight: .medium), trigger: player.isPlaying)
            Spacer()
            Button {
                forwardTaps += 1
                player.next()
            } label: {
                Image(systemName: "forward.fill")
                    .font(.system(size: 30))
                    .symbolEffect(.bounce.byLayer, value: forwardTaps)
                    .frame(width: 70, height: 70)
            }
            .buttonStyle(.pressable(scale: 0.8))
            .sensoryFeedback(.impact(weight: .light), trigger: forwardTaps)
            Spacer()
        }
        .foregroundStyle(Tone.primary)
    }
}

/// Barre de progression : fine au repos, elle s'épaissit et s'allume sous le
/// doigt ; la position n'est envoyée au lecteur qu'au relâchement (un saut
/// par geste, pas cinquante).
struct PlayerScrubber: View {
    let progress: Double
    let duration: Double
    var onSeek: (Double) -> Void
    /// Début / fin d'un glissement du doigt sur la barre.
    var onScrub: (Bool) -> Void = { _ in }

    @State private var dragFraction: Double?

    var body: some View {
        let fraction = min(1, max(0, dragFraction ?? progress))
        let dragging = dragFraction != nil
        return VStack(spacing: 8) {
            GeometryReader { proxy in
                ZStack(alignment: .leading) {
                    Capsule().fill(Color.white.opacity(0.2))
                    Capsule()
                        .fill(Color.white.opacity(dragging ? 1 : 0.75))
                        .frame(width: max(0, proxy.size.width * fraction))
                }
                .frame(height: dragging ? 12 : 6)
                .frame(maxHeight: .infinity)
                .contentShape(Rectangle())
                .gesture(
                    DragGesture(minimumDistance: 0)
                        .onChanged { value in
                            if dragFraction == nil { onScrub(true) }
                            dragFraction = min(1, max(0, Double(value.location.x / max(1, proxy.size.width))))
                        }
                        .onEnded { _ in
                            if let dragFraction { onSeek(dragFraction) }
                            dragFraction = nil
                            onScrub(false)
                        }
                )
            }
            .frame(height: 24)
            .scaleEffect(x: dragging ? 1.03 : 1, y: 1)

            HStack {
                Text(Self.format(fraction * duration))
                Spacer()
                Text("-" + Self.format(max(0, duration - fraction * duration)))
            }
            .font(Typo.mono)
            .foregroundStyle(dragging ? Tone.primary : Tone.tertiary)
        }
        .animation(Motion.snappy, value: dragging)
        .sensoryFeedback(.selection, trigger: dragging)
    }

    static func format(_ seconds: Double) -> String {
        guard seconds.isFinite else { return "0:00" }
        let total = max(0, Int(seconds))
        return String(format: "%d:%02d", total / 60, total % 60)
    }
}

/// Fondu en haut et en bas d'une zone défilante : le contenu apparaît et
/// disparaît au lieu d'être coupé net.
struct EdgeFade: View {
    var body: some View {
        LinearGradient(
            stops: [
                .init(color: .clear, location: 0),
                .init(color: .black, location: 0.08),
                .init(color: .black, location: 0.9),
                .init(color: .clear, location: 1),
            ],
            startPoint: .top, endPoint: .bottom
        )
    }
}

// MARK: - File d'attente

/// Les quatre bascules en tête de file, comme dans Musique : actives, elles
/// passent en pastille blanche à pictogramme sombre.
private struct QueueToggles: View {
    @ObservedObject var player: PlayerManager

    var body: some View {
        HStack(spacing: 10) {
            toggle("shuffle", isOn: player.shuffleEnabled, label: "Aléatoire") {
                player.toggleShuffle()
            }
            toggle(player.repeatMode == .one ? "repeat.1" : "repeat", isOn: player.repeatMode != .off, label: "Répéter") {
                player.cycleRepeat()
            }
            toggle("infinity", isOn: player.autoplayEnabled && !player.isStation, label: "Lecture automatique") {
                player.toggleAutoplay()
            }
            .disabled(player.isStation)
            toggle("arrow.triangle.merge", isOn: player.crossfadeEnabled, label: "AutoMix") {
                player.toggleCrossfade()
            }
        }
    }

    private func toggle(_ icon: String, isOn: Bool, label: String, action: @escaping () -> Void) -> some View {
        Button {
            withAnimation(Motion.smooth) { action() }
        } label: {
            Image(systemName: icon)
                .font(.system(size: 16, weight: .semibold))
                .contentTransition(.symbolEffect(.replace))
                .foregroundStyle(isOn ? Color.black : Tone.primary)
                .frame(maxWidth: .infinity)
                .frame(height: 38)
                .background(
                    Capsule(style: .continuous)
                        .fill(isOn ? Color.white : Color.white.opacity(0.12))
                )
        }
        .buttonStyle(.pressable(scale: 0.9))
        .sensoryFeedback(.selection, trigger: isOn)
        .accessibilityLabel(label)
        .accessibilityAddTraits(isOn ? .isSelected : [])
    }
}

/// Ligne de file : pochette, titre, artiste, et poignée de déplacement (un
/// appui long suffit à glisser la ligne).
private struct QueueRow: View {
    let track: Track
    var showsHandle = true
    let action: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            Button(action: action) {
                HStack(spacing: 12) {
                    Artwork(url: track.coverURL, cornerRadius: 6)
                        .frame(width: 44, height: 44)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(track.title)
                            .font(Typo.rowTitle)
                            .foregroundStyle(Tone.primary)
                            .lineLimit(1)
                        Text(track.artist)
                            .font(Typo.rowSubtitle)
                            .foregroundStyle(Tone.secondary)
                            .lineLimit(1)
                    }
                    Spacer(minLength: 0)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            if showsHandle {
                Image(systemName: "line.3.horizontal")
                    .font(.system(size: 15, weight: .medium))
                    .foregroundStyle(Tone.tertiary)
            }
        }
        .padding(.vertical, 4)
    }
}

private extension View {
    func queueRowStyle() -> some View {
        self
            .listRowBackground(Color.clear)
            .listRowSeparator(.hidden)
            .listRowInsets(EdgeInsets(top: 0, leading: 0, bottom: 0, trailing: 0))
    }
}

/// Contenu du menu « ⋯ » du lecteur plein écran (voir `actionsMenu`).
struct PlayerActionsMenu: View, Equatable {
    struct Actions {
        var addToPlaylist: (Track) -> Void
        var setSleepTimer: (PlayerManager.SleepTimer?) -> Void
        var openRoute: (Route) -> Void
        var startRadio: (String, String) -> Void
        var startDJRadio: (Track) -> Void
        var toggleLike: (Track) -> Void
        var reportWrongVersion: (Track) -> Void
        var openSound: () -> Void
        var shareStory: (Track) -> Void
        var addMoment: (Track) -> Void
    }

    let track: Track?
    let isLiked: Bool
    /// Valeur figée, pas un `@ObservedObject` : le gestionnaire de
    /// téléchargements publie en continu pendant un téléchargement, et chaque
    /// publication reconstruisait le menu ouvert (qui remontait en haut).
    let isDownloaded: Bool
    let isStartingRadio: Bool
    let sleepTimer: PlayerManager.SleepTimer?
    let actions: Actions

    static func == (lhs: Self, rhs: Self) -> Bool {
        lhs.track?.id == rhs.track?.id && lhs.isLiked == rhs.isLiked && lhs.isDownloaded == rhs.isDownloaded
            && lhs.isStartingRadio == rhs.isStartingRadio && lhs.sleepTimer == rhs.sleepTimer
    }

    var body: some View {
        Menu {
            if let track {
                Button { actions.addToPlaylist(track) } label: {
                    Label("Ajouter à une playlist…", systemImage: "text.badge.plus")
                }
                Button { actions.toggleLike(track) } label: {
                    Label(isLiked ? "Retirer de la bibliothèque" : "Ajouter à la bibliothèque",
                          systemImage: isLiked ? "minus.circle" : "plus.circle")
                }
                if isDownloaded {
                    Button(role: .destructive) { DownloadManager.shared.remove(track) } label: {
                        Label("Supprimer le téléchargement", systemImage: "arrow.down.circle.dotted")
                    }
                } else {
                    Button { DownloadManager.shared.download([track]) } label: {
                        Label("Télécharger", systemImage: "arrow.down.circle")
                    }
                }
                Menu {
                    Button { actions.addMoment(track) } label: {
                        Label("Réagir à ce moment", systemImage: "bubble.left.and.exclamationmark.bubble.right")
                    }
                    Button { actions.shareStory(track) } label: {
                        Label("Partager en story", systemImage: "square.and.arrow.up.on.square")
                    }
                } label: {
                    Label("Réagir et partager", systemImage: "square.and.arrow.up")
                }
                Menu {
                    Button { actions.startDJRadio(track) } label: {
                        Label("Radio DJ à partir de ce titre", systemImage: "dial.medium")
                    }
                    if let artistId = track.artistSourceId {
                        Button {
                            actions.startRadio(track.source, artistId)
                        } label: { Label("Radio de l'artiste", systemImage: "dot.radiowaves.left.and.right") }
                    }
                } label: {
                    Label("Radios", systemImage: "dot.radiowaves.left.and.right")
                }
                Button { actions.openSound() } label: {
                    Label("Son, égaliseur et AirPods", systemImage: "slider.vertical.3")
                }
                Menu {
                    ForEach([15, 30, 45, 60], id: \.self) { minutes in
                        Button("\(minutes) minutes") { actions.setSleepTimer(.minutes(minutes)) }
                    }
                    Button("Fin du titre") { actions.setSleepTimer(.endOfTrack) }
                    if sleepTimer != nil {
                        Button("Désactiver", role: .destructive) { actions.setSleepTimer(nil) }
                    }
                } label: {
                    Label(sleepTimer == nil ? "Minuteur de sommeil" : "Minuteur activé", systemImage: "moon.zzz")
                }
                Divider()
                if let artistId = track.artistSourceId {
                    Button {
                        actions.openRoute(.artist(source: track.source, id: artistId))
                    } label: { Label("Voir l'artiste", systemImage: "person.crop.circle") }
                }
                if let albumId = track.albumSourceId {
                    Button {
                        actions.openRoute(.album(source: track.source, id: albumId))
                    } label: { Label("Voir l'album", systemImage: "square.stack") }
                }
                Divider()
                Button { actions.reportWrongVersion(track) } label: {
                    Label("Mauvaise version ?", systemImage: "exclamationmark.bubble")
                }
            }
        } label: {
            Group {
                if isStartingRadio {
                    ProgressView().tint(.white)
                } else {
                    Image(systemName: "ellipsis")
                }
            }
            .font(.system(size: 17, weight: .semibold))
            .foregroundStyle(Tone.primary)
            .frame(width: 40, height: 40)
            .background(Circle().fill(Color.white.opacity(0.12)))
        }
    }
}

/// Réaction à poster à un instant du titre.
struct MomentRequest: Identifiable {
    let id = UUID()
    let track: Track
    let position: Double
}
