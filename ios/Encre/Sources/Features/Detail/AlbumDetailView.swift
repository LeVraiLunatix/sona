import SwiftUI

struct AlbumDetailView: View {
    let source: String
    let id: String
    var isPlaylist = false
    @Binding var path: NavigationPath

    @State private var album: Album?
    @State private var errorMessage: String?
    @State private var palette: [Color] = ArtworkPalette.fallback
    @AppStorage(Look.tintKey) private var tintOn = true
    @State private var inLibrary = false
    @State private var libraryBounce = 0
    @State private var shareTarget: ShareTarget?
    @State private var versions: [Album] = []
    @State private var find = ""
    @State private var motionURL: URL?
    @State private var reminded = false
    @State private var remindDenied = false
    @State private var showsLock = false
    @State private var lockDenied = false
    @State private var scrollY: CGFloat = 0
    @State private var coverHeight: CGFloat = 420
    @EnvironmentObject private var player: PlayerManager
    @Environment(\.addToPlaylist) private var addToPlaylist
    @ObservedObject private var gta = GtaTheme.shared

    /// Le titre passe dans la barre de navigation quand il quitte la pochette.
    private var titleOpacity: Double {
        min(1, max(0, Double((scrollY - (coverHeight - 150)) / 60)))
    }

    var body: some View {
        ScrollView {
            if let album {
                VStack(spacing: 0) {
                    header(album)
                    tracks(album).reveal(2)
                    footer(album).reveal(3)
                    if !versions.isEmpty { versionsSection.reveal(4) }
                }
                .padding(.bottom, 24)
            } else if let errorMessage {
                EmptyState(systemImage: "exclamationmark.triangle", title: "Album indisponible", message: errorMessage)
                    .padding(.top, 80)
            } else {
                ProgressView().tint(.white).frame(maxWidth: .infinity).padding(.top, 120)
            }
        }
        .scrollIndicators(.hidden)
        // Pas de flou iOS 26 en haut : il masquait le haut de la pochette.
        .scrollEdgeEffectHidden(true, for: .top)
        .onScrollGeometryChange(for: CGFloat.self) { $0.contentOffset.y + $0.contentInsets.top } action: { _, new in
            scrollY = new
        }
        .ignoresSafeArea(edges: .top)
        .background(alignment: .top) { glow }
        .pageBackground()
        // Album ou single de Grand Theft Auto VI : reconnu une fois chargé.
        .gtaPage("album:\(source):\(id)", active: !isPlaylist && album.map(GtaVI.isAlbum) == true)
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(.hidden, for: .navigationBar)
        .toolbar {
            ToolbarItem(placement: .principal) {
                Text(album?.title ?? "")
                    .font(Typo.headline)
                    .foregroundStyle(Tone.primary)
                    .lineLimit(1)
                    .opacity(titleOpacity)
            }
            ToolbarItem(placement: .topBarTrailing) {
                if let album, !album.tracks.isEmpty {
                    // Les titres pas encore sortis ne se lisent ni ne se téléchargent.
                    let ready = album.tracks.filter(\.isReleased)
                    Menu {
                        if album.releaseMoment != nil {
                            Button { Task { await toggleReminder(album) } } label: {
                                Label(reminded ? "Annuler le rappel" : "Me rappeler la sortie",
                                      systemImage: reminded ? "bell.slash" : "bell")
                            }
                        }
                        if !ready.isEmpty {
                            DownloadMenuItems(tracks: ready)
                            Button { player.playNext(ready) } label: {
                                Label("Lire ensuite", systemImage: "text.line.first.and.arrowtriangle.forward")
                            }
                            Button { player.playLater(ready) } label: {
                                Label("Lire après", systemImage: "text.line.last.and.arrowtriangle.forward")
                            }
                            if let addToPlaylist {
                                Button { addToPlaylist(ready) } label: {
                                    Label("Ajouter à une playlist…", systemImage: "text.badge.plus")
                                }
                            }
                        }
                        if !isPlaylist {
                            Button { shareTarget = .album(album) } label: {
                                Label("Partager…", systemImage: "link")
                            }
                        }
                    } label: {
                        Image(systemName: "ellipsis")
                    }
                }
            }
            ToolbarItem(placement: .topBarTrailing) {
                if album != nil && !isPlaylist {
                    Button { Task { await toggleLibrary() } } label: {
                        Image(systemName: inLibrary ? "checkmark" : "plus")
                            .contentTransition(.symbolEffect(.replace))
                            .symbolEffect(.bounce, value: libraryBounce)
                    }
                    .sensoryFeedback(.success, trigger: libraryBounce)
                }
            }
        }
        .sheet(item: $shareTarget) { target in SonaShareSheet(target: target) }
        .alert("Notifications désactivées", isPresented: $remindDenied) {
            Button("OK", role: .cancel) {}
        } message: {
            Text("Autorise les notifications de Sona dans Réglages pour être prévenu à la sortie de l'album.")
        }
        .alert("Activités en direct désactivées", isPresented: $lockDenied) {
            Button("OK", role: .cancel) {}
        } message: {
            Text("Autorise les activités en direct de Sona dans Réglages pour voir le compte à rebours sur l'écran verrouillé.")
        }
        .searchable(text: $find, prompt: isPlaylist ? "Rechercher dans cette playlist" : "Rechercher dans cet album")
        // Un bouton dans la barre plutôt qu'un champ au-dessus de la pochette.
        .searchToolbarBehavior(.minimize)
        .task { await load() }
    }

    /// Les titres qui correspondent à la recherche dans la page (tous quand le champ est vide).
    private func visibleTracks(_ album: Album) -> [Track] {
        let needle = find.trimmingCharacters(in: .whitespaces).folded
        guard !needle.isEmpty else { return album.tracks }
        return album.tracks.filter { "\($0.title) \($0.artist) \($0.album ?? "")".folded.contains(needle) }
    }

    /// Halo diffus aux couleurs de la pochette, fondu dans le noir.
    private var glow: some View {
        LinearGradient(colors: [palette[0].opacity(0.9), palette[3].opacity(0.4), .clear], startPoint: .top, endPoint: .bottom)
            .frame(height: 520)
            .blur(radius: 40)
            .ignoresSafeArea()
            .opacity(tintOn && !gta.on ? 1 : 0)
            .animation(.easeInOut(duration: 0.8), value: palette)
    }

    /// Pochette plein cadre sous la barre d'état, comme le lecteur et la fiche
    /// artiste : elle s'étire quand on tire vers le bas, défile plus lentement
    /// que le contenu (parallaxe), se fond dans la teinte de l'album, respire
    /// (`livingImage`) et laisse place à la boucle Apple Music quand il y en a
    /// une. Le titre est posé en bas, sur le fondu.
    private func header(_ album: Album) -> some View {
        VStack(spacing: 18) {
            Color.clear
                .aspectRatio(1 / 1.12, contentMode: .fit)
                .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { coverHeight = $0 }
                .overlay { immersiveCover(album) }
            if let moment = album.releaseMoment { upcomingBlock(album, moment) }
            actionRow(album)
        }
        .padding(.bottom, 20)
    }

    private func immersiveCover(_ album: Album) -> some View {
        GeometryReader { proxy in
            let minY = proxy.frame(in: .scrollView).minY
            let stretch = max(0, minY)
            let shift = minY > 0 ? 0 : -minY * 0.4
            let mediaHeight = proxy.size.height + stretch
            // Le fondu doit finir sur le bord bas du cadre malgré la parallaxe.
            let fadeEnd = max(0.2, (mediaHeight - shift) / mediaHeight)
            ZStack(alignment: .bottom) {
                ZStack {
                    Artwork(url: album.coverURL, cornerRadius: 0, symbol: "square.stack")
                        .frame(width: proxy.size.width, height: mediaHeight)
                        .livingImage()
                    // Pochette animée d'Apple Music, par-dessus la fixe, quand l'album en a une.
                    if let motionURL {
                        MotionOverlay(url: motionURL)
                            .frame(width: proxy.size.width, height: mediaHeight)
                    }
                }
                .frame(width: proxy.size.width, height: mediaHeight)
                .clipped()
                // Pochette fixe et vidéo ne forment qu'une image : sans ça, le fondu au
                // défilement les estompe chacune, et la pochette transparaît sous la vidéo.
                .compositingGroup()
                .mask {
                    LinearGradient(
                        stops: [
                            .init(color: .black, location: 0),
                            .init(color: .black, location: 0.6 * fadeEnd),
                            .init(color: .clear, location: fadeEnd),
                        ],
                        startPoint: .top, endPoint: .bottom
                    )
                }
                .overlay(alignment: .top) {
                    // Les boutons du haut restent lisibles sur une pochette claire.
                    LinearGradient(colors: [.black.opacity(0.45), .clear], startPoint: .top, endPoint: .bottom)
                        .frame(height: 150)
                }
                // La pochette s'éteint doucement en remontant.
                .opacity(max(0.3, 1 - Double(-minY / (proxy.size.height * 0.9))))
                .offset(y: minY > 0 ? -minY : shift)

                titleBlock(album)
                    .padding(.horizontal, 24)
                    .padding(.bottom, 8)
                    .reveal(0)
            }
            .clipped()
        }
    }

    private func titleBlock(_ album: Album) -> some View {
        VStack(spacing: 6) {
            Text(album.title)
                .font(.system(size: 28, weight: .heavy))
                .foregroundStyle(Tone.primary)
                .themeTitle(size: 30)
                .multilineTextAlignment(.center)
                .lineLimit(3)
                .minimumScaleFactor(0.7)
                .shadow(color: .black.opacity(0.35), radius: 14)
            Button {
                if let artistId = album.artistSourceId {
                    path.append(Route.artist(source: album.source, id: artistId))
                }
            } label: {
                Text(album.artist)
                    .font(.system(size: 19, weight: .medium))
                    .foregroundStyle(Tone.primary.opacity(0.85))
                    .shadow(color: .black.opacity(0.35), radius: 10)
            }
            .buttonStyle(.pressable)
            .disabled(album.artistSourceId == nil)
            if let meta = metaLine(album) {
                Text(meta).font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
            }
            DownloadStatusLine(tracks: album.tracks.filter(\.isReleased))
        }
    }

    /// Album annoncé : le jour de sortie et le compte à rebours. À zéro, la page
    /// se recharge (les titres se dégrisent).
    private func upcomingBlock(_ album: Album, _ moment: Date) -> some View {
        VStack(spacing: 14) {
            Label("Sortie le \(ReleaseClock.dayLabel(moment).lowercased())", systemImage: "calendar")
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(Tone.primary)
            CountdownTiles(target: moment) {
                Task {
                    try? await Task.sleep(for: .seconds(2))
                    await load()
                }
            }
            lockScreenRow(album, moment)
        }
        .padding(.horizontal, 20)
        .reveal(1)
    }

    /// Compte à rebours sur l'écran verrouillé et la Dynamic Island. iOS limite ces
    /// activités à 8 h : le bouton apparaît dans les 7 h 30 avant la sortie ; avant,
    /// un rappel programmé le lance tout seul à l'ouverture de l'app.
    @ViewBuilder
    private func lockScreenRow(_ album: Album, _ moment: Date) -> some View {
        if ReleaseActivity.canShow(moment) {
            Button { toggleLockScreen(album) } label: {
                Label(
                    showsLock ? "Retirer de l'écran verrouillé" : "Afficher sur l'écran verrouillé",
                    systemImage: showsLock ? "lock.slash" : "lock.iphone"
                )
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(Tone.primary)
                .padding(.horizontal, 14)
                .padding(.vertical, 9)
                .background(Capsule(style: .continuous).fill(Color.white.opacity(0.14)))
            }
            .buttonStyle(.pressable)
        } else if reminded {
            Text("Le compteur s'affichera sur l'écran verrouillé 7 h 30 avant la sortie.")
                .font(Typo.rowSubtitle)
                .foregroundStyle(Tone.tertiary)
                .multilineTextAlignment(.center)
        }
    }

    private func toggleLockScreen(_ album: Album) {
        if showsLock {
            ReleaseActivity.stop(album)
            showsLock = false
        } else {
            showsLock = ReleaseActivity.start(album)
            lockDenied = !showsLock
        }
    }

    private func actionRow(_ album: Album) -> some View {
        let playable = album.tracks.filter(\.isReleased)
        let waiting = album.releaseMoment != nil
        return HStack(spacing: 12) {
            if playable.isEmpty && waiting {
                // Rien n'est encore sorti : « Lecture » n'aurait rien à lire.
                PillButton(
                    title: reminded ? "Rappel activé" : "Me rappeler la sortie",
                    systemImage: reminded ? "bell.fill" : "bell"
                ) {
                    Task { await toggleReminder(album) }
                }
            } else {
                PillButton(title: "Lecture", systemImage: "play.fill") {
                    if let first = playable.first { player.play(first, context: playable, name: album.title) }
                }
                PillButton(title: "Aléatoire", systemImage: "shuffle", kind: .secondary) {
                    player.playShuffled(playable, name: album.title)
                }
            }
        }
        .padding(.horizontal, 20)
        .disabled(playable.isEmpty && !waiting)
        .reveal(1)
    }

    private func toggleReminder(_ album: Album) async {
        if reminded {
            NotificationManager.shared.cancelReminder(for: album)
            reminded = false
            showsLock = false
        } else {
            reminded = await NotificationManager.shared.remindRelease(of: album)
            remindDenied = !reminded
            showsLock = ReleaseActivity.isShowing(album)
        }
    }

    /// Album en plusieurs disques : « Disque 1 », « Disque 2 »…
    private func discCount(_ album: Album) -> Int {
        isPlaylist ? 1 : Set(album.tracks.compactMap(\.discNumber)).count
    }

    private func tracks(_ album: Album) -> some View {
        let showsDiscs = discCount(album) > 1 && find.isEmpty
        let list = visibleTracks(album)
        return LazyVStack(spacing: 0) {
            if list.isEmpty && !find.isEmpty {
                EmptyState(systemImage: "magnifyingglass", title: "Aucun titre", message: "Rien ici pour « \(find) ».")
            }
            ForEach(Array(list.enumerated()), id: \.offset) { index, track in
                if showsDiscs && (index == 0 || list[index - 1].discNumber != track.discNumber) {
                    HStack(spacing: 8) {
                        Image(systemName: "opticaldisc")
                        Text("Disque \(track.discNumber ?? 1)")
                    }
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(Tone.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.top, index == 0 ? 4 : 22)
                    .padding(.bottom, 6)
                }
                TrackRow(
                    track: track,
                    index: showsDiscs ? (track.trackNumber ?? index + 1) : index + 1,
                    showsArtwork: false,
                    isCurrent: player.current?.id == track.id,
                    isPlaying: player.isPlaying,
                    onOpenArtist: track.artistSourceId.map { id in { path.append(Route.artist(source: track.artistRouteSource, id: id)) } }
                ) {
                    player.play(track, context: list.filter(\.isReleased), name: album.title)
                }
                .padding(.vertical, 4)
                if index < list.count - 1 {
                    Divider().overlay(Tone.separator).padding(.leading, 40)
                }
            }
        }
        .padding(.horizontal, 20)
    }

    private func footer(_ album: Album) -> some View {
        Text(footerLine(album))
            .font(Typo.rowSubtitle)
            .foregroundStyle(Tone.tertiary)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 20)
            .padding(.top, 18)
    }

    /// « Autres versions » (deluxe, remasterisé…), comme sur Apple Music.
    private var versionsSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionHeader(title: "Autres versions").padding(.horizontal, 20)
            Carousel(items: versions) { other in
                AlbumTile(album: other) { path.append(Route.album(source: other.source, id: other.sourceId)) }
            }
        }
        .padding(.top, 30)
    }

    private func metaLine(_ album: Album) -> String? {
        let isAlbum = album.tracks.count > 1 || (album.trackCount ?? 0) > 1
        let kind = isPlaylist ? "Playlist" : (isAlbum ? "Album" : "Single")
        let parts = [kind, album.year, album.releaseMoment == nil ? nil : "À venir"].compactMap { $0 }
        return parts.joined(separator: " · ")
    }

    private func footerLine(_ album: Album) -> String {
        let count = album.trackCount ?? album.tracks.count
        let seconds = album.durationSeconds ?? album.tracks.compactMap(\.durationSeconds).reduce(0, +)
        var parts = ["\(count) titre\(count > 1 ? "s" : "")"]
        if discCount(album) > 1 { parts.append("\(discCount(album)) disques") }
        if seconds > 0 { parts.append("\(max(1, seconds / 60)) min") }
        return parts.joined(separator: ", ")
    }

    private func load() async {
        do {
            let loaded: Album
            if isPlaylist {
                loaded = try await APIClient.shared.playlist(source: source, id: id)
            } else {
                loaded = try await APIClient.shared.album(source: source, id: id)
            }
            withAnimation(Motion.smooth) { album = loaded }
            if loaded.releaseMoment != nil {
                reminded = await NotificationManager.shared.hasReminder(for: loaded)
                showsLock = ReleaseActivity.isShowing(loaded)
            }
            palette = await ArtworkPalette.colors(for: loaded.coverURL)
            if !isPlaylist {
                Task { motionURL = await MotionStore.albumURL(source: source, id: id) }
                versions = (try? await APIClient.shared.albumVersions(source: source, id: id)) ?? []
            }
            if !isPlaylist, let page = try? await APIClient.shared.library(kind: "album", limit: 200) {
                inLibrary = page.items.contains { $0.source == source && $0.sourceId == id }
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func toggleLibrary() async {
        do {
            if inLibrary {
                try await APIClient.shared.removeFromLibrary(kind: "album", source: source, sourceId: id)
            } else {
                try await APIClient.shared.addToLibrary(kind: "album", source: source, sourceId: id)
            }
            inLibrary.toggle()
            libraryBounce += 1
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
