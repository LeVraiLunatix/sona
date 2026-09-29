import ActivityKit
import Combine
import Foundation
import UIKit

/// Paroles sur l'écran verrouillé : une Live Activity qui suit la lecture
/// (titre, ligne chantée, ligne suivante), mise à jour à chaque nouvelle
/// ligne. Affichée par l'extension de widgets (`LyricsLiveActivity`).
///
/// iOS n'autorise à lancer une Live Activity que depuis l'app ouverte :
/// elle démarre au premier titre joué app ouverte, puis suit toute la
/// session, écran verrouillé compris. L'écoute ensemble a la sienne : pas
/// de paroles pendant une session.
@MainActor
final class LyricsActivity {
    static let shared = LyricsActivity()

    static var enabled: Bool { UserDefaults.standard.bool(forKey: "encre.lyricsActivity") }

    private var activity: Activity<LyricsActivityAttributes>?
    private var lastState: LyricsActivityAttributes.ContentState?
    private var lyrics: Lyrics?
    private var lyricsTrackID: String?
    private var loadTask: Task<Void, Never>?
    private var cancellables = Set<AnyCancellable>()

    private init() {}

    /// À appeler une fois au lancement.
    func bind(_ player: PlayerManager) {
        guard cancellables.isEmpty else { return }
        // Restes d'un lancement précédent (app fermée de force).
        for old in Activity<LyricsActivityAttributes>.activities {
            Task { await old.end(nil, dismissalPolicy: .immediate) }
        }
        // `receive(on:)` : les `@Published` préviennent avant d'avoir changé ;
        // on relit l'état du lecteur une fois la valeur en place.
        player.$current
            .map { $0?.id }
            .removeDuplicates()
            .receive(on: DispatchQueue.main)
            .sink { [weak self] _ in self?.trackChanged() }
            .store(in: &cancellables)
        player.$positionSeconds
            .receive(on: DispatchQueue.main)
            .sink { [weak self] _ in self?.refresh() }
            .store(in: &cancellables)
        player.$isPlaying
            .removeDuplicates()
            .receive(on: DispatchQueue.main)
            .sink { [weak self] _ in self?.refresh() }
            .store(in: &cancellables)
        NotificationCenter.default.publisher(for: UIApplication.didBecomeActiveNotification)
            .sink { [weak self] _ in self?.refresh() }
            .store(in: &cancellables)
    }

    func settingChanged() {
        if Self.enabled {
            trackChanged()
        } else {
            end()
        }
    }

    private func trackChanged() {
        loadTask?.cancel()
        lyrics = nil
        lyricsTrackID = nil
        guard Self.enabled, let track = PlayerManager.shared.current else {
            refresh()
            return
        }
        refresh()
        loadTask = Task { [weak self] in
            let found = try? await APIClient.shared.lyrics(for: track)
            guard let self, !Task.isCancelled, PlayerManager.shared.current?.id == track.id else { return }
            self.lyrics = found ?? nil
            self.lyricsTrackID = track.id
            self.refresh()
        }
    }

    private func refresh() {
        let player = PlayerManager.shared
        guard Self.enabled, let track = player.current, !PartyActivity.isActive else {
            end()
            return
        }
        var line: String?
        var nextLine: String?
        if let lyrics, lyricsTrackID == track.id, lyrics.synced, !lyrics.lines.isEmpty {
            let lines = lyrics.lines
            let position = player.positionSeconds + 0.3
            if let index = lines.lastIndex(where: { ($0.time ?? .infinity) <= position }) {
                let text = lines[index].text.trimmingCharacters(in: .whitespaces)
                line = text.isEmpty ? "♪" : text
                nextLine = lines[(index + 1)...].first { !$0.text.trimmingCharacters(in: .whitespaces).isEmpty }?.text
            } else {
                line = "♪"
                nextLine = lines.first { !$0.text.trimmingCharacters(in: .whitespaces).isEmpty }?.text
            }
        } else if let lyrics, lyricsTrackID == track.id, lyrics.instrumental {
            line = "♪ Instrumental"
        }
        let duration = player.durationSeconds > 0 ? player.durationSeconds : track.durationSeconds.map(Double.init)
        let state = LyricsActivityAttributes.ContentState(
            title: track.title,
            artist: track.artist,
            line: line,
            nextLine: nextLine,
            paused: !player.isPlaying,
            startedAt: player.isPlaying ? Date().addingTimeInterval(-player.positionSeconds) : nil,
            duration: duration
        )
        if let lastState, lastState.title == state.title, lastState.artist == state.artist,
           lastState.line == state.line, lastState.nextLine == state.nextLine, lastState.paused == state.paused,
           abs((lastState.startedAt ?? .distantPast).timeIntervalSince(state.startedAt ?? .distantPast)) < 3 {
            return
        }
        if let activity {
            lastState = state
            Task { await activity.update(ActivityContent(state: state, staleDate: nil)) }
            return
        }
        guard player.isPlaying, UIApplication.shared.applicationState == .active,
              ActivityAuthorizationInfo().areActivitiesEnabled else { return }
        activity = try? Activity.request(
            attributes: LyricsActivityAttributes(id: UUID().uuidString),
            content: ActivityContent(state: state, staleDate: nil)
        )
        lastState = activity == nil ? nil : state
    }

    func end() {
        guard let current = activity else { return }
        activity = nil
        lastState = nil
        Task { await current.end(nil, dismissalPolicy: .immediate) }
    }
}
