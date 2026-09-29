import AVFoundation
import Foundation

/// DJ vocal : entre deux titres, une voix annonce ce qui arrive (« On
/// enchaîne avec… »), comme à la radio. La musique baisse le temps de
/// l'annonce. Réglage dans Son (⋯ du lecteur).
@MainActor
final class DJVoice: NSObject {
    static let shared = DJVoice()

    static var enabled: Bool {
        get { UserDefaults.standard.bool(forKey: "encre.djVoice") }
        set { UserDefaults.standard.set(newValue, forKey: "encre.djVoice") }
    }

    private let synthesizer = AVSpeechSynthesizer()
    private var lastTrackID: String?
    private var previous: Track?
    private var announced = 0
    private var pending: Task<Void, Never>?

    private override init() {
        super.init()
        synthesizer.delegate = self
    }

    /// Un titre démarre : annonce quelques secondes après, une fois le
    /// fondu d'entrée passé. Pas deux fois pour le même titre (relance
    /// après une erreur, retour d'une instrumentale…).
    func trackStarted(_ track: Track) {
        guard track.id != lastTrackID else { return }
        lastTrackID = track.id
        let before = previous
        previous = track
        pending?.cancel()
        guard Self.enabled, before != nil else { return }
        pending = Task { [weak self] in
            try? await Task.sleep(for: .seconds(2.5))
            guard let self, !Task.isCancelled else { return }
            let player = PlayerManager.shared
            guard player.current?.id == track.id, player.isPlaying else { return }
            self.speak(self.line(for: track, after: before))
        }
    }

    func stop() {
        pending?.cancel()
        if synthesizer.isSpeaking { synthesizer.stopSpeaking(at: .word) }
    }

    private func line(for track: Track, after before: Track?) -> String {
        announced += 1
        let title = track.title
        let artist = track.artist
        let hour = Calendar.current.component(.hour, from: Date())
        if announced % 6 == 0 {
            return "Tu écoutes Sona. Prochain titre : \(title), de \(artist)."
        }
        if hour >= 23 || hour < 5, announced % 3 == 0 {
            return "Il se fait tard… \(title), de \(artist)."
        }
        if let before, before.artist.caseInsensitiveCompare(artist) == .orderedSame {
            return "Encore \(artist), avec \(title)."
        }
        if let before, announced % 4 == 0 {
            return "C'était \(before.title). Maintenant, \(title), de \(artist)."
        }
        let lines = [
            "On enchaîne avec \(title), de \(artist).",
            "Voici \(artist), avec \(title).",
            "Tu écoutes \(title), de \(artist).",
            "Place à \(artist) : \(title).",
        ]
        return lines[announced % lines.count]
    }

    private func speak(_ text: String) {
        let utterance = AVSpeechUtterance(string: text)
        utterance.voice = Self.bestVoice
        utterance.rate = AVSpeechUtteranceDefaultSpeechRate * 1.02
        utterance.pitchMultiplier = 0.95
        utterance.preUtteranceDelay = 0.2
        PlayerManager.shared.setDucked(true)
        synthesizer.speak(utterance)
    }

    /// La plus belle voix française installée (« améliorée » ou « premium »
    /// si l'iPhone en a téléchargé une : Réglages → Accessibilité →
    /// Contenu énoncé → Voix).
    private static let bestVoice: AVSpeechSynthesisVoice? = {
        let french = AVSpeechSynthesisVoice.speechVoices().filter { $0.language.hasPrefix("fr") }
        return french.max { $0.quality.rawValue < $1.quality.rawValue } ?? AVSpeechSynthesisVoice(language: "fr-FR")
    }()
}

extension DJVoice: AVSpeechSynthesizerDelegate {
    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        Task { @MainActor in PlayerManager.shared.setDucked(false) }
    }

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
        Task { @MainActor in PlayerManager.shared.setDucked(false) }
    }
}
