import AVFoundation
import Foundation

/// Pistes voix / instru séparées par le serveur (voir `app/services/karaoke.py`),
/// gardées sur l'iPhone : une fois téléchargées (≈ 7 Mo par titre), le
/// titre repasse en karaoké instantanément, même sans réseau s'il est aussi
/// téléchargé pour l'écoute hors ligne.
///
/// Dossier Caches : iOS peut le vider en cas de manque de place, les pistes
/// sont alors simplement retéléchargées depuis le serveur.
@MainActor
final class KaraokeStore {
    static let shared = KaraokeStore()

    struct Stems {
        let vocals: URL
        let instrumental: URL
    }

    enum StoreError: LocalizedError {
        case download

        var errorDescription: String? { "Pistes séparées impossibles à télécharger." }
    }

    /// Titres gardés au plus (les moins récemment chantés partent d'abord).
    private let maxTracks = 40
    private let directory: URL
    private var inFlight: [String: Task<Stems, Error>] = [:]

    private init() {
        let caches = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
        directory = caches.appendingPathComponent("Karaoke", isDirectory: true)
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    }

    private func url(for track: Track, stem: String) -> URL {
        let safe = "\(track.source)_\(track.sourceId)".map { $0.isLetter || $0.isNumber || $0 == "_" || $0 == "-" ? $0 : "_" }
        return directory.appendingPathComponent("\(String(safe))_\(stem).m4a")
    }

    /// Les deux pistes, si elles sont déjà sur l'iPhone.
    func localStems(for track: Track) -> Stems? {
        let stems = Stems(vocals: url(for: track, stem: "vocals"), instrumental: url(for: track, stem: "instrumental"))
        let manager = FileManager.default
        guard manager.fileExists(atPath: stems.vocals.path), manager.fileExists(atPath: stems.instrumental.path) else { return nil }
        return stems
    }

    /// Télécharge les deux pistes (le serveur doit les avoir prêtes). Un
    /// second appel pour le même titre attend simplement le premier.
    func fetch(_ track: Track) async throws -> Stems {
        if let stems = localStems(for: track) {
            markUsed(stems)
            return stems
        }
        if let running = inFlight[track.id] { return try await running.value }
        let task = Task { [self] () throws -> Stems in
            for stem in ["instrumental", "vocals"] {
                let request = try APIClient.shared.karaokeStemRequest(track, stem: stem)
                let (temporary, response) = try await URLSession.shared.download(for: request)
                guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
                    try? FileManager.default.removeItem(at: temporary)
                    throw StoreError.download
                }
                let destination = url(for: track, stem: stem)
                try? FileManager.default.removeItem(at: destination)
                try FileManager.default.moveItem(at: temporary, to: destination)
            }
            guard let stems = localStems(for: track) else { throw StoreError.download }
            return stems
        }
        inFlight[track.id] = task
        defer { inFlight[track.id] = nil }
        let stems = try await task.value
        prune()
        return stems
    }

    /// Titre suivant, pendant qu'on chante le titre en cours : ses pistes
    /// sont récupérées si le serveur les a déjà séparées — il démarrera
    /// directement en karaoké.
    func prefetch(_ track: Track) async {
        guard localStems(for: track) == nil,
              let status = try? await APIClient.shared.karaokeStatus(track), status.status == "ready" else { return }
        _ = try? await fetch(track)
    }

    func remove(_ track: Track) {
        for stem in ["vocals", "instrumental"] {
            try? FileManager.default.removeItem(at: url(for: track, stem: stem))
        }
    }

    private func markUsed(_ stems: Stems) {
        for url in [stems.vocals, stems.instrumental] {
            try? FileManager.default.setAttributes([.modificationDate: Date()], ofItemAtPath: url.path)
        }
    }

    private func prune() {
        let manager = FileManager.default
        guard let files = try? manager.contentsOfDirectory(at: directory, includingPropertiesForKeys: [.contentModificationDateKey]) else { return }
        // Une paire = un titre : on regroupe par nom sans le suffixe de piste.
        var groups: [String: (date: Date, files: [URL])] = [:]
        for file in files where file.pathExtension == "m4a" {
            let name = file.deletingPathExtension().lastPathComponent
            guard let cut = name.lastIndex(of: "_") else { continue }
            let key = String(name[..<cut])
            let date = (try? file.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
            let existing = groups[key]
            groups[key] = (max(date, existing?.date ?? .distantPast), (existing?.files ?? []) + [file])
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
