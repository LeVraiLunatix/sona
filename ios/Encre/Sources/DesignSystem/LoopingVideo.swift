import AVFoundation
import SwiftUI
import UIKit

/// Boucle vidéo muette plein cadre (flux HLS des pochettes et portraits
/// animés d'Apple Music, sans piste audio : elle ne touche ni à la session
/// audio ni à l'écran de verrouillage).
struct LoopingVideo: UIViewRepresentable {
    let url: URL
    var playing = true
    var onReady: () -> Void = {}

    func makeUIView(context: Context) -> LoopingVideoView { LoopingVideoView() }

    func updateUIView(_ view: LoopingVideoView, context: Context) {
        view.onReady = onReady
        view.load(url)
        view.setPlaying(playing)
    }

    static func dismantleUIView(_ view: LoopingVideoView, coordinator: ()) { view.stop() }
}

final class LoopingVideoView: UIView {
    override class var layerClass: AnyClass { AVPlayerLayer.self }

    var onReady: () -> Void = {}
    private var queue: AVQueuePlayer?
    private var looper: AVPlayerLooper?
    private var loaded: URL?
    private var wantsPlaying = true
    private var readyObservation: NSKeyValueObservation?

    private var playerLayer: AVPlayerLayer { layer as! AVPlayerLayer }

    func load(_ url: URL) {
        guard loaded != url else { return }
        loaded = url
        let player = AVQueuePlayer()
        player.isMuted = true
        player.allowsExternalPlayback = false
        player.preventsDisplaySleepDuringVideoPlayback = false
        looper = AVPlayerLooper(player: player, templateItem: AVPlayerItem(url: url))
        queue = player
        playerLayer.player = player
        playerLayer.videoGravity = .resizeAspectFill
        readyObservation = playerLayer.observe(\.isReadyForDisplay, options: [.new]) { [weak self] layer, _ in
            guard layer.isReadyForDisplay else { return }
            DispatchQueue.main.async { self?.onReady() }
        }
        player.play()
    }

    func setPlaying(_ playing: Bool) {
        wantsPlaying = playing
        refreshPlayback()
    }

    /// Retour sur la page (après un album, par exemple) : la vue est remise à
    /// l'écran sans qu'SwiftUI la mette à jour, la lecture repart d'ici.
    override func didMoveToWindow() {
        super.didMoveToWindow()
        refreshPlayback()
    }

    private func refreshPlayback() {
        if wantsPlaying && window != nil { queue?.play() } else { queue?.pause() }
    }

    func stop() {
        queue?.pause()
        looper?.disableLooping()
        playerLayer.player = nil
        readyObservation = nil
        looper = nil
        queue = nil
    }
}

/// La vidéo apparaît en fondu par-dessus ce qui est derrière (la pochette
/// fixe) dès qu'elle est prête ; en pause, à l'arrière-plan, en économie
/// d'énergie ou avec « Réduire les animations », elle ne tourne pas.
struct MotionOverlay: View {
    let url: URL
    var playing = true

    @State private var ready = false
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        if !reduceMotion && !ProcessInfo.processInfo.isLowPowerModeEnabled {
            LoopingVideo(url: url, playing: playing && scenePhase == .active) { ready = true }
                .opacity(ready ? 1 : 0)
                .animation(.easeIn(duration: 0.8), value: ready)
                .allowsHitTesting(false)
        }
    }
}

/// Boucles Apple Music d'un album ou d'un artiste, gardées en mémoire pour la
/// session (un titre de plus du même album ne redemande rien au serveur).
@MainActor
enum MotionStore {
    private static var cache: [String: MotionVideo?] = [:]

    /// Pochette animée de l'album du titre (format 3:4 d'abord).
    static func albumURL(for track: Track) async -> URL? {
        guard track.source != "exclusive", let id = track.albumSourceId else { return nil }
        let video = await albumVideo(source: track.source, id: id)
        return (video?.tall ?? video?.square).flatMap(URL.init(string:))
    }

    /// Pochette animée d'une page d'album (carré d'abord).
    static func albumSquareURL(source: String, id: String) async -> URL? {
        guard source != "exclusive" else { return nil }
        let video = await albumVideo(source: source, id: id)
        return (video?.square ?? video?.tall).flatMap(URL.init(string:))
    }

    private static func albumVideo(source: String, id: String) async -> MotionVideo? {
        await fetch("album:\(source):\(id)") {
            try await APIClient.shared.albumMotion(source: source, id: id)
        }
    }

    /// Portrait animé (carré) et logo de l'artiste.
    static func artist(source: String, id: String) async -> MotionVideo? {
        await fetch("artist:\(source):\(id)") {
            try await APIClient.shared.artistMotion(source: source, id: id)
        }
    }

    private static func fetch(_ key: String, _ load: () async throws -> MotionVideo) async -> MotionVideo? {
        if let hit = cache[key] { return hit }
        do {
            let video = try await load()
            cache[key] = video
            return video
        } catch APIError.server(let status, _) where status == 404 {
            cache[key] = .some(nil)  // pas de vidéo pour celui-là
            return nil
        } catch {
            return nil  // réseau ou serveur : on réessaiera
        }
    }
}
