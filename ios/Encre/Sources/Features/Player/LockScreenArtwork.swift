import AVFoundation
import MediaPlayer
import UIKit

/// Pochette animée d'Apple Music pour l'écran verrouillé et le Centre de
/// contrôle (iOS 26) : le serveur convertit la boucle en MP4 (3:4 et 1:1),
/// l'app la garde dans ses caches et la donne au système avec une image
/// d'aperçu (la première image de la vidéo).
@MainActor
enum LockScreenArtwork {
    /// Entrées à fusionner dans `nowPlayingInfo` ; vide si l'album n'a pas de
    /// vidéo, si l'économie d'énergie est active ou si le système ne les gère pas.
    static func entries(for track: Track) async -> [String: Any] {
        guard track.source != "exclusive", let albumId = track.albumSourceId,
              !ProcessInfo.processInfo.isLowPowerModeEnabled,
              let video = await MotionStore.albumMotion(source: track.source, id: albumId)
        else { return [:] }
        let supported = MPNowPlayingInfoCenter.supportedAnimatedArtworkKeys
        var result: [String: Any] = [:]
        if video.tall != nil, supported.contains(MPNowPlayingInfoProperty3x4AnimatedArtwork),
           let artwork = await artwork(source: track.source, id: albumId, kind: "tall") {
            result[MPNowPlayingInfoProperty3x4AnimatedArtwork] = artwork
        }
        if video.square != nil, supported.contains(MPNowPlayingInfoProperty1x1AnimatedArtwork),
           let artwork = await artwork(source: track.source, id: albumId, kind: "square") {
            result[MPNowPlayingInfoProperty1x1AnimatedArtwork] = artwork
        }
        return result
    }

    private static func artwork(source: String, id: String, kind: String) async -> MPMediaItemAnimatedArtwork? {
        guard let file = try? await APIClient.shared.albumMotionFile(source: source, id: id, kind: kind) else { return nil }
        let generator = AVAssetImageGenerator(asset: AVURLAsset(url: file))
        generator.appliesPreferredTrackTransform = true
        guard let frame = try? await generator.image(at: .zero).image else { return nil }
        let preview = UIImage(cgImage: frame)
        return MPMediaItemAnimatedArtwork(
            artworkID: "sona-\(source)-\(id)-\(kind)",
            previewImageRequestHandler: { _ in preview },
            videoAssetFileURLRequestHandler: { _ in file }
        )
    }
}
