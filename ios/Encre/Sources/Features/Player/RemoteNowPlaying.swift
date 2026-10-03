import AVFoundation
import Combine
import MediaPlayer
import UIKit

/// Quand l'iPhone pilote un autre appareil (le PC), il fait comme Spotify
/// Connect : l'écran verrouillé et le Centre de contrôle montrent ce que
/// joue le PC (pochette, titre, position) et ses boutons le pilotent ; les
/// boutons de volume de l'iPhone règlent le volume du PC.
///
/// iOS ne montre ces commandes que pour l'app qui joue du son : l'iPhone
/// joue donc du silence, tant qu'il pilote (rien ne sort des haut-parleurs).
/// Seulement quand on pilote vraiment (appareil choisi dans « Appareils »
/// ou télécommande touchée) : ouvrir l'app pendant que le PC joue ne coupe
/// jamais la musique d'une autre app.
@MainActor
final class RemoteNowPlaying {
    static let shared = RemoteNowPlaying()

    private var silence: AVAudioPlayer?
    private var volumeWatch: NSKeyValueObservation?
    private var volumeBeforeRemote: Double?
    /// Volume posé par l'app elle-même (pas par les boutons) : à ne pas renvoyer.
    private var ignoreVolumeUntil = Date.distantPast
    private var volumeTask: Task<Void, Never>?
    private var artworkURL: String?
    private var artwork: MPMediaItemArtwork?
    private var cancellables = Set<AnyCancellable>()
    private(set) var isActive = false

    private init() {}

    func start() {
        guard cancellables.isEmpty else { return }
        ConnectManager.shared.objectWillChange
            .merge(with: PlayerManager.shared.objectWillChange)
            .debounce(for: .milliseconds(120), scheduler: RunLoop.main)
            .sink { [weak self] _ in self?.update() }
            .store(in: &cancellables)
    }

    /// L'iPhone fait-il office de télécommande en ce moment ?
    private var target: ConnectDevice? {
        let connect = ConnectManager.shared
        guard connect.engaged, let device = connect.remoteTarget else { return nil }
        return device
    }

    func update() {
        guard let device = target else {
            deactivate()
            return
        }
        activate(volume: device.volume)
        publish(device)
    }

    // MARK: Silence et session audio

    private func activate(volume: Double?) {
        guard !isActive else { return }
        isActive = true
        let session = AVAudioSession.sharedInstance()
        try? session.setCategory(.playback, mode: .default, options: [])
        try? session.setActive(true)
        if silence == nil, let player = try? AVAudioPlayer(data: Self.silentWAV()) {
            player.numberOfLoops = -1
            player.volume = 0
            silence = player
        }
        silence?.play()
        // Les boutons de volume partent du volume du PC.
        volumeBeforeRemote = SystemVolume.current
        if let volume {
            ignoreVolumeUntil = Date().addingTimeInterval(0.6)
            SystemVolume.set(volume)
        }
        volumeWatch = session.observe(\.outputVolume, options: [.new]) { [weak self] _, change in
            guard let value = change.newValue else { return }
            Task { @MainActor in self?.volumeChanged(Double(value)) }
        }
    }

    private func deactivate() {
        guard isActive else { return }
        isActive = false
        volumeWatch?.invalidate()
        volumeWatch = nil
        volumeTask?.cancel()
        silence?.stop()
        if let volumeBeforeRemote {
            ignoreVolumeUntil = Date().addingTimeInterval(0.6)
            SystemVolume.set(volumeBeforeRemote)
        }
        volumeBeforeRemote = nil
        // L'écran verrouillé retrouve ce que joue (ou jouait) l'iPhone.
        PlayerManager.shared.restoreNowPlayingInfo()
        if !PlayerManager.shared.isPlaying {
            try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        }
    }

    /// Bouton de volume de l'iPhone : le volume part au PC (un envoi par
    /// rafale d'appuis).
    private func volumeChanged(_ value: Double) {
        guard isActive, Date() > ignoreVolumeUntil else { return }
        volumeTask?.cancel()
        volumeTask = Task {
            try? await Task.sleep(for: .milliseconds(150))
            guard !Task.isCancelled else { return }
            ConnectManager.shared.remote("volume", volume: value)
        }
    }

    // MARK: Écran verrouillé

    private func publish(_ device: ConnectDevice) {
        let connect = ConnectManager.shared
        let now = connect.now(on: device)
        guard let track = now.track else {
            MPNowPlayingInfoCenter.default().nowPlayingInfo = [
                MPMediaItemPropertyTitle: "Rien en lecture",
                MPMediaItemPropertyArtist: device.name,
                MPNowPlayingInfoPropertyPlaybackRate: 0.0,
            ]
            return
        }
        var info: [String: Any] = [
            MPMediaItemPropertyTitle: track.title,
            MPMediaItemPropertyArtist: "\(track.artist) · sur \(device.name)",
            MPNowPlayingInfoPropertyElapsedPlaybackTime: now.position,
            MPNowPlayingInfoPropertyPlaybackRate: now.paused ? 0.0 : 1.0,
        ]
        if let album = track.album { info[MPMediaItemPropertyAlbumTitle] = album }
        if let duration = track.durationSeconds { info[MPMediaItemPropertyPlaybackDuration] = Double(duration) }
        if track.coverURL == artworkURL, let artwork { info[MPMediaItemPropertyArtwork] = artwork }
        MPNowPlayingInfoCenter.default().nowPlayingInfo = info
        if track.coverURL != artworkURL { loadArtwork(track.coverURL) }
    }

    private func loadArtwork(_ urlString: String?) {
        artworkURL = urlString
        artwork = nil
        guard let urlString, let url = URL(string: urlString) else { return }
        Task {
            guard let loaded = try? await URLSession.shared.data(from: url), let image = UIImage(data: loaded.0),
                  artworkURL == urlString else { return }
            artwork = MPMediaItemArtwork(boundsSize: image.size) { _ in image }
            update()
        }
    }

    /// Une seconde de silence (WAV 8 kHz, 16 bits, mono), jouée en boucle.
    private static func silentWAV() -> Data {
        let sampleRate: UInt32 = 8000
        let samples = Data(count: Int(sampleRate) * 2)
        var data = Data()
        func append<T: FixedWidthInteger>(_ value: T) { withUnsafeBytes(of: value.littleEndian) { data.append(contentsOf: $0) } }
        data.append(contentsOf: Array("RIFF".utf8))
        append(UInt32(36 + samples.count))
        data.append(contentsOf: Array("WAVEfmt ".utf8))
        append(UInt32(16))
        append(UInt16(1))  // PCM
        append(UInt16(1))  // mono
        append(sampleRate)
        append(sampleRate * 2)
        append(UInt16(2))
        append(UInt16(16))
        data.append(contentsOf: Array("data".utf8))
        append(UInt32(samples.count))
        data.append(samples)
        return data
    }
}
