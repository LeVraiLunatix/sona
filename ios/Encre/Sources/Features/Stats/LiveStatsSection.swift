import SwiftUI

/// Haut de l'onglet Stats : ce qui se passe maintenant, pour voir en direct
/// que tout fonctionne — le titre en cours et sa progression vers le seuil
/// où l'écoute compte (moitié du titre ou 4 min), ce que le serveur en sait,
/// l'état de Last.fm, et les dernières écoutes enregistrées.
struct LiveStatsSection: View {
    @EnvironmentObject private var player: PlayerManager
    @ObservedObject private var scrobbler = Scrobbler.shared
    @State private var live: LiveStats?
    @State private var pulse = false

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 8) {
                Circle()
                    .fill(player.isPlaying ? Color.green : Tone.tertiary)
                    .frame(width: 8, height: 8)
                    .scaleEffect(pulse && player.isPlaying ? 1.6 : 1)
                    .opacity(pulse && player.isPlaying ? 0.4 : 1)
                    .animation(.easeInOut(duration: 1).repeatForever(autoreverses: true), value: pulse)
                Text("EN DIRECT").font(Typo.caption).tracking(1.5).foregroundStyle(Tone.secondary)
                Spacer()
                if let live {
                    Text("Aujourd'hui · \(live.todayPlays) écoute\(live.todayPlays > 1 ? "s" : "") · \(live.todayMinutes) min")
                        .font(Typo.caption)
                        .foregroundStyle(Tone.tertiary)
                        .contentTransition(.numericText())
                }
            }

            nowPlayingCard
            statusRows

            if let recent = live?.recent, !recent.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Text("Dernières écoutes comptées").font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
                    ForEach(recent.prefix(4)) { play in
                        HStack(spacing: 12) {
                            Artwork(url: play.coverURL, cornerRadius: 6).frame(width: 36, height: 36)
                            VStack(alignment: .leading, spacing: 1) {
                                Text(play.title).font(Typo.rowTitle).foregroundStyle(Tone.primary).lineLimit(1)
                                Text(play.artist).font(Typo.caption).foregroundStyle(Tone.secondary).lineLimit(1)
                            }
                            Spacer()
                            Text(relative(play.playedAt)).font(Typo.caption).foregroundStyle(Tone.tertiary)
                        }
                        .transition(.move(edge: .top).combined(with: .opacity))
                    }
                }
                .animation(Motion.smooth, value: recent)
            }
        }
        .padding(18)
        .background(
            RoundedRectangle(cornerRadius: 22, style: .continuous)
                .fill(Tone.surface)
                .overlay(
                    RoundedRectangle(cornerRadius: 22, style: .continuous)
                        .stroke(Color.white.opacity(0.06), lineWidth: 1)
                )
        )
        .onAppear { pulse = true }
        .task {
            while !Task.isCancelled {
                await load()
                try? await Task.sleep(for: .seconds(10))
            }
        }
        // Rafraîchi aussitôt quand l'écoute vient de compter ou change de titre.
        .onChange(of: player.didScrobble) { _, counted in
            if counted { Task { try? await Task.sleep(for: .seconds(2)); await load() } }
        }
        .onChange(of: player.current?.id) { _, _ in
            Task { try? await Task.sleep(for: .seconds(2)); await load() }
        }
    }

    // MARK: - Titre en cours

    @ViewBuilder
    private var nowPlayingCard: some View {
        if let track = player.current {
            HStack(spacing: 14) {
                ZStack {
                    Artwork(url: track.coverURL, cornerRadius: 10)
                    if player.isPlaying {
                        Color.black.opacity(0.35).clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                        EqualizerBars(isAnimating: true).frame(width: 18, height: 16)
                    }
                }
                .frame(width: 64, height: 64)

                VStack(alignment: .leading, spacing: 6) {
                    Text(track.title).font(Typo.headline).foregroundStyle(Tone.primary).lineLimit(1)
                    Text(track.artist).font(Typo.rowSubtitle).foregroundStyle(Tone.secondary).lineLimit(1)
                    ScrobbleGauge(progress: player.scrobbleProgress, counted: player.didScrobble)
                }
            }
            .animation(Motion.smooth, value: player.didScrobble)
        } else {
            HStack(spacing: 12) {
                Image(systemName: "waveform").font(.system(size: 22)).foregroundStyle(Tone.tertiary)
                Text("Rien en lecture. Lance un titre : il apparaît ici en direct.")
                    .font(Typo.rowSubtitle)
                    .foregroundStyle(Tone.secondary)
            }
        }
    }

    // MARK: - État de la chaîne (serveur, Last.fm, envois en attente)

    private var statusRows: some View {
        VStack(alignment: .leading, spacing: 8) {
            if player.current != nil {
                statusRow(
                    ok: live?.nowPlaying != nil,
                    okText: "Le serveur te voit en train d'écouter",
                    waitingText: player.isPlaying ? "Le serveur n'a pas encore reçu le titre en cours" : "En pause : invisible pour tes amis"
                )
            }
            if let lastfm = live?.lastfm {
                if !lastfm.connected || !lastfm.enabled {
                    statusRow(ok: false, okText: "", waitingText: "Envoi vers Last.fm désactivé (Réglages)")
                } else if let error = lastfm.error {
                    statusRow(ok: false, okText: "", waitingText: "Last.fm : \(error)", isError: true)
                } else if let scrobbledAt = lastfm.scrobbledAt {
                    statusRow(
                        ok: true,
                        okText: "Last.fm @\(lastfm.username ?? "") · dernier scrobble \(relative(scrobbledAt))"
                            + (lastfm.lastTitle.map { " (\($0))" } ?? ""),
                        waitingText: ""
                    )
                } else if lastfm.nowPlayingAt != nil {
                    statusRow(ok: true, okText: "Last.fm @\(lastfm.username ?? "") reçoit ton écoute en direct", waitingText: "")
                } else {
                    statusRow(ok: false, okText: "", waitingText: "Last.fm @\(lastfm.username ?? "") : rien envoyé depuis le démarrage du serveur")
                }
            }
            if scrobbler.pendingCount > 0 {
                statusRow(
                    ok: false,
                    okText: "",
                    waitingText: "\(scrobbler.pendingCount) écoute\(scrobbler.pendingCount > 1 ? "s" : "") en attente d'envoi (hors connexion)"
                )
            }
        }
    }

    private func statusRow(ok: Bool, okText: String, waitingText: String, isError: Bool = false) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: ok ? "checkmark.circle.fill" : (isError ? "exclamationmark.triangle.fill" : "circle.dotted"))
                .foregroundStyle(ok ? Color.green : (isError ? Tone.danger : Tone.tertiary))
                .font(.system(size: 13, weight: .semibold))
            Text(ok ? okText : waitingText)
                .font(Typo.caption)
                .foregroundStyle(isError ? Tone.danger : Tone.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private func load() async {
        if let fresh = try? await APIClient.shared.liveStats() {
            withAnimation(Motion.smooth) { live = fresh }
        }
    }
}

/// Jauge « compte comme écoute » : se remplit jusqu'au seuil (moitié du
/// titre ou 4 min), puis devient une coche.
struct ScrobbleGauge: View {
    let progress: Double
    let counted: Bool

    var body: some View {
        HStack(spacing: 8) {
            GeometryReader { proxy in
                ZStack(alignment: .leading) {
                    Capsule().fill(Color.white.opacity(0.15))
                    Capsule()
                        .fill(counted ? Color.green : Color.white)
                        .frame(width: proxy.size.width * (counted ? 1 : progress))
                        .animation(.linear(duration: 0.5), value: progress)
                }
            }
            .frame(height: 5)
            Group {
                if counted {
                    Label("Comptée", systemImage: "checkmark")
                        .foregroundStyle(Color.green)
                } else {
                    Text("\(Int(progress * 100)) %")
                        .foregroundStyle(Tone.tertiary)
                        .monospacedDigit()
                }
            }
            .font(Typo.caption)
            .fixedSize()
            .contentTransition(.numericText())
        }
    }
}
