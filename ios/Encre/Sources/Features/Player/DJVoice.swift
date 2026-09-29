import AVFoundation
import Foundation

/// DJ vocal : entre deux titres, une voix annonce ce qui arrive, comme à la
/// radio — la musique baisse le temps de l'annonce. Le texte est écrit par
/// le serveur à partir de tes écoutes (découverte, titre en boucle…) et lu
/// par une voix neuronale (naturelle) ; à défaut, par la plus belle voix
/// française de l'iPhone. Réglages dans Son (⋯ du lecteur).
@MainActor
final class DJVoice: NSObject {
    static let shared = DJVoice()

    static var enabled: Bool {
        get { UserDefaults.standard.bool(forKey: "encre.djVoice") }
        set { UserDefaults.standard.set(newValue, forKey: "encre.djVoice") }
    }

    /// Voix neuronale choisie (voir `app/services/dj_voice.py`).
    static var voice: String {
        UserDefaults.standard.string(forKey: "encre.djVoiceName") ?? "remy"
    }

    static let voices: [(id: String, name: String)] = [
        ("remy", "Rémy"),
        ("vivienne", "Vivienne"),
        ("henri", "Henri"),
        ("denise", "Denise"),
    ]

    private let synthesizer = AVSpeechSynthesizer()
    private var audioPlayer: AVAudioPlayer?
    private var lastTrackID: String?
    private var previous: Track?
    private var pending: Task<Void, Never>?

    private override init() {
        super.init()
        synthesizer.delegate = self
    }

    /// Un titre démarre : l'annonce est préparée tout de suite, lue une fois
    /// le fondu d'entrée passé (par-dessus l'intro, comme à la radio). Pas
    /// deux fois pour le même titre (relance après une erreur…).
    func trackStarted(_ track: Track) {
        guard track.id != lastTrackID else { return }
        lastTrackID = track.id
        let before = previous
        previous = track
        pending?.cancel()
        guard Self.enabled, before != nil else { return }
        pending = Task { [weak self] in
            let started = Date()
            let intro = try? await APIClient.shared.djIntro(for: track, after: before, voice: Self.voice)
            let wait = 2.5 - Date().timeIntervalSince(started)
            if wait > 0 { try? await Task.sleep(for: .seconds(wait)) }
            guard let self, !Task.isCancelled else { return }
            let player = PlayerManager.shared
            // Trop tard (plus de 12 s de titre) ou titre changé : on se tait.
            guard player.current?.id == track.id, player.isPlaying, player.positionSeconds < 12 else { return }
            if let audio = intro?.audio, self.play(audio) { return }
            self.speak(intro?.text ?? "On enchaîne avec \(track.title), de \(track.artist).")
        }
    }

    /// « Essayer la voix » : annonce du titre en cours, tout de suite.
    func preview() {
        guard let track = PlayerManager.shared.current else { return }
        stop()
        pending = Task { [weak self] in
            let intro = try? await APIClient.shared.djIntro(for: track, after: nil, voice: Self.voice)
            guard let self, !Task.isCancelled else { return }
            if let audio = intro?.audio, self.play(audio) { return }
            self.speak(intro?.text ?? "Tu écoutes \(track.title), de \(track.artist).")
        }
    }

    func stop() {
        pending?.cancel()
        audioPlayer?.stop()
        audioPlayer = nil
        if synthesizer.isSpeaking { synthesizer.stopSpeaking(at: .word) }
        PlayerManager.shared.setDucked(false)
    }

    /// Voix neuronale (MP3 du serveur).
    private func play(_ data: Data) -> Bool {
        guard let player = try? AVAudioPlayer(data: data) else { return false }
        player.delegate = self
        player.volume = 1
        audioPlayer = player
        PlayerManager.shared.setDucked(true)
        guard player.play() else {
            PlayerManager.shared.setDucked(false)
            return false
        }
        return true
    }

    /// Voix de l'iPhone, en secours.
    private func speak(_ text: String) {
        let utterance = AVSpeechUtterance(string: text)
        utterance.voice = Self.bestVoice
        utterance.rate = AVSpeechUtteranceDefaultSpeechRate
        utterance.pitchMultiplier = 1
        utterance.preUtteranceDelay = 0.1
        utterance.postUtteranceDelay = 0.1
        PlayerManager.shared.setDucked(true)
        synthesizer.speak(utterance)
    }

    /// La plus belle voix française installée (« premium » ou « améliorée »
    /// si téléchargée : Réglages → Accessibilité → Contenu énoncé → Voix).
    private static let bestVoice: AVSpeechSynthesisVoice? = {
        let french = AVSpeechSynthesisVoice.speechVoices().filter { $0.language == "fr-FR" }
        return french.max { $0.quality.rawValue < $1.quality.rawValue } ?? AVSpeechSynthesisVoice(language: "fr-FR")
    }()

    private func finished() {
        audioPlayer = nil
        PlayerManager.shared.setDucked(false)
    }
}

extension DJVoice: AVSpeechSynthesizerDelegate, AVAudioPlayerDelegate {
    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        Task { @MainActor in self.finished() }
    }

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
        Task { @MainActor in self.finished() }
    }

    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        Task { @MainActor in self.finished() }
    }

    nonisolated func audioPlayerDecodeErrorDidOccur(_ player: AVAudioPlayer, error: Error?) {
        Task { @MainActor in self.finished() }
    }
}
