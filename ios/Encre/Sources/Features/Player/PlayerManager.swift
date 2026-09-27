import AVFoundation
import Combine
import Foundation

/// Lecture audio : encapsule `AVPlayer`, pointé sur `/stream/{source}/{id}`
/// de l'API Sona (téléchargement + vérification côté serveur, servi avec
/// support `Range` — voir `APIClient.streamRequest`).
@MainActor
final class PlayerManager: ObservableObject {
    static let shared = PlayerManager()

    @Published private(set) var current: Track?
    @Published private(set) var isPlaying = false
    @Published private(set) var isLoading = false
    @Published private(set) var progress: Double = 0 // 0...1
    @Published private(set) var positionSeconds: Double = 0
    @Published var errorMessage: String?

    private var player: AVPlayer?
    private var timeObserver: Any?
    private var endObserver: NSObjectProtocol?

    func play(_ track: Track) {
        guard track.id != current?.id || player == nil else {
            togglePlayPause()
            return
        }
        teardown()
        current = track
        isLoading = true
        errorMessage = nil

        do {
            let (url, headers) = try APIClient.shared.streamRequest(source: track.source, id: track.sourceId)
            let asset = AVURLAsset(url: url, options: ["AVURLAssetHTTPHeaderFieldsKey": headers])
            let item = AVPlayerItem(asset: asset)
            let player = AVPlayer(playerItem: item)
            self.player = player

            endObserver = NotificationCenter.default.addObserver(
                forName: .AVPlayerItemDidPlayToEndTime, object: item, queue: .main
            ) { [weak self] _ in
                Task { @MainActor in self?.isPlaying = false }
            }

            timeObserver = player.addPeriodicTimeObserver(
                forInterval: CMTime(seconds: 0.5, preferredTimescale: 600), queue: .main
            ) { [weak self] time in
                // Le bloc de `addPeriodicTimeObserver` n'est pas isolé à
                // l'acteur, même exécuté sur la file main : `Task { @MainActor }`
                // fait le saut explicite requis pour toucher les propriétés
                // `@Published` de ce `@MainActor final class`.
                Task { @MainActor in
                    guard let self, let duration = self.player?.currentItem?.duration.seconds, duration.isFinite, duration > 0 else { return }
                    self.positionSeconds = time.seconds
                    self.progress = time.seconds / duration
                }
            }

            player.play()
            isPlaying = true
            isLoading = false
        } catch {
            isLoading = false
            errorMessage = error.localizedDescription
        }
    }

    func togglePlayPause() {
        guard let player else { return }
        if isPlaying {
            player.pause()
        } else {
            player.play()
        }
        isPlaying.toggle()
    }

    func seek(toFraction fraction: Double) {
        guard let player, let duration = player.currentItem?.duration.seconds, duration.isFinite else { return }
        let target = CMTime(seconds: fraction * duration, preferredTimescale: 600)
        player.seek(to: target)
    }

    private func teardown() {
        if let timeObserver { player?.removeTimeObserver(timeObserver) }
        if let endObserver { NotificationCenter.default.removeObserver(endObserver) }
        timeObserver = nil
        endObserver = nil
        player?.pause()
        player = nil
        progress = 0
        positionSeconds = 0
    }
}
