import AVFoundation
import Foundation

/// Pistes voix / instru séparées par le serveur (voir `app/services/karaoke.py`),
/// gardées sur l'iPhone : une fois téléchargées (≈ 7 Mo par titre), le
/// titre repasse en karaoké instantanément.
///
/// Deux qualités : « fast » (passe rapide, prête en 2 min environ) puis
/// « hq » (passe fine, qui la remplace). Deux dossiers :
/// - Caches : iOS peut le vider en cas de manque de place, les pistes sont
///   alors simplement retéléchargées depuis le serveur ;
/// - titres téléchargés pour l'écoute hors ligne : leurs pistes sont gardées
///   avec eux (dossier des téléchargements), le karaoké marche sans réseau.
@MainActor
final class KaraokeStore {
    static let shared = KaraokeStore()

    struct Stems {
        let vocals: URL
        let instrumental: URL
        /// « fast » ou « hq ».
        let quality: String
    }

    enum StoreError: LocalizedError {
        case download

        var errorDescription: String? { "Pistes séparées impossibles à télécharger." }
    }

    /// Qualités, de la meilleure à la moins bonne.
    static let qualities = ["hq", "fast"]

    /// Titres gardés au plus dans le cache (les moins récemment chantés
    /// partent d'abord ; jamais ceux des titres téléchargés).
    private let maxTracks = 40
    private let cacheDirectory: URL
    private let offlineDirectory: URL
    private var inFlight: [String: Task<Stems, Error>] = [:]

    private init() {
        let manager = FileManager.default
        let caches = manager.urls(for: .cachesDirectory, in: .userDomainMask)[0]
        cacheDirectory = caches.appendingPathComponent("Karaoke", isDirectory: true)
        // Dans le dossier des téléchargements (exclu de la sauvegarde iCloud).
        let support = manager.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        offlineDirectory = support.appendingPathComponent("Downloads/Karaoke", isDirectory: true)
        for directory in [cacheDirectory, offlineDirectory] {
            try? manager.createDirectory(at: directory, withIntermediateDirectories: true)
        }
        // Pistes d'avant les deux qualités (sans qualité dans le nom) :
        // plus lues, supprimées.
        let old = (try? manager.contentsOfDirectory(at: cacheDirectory, includingPropertiesForKeys: nil)) ?? []
        for file in old where !file.lastPathComponent.contains("_hq_") && !file.lastPathComponent.contains("_fast_") {
            try? manager.removeItem(at: file)
        }
    }

    private func url(for track: Track, stem: String, quality: String, in directory: URL) -> URL {
        let safe = "\(track.source)_\(track.sourceId)".map { $0.isLetter || $0.isNumber || $0 == "_" || $0 == "-" ? $0 : "_" }
        return directory.appendingPathComponent("\(String(safe))_\(quality)_\(stem).m4a")
    }

    private func stems(for track: Track, quality: String, in directory: URL) -> Stems? {
        let stems = Stems(
            vocals: url(for: track, stem: "vocals", quality: quality, in: directory),
            instrumental: url(for: track, stem: "instrumental", quality: quality, in: directory),
            quality: quality
        )
        let manager = FileManager.default
        guard manager.fileExists(atPath: stems.vocals.path), manager.fileExists(atPath: stems.instrumental.path) else { return nil }
        return stems
    }

    /// Les meilleures pistes déjà sur l'iPhone.
    func localStems(for track: Track) -> Stems? {
        for quality in Self.qualities {
            for directory in [offlineDirectory, cacheDirectory] {
                if let found = stems(for: track, quality: quality, in: directory) { return found }
            }
        }
        return nil
    }

    /// Télécharge les deux pistes dans la qualité annoncée par le serveur
    /// (les deux dans la même : voix + instru redonnent alors le titre).
    /// Un second appel pour le même titre attend simplement le premier.
    func fetch(_ track: Track, quality: String) async throws -> Stems {
        if let local = localStems(for: track), local.quality == quality || local.quality == "hq" {
            markUsed(local)
            return local
        }
        let key = "\(track.id)|\(quality)"
        if let running = inFlight[key] { return try await running.value }
        let directory = DownloadManager.shared.isDownloaded(track) ? offlineDirectory : cacheDirectory
        let task = Task { [self] () throws -> Stems in
            for stem in ["instrumental", "vocals"] {
                let request = try APIClient.shared.karaokeStemRequest(track, stem: stem, quality: quality)
                let (temporary, response) = try await URLSession.shared.download(for: request)
                guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
                    try? FileManager.default.removeItem(at: temporary)
                    throw StoreError.download
                }
                let destination = url(for: track, stem: stem, quality: quality, in: directory)
                try? FileManager.default.removeItem(at: destination)
                try FileManager.default.moveItem(at: temporary, to: destination)
            }
            guard let stems = stems(for: track, quality: quality, in: directory) else { throw StoreError.download }
            return stems
        }
        inFlight[key] = task
        defer { inFlight[key] = nil }
        let stems = try await task.value
        // Pistes fines arrivées : les rapides ne servent plus.
        if quality == "hq" { remove(track, quality: "fast") }
        prune()
        return stems
    }

    /// Titre suivant, ou titre téléchargé qu'on écoute : ses pistes sont
    /// récupérées si le serveur les a (en mieux que celles déjà là).
    func prefetch(_ track: Track) async {
        let local = localStems(for: track)
        guard local?.quality != "hq",
              let status = try? await APIClient.shared.karaokeStatus(track), status.status == "ready" else { return }
        let quality = status.quality ?? "hq"
        guard local == nil || quality == "hq" else { return }
        _ = try? await fetch(track, quality: quality)
    }

    /// Titre téléchargé pour l'écoute hors ligne : ses pistes (déjà là, ou
    /// prêtes sur le serveur) sont gardées avec lui.
    func keepOffline(_ track: Track) async {
        let manager = FileManager.default
        for quality in Self.qualities {
            for stem in ["vocals", "instrumental"] {
                let cached = url(for: track, stem: stem, quality: quality, in: cacheDirectory)
                guard manager.fileExists(atPath: cached.path) else { continue }
                let kept = url(for: track, stem: stem, quality: quality, in: offlineDirectory)
                try? manager.removeItem(at: kept)
                try? manager.moveItem(at: cached, to: kept)
            }
        }
        await prefetch(track)
    }

    /// Titre retiré des téléchargements : ses pistes retournent au cache
    /// (elles peuvent encore servir, iOS pourra les effacer).
    func releaseOffline(_ track: Track) {
        let manager = FileManager.default
        for quality in Self.qualities {
            for stem in ["vocals", "instrumental"] {
                let kept = url(for: track, stem: stem, quality: quality, in: offlineDirectory)
                guard manager.fileExists(atPath: kept.path) else { continue }
                let cached = url(for: track, stem: stem, quality: quality, in: cacheDirectory)
                try? manager.removeItem(at: cached)
                try? manager.moveItem(at: kept, to: cached)
            }
        }
        prune()
    }

    /// Tous les téléchargements supprimés : leurs pistes aussi.
    func removeAllOffline() {
        let manager = FileManager.default
        let files = (try? manager.contentsOfDirectory(at: offlineDirectory, includingPropertiesForKeys: nil)) ?? []
        files.forEach { try? manager.removeItem(at: $0) }
    }

    /// Pistes illisibles : supprimées partout (retéléchargées au besoin).
    func remove(_ track: Track, quality: String? = nil) {
        for level in quality.map({ [$0] }) ?? Self.qualities {
            for directory in [offlineDirectory, cacheDirectory] {
                for stem in ["vocals", "instrumental"] {
                    try? FileManager.default.removeItem(at: url(for: track, stem: stem, quality: level, in: directory))
                }
            }
        }
    }

    private func markUsed(_ stems: Stems) {
        for url in [stems.vocals, stems.instrumental] {
            try? FileManager.default.setAttributes([.modificationDate: Date()], ofItemAtPath: url.path)
        }
    }

    private func prune() {
        let manager = FileManager.default
        guard let files = try? manager.contentsOfDirectory(
            at: cacheDirectory, includingPropertiesForKeys: [.contentModificationDateKey]
        ) else { return }
        // Un titre = ses pistes (toutes qualités) : on regroupe par nom sans
        // les suffixes de qualité et de piste.
        var groups: [String: (date: Date, files: [URL])] = [:]
        for file in files where file.pathExtension == "m4a" {
            var name = file.deletingPathExtension().lastPathComponent
            for _ in 0..<2 {
                if let cut = name.lastIndex(of: "_") { name = String(name[..<cut]) }
            }
            let date = (try? file.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
            let existing = groups[name]
            groups[name] = (max(date, existing?.date ?? .distantPast), (existing?.files ?? []) + [file])
        }
        guard groups.count > maxTracks else { return }
        for (_, group) in groups.sorted(by: { $0.value.date < $1.value.date }).prefix(groups.count - maxTracks) {
            group.files.forEach { try? manager.removeItem(at: $0) }
        }
    }
}

/// Lecture des deux pistes ensemble : une composition à deux pistes audio,
/// lues par le même lecteur — elles restent donc parfaitement calées, et
/// seul le volume de la voix change (dans le traitement du son, voir
/// `AudioEffects.vocalGain`), en direct, sans jamais recharger le titre.
/// Sur le fil principal : iOS y exige la création de l'`AVPlayerItem`.
@MainActor
enum KaraokeMix {
    enum MixError: Error { case invalid }

    static func item(_ stems: KaraokeStore.Stems) async throws -> AVPlayerItem {
        let instrumentalAsset = AVURLAsset(url: stems.instrumental)
        let vocalsAsset = AVURLAsset(url: stems.vocals)
        guard let instrumentalSource = try await instrumentalAsset.loadTracks(withMediaType: .audio).first,
              let vocalsSource = try await vocalsAsset.loadTracks(withMediaType: .audio).first else {
            throw MixError.invalid
        }
        let instrumentalRange = try await instrumentalSource.load(.timeRange)
        let vocalsRange = try await vocalsSource.load(.timeRange)

        let composition = AVMutableComposition()
        guard let instrumental = composition.addMutableTrack(withMediaType: .audio, preferredTrackID: kCMPersistentTrackID_Invalid),
              let vocals = composition.addMutableTrack(withMediaType: .audio, preferredTrackID: kCMPersistentTrackID_Invalid) else {
            throw MixError.invalid
        }
        try instrumental.insertTimeRange(instrumentalRange, of: instrumentalSource, at: .zero)
        try vocals.insertTimeRange(vocalsRange, of: vocalsSource, at: .zero)

        let item = AVPlayerItem(asset: composition)
        guard let mix = AudioEffects.stemsMix(instrumental: instrumental, vocals: vocals) else { throw MixError.invalid }
        item.audioMix = mix
        return item
    }
}
