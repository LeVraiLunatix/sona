import SwiftUI

struct ArtistDetailView: View {
    let source: String
    let id: String
    @Binding var path: NavigationPath

    @State private var artist: Artist?
    @State private var topTracks: [Track] = []
    @State private var exclusives: [Track] = []
    @State private var bio: ArtistBio?
    @State private var bioExpanded = false
    @State private var albums: [Album] = []
    @State private var singles: [Album] = []
    @State private var otherVersions: [Album] = []
    @State private var related: [Artist] = []
    @State private var errorMessage: String?
    @State private var showsAllTracks = false
    @State private var isStartingRadio = false
    @State private var radioError: String?
    @State private var inLibrary = false
    @State private var libraryBounce = 0
    /// Teinte tirée de la photo : le haut de la page y est plongé, comme la
    /// fiche artiste de Musique.
    @State private var tint: Color = .black
    @State private var scrollY: CGFloat = 0
    @State private var motion: MotionVideo?
    @EnvironmentObject private var player: PlayerManager

    private var motionURL: URL? { (motion?.square ?? motion?.wide).flatMap(URL.init(string:)) }
    private var logoURL: URL? { motion?.logo.flatMap(URL.init(string:)) }

    /// Couleur de marque de l'artiste (celle de son logo) : les gros boutons la
    /// prennent, comme sur Musique. Blanc tant qu'on ne la connaît pas.
    private var accent: (color: Color, isLight: Bool) {
        guard let hex = motion?.accent, hex.count == 6, let value = UInt32(hex, radix: 16) else { return (.white, true) }
        let red = Double((value >> 16) & 0xFF) / 255, green = Double((value >> 8) & 0xFF) / 255, blue = Double(value & 0xFF) / 255
        return (Color(hex: value), 0.2126 * red + 0.7152 * green + 0.0722 * blue > 0.6)
    }

    private let headerHeight: CGFloat = 500

    /// Le nom passe dans la barre de navigation quand il quitte la photo.
    private var titleOpacity: Double {
        min(1, max(0, Double((scrollY - (headerHeight - 150)) / 60)))
    }

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                if let artist {
                    VStack(alignment: .leading, spacing: 0) {
                        header(artist)
                        VStack(alignment: .leading, spacing: 34) {
                            actions(scrollToBio: { withAnimation(Motion.smooth) { proxy.scrollTo("bio", anchor: .top) } })
                                .reveal(0)
                            if let latest = latestRelease { latestCard(latest).reveal(1) }
                            if !exclusives.isEmpty { exclusivesSection.reveal(1) }
                            if !topTracks.isEmpty { popular.reveal(1) }
                            if !albums.isEmpty {
                                carousel("Albums", albums).reveal(2)
                            }
                            if !singles.isEmpty {
                                carousel("Singles et EP", singles).reveal(3)
                            }
                            if !otherVersions.isEmpty {
                                carousel("Autres versions", otherVersions).reveal(3)
                            }
                            if !related.isEmpty { relatedSection.reveal(4) }
                            if let bio { bioSection(bio).id("bio").reveal(4) }
                        }
                        .padding(.top, 20)
                    }
                    .background(alignment: .top) {
                        LinearGradient(colors: [tint, Tone.background], startPoint: .top, endPoint: .bottom)
                            .frame(height: 1100)
                    }
                    .padding(.bottom, 24)
                } else if let errorMessage {
                    EmptyState(systemImage: "exclamationmark.triangle", title: "Artiste indisponible", message: errorMessage)
                        .padding(.top, 140)
                } else {
                    ProgressView().tint(.white).frame(maxWidth: .infinity).padding(.top, 200)
                }
            }
            .scrollIndicators(.hidden)
            // Pas de flou iOS 26 en haut : il masquait le haut de la photo.
            .scrollEdgeEffectHidden(true, for: .top)
            .onScrollGeometryChange(for: CGFloat.self) { $0.contentOffset.y + $0.contentInsets.top } action: { _, new in
                scrollY = new
            }
        }
        .ignoresSafeArea(edges: .top)
        .background(Tone.background)
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(.hidden, for: .navigationBar)
        .toolbar {
            ToolbarItem(placement: .principal) {
                Text(artist?.name ?? "")
                    .font(Typo.headline)
                    .foregroundStyle(Tone.primary)
                    .opacity(titleOpacity)
            }
            ToolbarItem(placement: .topBarTrailing) {
                if artist != nil {
                    Menu {
                        Button { startRadio() } label: {
                            Label("Radio de l'artiste", systemImage: "dot.radiowaves.left.and.right")
                        }
                        Button { shuffleTopTracks() } label: {
                            Label("Lecture aléatoire", systemImage: "shuffle")
                        }
                        .disabled(topTracks.isEmpty)
                    } label: {
                        Image(systemName: "ellipsis")
                    }
                }
            }
        }
        .task { await load() }
    }

    // MARK: - En-tête

    /// Photo plein cadre sous la barre d'état : elle se fond dans la teinte de
    /// la page (masque, pas de voile noir), s'étire quand on tire vers le bas
    /// et défile plus lentement que le contenu (parallaxe). Nom centré.
    private func header(_ artist: Artist) -> some View {
        GeometryReader { proxy in
            let minY = proxy.frame(in: .scrollView).minY
            let stretch = max(0, minY)
            // La parallaxe décale l'image vers le bas : le fondu doit finir sur
            // le bord bas du cadre (sinon la photo est coupée net) et non sur
            // celui de l'image.
            let shift = minY > 0 ? 0 : -minY * 0.4
            let mediaHeight = headerHeight + stretch
            let fadeEnd = max(0.2, (mediaHeight - shift) / mediaHeight)
            ZStack(alignment: .bottom) {
                ZStack {
                    Artwork(url: artist.pictureURL, cornerRadius: 0, symbol: "person.fill")
                        .frame(width: proxy.size.width, height: headerHeight + stretch)
                        .livingImage()
                    // Portrait animé d'Apple Music, par-dessus la photo fixe.
                    if let motionURL {
                        MotionOverlay(url: motionURL)
                            .frame(width: proxy.size.width, height: headerHeight + stretch)
                    }
                }
                    .frame(width: proxy.size.width, height: headerHeight + stretch)
                    .clipped()
                    // Photo fixe et vidéo ne forment qu'une image : sans ça, le fondu au
                    // défilement les estompe chacune, et la photo transparaît sous la vidéo.
                    .compositingGroup()
                    .mask {
                        LinearGradient(
                            stops: [
                                .init(color: .black, location: 0),
                                .init(color: .black, location: 0.55 * fadeEnd),
                                .init(color: .clear, location: fadeEnd),
                            ],
                            startPoint: .top, endPoint: .bottom
                        )
                    }
                    // La photo s'éteint doucement en remontant (immersif, sans bord).
                    .opacity(max(0.3, 1 - Double(-minY / (headerHeight * 0.9))))
                    .offset(y: minY > 0 ? -minY : shift)
                VStack(spacing: 4) {
                    nameView(artist)
                    if let fans = artist.fans, fans > 0 {
                        Text("\(fans.formatted(.number.notation(.compactName))) fans")
                            .font(Typo.rowSubtitle)
                            .foregroundStyle(Tone.secondary)
                    }
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 12)
                .reveal(0)
            }
            .clipped()
        }
        .frame(height: headerHeight)
    }

    /// Le nom en gros, ou le logo de l'artiste quand Apple Music en a un (le
    /// nom reste affiché le temps qu'il se charge).
    @ViewBuilder
    private func nameView(_ artist: Artist) -> some View {
        let name = Text(artist.name)
            .font(.system(size: 44, weight: .heavy))
            .foregroundStyle(Tone.primary)
            .multilineTextAlignment(.center)
            .lineLimit(2)
            .minimumScaleFactor(0.6)
            .shadow(color: .black.opacity(0.35), radius: 14)
        if let logoURL {
            AsyncImage(url: logoURL, transaction: Transaction(animation: .easeOut(duration: 0.4))) { phase in
                if case .success(let image) = phase {
                    // Logo sombre (Favé…) : sa forme en blanc, sinon il se perd sur le fond noir.
                    image.renderingMode(motion?.darkLogo == true ? .template : .original)
                        .resizable().scaledToFit()
                        .foregroundStyle(Color.white)
                        .frame(maxWidth: 300, maxHeight: 110)
                        .shadow(color: .black.opacity(0.35), radius: 14)
                        .accessibilityLabel(artist.name)
                        .transition(.opacity)
                } else {
                    name
                }
            }
        } else {
            name
        }
    }

    /// i (à propos) · lecture · étoile (bibliothèque), centrés sous le nom.
    private func actions(scrollToBio: @escaping () -> Void) -> some View {
        VStack(spacing: 10) {
            HStack(spacing: 18) {
                roundButton("info", size: 52, label: "À propos", action: scrollToBio)
                    .disabled(bio == nil)
                roundButton("play.fill", size: 76, filled: true, label: "Lecture") {
                    if let first = topTracks.first { player.play(first, context: topTracks, name: artist?.name) }
                }
                .disabled(topTracks.isEmpty)
                roundButton(
                    inLibrary ? "star.fill" : "star", size: 52, bounce: libraryBounce,
                    label: inLibrary ? "Retirer de la bibliothèque" : "Ajouter à la bibliothèque"
                ) {
                    Task { await toggleLibrary() }
                }
                .sensoryFeedback(.success, trigger: libraryBounce)
            }
            if let radioError {
                Text(radioError).font(Typo.rowSubtitle).foregroundStyle(Tone.danger)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.horizontal, 20)
    }

    private func roundButton(
        _ symbol: String, size: CGFloat, filled: Bool = false, bounce: Int = 0, label: String,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            Image(systemName: symbol)
                .font(.system(size: size * 0.38, weight: .semibold))
                .foregroundStyle(filled ? (accent.isLight ? Color.black : Color.white) : Tone.primary)
                .contentTransition(.symbolEffect(.replace))
                .symbolEffect(.bounce, value: bounce)
                .frame(width: size, height: size)
                .background(Circle().fill(filled ? accent.color : accent.color.opacity(0.22)))
                .animation(.easeInOut(duration: 0.6), value: motion?.accent)
        }
        .buttonStyle(.pressable(scale: 0.88))
        .accessibilityLabel(label)
    }

    /// La sortie la plus récente (l'API ne donne que l'année).
    private var latestRelease: Album? {
        (albums + singles).filter { $0.year != nil }.max { ($0.year ?? "") < ($1.year ?? "") }
    }

    private func latestCard(_ album: Album) -> some View {
        Button { path.append(Route.album(source: album.source, id: album.sourceId)) } label: {
            HStack(spacing: 14) {
                Artwork(url: album.coverURL, cornerRadius: 10, symbol: "square.stack")
                    .frame(width: 76, height: 76)
                VStack(alignment: .leading, spacing: 3) {
                    Text(["Dernière sortie", album.year].compactMap { $0 }.joined(separator: " · "))
                        .font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
                    Text(album.title).font(Typo.headline).foregroundStyle(Tone.primary).lineLimit(2)
                    if let count = album.trackCount {
                        Text(count == 1 ? "1 morceau" : "\(count) morceaux")
                            .font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
                    }
                }
                Spacer(minLength: 0)
                Image(systemName: "chevron.right")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(Tone.tertiary)
            }
            .padding(12)
            .glassRounded(24)
        }
        .buttonStyle(.pressable)
        .padding(.horizontal, 20)
    }

    private var popular: some View {
        let visible = showsAllTracks ? topTracks : Array(topTracks.prefix(5))
        return VStack(alignment: .leading, spacing: 10) {
            SectionHeader(
                title: "Populaires",
                actionLabel: topTracks.count > 5 ? (showsAllTracks ? "Moins" : "Tout voir") : nil,
                action: { withAnimation(Motion.smooth) { showsAllTracks.toggle() } }
            )
            LazyVStack(spacing: 2) {
                ForEach(visible) { track in
                    TrackRow(
                        track: track,
                        isCurrent: player.current?.id == track.id,
                        isPlaying: player.isPlaying,
                        onOpenAlbum: track.albumSourceId.map { id in { path.append(Route.album(source: track.source, id: id)) } }
                    ) {
                        player.play(track, context: topTracks, name: artist?.name)
                    }
                    .transition(.opacity.combined(with: .move(edge: .top)))
                }
            }
        }
        .padding(.horizontal, 20)
    }

    /// Les exclus de l'artiste (ajoutés à la main), avec l'année et la pastille Exclu / Inédit.
    private var exclusivesSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(title: "Exclus")
            LazyVStack(spacing: 2) {
                ForEach(exclusives) { track in
                    TrackRow(
                        track: track,
                        isCurrent: player.current?.id == track.id,
                        isPlaying: player.isPlaying
                    ) {
                        player.play(track, context: exclusives, name: "Exclus · \(artist?.name ?? "")")
                    }
                }
            }
        }
        .padding(.horizontal, 20)
    }

    /// « À propos » : biographie Wikipédia, repliée tant qu'on ne demande pas la suite.
    private func bioSection(_ bio: ArtistBio) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(title: "À propos")
            Text(bio.text)
                .font(Typo.body)
                .foregroundStyle(Tone.secondary)
                .lineLimit(bioExpanded ? nil : 5)
                .animation(Motion.smooth, value: bioExpanded)
            HStack {
                Button(bioExpanded ? "Réduire" : "Lire la suite") { bioExpanded.toggle() }
                    .font(Typo.rowSubtitle)
                    .foregroundStyle(Tone.primary)
                Spacer()
                if let link = bio.url, let url = URL(string: link) {
                    Link(bio.source ?? "Wikipédia", destination: url)
                        .font(Typo.rowSubtitle)
                        .foregroundStyle(Tone.tertiary)
                }
            }
        }
        .padding(.horizontal, 20)
    }

    private func carousel(_ title: String, _ list: [Album]) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionHeader(title: title).padding(.horizontal, 20)
            Carousel(items: list) { album in
                AlbumTile(album: album) { path.append(Route.album(source: album.source, id: album.sourceId)) }
            }
        }
    }

    private var relatedSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionHeader(title: "Artistes similaires").padding(.horizontal, 20)
            Carousel(items: related, spacing: 18) { other in
                let route = Route.artist(source: other.source, id: other.sourceId)
                ArtistBubble(name: other.name, pictureURL: other.pictureURL, route: route, size: 100) {
                    path.append(route)
                }
            }
        }
    }

    // MARK: - Données

    private func load() async {
        do {
            async let artistTask = APIClient.shared.artist(source: source, id: id)
            async let topTask = APIClient.shared.artistTopTracks(source: source, id: id)
            async let albumsTask = APIClient.shared.artistAlbums(source: source, id: id)
            let loaded = try await artistTask
            exclusives = (try? await APIClient.shared.artistExclusives(source: source, id: id, name: loaded.name)) ?? []
            // Titres et albums facultatifs : une fiche avec photo et nom vaut
            // mieux qu'un écran d'erreur si l'un des deux ne répond pas.
            let top = (try? await topTask) ?? []
            let albumSet = try? await albumsTask
            let colors = Look.tintEnabled ? await ArtworkPalette.colors(for: loaded.pictureURL) : []
            withAnimation(Motion.smooth) {
                // Coin bas-gauche de la photo : la couleur où le nom se pose.
                if colors.count > 2 { tint = colors[2] }
                artist = loaded
                topTracks = top
                albums = albumSet?.albums ?? []
                singles = albumSet?.singles ?? []
                otherVersions = albumSet?.otherVersions ?? []
            }
        } catch {
            errorMessage = error.localizedDescription
            return
        }
        Task { motion = await MotionStore.artist(source: source, id: id) }
        let similar = (try? await APIClient.shared.relatedArtists(source: source, id: id)) ?? []
        withAnimation(Motion.smooth) { related = similar }
        if let found = try? await APIClient.shared.artistBio(source: source, id: id) {
            withAnimation(Motion.smooth) { bio = found }
        }
        if let page = try? await APIClient.shared.library(kind: "artist", limit: 200) {
            inLibrary = page.items.contains { $0.source == source && $0.sourceId == id }
        }
    }

    private func shuffleTopTracks() {
        let shuffled = topTracks.shuffled()
        if let first = shuffled.first { player.play(first, context: shuffled, name: artist?.name) }
    }

    private func startRadio() {
        isStartingRadio = true
        radioError = nil
        let source = source, id = id
        Task {
            do {
                try await player.playStation(name: artist.map { "Radio \($0.name)" }) {
                    try await APIClient.shared.artistRadio(source: source, id: id)
                }
            } catch {
                radioError = error.localizedDescription
            }
            isStartingRadio = false
        }
    }

    private func toggleLibrary() async {
        do {
            if inLibrary {
                try await APIClient.shared.removeFromLibrary(kind: "artist", source: source, sourceId: id)
            } else {
                try await APIClient.shared.addToLibrary(kind: "artist", source: source, sourceId: id)
            }
            inLibrary.toggle()
            libraryBounce += 1
        } catch {
            radioError = error.localizedDescription
        }
    }
}
