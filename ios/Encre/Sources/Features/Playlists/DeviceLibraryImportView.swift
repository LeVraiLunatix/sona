import MediaPlayer
import SwiftUI

/// Import d'une playlist depuis la bibliothèque Musique de l'iPhone : la
/// liste complète (la page web publique d'Apple Music s'arrête à 300
/// titres), sans lien à partager. Il faut que la playlist soit dans la
/// bibliothèque (synchronisation de la bibliothèque activée dans Musique).
struct DeviceLibraryImportView: View {
    var onStarted: (UserPlaylist) -> Void

    private struct DevicePlaylist: Identifiable {
        let id: UInt64
        let name: String
        let count: Int
        let artwork: UIImage?
        let tracks: [DeviceTrack]
    }

    @State private var authorization = MPMediaLibrary.authorizationStatus()
    @State private var playlists: [DevicePlaylist] = []
    @State private var isLoading = false
    @State private var sendingId: UInt64?
    @State private var errorMessage: String?

    var body: some View {
        List {
            switch authorization {
            case .authorized:
                if isLoading {
                    ProgressView().tint(.white).frame(maxWidth: .infinity).listRowBackground(Color.clear)
                } else if playlists.isEmpty {
                    Text("Aucune playlist dans ta bibliothèque Musique. Ajoute-la à ta bibliothèque dans l'app Musique (et active « Synchroniser la bibliothèque »).")
                        .font(Typo.rowSubtitle)
                        .foregroundStyle(Tone.secondary)
                        .listRowBackground(Color.clear)
                }
                ForEach(playlists) { playlist in
                    Button { Task { await send(playlist) } } label: {
                        HStack(spacing: 14) {
                            Group {
                                if let artwork = playlist.artwork {
                                    Image(uiImage: artwork).resizable().scaledToFill()
                                } else {
                                    Image(systemName: "music.note.list")
                                        .font(.system(size: 20))
                                        .foregroundStyle(Tone.secondary)
                                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                                        .background(Tone.surfaceStrong)
                                }
                            }
                            .frame(width: 52, height: 52)
                            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                            VStack(alignment: .leading, spacing: 2) {
                                Text(playlist.name).font(Typo.rowTitle).foregroundStyle(Tone.primary).lineLimit(1)
                                Text("\(playlist.count) titres").font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
                            }
                            Spacer()
                            if sendingId == playlist.id { ProgressView().tint(.white) }
                        }
                    }
                    .disabled(sendingId != nil || playlist.tracks.isEmpty)
                    .listRowBackground(Color.clear)
                }
            case .notDetermined:
                VStack(alignment: .leading, spacing: 14) {
                    Text("Sona a besoin d'accéder à ta bibliothèque Musique pour lire tes playlists en entier.")
                        .font(Typo.rowSubtitle)
                        .foregroundStyle(Tone.secondary)
                    PillButton(title: "Autoriser l'accès", systemImage: "music.note.house") {
                        Task { await requestAccess() }
                    }
                }
                .listRowBackground(Color.clear)
            default:
                Text("Accès à la bibliothèque Musique refusé. Autorise-le dans Réglages › Sona › Médias et Apple Music.")
                    .font(Typo.rowSubtitle)
                    .foregroundStyle(Tone.secondary)
                    .listRowBackground(Color.clear)
            }
            if let errorMessage {
                Text(errorMessage).font(Typo.rowSubtitle).foregroundStyle(Tone.danger).listRowBackground(Color.clear)
            }
        }
        .listStyle(.plain)
        .scrollContentBackground(.hidden)
        .background(Tone.background)
        .navigationTitle("Bibliothèque Musique")
        .navigationBarTitleDisplayMode(.inline)
        .task { if authorization == .authorized { loadPlaylists() } }
    }

    private func requestAccess() async {
        let status = await withCheckedContinuation { continuation in
            MPMediaLibrary.requestAuthorization { continuation.resume(returning: $0) }
        }
        authorization = status
        if status == .authorized { loadPlaylists() }
    }

    private func loadPlaylists() {
        isLoading = true
        defer { isLoading = false }
        let collections = (MPMediaQuery.playlists().collections as? [MPMediaPlaylist]) ?? []
        playlists = collections.compactMap { collection in
            let tracks = collection.items.compactMap { item -> DeviceTrack? in
                guard let title = item.title, !title.isEmpty, let artist = item.artist, !artist.isEmpty else { return nil }
                let storeId = item.playbackStoreID
                return DeviceTrack(
                    title: title, artist: artist, album: item.albumTitle,
                    durationSeconds: item.playbackDuration > 0 ? Int(item.playbackDuration) : nil,
                    appleId: storeId.isEmpty || storeId == "0" ? nil : storeId
                )
            }
            guard !tracks.isEmpty else { return nil }
            let name = collection.name ?? "Playlist"
            let artwork = collection.items.first?.artwork?.image(at: CGSize(width: 104, height: 104))
            return DevicePlaylist(id: collection.persistentID, name: name, count: tracks.count, artwork: artwork, tracks: tracks)
        }
    }

    private func send(_ playlist: DevicePlaylist) async {
        sendingId = playlist.id
        errorMessage = nil
        do {
            let started = try await APIClient.shared.importDevicePlaylist(name: playlist.name, tracks: playlist.tracks)
            onStarted(started)
        } catch {
            errorMessage = error.localizedDescription
        }
        sendingId = nil
    }
}
