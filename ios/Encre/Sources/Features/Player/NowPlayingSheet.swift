import CoreImage
import Foundation
import SwiftUI
import UIKit

/// Lecteur plein écran — variante "intégrée" du prototype (Encre.dc.html
/// §1a) : pochette, transport, paroles/file d'attente. Le geste de
/// fermeture est celui, natif, de la feuille SwiftUI (glisser vers le bas)
/// plutôt qu'une reproduction à la main de l'animation `clip-path` du
/// prototype.
struct NowPlayingSheet: View {
    @ObservedObject var player: PlayerManager
    /// Ferme cette feuille et pousse la destination sur la pile de l'onglet
    /// actif (voir `RootTabView.openRoute`) — plus simple et plus sûr qu'une
    /// pile de navigation imbriquée dans la feuille elle-même.
    var onOpenRoute: (Route) -> Void
    @Environment(\.dismiss) private var dismiss

    // `Equatable` explicite : Swift ne synthétise `==` que si la conformance
    // est déclarée, même pour un enum sans valeur associée.
    private enum Mode: Equatable { case cover, lyrics, queue }
    @State private var mode: Mode = .cover
    @State private var isLiked = false
    @State private var backdropColor: Color = EncreColor.bg

    private enum LyricsState: Equatable {
        case idle, loading, loaded(Lyrics), unavailable(String)
    }
    @State private var lyricsState: LyricsState = .idle
    /// Id du morceau dont `lyricsState` porte les paroles : évite de les
    /// recharger à chaque aller-retour pochette ↔ paroles.
    @State private var lyricsTrackId: String?

    var body: some View {
        VStack(spacing: 0) {
            Capsule()
                .fill(EncreColor.neutral400)
                .frame(width: 44, height: 5)
                .padding(.top, 10)
                .padding(.bottom, 18)

            if let track = player.current {
                Group {
                    switch mode {
                    case .cover: coverPanel(track)
                    case .lyrics: lyricsPanel
                    case .queue: queuePanel
                    }
                }
                .frame(height: 360)

                titleRow(track)
                    .padding(.horizontal, 30)
                    .padding(.top, 22)

                WaveformScrubber(trackId: track.id, progress: player.progress) { fraction in
                    player.seek(toFraction: fraction)
                }
                .frame(height: 40)
                .padding(.horizontal, 30)
                .padding(.top, 18)

                HStack {
                    Text(formatted(player.positionSeconds))
                    Spacer()
                    Text("-" + formatted(max(0, Double(track.durationSeconds ?? 0) - player.positionSeconds)))
                }
                .font(EncreFont.body(13))
                .foregroundStyle(EncreColor.neutral700)
                .monospacedDigit()
                .padding(.horizontal, 30)
                .padding(.top, 4)

                transportRow
                    .padding(.top, 26)

                SystemVolumeView()
                    .frame(height: 32)
                    .padding(.horizontal, 36)
                    .padding(.top, 26)

                modeRow
                    .padding(.top, 22)

                if let message = player.errorMessage {
                    Text(message)
                        .font(EncreFont.body(14))
                        .foregroundStyle(EncreColor.accent2_700)
                        .padding(.top, 16)
                        .padding(.horizontal, 36)
                }
            }

            Spacer(minLength: 12)
        }
        .frame(maxWidth: .infinity)
        .background { backdrop }
        .task(id: player.current?.id) {
            await refreshLikeState()
            await updateBackdropColor()
        }
        // Chargées seulement quand le panneau est ouvert (pas pour chaque
        // morceau joué), puis gardées tant que le morceau ne change pas.
        .task(id: "\(player.current?.id ?? "")|\(mode == .lyrics)") {
            await loadLyricsIfNeeded()
        }
    }

    /// Fond dégradé teinté de la couleur moyenne de la pochette + texture
    /// floutée dessus — la signature visuelle du lecteur plein écran d'Apple
    /// Music (qui fait la même extraction de couleur), plutôt qu'un simple
    /// voile sombre uniforme qui rendait la même chose quelle que soit la
    /// pochette.
    @ViewBuilder
    private var backdrop: some View {
        ZStack {
            LinearGradient(colors: [backdropColor, EncreColor.bg], startPoint: .top, endPoint: .bottom)
            if let urlString = player.current?.coverURL, let url = URL(string: urlString) {
                AsyncImage(url: url) { phase in
                    if case .success(let image) = phase {
                        image.resizable().scaledToFill()
                    }
                }
                .blur(radius: 80)
                .opacity(0.5)
                .overlay(LinearGradient(colors: [.clear, EncreColor.bg], startPoint: .top, endPoint: .bottom))
            }
        }
        .ignoresSafeArea()
        .animation(.easeInOut(duration: 0.6), value: backdropColor)
    }

    /// Moyenne des couleurs de la pochette (filtre Core Image `CIAreaAverage`,
    /// rendu sur un unique pixel) : la même technique qu'utilise Apple Music
    /// pour teinter son fond, plutôt qu'une couleur fixe qui ignorerait la
    /// pochette réelle.
    private func updateBackdropColor() async {
        guard let urlString = player.current?.coverURL, let url = URL(string: urlString),
              let (data, _) = try? await URLSession.shared.data(from: url),
              let uiImage = UIImage(data: data), let ciImage = CIImage(image: uiImage),
              let filter = CIFilter(name: "CIAreaAverage", parameters: [
                kCIInputImageKey: ciImage, kCIInputExtentKey: CIVector(cgRect: ciImage.extent),
              ]),
              let output = filter.outputImage
        else {
            backdropColor = EncreColor.bg
            return
        }
        var pixel = [UInt8](repeating: 0, count: 4)
        let context = CIContext(options: [.workingColorSpace: NSNull()])
        context.render(
            output, toBitmap: &pixel, rowBytes: 4, bounds: CGRect(x: 0, y: 0, width: 1, height: 1),
            format: .RGBA8, colorSpace: nil
        )
        backdropColor = Color(red: Double(pixel[0]) / 255, green: Double(pixel[1]) / 255, blue: Double(pixel[2]) / 255)
    }

    // MARK: - Panneaux

    private func coverPanel(_ track: Track) -> some View {
        // Le décalage CMJN (deux aplats décalés derrière la pochette) faisait
        // sens sur les placeholders sans vraie image, mais rendait mal sur de
        // vraies photos de pochette — une seule pochette nette avec juste une
        // ombre, comme Apple Music, plutôt qu'un effet qui la brouille.
        CoverArt(url: track.coverURL, title: track.title, showsHalftone: true)
            .frame(width: 300, height: 300)
            .encreShadow(EncreShadow.lg)
    }

    @ViewBuilder
    private var lyricsPanel: some View {
        switch lyricsState {
        case .idle, .loading:
            ProgressView().tint(EncreColor.text).frame(maxWidth: .infinity, maxHeight: .infinity)
        case .unavailable(let message):
            lyricsMessage(title: "Paroles indisponibles", detail: message)
        case .loaded(let lyrics):
            if lyrics.instrumental {
                lyricsMessage(title: "Morceau instrumental", detail: "Pas de paroles à suivre : juste la musique.")
            } else if lyrics.synced {
                syncedLyrics(lyrics.lines)
            } else {
                plainLyrics(lyrics.lines)
            }
        }
    }

    private func lyricsMessage(title: String, detail: String) -> some View {
        VStack(spacing: 10) {
            Image(systemName: "quote.opening")
                .font(.system(size: 30))
                .foregroundStyle(EncreColor.neutral500)
            Text(title)
                .font(EncreFont.heading(20))
                .foregroundStyle(EncreColor.text)
            Text(detail)
                .font(EncreFont.body(15))
                .foregroundStyle(EncreColor.neutral600)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 40)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    /// Paroles synchronisées façon Apple Music : la ligne en cours en
    /// grand et en clair, recentrée à chaque changement ; taper une ligne y
    /// ramène la lecture.
    private func syncedLyrics(_ lines: [Lyrics.Line]) -> some View {
        // Légère avance : la ligne s'allume au moment où elle est chantée
        // plutôt qu'un poil après (tick du lecteur toutes les 0,5 s).
        let position = player.positionSeconds + 0.3
        let active = lines.lastIndex(where: { ($0.time ?? 0) <= position })
        return ScrollViewReader { proxy in
            ScrollView(showsIndicators: false) {
                VStack(alignment: .leading, spacing: 18) {
                    ForEach(Array(lines.enumerated()), id: \.offset) { index, line in
                        Text(line.text.isEmpty ? "♪" : line.text)
                            .font(EncreFont.heading(26))
                            .foregroundStyle(index == active ? EncreColor.text : EncreColor.neutral500)
                            .scaleEffect(index == active ? 1 : 0.96, anchor: .leading)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .contentShape(Rectangle())
                            .onTapGesture {
                                if let time = line.time { player.seek(toSeconds: time) }
                            }
                            .id(index)
                    }
                }
                .padding(.horizontal, 30)
                .padding(.vertical, 150)
                .animation(.easeOut(duration: 0.25), value: active)
            }
            .mask { lyricsFade }
            .onAppear {
                if let active { proxy.scrollTo(active, anchor: .center) }
            }
            .onChange(of: active) { _, newValue in
                guard let newValue else { return }
                withAnimation(.easeInOut(duration: 0.4)) { proxy.scrollTo(newValue, anchor: .center) }
            }
        }
    }

    private func plainLyrics(_ lines: [Lyrics.Line]) -> some View {
        ScrollView(showsIndicators: false) {
            Text(lines.map(\.text).joined(separator: "\n"))
                .font(EncreFont.body(20))
                .lineSpacing(6)
                .foregroundStyle(EncreColor.text)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 30)
                .padding(.vertical, 40)
        }
        .mask { lyricsFade }
    }

    /// Fondu en haut et en bas du panneau : les lignes apparaissent et
    /// disparaissent au lieu d'être coupées net au bord.
    private var lyricsFade: some View {
        LinearGradient(
            stops: [
                .init(color: .clear, location: 0),
                .init(color: .black, location: 0.12),
                .init(color: .black, location: 0.88),
                .init(color: .clear, location: 1),
            ],
            startPoint: .top, endPoint: .bottom
        )
    }

    private func loadLyricsIfNeeded() async {
        guard mode == .lyrics, let track = player.current else { return }
        if lyricsTrackId == track.id, case .loaded = lyricsState { return }
        lyricsTrackId = track.id
        lyricsState = .loading
        do {
            let lyrics = try await APIClient.shared.lyrics(for: track)
            guard player.current?.id == track.id else { return }
            if let lyrics {
                lyricsState = .loaded(lyrics)
            } else {
                lyricsState = .unavailable("Pas de paroles connues pour ce morceau.")
            }
        } catch {
            guard !Task.isCancelled, player.current?.id == track.id else { return }
            lyricsState = .unavailable("Les paroles n'ont pas pu être chargées — réessaie dans un instant.")
        }
    }

    private var queuePanel: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                Text("À SUIVRE")
                    .font(EncreFont.heading(12))
                    .tracking(2)
                    .foregroundStyle(EncreColor.accent2_700)
                    .padding(.horizontal, 30)

                if player.upNext.isEmpty {
                    Text("Rien après ce morceau — il vient d'un résultat isolé plutôt que d'un album ou d'une liste.")
                        .font(EncreFont.bodyItalic(15))
                        .foregroundStyle(EncreColor.neutral600)
                        .padding(.horizontal, 30)
                } else {
                    VStack(spacing: 10) {
                        ForEach(player.upNext) { track in
                            Button { player.playFromUpNext(track) } label: {
                                HStack(spacing: 14) {
                                    CoverArt(url: track.coverURL, title: track.title).frame(width: 52, height: 52)
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(track.title).font(EncreFont.heading(17)).foregroundStyle(EncreColor.text).lineLimit(1)
                                        Text(track.artist).font(EncreFont.bodyItalic(14)).foregroundStyle(EncreColor.neutral700).lineLimit(1)
                                    }
                                    Spacer()
                                }
                                .padding(8)
                            }
                            .buttonStyle(.plain)
                            .glassRounded(18)
                        }
                    }
                    .padding(.horizontal, 30)
                }
            }
            .padding(.vertical, 8)
        }
    }

    // MARK: - Rangées communes

    private func titleRow(_ track: Track) -> some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text(track.title)
                    .font(EncreFont.heading(24))
                    .foregroundStyle(EncreColor.text)
                    .lineLimit(1)
                if let artistId = track.artistSourceId {
                    Button {
                        onOpenRoute(.artist(source: track.source, id: artistId))
                    } label: {
                        Text(track.artist)
                            .font(EncreFont.bodyItalic(18))
                            .foregroundStyle(EncreColor.spotDeep)
                            .lineLimit(1)
                    }
                    .buttonStyle(.plain)
                } else {
                    Text(track.artist)
                        .font(EncreFont.bodyItalic(18))
                        .foregroundStyle(EncreColor.spotDeep)
                        .lineLimit(1)
                }
            }
            Spacer(minLength: 8)
            Button {
                Task { await toggleLike(track) }
            } label: {
                Image(systemName: isLiked ? "heart.fill" : "heart")
                    .font(.system(size: 20))
                    .frame(width: 44, height: 44)
                    .contentTransition(.symbolEffect(.replace))
            }
            .glassCircle(interactive: true)
            .foregroundStyle(isLiked ? EncreColor.accent2 : EncreColor.text)
        }
    }

    private var transportRow: some View {
        HStack(spacing: 40) {
            Button { player.previous() } label: {
                Image(systemName: "backward.fill").font(.system(size: 26))
            }
            .foregroundStyle(EncreColor.text)

            Button {
                withAnimation(.easeOut(duration: 0.15)) { player.togglePlayPause() }
            } label: {
                Image(systemName: player.isLoading ? "hourglass" : (player.isPlaying ? "pause.fill" : "play.fill"))
                    .font(.system(size: 34))
                    .frame(width: 78, height: 78)
                    .contentTransition(.symbolEffect(.replace))
            }
            .glassCircle(interactive: true)
            .foregroundStyle(EncreColor.text)

            Button { player.next() } label: {
                Image(systemName: "forward.fill").font(.system(size: 26))
            }
            .foregroundStyle(EncreColor.text)
        }
    }

    private var modeRow: some View {
        HStack(spacing: 56) {
            modeButton(.lyrics, icon: "quote.opening")
            modeButton(.queue, icon: "list.bullet")
        }
    }

    private func modeButton(_ target: Mode, icon: String) -> some View {
        Button {
            mode = (mode == target) ? .cover : target
        } label: {
            Image(systemName: icon)
                .font(.system(size: 22))
                .frame(width: 46, height: 46)
        }
        .foregroundStyle(mode == target ? EncreColor.spot : EncreColor.neutral700)
    }

    // MARK: - Bibliothèque ("aimé")

    private func refreshLikeState() async {
        guard let track = player.current else { return }
        // Pas de route API pour vérifier un seul morceau : on relit la
        // bibliothèque (déjà rapide, usage personnel) et on regarde s'il y est.
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
        } catch {
            player.errorMessage = error.localizedDescription
        }
    }

    private func formatted(_ seconds: Double) -> String {
        let total = max(0, Int(seconds))
        return String(format: "%d:%02d", total / 60, total % 60)
    }
}
