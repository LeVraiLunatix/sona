import AVFoundation
import Combine
import Foundation
import MediaPlayer
import SwiftUI
import UIKit

enum StationError: LocalizedError {
    case empty

    var errorDescription: String? {
        "Cette radio n'a rien renvoyé pour l'instant — réessaie dans un instant."
    }
}

/// Lecture audio : encapsule `AVPlayer`, pointé sur `/stream/{source}/{id}`
/// de l'API Sona (téléchargement + vérification côté serveur, servi avec
/// support `Range` — voir `APIClient.streamRequest`). Garde aussi le
/// contexte de lecture (l'album, la liste d'artiste... d'où vient le
/// morceau) pour "suivant"/"précédent" — un concept purement côté app, la
/// notion de file d'attente n'existe pas côté serveur.
@MainActor
final class PlayerManager: ObservableObject {
    static let shared = PlayerManager()

    @Published private(set) var current: Track?
    @Published private(set) var isPlaying = false
    @Published private(set) var isLoading = false
    @Published private(set) var progress: Double = 0 // 0...1
    @Published private(set) var positionSeconds: Double = 0
    /// Durée réelle du fichier en cours (0 tant qu'elle n'est pas connue) :
    /// plus juste que celle du catalogue, parfois arrondie ou absente.
    @Published private(set) var durationSeconds: Double = 0

    /// Durée de référence du morceau en cours. Celle du catalogue d'abord :
    /// pendant la lecture directe, le serveur relaie le flux YouTube tel
    /// quel (MP4 fragmenté), dont iOS estime mal la durée — souvent le
    /// double, d'où une barre à mi-course quand le titre se termine. Celle
    /// d'iOS ne sert que si le catalogue n'en donne pas.
    private func referenceDuration() -> Double? {
        if let catalog = current?.durationSeconds, catalog > 0 { return Double(catalog) }
        if let item = player?.currentItem?.duration.seconds, item.isFinite, item > 0 { return item }
        return nil
    }
    @Published var errorMessage: String?

    /// Morceaux à venir après `current`, dans l'ordre — pour l'écran "À
    /// suivre" du lecteur plein écran.
    var upNext: [Track] {
        guard let current, let index = context.firstIndex(where: { $0.id == current.id }) else { return [] }
        return Array(context[(index + 1)...])
    }

    // MARK: Écoute ensemble

    /// Invité d'une session : la lecture suit l'hôte — pas de titre suivant
    /// ni de lecture automatique de son côté, c'est l'hôte qui enchaîne.
    @Published var followsParty = false
    /// Position où se placer dès que le titre est prêt (rejoindre en cours).
    private var pendingSeekSeconds: Double?

    func playForParty(_ track: Track, at position: Double) {
        endStation()
        resetQueueState(name: "Écoute ensemble")
        pendingSeekSeconds = position > 1 ? position : nil
        start(track, context: [track])
    }

    /// Sona Connect : la file en cours (autour du titre joué) et sa position.
    var connectPlayback: ConnectPlayback? {
        guard let current else { return nil }
        let index = context.firstIndex(where: { $0.id == current.id }) ?? 0
        let queue = context.isEmpty ? [current] : context
        let start = max(0, index - 20)
        let window = Array(queue[start..<min(queue.count, start + 150)])
        return ConnectPlayback(
            queue: window, index: context.isEmpty ? 0 : index - start,
            position: positionSeconds, paused: !isPlaying, volume: SystemVolume.current, name: contextName
        )
    }

    /// Sona Connect : reprend ici une lecture venue d'un autre appareil.
    func playTransferred(queue: [Track], index: Int, position: Double, name: String?) {
        guard queue.indices.contains(index) else { return }
        endStation()
        resetQueueState(name: name)
        pendingSeekSeconds = position > 1 ? position : nil
        start(queue[index], context: queue)
    }

    func pause() {
        if mixTask != nil { promoteMix() }
        player?.pause()
    }

    func resume() {
        if startRestored() { return }
        guard let player else { return }
        try? AVAudioSession.sharedInstance().setActive(true)
        player.play()
    }

    /// Relance le titre en cours depuis le début, en redemandant le flux au
    /// serveur (après « Mauvaise version ? »).
    func reloadCurrent() {
        guard let current else { return }
        start(current, context: context)
    }

    // MARK: AutoMix

    /// Durée de l'enchaînement entre deux titres.
    private let mixLength: Double = 8
    private var mixIncoming: AVPlayer?
    private var mixIncomingTrack: Track?
    private var mixTask: Task<Void, Never>?
    private var mixRate: Float = 1
    private var isFadingIn = false
    private var bpmCache: [String: Double] = [:]
    /// Un enchaînement est en cours (affiché dans le lecteur).
    @Published private(set) var isMixing = false
    /// Tempo de B calé sur A pendant l'enchaînement (1 = inchangé).
    @Published private(set) var mixTempoRatio: Double = 1

    private func bpm(of track: Track) -> Double? { track.bpm ?? bpmCache[track.id] }

    /// Analyses audio (serveur) : sonie, début, outro, fin.
    private var analysisCache: [String: TrackAnalysis] = [:]
    private var analysisRequested: [String: Date] = [:]
    /// Sonie visée (LUFS) : les titres plus forts sont baissés d'autant,
    /// tous sonnent pareil d'un titre à l'autre.
    private let targetLoudness = -10.0

    private func analysis(of track: Track?) -> TrackAnalysis? {
        track.flatMap { analysisCache[$0.id] }
    }

    /// Demandée au plus toutes les 30 s par titre (elle est calculée par le
    /// serveur une fois le fichier en cache).
    private func fetchAnalysis(_ track: Track) {
        guard analysisCache[track.id] == nil else { return }
        if let last = analysisRequested[track.id], Date().timeIntervalSince(last) < 30 { return }
        analysisRequested[track.id] = Date()
        Task { [weak self] in
            guard let found = await APIClient.shared.analysis(source: track.source, id: track.sourceId) else { return }
            guard let self else { return }
            self.analysisCache[track.id] = found
            // Titre en cours : volume égalisé dès que l'analyse arrive.
            if self.crossfadeEnabled, self.current?.id == track.id, self.mixTask == nil, !self.isFadingIn,
               let player = self.player, player.volume > 0.99 {
                player.volume = self.gain(for: track)
            }
        }
    }

    /// Volume qui ramène le titre à la sonie visée (jamais au-dessus de 1).
    private func gain(for track: Track?) -> Float {
        guard crossfadeEnabled, let loudness = analysis(of: track)?.loudness else { return 1 }
        return Float(min(1, pow(10, (targetLoudness - loudness) / 20)))
    }

    /// Durée d'enchaînement : l'outro de A (4 à 12 s), arrondie à des
    /// mesures entières quand le tempo est connu.
    private func mixDuration(for track: Track, position: Double, end: Double) -> Double {
        var length = mixLength
        if analysis(of: track) != nil { length = min(12, max(4, end - position)) }
        if let bpm = bpm(of: track), bpm > 0 {
            let bar = 240 / bpm
            length = min(16, max(bar * 2, (length / bar).rounded() * bar))
        }
        return max(2, min(length, end - position))
    }

    /// Tempo inconnu : demandé une fois (fiche complète, en cache serveur).
    private func fetchBPM(_ track: Track) {
        guard bpm(of: track) == nil, track.source == "deezer" else { return }
        Task { [weak self] in
            if let full = try? await APIClient.shared.track(source: track.source, id: track.sourceId), let value = full.bpm {
                self?.bpmCache[track.id] = value
            }
        }
    }

    /// Rapport de vitesse qui cale le tempo de B sur celui de A, à ±8 % au
    /// plus (au-delà, on ne déforme pas le titre : simple fondu).
    private func tempoRatio(from a: Track, to b: Track) -> Float {
        guard let bpmA = bpm(of: a), let bpmB = bpm(of: b), bpmA > 0, bpmB > 0 else { return 1 }
        for ratio in [bpmA / bpmB, bpmA / (bpmB * 2), (bpmA * 2) / bpmB] where abs(ratio - 1) <= 0.08 {
            return Float(ratio)
        }
        return 1
    }

    /// À chaque tic de lecture quand l'AutoMix est actif : B est chargé en
    /// silence un peu avant, puis l'enchaînement démarre quand A retombe
    /// (outro repérée par l'analyse du serveur), sinon `mixLength` secondes
    /// avant la fin. Sans suivant prêt, simple fondu de sortie.
    private func autoMixTick(position: Double, duration: Double) {
        let info = analysis(of: current)
        // Fin réelle (silence final ignoré) et moment où le titre retombe.
        let end = min(info?.end ?? duration, duration)
        // Pas plus de 16 s avant la fin : on coupe l'outro, pas le morceau.
        let mixStart = info.map { max($0.mixOut, $0.end - 16, $0.start) } ?? (duration - mixLength)
        let canMix = !followsParty && repeatMode != .one && sleepTimer != .endOfTrack
        if canMix, let next = upNext.first, position < end {
            if mixIncoming != nil, mixIncomingTrack?.id != next.id, mixTask == nil { cancelMix() }
            if position < mixStart - 20, mixIncoming != nil, mixTask == nil {
                cancelMix()  // retour en arrière dans A
            } else if position >= mixStart - 25 {
                fetchAnalysis(next)
                if let current { fetchAnalysis(current) }
            }
            if position >= mixStart - 6 { prepareMix(next: next) }
            if position >= mixStart, end - position > 0.5, mixTask == nil {
                beginMix(length: mixDuration(for: current ?? next, position: position, end: end))
            }
        }
        guard mixTask == nil else { return }
        let remaining = end - position
        let base = gain(for: current)
        if remaining > 0 && remaining < 4 {
            player?.volume = base * Float(max(0.05, remaining / 4))
        } else if remaining >= 4 && position > 2, let player, abs(player.volume - base) > 0.01, !isFadingIn {
            player.volume = base  // retour en arrière après le début du fondu
        }
    }

    private func prepareMix(next: Track) {
        guard mixIncoming == nil else { return }
        let asset: AVURLAsset
        if let local = DownloadManager.shared.localURL(for: next) {
            asset = AVURLAsset(url: local)
        } else if let request = try? APIClient.shared.streamRequest(source: next.source, id: next.sourceId) {
            asset = AVURLAsset(url: request.url, options: ["AVURLAssetHTTPHeaderFieldsKey": request.headers])
        } else {
            return
        }
        let item = AVPlayerItem(asset: asset)
        // Changer la vitesse sans changer la hauteur (pas d'effet « chipmunk »).
        item.audioTimePitchAlgorithm = .timeDomain
        let incoming = AVPlayer(playerItem: item)
        incoming.volume = 0
        mixIncoming = incoming
        mixIncomingTrack = next
    }

    /// A descend, B monte (courbe à puissance constante : le volume perçu
    /// reste stable), B éventuellement accéléré ou ralenti pour tomber sur
    /// le tempo de A.
    private func beginMix(length: Double) {
        guard let outgoing = player, let incoming = mixIncoming, let next = mixIncomingTrack, let current,
              incoming.currentItem?.status == .readyToPlay else { return }
        let rate = tempoRatio(from: current, to: next)
        mixRate = rate
        mixTempoRatio = Double(rate)
        // B démarre là où le son commence vraiment (pas de blanc).
        if let start = analysis(of: next)?.start, start > 0.3 {
            incoming.seek(to: CMTime(seconds: start, preferredTimescale: 600), toleranceBefore: .zero, toleranceAfter: .zero)
        }
        incoming.playImmediately(atRate: rate)
        isMixing = true
        let gainA = gain(for: current)
        let gainB = gain(for: next)
        mixTask = Task { [weak self] in
            let start = Date()
            while !Task.isCancelled {
                let t = min(1, Date().timeIntervalSince(start) / length)
                // Puissance constante, avec un léger décalage façon DJ : B
                // s'installe avant que A ne s'efface vraiment.
                let tA = max(0, min(1, (t - 0.15) / 0.85))
                let tB = min(1, t / 0.85)
                outgoing.volume = gainA * Float(cos(tA * .pi / 2))
                incoming.volume = gainB * Float(sin(tB * .pi / 2))
                if t >= 1 { break }
                try? await Task.sleep(for: .milliseconds(50))
            }
            guard !Task.isCancelled else { return }
            self?.promoteMix()
        }
    }

    /// Fin de l'enchaînement : B devient le titre en cours (file, écran
    /// verrouillé, écoutes, tout suit), puis revient doucement à sa vitesse.
    private func promoteMix() {
        guard let incoming = mixIncoming, let next = mixIncomingTrack else { return }
        mixTask?.cancel()
        mixTask = nil
        mixIncoming = nil
        mixIncomingTrack = nil
        isMixing = false
        teardown()
        current = next
        if refill != nil && upNext.count < 3 {
            Task { await self.topUpStation() }
        } else if refill == nil && autoplayEnabled && upNext.count < 2 {
            requestAutoplay()
        }
        errorMessage = nil
        updateNowPlayingInfo(for: next)
        fetchArtwork(for: next)
        recoveryAttempted = false
        beginPlayback(next, prepared: incoming)
        fetchBPM(next)
        let rate = mixRate
        mixRate = 1
        guard rate != 1 else { return }
        Task { [weak self, weak incoming] in
            for step in 1...20 {
                try? await Task.sleep(for: .milliseconds(400))
                guard let incoming, incoming.timeControlStatus == .playing else { return }
                incoming.rate = rate + (1 - rate) * Float(step) / 20
            }
            self?.mixTempoRatio = 1
        }
    }

    private func cancelMix() {
        mixTask?.cancel()
        mixTask = nil
        mixIncoming?.pause()
        mixIncoming = nil
        mixIncomingTrack = nil
        if isMixing { isMixing = false }
    }

    // MARK: Fin du titre

    private func handleTrackEnd() {
        if mixTask != nil {
            // Fin de A pendant l'enchaînement : B prend la main.
            promoteMix()
            return
        }
        guard !endHandled, player != nil else { return }
        endHandled = true
        stallTask?.cancel()
        advance(by: 1, automatic: true)
    }

    /// Lecteur qui attend des données dans les toutes dernières secondes du
    /// titre : le flux est sans doute fini sans l'avoir dit. S'il n'a pas
    /// repris 3 s plus tard, on passe au suivant.
    private func watchForStallAtEnd(_ track: Track) {
        guard let duration = referenceDuration(), positionSeconds >= duration - 4 else { return }
        stallTask?.cancel()
        stallTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(3))
            guard let self, !Task.isCancelled, self.current?.id == track.id,
                  self.player?.timeControlStatus != .playing else { return }
            self.handleTrackEnd()
        }
    }

    // MARK: Amis : en pause, plus « en train d'écouter »

    /// Pause qui dure (5 s : pas pour un simple saut dans le titre) : les
    /// amis ne voient plus le titre comme en cours d'écoute.
    private func presencePaused() {
        guard presenceShared else { return }
        presenceStopTask?.cancel()
        presenceStopTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(5))
            guard let self, !Task.isCancelled, !self.isPlaying else { return }
            self.presenceShared = false
            try? await APIClient.shared.stopNowPlaying()
        }
    }

    private func presenceResumed() {
        presenceStopTask?.cancel()
        guard !presenceShared, let current else { return }
        presenceShared = true
        let position = positionSeconds
        Task { try? await APIClient.shared.nowPlaying(current, position: position) }
    }

    // MARK: Lire ensuite / Lire après

    /// Juste après le titre en cours.
    func playNext(_ tracks: [Track]) {
        guard let index = currentIndex else {
            if let first = tracks.first { play(first, context: tracks) }
            return
        }
        let fresh = tracks.filter { $0.id != current?.id }
        context.removeAll { track in fresh.contains { $0.id == track.id } && track.id != current?.id }
        let at = (context.firstIndex { $0.id == current?.id } ?? index) + 1
        context.insert(contentsOf: fresh, at: at)
        if let start = autoplayStart { autoplayStart = start + fresh.count }
        nextPrepared = false
    }

    /// À la fin de « Poursuivre la lecture » (avant les titres ajoutés par
    /// la lecture automatique).
    func playLater(_ tracks: [Track]) {
        guard currentIndex != nil else {
            if let first = tracks.first { play(first, context: tracks) }
            return
        }
        let fresh = tracks.filter { track in track.id != current?.id && !upNext.contains { $0.id == track.id } }
        let at = min(autoplayStart ?? context.count, context.count)
        context.insert(contentsOf: fresh, at: at)
        if autoplayStart != nil { autoplayStart = at + fresh.count }
    }

    // MARK: Minuteur de sommeil

    enum SleepTimer: Equatable {
        case minutes(Int)
        case endOfTrack
    }

    @Published private(set) var sleepTimer: SleepTimer?
    /// Heure d'arrêt, pour le compte à rebours affiché.
    @Published private(set) var sleepDeadline: Date?

    func setSleepTimer(_ timer: SleepTimer?) {
        sleepTask?.cancel()
        sleepTask = nil
        sleepTimer = timer
        sleepDeadline = nil
        guard case .minutes(let minutes) = timer else { return }
        let deadline = Date().addingTimeInterval(TimeInterval(minutes * 60))
        sleepDeadline = deadline
        sleepTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(minutes * 60))
            guard let self, !Task.isCancelled else { return }
            await self.fadeOutAndPause()
        }
    }

    /// Baisse le son en 5 s puis met en pause (l'arrêt net réveille).
    private func fadeOutAndPause() async {
        sleepTimer = nil
        sleepDeadline = nil
        guard let player else { return }
        for step in stride(from: 10, through: 0, by: -1) {
            player.volume = Float(step) / 10
            try? await Task.sleep(for: .milliseconds(500))
        }
        player.pause()
        player.volume = 1
    }

    // MARK: File d'attente (façon Musique)

    enum RepeatMode { case off, all, one }

    @Published private(set) var shuffleEnabled = false
    @Published private(set) var repeatMode: RepeatMode = .off
    /// ∞ : quand la liste se termine, des titres similaires (le « mix » de
    /// l'artiste) s'enchaînent tout seuls.
    @Published private(set) var autoplayEnabled = UserDefaults.standard.object(forKey: "encre.autoplay") as? Bool ?? true
    /// AutoMix : les titres s'enchaînent en se superposant (fondu à puissance
    /// constante, tempo calé si possible), voir « AutoMix » plus bas.
    @Published private(set) var crossfadeEnabled = UserDefaults.standard.bool(forKey: "encre.crossfade")
    /// D'où vient la lecture (« De Nuance ») — l'album, l'artiste, la radio...
    @Published private(set) var contextName: String?
    /// Indice, dans `context`, du premier titre ajouté par la lecture
    /// automatique (après la liste d'origine).
    @Published private var autoplayStart: Int?
    private var unshuffledContext: [Track]?
    private var autoplayTask: Task<Void, Never>?

    private var currentIndex: Int? {
        guard let current else { return nil }
        return context.firstIndex(where: { $0.id == current.id })
    }

    /// « Poursuivre la lecture » : la suite de la liste d'origine.
    var queuedNext: [Track] {
        guard let index = currentIndex else { return [] }
        let end = max(index + 1, min(autoplayStart ?? context.count, context.count))
        return Array(context[(index + 1)..<end])
    }

    /// « Lecture automatique » : les titres similaires ajoutés ensuite.
    var autoplayNext: [Track] {
        guard let index = currentIndex, let start = autoplayStart else { return [] }
        let from = max(index + 1, start)
        return from < context.count ? Array(context[from...]) : []
    }

    func toggleShuffle() {
        guard let index = currentIndex else { return }
        let end = autoplayStart ?? context.count
        if shuffleEnabled {
            if let original = unshuffledContext {
                let known = Set(original.map(\.id))
                context = original + context.filter { !known.contains($0.id) }
            }
            unshuffledContext = nil
            shuffleEnabled = false
        } else {
            unshuffledContext = context
            if index + 1 < end {
                context.replaceSubrange((index + 1)..<end, with: context[(index + 1)..<end].shuffled())
            }
            shuffleEnabled = true
        }
    }

    func cycleRepeat() {
        switch repeatMode {
        case .off: repeatMode = .all
        case .all: repeatMode = .one
        case .one: repeatMode = .off
        }
    }

    func toggleAutoplay() {
        autoplayEnabled.toggle()
        UserDefaults.standard.set(autoplayEnabled, forKey: "encre.autoplay")
        if autoplayEnabled {
            if upNext.count < 2 { requestAutoplay() }
        } else {
            autoplayTask?.cancel()
            autoplayTask = nil
            if let start = autoplayStart {
                let keepEnd = max(start, (currentIndex ?? -1) + 1)
                if keepEnd < context.count { context.removeSubrange(keepEnd..<context.count) }
                autoplayStart = nil
            }
        }
    }

    func toggleCrossfade() {
        crossfadeEnabled.toggle()
        UserDefaults.standard.set(crossfadeEnabled, forKey: "encre.crossfade")
        if !crossfadeEnabled { player?.volume = 1 }
    }

    /// Réordonne « Poursuivre la lecture » (glisser-déposer dans la file).
    func moveQueued(from source: IndexSet, to destination: Int) {
        guard let index = currentIndex else { return }
        let end = min(autoplayStart ?? context.count, context.count)
        guard index + 1 < end else { return }
        var queued = Array(context[(index + 1)..<end])
        queued.move(fromOffsets: source, toOffset: destination)
        context.replaceSubrange((index + 1)..<end, with: queued)
    }

    func removeFromQueue(_ track: Track) {
        guard let current = currentIndex,
              let index = context.indices.first(where: { $0 > current && context[$0].id == track.id }) else { return }
        context.remove(at: index)
        if let start = autoplayStart, index < start { autoplayStart = start - 1 }
    }

    /// Ajoute le « mix » de l'artiste en cours à la fin de la file.
    private func requestAutoplay() {
        guard autoplayTask == nil, refill == nil, repeatMode != .all, autoplayEnabled, !followsParty,
              let seed = current, let artistId = seed.artistSourceId else { return }
        let generation = contextGeneration
        autoplayTask = Task { [weak self] in
            let tracks = (try? await APIClient.shared.artistRadio(source: seed.source, id: artistId)) ?? []
            guard let self else { return }
            defer { if self.contextGeneration == generation { self.autoplayTask = nil } }
            guard !Task.isCancelled, self.contextGeneration == generation, self.autoplayEnabled else { return }
            let fresh = PlayerManager.withoutDuplicates(tracks, excluding: Set(self.context.map(\.id)))
            guard !fresh.isEmpty else { return }
            if self.autoplayStart == nil { self.autoplayStart = self.context.count }
            self.context.append(contentsOf: fresh)
        }
    }

    /// `@Published` : une station qui se recharge allonge la liste en cours
    /// de lecture, et "À suivre" doit le refléter sans attendre le morceau
    /// suivant.
    @Published private var context: [Track] = []
    /// Station en cours (radio thématique ou d'artiste) : rappelée pour
    /// allonger `context` quand il ne reste presque plus rien à suivre — la
    /// radio ne s'arrête jamais. `nil` pour un album, une liste... finis.
    private var refill: (() async throws -> [Track])?
    /// Une radio est en cours : la file se renouvelle toute seule.
    var isStation: Bool { refill != nil }
    private var refillTask: Task<Void, Never>?
    /// Incrémenté à chaque nouveau contexte : un rechargement de station
    /// terminé après que l'utilisateur a lancé autre chose ne doit pas
    /// ajouter ses morceaux à la nouvelle liste.
    private var contextGeneration = 0
    private var player: AVPlayer?
    private var timeObserver: Any?
    private var endObserver: NSObjectProtocol?
    private var failedEndObserver: NSObjectProtocol?
    private var stallTask: Task<Void, Never>?
    /// Fin du titre déjà traitée (passage au suivant lancé) : plusieurs
    /// signaux peuvent l'annoncer, un seul doit compter.
    private var endHandled = false
    private var statusObserver: NSKeyValueObservation?
    private var timeControlObserver: NSKeyValueObservation?
    private var interruptionObserver: NSObjectProtocol?
    private var routeChangeObserver: NSObjectProtocol?
    private var coverTask: Task<Void, Never>?
    private var loadTimeoutTask: Task<Void, Never>?
    private var prepareTask: Task<Void, Never>?
    private var recoveryAttempted = false
    private var prefetchTask: Task<Void, Never>?
    private var nextPrepared = false
    /// Temps réellement écouté du morceau en cours (les sauts ne comptent
    /// pas) : décide s'il devient une écoute des stats (voir `Scrobbler`).
    private var listenedSeconds: Double = 0
    private var lastTick: Double?
    private var listenStartedAt: Date?
    /// L'écoute en cours a déjà été enregistrée (dès la moitié du titre).
    private var scrobbled = false
    private var nowPlayingArtwork: MPMediaItemArtwork?
    /// Avancée vers le seuil où l'écoute compte (moitié du titre ou 4 min),
    /// de 0 à 1, et écoute déjà comptée : affichées en direct dans Stats.
    @Published private(set) var scrobbleProgress: Double = 0
    @Published private(set) var didScrobble = false
    /// « En train d'écouter » annoncé aux amis pour le titre en cours.
    private var presenceShared = false
    private var presenceStopTask: Task<Void, Never>?
    private var sleepTask: Task<Void, Never>?

    private init() {
        configureAudioSession()
        configureRemoteCommands()
    }

    // MARK: - Session audio & Centre de contrôle

    /// Catégorie `.playback` : seule catégorie qui (1) ignore le bouton
    /// silence — sans ça, un morceau lancé silencieux passe facilement pour
    /// "qui ne se lance pas" — et (2) autorise la lecture en fond une fois
    /// `UIBackgroundModes: [audio]` déclaré dans `project.yml`.
    private func configureAudioSession() {
        let session = AVAudioSession.sharedInstance()
        try? session.setCategory(.playback, mode: .default)

        interruptionObserver = NotificationCenter.default.addObserver(
            forName: AVAudioSession.interruptionNotification, object: session, queue: .main
        ) { [weak self] notification in
            Task { @MainActor in self?.handleInterruption(notification) }
        }
        // Écouteurs débranchés / sortie audio changée pendant la lecture :
        // convention système (Musique, Podcasts...) — on met en pause plutôt
        // que de continuer à jouer bruyamment sur le haut-parleur.
        routeChangeObserver = NotificationCenter.default.addObserver(
            forName: AVAudioSession.routeChangeNotification, object: session, queue: .main
        ) { [weak self] notification in
            Task { @MainActor in self?.handleRouteChange(notification) }
        }
    }

    private func handleInterruption(_ notification: Notification) {
        guard let info = notification.userInfo,
              let typeValue = info[AVAudioSessionInterruptionTypeKey] as? UInt,
              let type = AVAudioSession.InterruptionType(rawValue: typeValue) else { return }
        switch type {
        case .began:
            player?.pause()
            isPlaying = false
        case .ended:
            guard let optionsValue = info[AVAudioSessionInterruptionOptionKey] as? UInt else { return }
            if AVAudioSession.InterruptionOptions(rawValue: optionsValue).contains(.shouldResume) {
                player?.play()
                isPlaying = true
            }
        @unknown default:
            break
        }
    }

    private func handleRouteChange(_ notification: Notification) {
        guard let info = notification.userInfo,
              let reasonValue = info[AVAudioSessionRouteChangeReasonKey] as? UInt,
              let reason = AVAudioSession.RouteChangeReason(rawValue: reasonValue) else { return }
        switch reason {
        case .oldDeviceUnavailable:
            if isPlaying { pausedByRouteAt = Date() }
            player?.pause()
            isPlaying = false
        case .newDeviceAvailable:
            // Écouteurs remis : reprise si c'est eux qui avaient coupé la lecture.
            let headphones: Set<AVAudioSession.Port> = [.headphones, .bluetoothA2DP, .bluetoothLE, .bluetoothHFP]
            let onHeadphones = AVAudioSession.sharedInstance().currentRoute.outputs.contains { headphones.contains($0.portType) }
            if onHeadphones, let pausedAt = pausedByRouteAt, Date().timeIntervalSince(pausedAt) < 15 * 60,
               UserDefaults.standard.object(forKey: "encre.autoResume") as? Bool ?? true {
                pausedByRouteAt = nil
                resume()
            }
        default:
            break
        }
    }

    /// Play/pause/suivant/précédent depuis l'écran verrouillé, le Centre de
    /// contrôle ou les boutons d'un casque/des AirPods.
    private func configureRemoteCommands() {
        let commands = MPRemoteCommandCenter.shared()
        commands.playCommand.addTarget { [weak self] _ in
            guard let self else { return .noSuchContent }
            if self.startRestored() { return .success }
            guard self.player != nil else { return .noSuchContent }
            self.player?.play()
            self.isPlaying = true
            return .success
        }
        commands.pauseCommand.addTarget { [weak self] _ in
            guard let self, self.player != nil else { return .noSuchContent }
            if self.mixTask != nil { self.promoteMix() }
            self.player?.pause()
            self.isPlaying = false
            return .success
        }
        commands.nextTrackCommand.addTarget { [weak self] _ in
            self?.next()
            return .success
        }
        commands.previousTrackCommand.addTarget { [weak self] _ in
            self?.previous()
            return .success
        }
        commands.changePlaybackPositionCommand.addTarget { [weak self] event in
            guard let self, let event = event as? MPChangePlaybackPositionCommandEvent,
                  let duration = self.referenceDuration()
            else { return .commandFailed }
            self.seek(toFraction: event.positionTime / duration)
            return .success
        }
    }

    // MARK: - Lecture

    /// Lance un morceau. `context` est la liste d'où il vient (les morceaux
    /// d'un album, d'un artiste, l'historique...) et doit inclure `track`
    /// lui-même — vide pour un morceau isolé (résultat de recherche, lien
    /// collé) : "suivant"/"précédent" n'ont alors rien à proposer.
    func play(_ track: Track, context playbackContext: [Track] = [], name: String? = nil) {
        guard track.id != current?.id || player == nil else {
            togglePlayPause()
            return
        }
        endStation()
        resetQueueState(name: name)
        start(track, context: playbackContext)
    }

    private func resetQueueState(name: String?) {
        contextName = name
        shuffleEnabled = false
        unshuffledContext = nil
        autoplayStart = nil
    }

    /// Lance une station : `fetch` donne les premiers morceaux, puis est
    /// rappelée chaque fois que la file s'épuise (nouveau tirage côté
    /// serveur). Lève une erreur si le tout premier tirage échoue ou est
    /// vide, pour que l'écran appelant puisse l'afficher — rien ne joue
    /// encore à ce stade, le mini-lecteur ne le montrerait pas.
    func playStation(name: String? = nil, fetch: @escaping () async throws -> [Track]) async throws {
        let fetched = try await fetch()
        let tracks = PlayerManager.withoutDuplicates(fetched, excluding: [])
        guard let first = tracks.first else { throw StationError.empty }
        endStation()
        resetQueueState(name: name)
        refill = fetch
        start(first, context: tracks)
    }

    /// Radio DJ à partir d'un titre : lui d'abord, puis une suite sans fin
    /// pensée pour l'AutoMix (activé au passage). Chaque rechargement repart
    /// du dernier titre en file : la chaîne de tempos continue.
    func playDJRadio(from seed: Track) async throws {
        let batch = try await APIClient.shared.djRadio(seed: seed, exclude: [seed.sourceId])
        guard !batch.isEmpty else { throw StationError.empty }
        if !crossfadeEnabled { toggleCrossfade() }
        let alreadyPlaying = current?.id == seed.id && player != nil
        endStation()
        resetQueueState(name: "Radio DJ · \(seed.title)")
        refill = { [weak self] in
            guard let self else { return [] }
            let tail = self.context.last ?? seed
            return try await APIClient.shared.djRadio(seed: tail, exclude: self.context.suffix(80).map(\.sourceId))
        }
        let tracks = PlayerManager.withoutDuplicates([seed] + batch, excluding: [])
        if alreadyPlaying {
            // Le titre joue déjà : on garde la lecture, seule la suite change.
            context = tracks
        } else {
            start(seed, context: tracks)
        }
    }

    private func endStation() {
        refill = nil
        refillTask?.cancel()
        refillTask = nil
        autoplayTask?.cancel()
        autoplayTask = nil
        contextGeneration += 1
    }

    /// Démarre la lecture sans toucher à la station en cours : utilisé tel
    /// quel pour avancer/reculer dans le contexte, où `play` couperait la
    /// radio.
    private func start(_ track: Track, context playbackContext: [Track]) {
        teardown()
        if track.id != current?.id { restoredPosition = nil }
        current = track
        context = playbackContext.isEmpty ? [track] : playbackContext
        if refill != nil && upNext.count < 3 {
            Task { await self.topUpStation() }
        } else if refill == nil && autoplayEnabled && upNext.count < 2 {
            requestAutoplay()
        }
        errorMessage = nil
        if let remotePlayback {
            // Lecture sur la TV / PS5 : rien ne joue sur l'iPhone.
            isLoading = false
            remotePlayback(track, upNext)
            return
        }
        isLoading = true

        // Activée à chaque lecture plutôt qu'une fois pour toutes : la
        // session peut avoir été désactivée par une interruption (appel,
        // Siri...) entre deux morceaux.
        try? AVAudioSession.sharedInstance().setActive(true)
        updateNowPlayingInfo(for: track)
        fetchArtwork(for: track)

        // Lecture directe : le serveur relaie le flux (déjà en cache, ou
        // YouTube en direct le temps de préparer le fichier) — démarrage en
        // quelques secondes. En cas d'échec, `recover` prend le relais.
        recoveryAttempted = false
        beginPlayback(track)
        if crossfadeEnabled { fetchBPM(track) }
    }

    /// La lecture directe a échoué ou traîne : on demande au serveur de
    /// préparer le fichier complet (sa réponse dit pourquoi si c'est
    /// impossible), puis on relance une seule fois depuis son cache.
    private func recover(_ track: Track, reason: String?) {
        guard current?.id == track.id else { return }
        guard !recoveryAttempted else {
            isLoading = false
            isPlaying = false
            errorMessage = reason ?? "La lecture a échoué."
            return
        }
        recoveryAttempted = true
        teardown()
        isLoading = true
        errorMessage = nil
        prepareTask = Task { [weak self] in
            do {
                try await APIClient.shared.prepareStream(source: track.source, id: track.sourceId)
            } catch {
                guard let self, !Task.isCancelled, self.current?.id == track.id else { return }
                self.isLoading = false
                self.isPlaying = false
                self.errorMessage = error.localizedDescription
                return
            }
            guard let self, !Task.isCancelled, self.current?.id == track.id else { return }
            self.beginPlayback(track, preferLocal: false)
        }
    }

    /// Lecture proprement dite, une fois le fichier prêt côté serveur :
    /// servi depuis son cache disque, il démarre quasi instantanément.
    /// Un titre téléchargé part du fichier sur l'iPhone (instantané, sans
    /// réseau) ; `preferLocal: false` après un échec de ce fichier.
    private func beginPlayback(_ track: Track, preferLocal: Bool = true, prepared: AVPlayer? = nil) {
        do {
            let player: AVPlayer
            let item: AVPlayerItem
            if let prepared, let preparedItem = prepared.currentItem {
                // AutoMix : le titre joue déjà (entré en fondu), on le reprend tel quel.
                player = prepared
                item = preparedItem
                player.volume = gain(for: track)
            } else {
                let asset: AVURLAsset
                if preferLocal, let local = DownloadManager.shared.localURL(for: track) {
                    asset = AVURLAsset(url: local)
                } else {
                    let (url, headers) = try APIClient.shared.streamRequest(source: track.source, id: track.sourceId)
                    asset = AVURLAsset(url: url, options: ["AVURLAssetHTTPHeaderFieldsKey": headers])
                }
                item = AVPlayerItem(asset: asset)
                player = AVPlayer(playerItem: item)
                // Volume fixe au maximum : le vrai contrôle de volume, ce sont les
                // boutons physiques et le curseur du Centre de contrôle (voir
                // `SystemVolumeView` dans `NowPlayingSheet`), pas un curseur
                // interne à l'app désynchronisé du reste de l'iPhone.
                player.volume = crossfadeEnabled ? 0 : 1
            }
            if crossfadeEnabled { fetchAnalysis(track) }
            prepareItem(item)
            if singAlong && prepared == nil { lookForInstrumental(track) }
            self.player = player
            if crossfadeEnabled && prepared == nil {
                // Fondu entrant sur 1,5 s, jusqu'au volume égalisé du titre.
                isFadingIn = true
                Task { [weak self, weak player] in
                    for step in 1...10 {
                        try? await Task.sleep(for: .milliseconds(150))
                        player?.volume = (self?.gain(for: track) ?? 1) * Float(step) / 10
                    }
                    self?.isFadingIn = false
                }
            }

            // `AVPlayerItem.status` : seul moyen fiable de détecter un flux qui
            // échoue (404, timeout, format non supporté...). Sans ça, un échec
            // laissait auparavant `isPlaying = true` sans le moindre son ni
            // message d'erreur — la cause la plus probable de "ça ne se lance
            // pas".
            statusObserver = item.observe(\.status, options: [.new]) { [weak self] item, _ in
                Task { @MainActor in
                    guard let self, self.player?.currentItem === item else { return }
                    switch item.status {
                    case .failed:
                        self.recover(track, reason: item.error?.localizedDescription)
                    case .readyToPlay:
                        self.isLoading = false
                        self.loadTimeoutTask?.cancel()
                        if let seconds = self.pendingSeekSeconds {
                            self.pendingSeekSeconds = nil
                            self.seek(toSeconds: seconds)
                        }
                    default:
                        break
                    }
                }
            }

            // `AVPlayer.timeControlStatus` reflète l'état réel du lecteur
            // (en train de jouer, en pause, ou en train d'attendre des
            // données) plutôt qu'un booléen local qu'on bascule à la main et
            // qui peut diverger de la réalité.
            timeControlObserver = player.observe(\.timeControlStatus, options: [.new]) { [weak self] player, _ in
                Task { @MainActor in
                    guard let self, self.player === player else { return }
                    switch player.timeControlStatus {
                    case .playing:
                        self.isPlaying = true
                        self.isLoading = false
                        self.presenceResumed()
                    case .paused:
                        self.isPlaying = false
                        self.presencePaused()
                    case .waitingToPlayAtSpecifiedRate:
                        self.isLoading = true
                        self.watchForStallAtEnd(track)
                    @unknown default:
                        break
                    }
                }
            }

            endObserver = NotificationCenter.default.addObserver(
                forName: .AVPlayerItemDidPlayToEndTime, object: item, queue: .main
            ) { [weak self] _ in
                Task { @MainActor in self?.handleTrackEnd() }
            }
            // Flux direct coupé avant la fin annoncée (relais YouTube) : iOS
            // envoie ce signal-là au lieu de « fin du titre ». Tout près de
            // la fin, on passe au suivant ; plus tôt, on relance le titre.
            failedEndObserver = NotificationCenter.default.addObserver(
                forName: .AVPlayerItemFailedToPlayToEndTime, object: item, queue: .main
            ) { [weak self] notification in
                let reason = (notification.userInfo?[AVPlayerItemFailedToPlayToEndTimeErrorKey] as? Error)?.localizedDescription
                Task { @MainActor in
                    guard let self, self.player?.currentItem === item else { return }
                    if let duration = self.referenceDuration(), self.positionSeconds >= duration - 8 {
                        self.handleTrackEnd()
                    } else {
                        self.recover(track, reason: reason)
                    }
                }
            }

            timeObserver = player.addPeriodicTimeObserver(
                forInterval: CMTime(seconds: 0.5, preferredTimescale: 600), queue: .main
            ) { [weak self] time in
                // Le bloc de `addPeriodicTimeObserver` n'est pas isolé à
                // l'acteur, même exécuté sur la file main : `Task { @MainActor }`
                // fait le saut explicite requis pour toucher les propriétés
                // `@Published` de ce `@MainActor final class`.
                Task { @MainActor in
                    guard let self, let duration = self.referenceDuration() else { return }
                    if self.crossfadeEnabled {
                        self.autoMixTick(position: time.seconds, duration: duration)
                    }
                    if let last = self.lastTick, self.isPlaying {
                        let delta = time.seconds - last
                        if delta > 0 && delta <= 1.5 { self.listenedSeconds += delta }
                    }
                    self.lastTick = time.seconds
                    self.positionSeconds = time.seconds
                    self.durationSeconds = duration
                    self.progress = min(1, time.seconds / duration)
                    // Écoute comptée dès la moitié du titre (ou 4 min), comme
                    // Last.fm : elle apparaît sur le profil pendant qu'on
                    // écoute encore, pas seulement au titre suivant.
                    let threshold = min(duration / 2, 240)
                    if threshold > 0 {
                        let value = min(1, self.listenedSeconds / threshold)
                        if abs(value - self.scrobbleProgress) >= 0.01 || value == 1 { self.scrobbleProgress = value }
                    }
                    if !self.scrobbled, let track = self.current, let startedAt = self.listenStartedAt,
                       Scrobbler.qualifies(listened: self.listenedSeconds, duration: duration) {
                        self.scrobbled = true
                        self.didScrobble = true
                        Scrobbler.shared.record(track, startedAt: startedAt, listened: duration, duration: duration)
                    }
                    // Durée du catalogue dépassée : le flux joue du vide ou
                    // n'annoncera jamais sa fin — on enchaîne.
                    if time.seconds >= duration + 1.5 {
                        self.handleTrackEnd()
                    }
                    if !self.nextPrepared && self.progress >= 0.6 {
                        self.nextPrepared = true
                        self.prepareNext()
                    }
                    self.updateNowPlayingElapsedTime()
                    self.saveSession()
                }
            }

            endHandled = false
            scrobbleProgress = 0
            didScrobble = false
            if prepared == nil {
                player.play()
            } else {
                isPlaying = true
                isLoading = false
            }
            listenStartedAt = Date()
            scrobbled = false
            nextPrepared = false
            updateNowPlayingInfo(for: track)
            if !followsParty { DJVoice.shared.trackStarted(track) }
            presenceShared = true
            presenceStopTask?.cancel()
            Task { try? await APIClient.shared.nowPlaying(track) }

            // Sans ça, un flux qui ne se décide jamais (serveur qui télécharge
            // et vérifie l'audio en tâche de fond, requête qui ne timeout pas
            // toute seule...) laissait le sablier tourner indéfiniment sans le
            // moindre message — impossible à distinguer d'un blocage réel.
            loadTimeoutTask?.cancel()
            guard prepared == nil else { return }
            loadTimeoutTask = Task { [weak self] in
                try? await Task.sleep(for: .seconds(25))
                guard let self, !Task.isCancelled, self.current?.id == track.id, self.isLoading else { return }
                self.recover(track, reason: "Le morceau met trop de temps à démarrer. Réessaie dans un instant.")
            }
        } catch {
            isLoading = false
            errorMessage = error.localizedDescription
        }
    }

    /// Fait préparer le morceau suivant par le serveur pendant l'écoute du
    /// courant : « suivant » (ou la fin du morceau) enchaîne sans attente.
    /// Lancé une fois le morceau en cours bien entamé (60 %) : son propre
    /// fichier est alors prêt côté serveur, qui n'a plus qu'un téléchargement
    /// à mener — le suivant — au lieu de deux en même temps (de quoi saturer
    /// une petite machine). « Suivant » reste instantané.
    private func prepareNext() {
        prefetchTask?.cancel()
        if crossfadeEnabled, let next = upNext.first { fetchBPM(next) }
        guard let next = upNext.first, !DownloadManager.shared.isDownloaded(next) else { return }
        prefetchTask = Task {
            try? await APIClient.shared.prepareStream(source: next.source, id: next.sourceId)
        }
    }

    func togglePlayPause() {
        if let remoteToggle {
            remoteToggle()
            return
        }
        if startRestored() { return }
        if mixTask != nil { promoteMix() }
        guard let player else { return }
        if player.timeControlStatus == .playing {
            player.pause()
        } else {
            try? AVAudioSession.sharedInstance().setActive(true)
            // Morceau terminé sans suivant : relancer depuis le début plutôt
            // que de rester bloqué sur la dernière image.
            if progress >= 0.995 {
                // Réécoute depuis le début : une nouvelle écoute à compter.
                seek(toFraction: 0)
                listenStartedAt = Date()
                listenedSeconds = 0
                scrobbled = false
                didScrobble = false
                scrobbleProgress = 0
                if let current { Task { try? await APIClient.shared.nowPlaying(current) } }
            }
            player.play()
        }
    }

    /// Repart au début du morceau en cours, ou passe au précédent s'il vient
    /// de démarrer — même règle que le prototype (Encre.dc.html : `prev`).
    func previous() {
        guard positionSeconds <= 3, let current, let index = context.firstIndex(where: { $0.id == current.id }), index > 0 else {
            seek(toFraction: 0)
            return
        }
        start(context[index - 1], context: context)
    }

    func next() {
        advance(by: 1)
    }

    /// Saute directement à un morceau de "À suivre" : ne change pas le
    /// contexte, juste la position de lecture dedans.
    func playFromUpNext(_ track: Track) {
        start(track, context: context)
    }

    /// `automatic` : fin naturelle du titre (répéter le titre s'applique),
    /// par opposition au bouton « suivant ».
    private func advance(by offset: Int, automatic: Bool = false) {
        guard let current, let index = context.firstIndex(where: { $0.id == current.id }) else {
            isPlaying = false
            return
        }
        if automatic && followsParty {
            // Invité : on attend le titre suivant de l'hôte.
            player?.pause()
            isPlaying = false
            return
        }
        if automatic && sleepTimer == .endOfTrack {
            // Minuteur « fin du titre » : on s'arrête là.
            sleepTimer = nil
            player?.pause()
            isPlaying = false
            return
        }
        if automatic && repeatMode == .one {
            start(current, context: context)
            return
        }
        var target = index + offset
        if repeatMode == .all && target >= (autoplayStart ?? context.count) {
            target = 0
        }
        if context.indices.contains(target) {
            start(context[target], context: context)
        } else if refill != nil {
            // Normalement déjà rechargée par `start` (moins de 3 morceaux à
            // suivre) ; ce chemin couvre un rechargement lent ou échoué.
            Task {
                await self.topUpStation()
                guard self.current?.id == current.id, self.context.indices.contains(target) else {
                    self.isPlaying = false
                    return
                }
                self.start(self.context[target], context: self.context)
            }
        } else {
            // Fin de la liste : l'écoute du dernier morceau compte dès maintenant.
            finishListening()
            isPlaying = false
        }
    }

    /// Allonge la station en cours d'un nouveau tirage, sans doublons (un
    /// tirage Deezer repioche volontiers des titres déjà passés). Un seul
    /// rechargement à la fois : un second appel attend simplement le premier.
    private func topUpStation() async {
        if let refillTask {
            await refillTask.value
            return
        }
        guard let refill else { return }
        let generation = contextGeneration
        let task = Task { [weak self] in
            guard let more = try? await refill() else { return }
            guard let self, !Task.isCancelled, self.contextGeneration == generation else { return }
            self.context.append(contentsOf: PlayerManager.withoutDuplicates(more, excluding: Set(self.context.map(\.id))))
        }
        refillTask = task
        await task.value
        if contextGeneration == generation { refillTask = nil }
    }

    /// Un même morceau deux fois dans le contexte casserait "suivant" (qui
    /// repère la position par `firstIndex`) : une station n'y met donc
    /// chaque titre qu'une fois.
    private static func withoutDuplicates(_ tracks: [Track], excluding known: Set<String>) -> [Track] {
        var seen = known
        return tracks.filter { seen.insert($0.id).inserted }
    }

    // MARK: TV / PS5

    /// Lecture déportée (voir `CastManager`) : chaque titre lancé part sur
    /// l'écran au lieu de jouer ici, et lecture/pause le pilote.
    var remotePlayback: ((Track, [Track]) -> Void)?
    var remoteToggle: (() -> Void)?

    // MARK: Karaoké, égaliseur, audio spatial

    /// Mode « chante » : la vraie instrumentale du titre quand elle existe
    /// (YouTube, même durée : les paroles restent calées), sinon la voix
    /// baissée par traitement du son (voir `AudioEffects`).
    @Published private(set) var singAlong = false
    @Published private(set) var singSource: SingSource = .off
    enum SingSource { case off, searching, instrumental, reduced }

    /// Audio spatial (AirPods) : la stéréo spatialisée par iOS, avec suivi
    /// des mouvements de la tête si activé dans le Centre de contrôle.
    @Published var spatialAudio = UserDefaults.standard.object(forKey: "encre.spatial") as? Bool ?? true {
        didSet {
            UserDefaults.standard.set(spatialAudio, forKey: "encre.spatial")
            if let item = player?.currentItem { applySpatial(item) }
        }
    }

    func setSingAlong(_ on: Bool) {
        singAlong = on
        if on {
            if let current { lookForInstrumental(current) }
        } else {
            AudioEffects.singAmount = 0
            if singSource == .instrumental, let current { swapAudio(to: originalAsset(for: current)) }
            singSource = .off
        }
    }

    /// En attendant (ou à défaut de) l'instrumentale : voix baissée.
    private func lookForInstrumental(_ track: Track) {
        singSource = .searching
        AudioEffects.singAmount = 1
        if let item = player?.currentItem { prepareItem(item) }
        Task { [weak self] in
            let found = await APIClient.shared.instrumental(for: track)
            guard let self, self.singAlong, self.current?.id == track.id else { return }
            if let found, let request = try? APIClient.shared.streamRequest(source: found.source, id: found.id) {
                AudioEffects.singAmount = 0
                self.swapAudio(to: AVURLAsset(url: request.url, options: ["AVURLAssetHTTPHeaderFieldsKey": request.headers]))
                self.singSource = .instrumental
            } else {
                self.singSource = .reduced
            }
        }
    }

    private func originalAsset(for track: Track) -> AVURLAsset? {
        if let local = DownloadManager.shared.localURL(for: track) { return AVURLAsset(url: local) }
        guard let request = try? APIClient.shared.streamRequest(source: track.source, id: track.sourceId) else { return nil }
        return AVURLAsset(url: request.url, options: ["AVURLAssetHTTPHeaderFieldsKey": request.headers])
    }

    /// Change le son du titre en cours sans changer de titre (instrumentale
    /// ↔ original) : même position, même état lecture/pause.
    private func swapAudio(to asset: AVURLAsset?) {
        guard let asset, let player else { return }
        let position = player.currentTime()
        let wasPlaying = player.timeControlStatus != .paused
        let item = AVPlayerItem(asset: asset)
        prepareItem(item)
        if let endObserver { NotificationCenter.default.removeObserver(endObserver) }
        endObserver = NotificationCenter.default.addObserver(
            forName: .AVPlayerItemDidPlayToEndTime, object: item, queue: .main
        ) { [weak self] _ in
            Task { @MainActor in self?.handleTrackEnd() }
        }
        player.replaceCurrentItem(with: item)
        player.seek(to: position, toleranceBefore: .zero, toleranceAfter: .zero)
        if wasPlaying { player.play() }
    }

    /// Réglages audio d'un nouvel item : traitement (chante, égaliseur) et
    /// audio spatial.
    private func prepareItem(_ item: AVPlayerItem) {
        applySpatial(item)
        if (singAlong || AudioEffects.isEQActive || AudioEffects.visualizerOn), item.audioMix == nil {
            Task { [weak item] in
                guard let item, let mix = await AudioEffects.audioMix(for: item) else { return }
                item.audioMix = mix
            }
        }
    }

    private func applySpatial(_ item: AVPlayerItem) {
        item.allowedAudioSpatializationFormats = spatialAudio ? .monoStereoAndMultichannel : .multichannel
    }

    /// DJ vocal : le son baisse le temps de l'annonce, puis remonte.
    func setDucked(_ ducked: Bool) {
        guard let player, let current, !isMixing, !isFadingIn else { return }
        let from = player.volume
        let to = gain(for: current) * (ducked ? 0.3 : 1)
        Task { [weak player] in
            for step in 1...8 {
                try? await Task.sleep(for: .milliseconds(40))
                player?.volume = from + (to - from) * Float(step) / 8
            }
        }
    }

    /// Égaliseur modifié : le traitement se branche si besoin sur le titre en cours.
    func audioEffectsChanged() {
        if let item = player?.currentItem { prepareItem(item) }
    }

    // MARK: Reprise de la lecture

    private struct SavedSession: Codable {
        var track: Track
        var context: [Track]
        var position: Double
        var name: String?
    }

    private static let sessionKey = "encre.lastSession"
    private var lastSessionSave = Date.distantPast
    /// Position où reprendre le titre restauré, au premier appui sur lecture.
    private var restoredPosition: Double?

    /// Mémorise le titre, la position et la file (toutes les 10 s au plus).
    func saveSession(force: Bool = false) {
        guard let current, force || Date().timeIntervalSince(lastSessionSave) > 10 else { return }
        lastSessionSave = Date()
        let index = context.firstIndex(where: { $0.id == current.id }) ?? 0
        let window = Array(context[max(0, index - 20)..<min(context.count, index + 150)])
        let saved = SavedSession(track: current, context: window, position: positionSeconds, name: contextName)
        if let data = try? JSONEncoder().encode(saved) {
            UserDefaults.standard.set(data, forKey: Self.sessionKey)
        }
    }

    /// Au lancement : le dernier titre, en pause, prêt à reprendre là où on
    /// l'avait laissé (mini-lecteur visible tout de suite).
    func restoreSession() {
        guard current == nil,
              let data = UserDefaults.standard.data(forKey: Self.sessionKey),
              let saved = try? JSONDecoder().decode(SavedSession.self, from: data) else { return }
        current = saved.track
        context = saved.context.isEmpty ? [saved.track] : saved.context
        contextName = saved.name
        restoredPosition = saved.position
        positionSeconds = saved.position
        if let duration = saved.track.durationSeconds, duration > 0 {
            durationSeconds = Double(duration)
            progress = min(1, saved.position / Double(duration))
        }
        updateNowPlayingInfo(for: saved.track)
        fetchArtwork(for: saved.track)
    }

    /// Lecture demandée sur le titre restauré : il démarre à sa position.
    private func startRestored() -> Bool {
        guard player == nil, let current, let position = restoredPosition else { return false }
        restoredPosition = nil
        pendingSeekSeconds = position > 3 ? position : nil
        start(current, context: context)
        return true
    }

    // MARK: AirPods

    /// Écouteurs retirés pendant la lecture : quand ils reviennent (dans les
    /// 15 minutes), la lecture reprend toute seule.
    private var pausedByRouteAt: Date?

    /// Position exacte, lue à la demande (paroles mot à mot, à chaque image) :
    /// `positionSeconds` n'est publiée que deux fois par seconde.
    var exactPositionSeconds: Double {
        guard let seconds = player?.currentTime().seconds, seconds.isFinite else { return positionSeconds }
        return seconds
    }

    /// Saut à une position absolue — une ligne de paroles synchronisées
    /// tapée, par exemple.
    func seek(toSeconds seconds: Double) {
        guard let player else { return }
        endHandled = false  // retour en arrière : la fin pourra de nouveau enchaîner
        player.seek(to: CMTime(seconds: max(0, seconds), preferredTimescale: 600))
        positionSeconds = max(0, seconds)
        if durationSeconds > 0 { progress = min(1, positionSeconds / durationSeconds) }
        updateNowPlayingElapsedTime()
    }

    func seek(toFraction fraction: Double) {
        guard let player, let duration = referenceDuration() else { return }
        let clamped = min(1, max(0, fraction))
        endHandled = false  // retour en arrière : la fin pourra de nouveau enchaîner
        player.seek(to: CMTime(seconds: clamped * duration, preferredTimescale: 600))
        // Mis à jour tout de suite : sans ça, la barre revient une demi-seconde
        // à l'ancienne position (prochain tick) avant de sauter à la nouvelle.
        progress = clamped
        positionSeconds = clamped * duration
        updateNowPlayingElapsedTime()
    }

    /// Clôt l'écoute du morceau en cours : l'enregistre dans les stats si
    /// elle a assez duré, puis remet le compteur à zéro.
    private func finishListening() {
        if !scrobbled, let track = current, let startedAt = listenStartedAt {
            let duration = durationSeconds > 0 ? durationSeconds : Double(track.durationSeconds ?? 0)
            Scrobbler.shared.record(track, startedAt: startedAt, listened: listenedSeconds, duration: duration)
        }
        listenedSeconds = 0
        lastTick = nil
        listenStartedAt = nil
        scrobbled = false
    }

    private func teardown() {
        cancelMix()
        finishListening()
        if let timeObserver { player?.removeTimeObserver(timeObserver) }
        if let endObserver { NotificationCenter.default.removeObserver(endObserver) }
        if let failedEndObserver { NotificationCenter.default.removeObserver(failedEndObserver) }
        failedEndObserver = nil
        stallTask?.cancel()
        stallTask = nil
        statusObserver?.invalidate()
        timeControlObserver?.invalidate()
        coverTask?.cancel()
        loadTimeoutTask?.cancel()
        prepareTask?.cancel()
        prepareTask = nil
        timeObserver = nil
        endObserver = nil
        statusObserver = nil
        timeControlObserver = nil
        player?.pause()
        player = nil
        progress = 0
        positionSeconds = 0
        durationSeconds = 0
    }

    // MARK: - Écran verrouillé / Centre de contrôle

    private func updateNowPlayingInfo(for track: Track) {
        var info: [String: Any] = [
            MPMediaItemPropertyTitle: track.title,
            MPMediaItemPropertyArtist: track.artist,
            MPNowPlayingInfoPropertyPlaybackRate: 1.0,
        ]
        if let album = track.album { info[MPMediaItemPropertyAlbumTitle] = album }
        if let duration = track.durationSeconds { info[MPMediaItemPropertyPlaybackDuration] = Double(duration) }
        if let nowPlayingArtwork { info[MPMediaItemPropertyArtwork] = nowPlayingArtwork }
        MPNowPlayingInfoCenter.default().nowPlayingInfo = info
    }

    private func updateNowPlayingElapsedTime() {
        guard var info = MPNowPlayingInfoCenter.default().nowPlayingInfo else { return }
        info[MPNowPlayingInfoPropertyElapsedPlaybackTime] = positionSeconds
        info[MPNowPlayingInfoPropertyPlaybackRate] = isPlaying ? 1.0 : 0.0
        MPNowPlayingInfoCenter.default().nowPlayingInfo = info
    }

    /// Récupère la pochette pour l'écran verrouillé : purement cosmétique, un
    /// échec (pas de réseau, pas de pochette) laisse juste l'info sans
    /// artwork plutôt que de bloquer l'affichage des contrôles.
    private func fetchArtwork(for track: Track) {
        nowPlayingArtwork = nil
        guard let urlString = track.coverURL, let url = URL(string: urlString) else { return }
        coverTask = Task { [weak self] in
            guard let (data, _) = try? await URLSession.shared.data(from: url), let image = UIImage(data: data) else { return }
            guard !Task.isCancelled else { return }
            let artwork = MPMediaItemArtwork(boundsSize: image.size) { _ in image }
            await MainActor.run {
                guard let self, self.current?.id == track.id else { return }
                self.nowPlayingArtwork = artwork
                self.updateNowPlayingInfo(for: track)
            }
        }
    }
}
