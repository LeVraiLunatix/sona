import AVFoundation
import Combine
import Foundation
import MediaPlayer
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
              let reason = AVAudioSession.RouteChangeReason(rawValue: reasonValue),
              reason == .oldDeviceUnavailable else { return }
        player?.pause()
        isPlaying = false
    }

    /// Play/pause/suivant/précédent depuis l'écran verrouillé, le Centre de
    /// contrôle ou les boutons d'un casque/des AirPods.
    private func configureRemoteCommands() {
        let commands = MPRemoteCommandCenter.shared()
        commands.playCommand.addTarget { [weak self] _ in
            guard let self, self.player != nil else { return .noSuchContent }
            self.player?.play()
            self.isPlaying = true
            return .success
        }
        commands.pauseCommand.addTarget { [weak self] _ in
            guard let self, self.player != nil else { return .noSuchContent }
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
    func play(_ track: Track, context playbackContext: [Track] = []) {
        guard track.id != current?.id || player == nil else {
            togglePlayPause()
            return
        }
        endStation()
        start(track, context: playbackContext)
    }

    /// Lance une station : `fetch` donne les premiers morceaux, puis est
    /// rappelée chaque fois que la file s'épuise (nouveau tirage côté
    /// serveur). Lève une erreur si le tout premier tirage échoue ou est
    /// vide, pour que l'écran appelant puisse l'afficher — rien ne joue
    /// encore à ce stade, le mini-lecteur ne le montrerait pas.
    func playStation(fetch: @escaping () async throws -> [Track]) async throws {
        let fetched = try await fetch()
        let tracks = PlayerManager.withoutDuplicates(fetched, excluding: [])
        guard let first = tracks.first else { throw StationError.empty }
        endStation()
        refill = fetch
        start(first, context: tracks)
    }

    private func endStation() {
        refill = nil
        refillTask?.cancel()
        refillTask = nil
        contextGeneration += 1
    }

    /// Démarre la lecture sans toucher à la station en cours : utilisé tel
    /// quel pour avancer/reculer dans le contexte, où `play` couperait la
    /// radio.
    private func start(_ track: Track, context playbackContext: [Track]) {
        teardown()
        current = track
        context = playbackContext.isEmpty ? [track] : playbackContext
        if refill != nil && upNext.count < 3 {
            Task { await self.topUpStation() }
        }
        isLoading = true
        errorMessage = nil

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
            self.beginPlayback(track)
        }
    }

    /// Lecture proprement dite, une fois le fichier prêt côté serveur :
    /// servi depuis son cache disque, il démarre quasi instantanément.
    private func beginPlayback(_ track: Track) {
        do {
            let (url, headers) = try APIClient.shared.streamRequest(source: track.source, id: track.sourceId)
            let asset = AVURLAsset(url: url, options: ["AVURLAssetHTTPHeaderFieldsKey": headers])
            let item = AVPlayerItem(asset: asset)
            let player = AVPlayer(playerItem: item)
            // Volume fixe au maximum : le vrai contrôle de volume, ce sont les
            // boutons physiques et le curseur du Centre de contrôle (voir
            // `SystemVolumeView` dans `NowPlayingSheet`), pas un curseur
            // interne à l'app désynchronisé du reste de l'iPhone.
            player.volume = 1
            self.player = player

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
                    case .paused:
                        self.isPlaying = false
                    case .waitingToPlayAtSpecifiedRate:
                        self.isLoading = true
                    @unknown default:
                        break
                    }
                }
            }

            endObserver = NotificationCenter.default.addObserver(
                forName: .AVPlayerItemDidPlayToEndTime, object: item, queue: .main
            ) { [weak self] _ in
                Task { @MainActor in self?.advance(by: 1) }
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
                    if !self.scrobbled, let track = self.current, let startedAt = self.listenStartedAt,
                       Scrobbler.qualifies(listened: self.listenedSeconds, duration: duration) {
                        self.scrobbled = true
                        Scrobbler.shared.record(track, startedAt: startedAt, listened: duration, duration: duration)
                    }
                    if !self.nextPrepared && self.progress >= 0.6 {
                        self.nextPrepared = true
                        self.prepareNext()
                    }
                    self.updateNowPlayingElapsedTime()
                }
            }

            player.play()
            listenStartedAt = Date()
            scrobbled = false
            nextPrepared = false
            updateNowPlayingInfo(for: track)
            Task { try? await APIClient.shared.nowPlaying(track) }

            // Sans ça, un flux qui ne se décide jamais (serveur qui télécharge
            // et vérifie l'audio en tâche de fond, requête qui ne timeout pas
            // toute seule...) laissait le sablier tourner indéfiniment sans le
            // moindre message — impossible à distinguer d'un blocage réel.
            loadTimeoutTask?.cancel()
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
        guard let next = upNext.first else { return }
        prefetchTask = Task {
            try? await APIClient.shared.prepareStream(source: next.source, id: next.sourceId)
        }
    }

    func togglePlayPause() {
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

    private func advance(by offset: Int) {
        guard let current, let index = context.firstIndex(where: { $0.id == current.id }) else {
            isPlaying = false
            return
        }
        let target = index + offset
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

    /// Saut à une position absolue — une ligne de paroles synchronisées
    /// tapée, par exemple.
    func seek(toSeconds seconds: Double) {
        guard let player else { return }
        player.seek(to: CMTime(seconds: max(0, seconds), preferredTimescale: 600))
        positionSeconds = max(0, seconds)
        if durationSeconds > 0 { progress = min(1, positionSeconds / durationSeconds) }
        updateNowPlayingElapsedTime()
    }

    func seek(toFraction fraction: Double) {
        guard let player, let duration = referenceDuration() else { return }
        let clamped = min(1, max(0, fraction))
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
        finishListening()
        if let timeObserver { player?.removeTimeObserver(timeObserver) }
        if let endObserver { NotificationCenter.default.removeObserver(endObserver) }
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
