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
    @Namespace private var hero

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
                        case .artwork: artworkPanel(track)
                        case .lyrics: compactPanel(track) { LyricsView(player: player, track: track) }
                        case .queue: compactPanel(track) { queueList }
                        }
                    }
                    .frame(maxHeight: .infinity)

                    controls(track)
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
        .onChange(of: player.current == nil) { _, isEmpty in
            if isEmpty { dismiss() }
        }
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
            Capsule().fill(Color.white.opacity(0.35)).frame(width: 38, height: 5)
            Spacer()
            actionsMenu
        }
        .padding(.top, 8)
    }

    private var actionsMenu: some View {
        Menu {
            if let track = player.current {
                if let artistId = track.artistSourceId {
                    Button {
                        onOpenRoute(.artist(source: track.source, id: artistId))
                    } label: { Label("Voir l'artiste", systemImage: "person.crop.circle") }
                    Button {
                        startArtistRadio(source: track.source, artistId: artistId)
                    } label: { Label("Radio de l'artiste", systemImage: "dot.radiowaves.left.and.right") }
                }
                if let albumId = track.albumSourceId {
                    Button {
                        onOpenRoute(.album(source: track.source, id: albumId))
                    } label: { Label("Voir l'album", systemImage: "square.stack") }
                }
                Button {
                    Task { await toggleLike(track) }
                } label: {
                    Label(isLiked ? "Retirer de la bibliothèque" : "Ajouter à la bibliothèque",
                          systemImage: isLiked ? "minus.circle" : "plus.circle")
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

    private var queueList: some View {
        ScrollView(showsIndicators: false) {
            LazyVStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text("À suivre").font(Typo.headline).foregroundStyle(Tone.primary)
                    Spacer()
                    if player.isStation {
                        Label("Radio", systemImage: "dot.radiowaves.left.and.right")
                            .font(Typo.caption)
                            .foregroundStyle(Tone.secondary)
                    }
                }
                .padding(.bottom, 6)

                if player.upNext.isEmpty {
                    Text("Rien après ce morceau.")
                        .font(Typo.rowSubtitle)
                        .foregroundStyle(Tone.secondary)
                        .padding(.vertical, 20)
                } else {
                    ForEach(player.upNext) { track in
                        TrackRow(track: track) { player.playFromUpNext(track) }
                    }
                }
            }
            .padding(.vertical, 8)
        }
        .mask { EdgeFade() }
    }

    // MARK: - Commandes

    private func controls(_ track: Track) -> some View {
        VStack(spacing: 0) {
            PlayerScrubber(
                progress: player.progress,
                duration: player.durationSeconds > 0 ? player.durationSeconds : Double(track.durationSeconds ?? 0)
            ) { fraction in
                player.seek(toFraction: fraction)
            }

            if let message = player.errorMessage {
                Text(message)
                    .font(Typo.rowSubtitle)
                    .foregroundStyle(Tone.danger)
                    .multilineTextAlignment(.center)
                    .padding(.top, 6)
                    .transition(.opacity)
            }

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

    private func startArtistRadio(source: String, artistId: String) {
        isStartingRadio = true
        Task {
            do {
                try await player.playStation {
                    try await APIClient.shared.artistRadio(source: source, id: artistId)
                }
            } catch {
                player.errorMessage = error.localizedDescription
            }
            isStartingRadio = false
        }
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
                            dragFraction = min(1, max(0, Double(value.location.x / max(1, proxy.size.width))))
                        }
                        .onEnded { _ in
                            if let dragFraction { onSeek(dragFraction) }
                            dragFraction = nil
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
