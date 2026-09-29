import Combine
import Foundation

/// « Écoute ensemble » côté app. Toutes les deux secondes :
/// - l'hôte envoie ce qu'il joue (titre, position, pause) dès que ça change,
///   et reprend dans sa file les titres proposés par les autres ;
/// - un invité relit l'état et cale son lecteur dessus : même titre, même
///   position (à ~2 s près), même pause.
@MainActor
final class PartyManager: ObservableObject {
    static let shared = PartyManager()

    @Published private(set) var state: PartyState?
    @Published var errorMessage: String?
    /// Réactions arrivées depuis la dernière lecture de l'état (animées à l'écran).
    @Published private(set) var freshReactions: [PartyReaction] = []
    /// Invité : décalage avec la position de l'hôte, pour l'afficher.
    @Published private(set) var driftSeconds: Double = 0

    private var loop: Task<Void, Never>?
    private var lastReactionId = 0
    private var fetchedAt = Date()
    /// Dernier état envoyé par l'hôte.
    private var sent: (trackId: String?, paused: Bool, position: Double, at: Date)?

    private let player = PlayerManager.shared

    var isInParty: Bool { state != nil }
    var isHost: Bool { state?.isHost == true }
    var isGuest: Bool { state != nil && state?.isHost == false }

    private init() {}

    // MARK: - Entrer / sortir

    func create() async {
        do {
            let fresh = try await APIClient.shared.createParty()
            enter(fresh)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func join(code: String) async {
        do {
            let fresh = try await APIClient.shared.joinParty(code: code.uppercased().trimmingCharacters(in: .whitespaces))
            enter(fresh)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func leave() async {
        guard let code = state?.code else { return }
        loop?.cancel()
        loop = nil
        state = nil
        sent = nil
        player.followsParty = false
        try? await APIClient.shared.leaveParty(code: code)
    }

    private func enter(_ fresh: PartyState) {
        errorMessage = nil
        lastReactionId = fresh.reactions.map(\.id).max() ?? 0
        sent = nil
        state = fresh
        fetchedAt = Date()
        player.followsParty = !fresh.isHost
        if !fresh.isHost { follow(fresh) }
        loop?.cancel()
        loop = Task { [weak self] in
            while !Task.isCancelled {
                await self?.tick()
                try? await Task.sleep(for: .seconds(2))
            }
        }
    }

    // MARK: - Boucle

    private func tick() async {
        guard let code = state?.code else { return }
        do {
            var fresh = try await APIClient.shared.partyState(code: code)
            fetchedAt = Date()
            if fresh.isHost {
                fresh = await publishIfNeeded(fresh)
                fresh = await takeProposals(fresh)
            } else {
                follow(fresh)
            }
            collectReactions(fresh)
            state = fresh
        } catch APIError.server(let status, _) where status == 404 || status == 403 {
            // Session terminée (l'hôte est parti) ou plus membre.
            errorMessage = "La session est terminée."
            loop?.cancel()
            state = nil
            player.followsParty = false
        } catch {
            // Coupure passagère : on réessaie au prochain tour.
        }
    }

    /// Hôte : envoie l'état du lecteur s'il a changé (titre, pause, saut).
    private func publishIfNeeded(_ current: PartyState) async -> PartyState {
        let track = player.current
        let paused = !player.isPlaying
        let position = player.positionSeconds
        var changed = sent == nil || sent?.trackId != track?.id || sent?.paused != paused
        if let sent, !changed, !paused {
            let expected = sent.position + Date().timeIntervalSince(sent.at)
            changed = abs(expected - position) > 3  // saut dans le titre
        }
        guard changed else { return current }
        sent = (track?.id, paused, position, Date())
        return (try? await APIClient.shared.setPartyState(code: current.code, track: track, position: position, paused: paused)) ?? current
    }

    /// Hôte : les titres proposés passent dans sa file (après ceux déjà prévus).
    private func takeProposals(_ current: PartyState) async -> PartyState {
        guard !current.queue.isEmpty else { return current }
        player.playLater(current.queue.map(\.track))
        return (try? await APIClient.shared.consumePartyQueue(code: current.code, ids: current.queue.map(\.id))) ?? current
    }

    /// Invité : même titre, même position, même pause que l'hôte.
    private func follow(_ fresh: PartyState) {
        guard let track = fresh.track else { return }
        let target = fresh.position + (fresh.paused ? 0 : Date().timeIntervalSince(fetchedAt))
        if player.current?.id != track.id {
            player.playForParty(track, at: target)
            if fresh.paused { player.pause() }
            return
        }
        if fresh.paused {
            if player.isPlaying { player.pause() }
            if abs(player.positionSeconds - target) > 2 { player.seek(toSeconds: target) }
            driftSeconds = 0
            return
        }
        if !player.isPlaying && !player.isLoading { player.resume() }
        guard !player.isLoading else { return }
        let drift = player.positionSeconds - target
        driftSeconds = drift
        if abs(drift) > 2.5 { player.seek(toSeconds: target) }
    }

    private func collectReactions(_ fresh: PartyState) {
        let new = fresh.reactions.filter { $0.id > lastReactionId }
        guard !new.isEmpty else { return }
        lastReactionId = new.map(\.id).max() ?? lastReactionId
        freshReactions = new
    }

    // MARK: - Actions

    func propose(_ track: Track) async {
        guard let code = state?.code else { return }
        do {
            state = try await APIClient.shared.proposeToParty(code: code, track: track)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func react(_ emoji: String) async {
        guard let code = state?.code else { return }
        if let fresh = try? await APIClient.shared.reactInParty(code: code, emoji: emoji) {
            collectReactions(fresh)
            state = fresh
        }
    }
}
