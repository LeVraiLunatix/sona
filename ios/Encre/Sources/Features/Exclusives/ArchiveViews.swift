import SwiftUI

// Artistes « à identités » (ex. FEMTOGO / baby hayabusa / reggie petrucci) : une archive.
// Leur page n'est pas celle d'un service externe mais une discographie bâtie sur les fichiers
// ajoutés à la main — on choisit l'identité à écouter, puis ses albums, EP et singles.

/// Nom affiché pour l'artiste à identités (la page ne demande rien à Deezer).
let archiveArtistName = "FEMTO"

/// Sceau SPK des archives.
struct SPKSeal: View {
    /// `nil` : prend la place que le parent lui laisse.
    var size: CGFloat?

    var body: some View {
        Image("SPKSeal")
            .resizable()
            .scaledToFit()
            .frame(width: size, height: size)
            .clipShape(RoundedRectangle(cornerRadius: (size ?? 100) * 0.2, style: .continuous))
    }
}

// MARK: - Aiguillage de la page artiste

/// Choisit la page d'un artiste : la discographie d'archive s'il a des identités, sinon la fiche habituelle.
struct ArtistPage: View {
    let source: String
    let id: String
    @Binding var path: NavigationPath
    @State private var personas: [String]?

    var body: some View {
        Group {
            if let personas {
                if personas.isEmpty {
                    ArtistDetailView(source: source, id: id, path: $path)
                } else {
                    PersonaArtistView(source: source, id: id, personas: personas, path: $path)
                }
            } else {
                ProgressView().tint(.white)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(Tone.background)
            }
        }
        .task {
            guard personas == nil else { return }
            // Une erreur réseau retombe sur la fiche habituelle (qui affichera elle-même l'erreur).
            personas = (try? await APIClient.shared.artistPersonas(source: source, id: id)) ?? []
        }
    }
}

// MARK: - Page de l'artiste à identités

struct PersonaArtistView: View {
    let source: String
    let id: String
    let personas: [String]
    @Binding var path: NavigationPath

    @EnvironmentObject private var player: PlayerManager
    @State private var discography: ExclusiveDiscography?
    @State private var errorMessage: String?
    @State private var current = ""

    private var defaultsKey: String { "sona.persona.\(source):\(id)" }
    private var releases: [ExclusiveRelease] { (discography?.releases ?? []).filter { $0.persona == current } }
    private var tracks: [Track] { releases.flatMap(\.tracks) }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 26) {
                header.reveal(0)
                tabs.reveal(1)
                if let discography {
                    if releases.isEmpty {
                        Text("Aucune sortie de \(current) pour l'instant.")
                            .font(Typo.rowSubtitle).foregroundStyle(Tone.secondary).padding(.horizontal, 20)
                    } else {
                        section("Albums", releases.filter { $0.kind == "album" || !["ep", "single"].contains($0.kind) })
                        section("EP", releases.filter { $0.kind == "ep" })
                        section("Singles", releases.filter { $0.kind == "single" })
                    }
                    sharedSection(discography)
                } else if let errorMessage {
                    EmptyState(systemImage: "exclamationmark.triangle", title: "Discographie indisponible", message: errorMessage)
                } else {
                    ProgressView().tint(.white).frame(maxWidth: .infinity).padding(.top, 40)
                }
            }
            .padding(.bottom, 28)
        }
        .scrollIndicators(.hidden)
        .background(Tone.background)
        .navigationBarTitleDisplayMode(.inline)
        .task {
            let saved = UserDefaults.standard.string(forKey: defaultsKey)
            current = personas.contains(saved ?? "") ? (saved ?? "") : (personas.first ?? "")
            await load()
        }
    }

    private var header: some View {
        let count = discography?.releases.count ?? 0
        return VStack(alignment: .leading, spacing: 16) {
            HStack(alignment: .top, spacing: 16) {
                SPKSeal(size: 92)
                VStack(alignment: .leading, spacing: 4) {
                    Text("ARTISTE · \(personas.count) IDENTITÉ\(personas.count > 1 ? "S" : "") · \(count) SORTIE\(count > 1 ? "S" : "")")
                        .font(Typo.caption).tracking(0.6).foregroundStyle(Tone.tertiary)
                    Text(archiveArtistName).font(Typo.largeTitle).foregroundStyle(Tone.primary)
                    Text("(archives)").font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
                    Text("sous le nom de \(current) — \(subline)")
                        .font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
                        .padding(.top, 2)
                }
                Spacer(minLength: 0)
            }
            HStack(spacing: 12) {
                PillButton(title: "Lecture", systemImage: "play.fill") {
                    if let first = tracks.first { player.play(first, context: tracks, name: current) }
                }
                PillButton(title: "Aléatoire", systemImage: "shuffle", kind: .secondary) {
                    player.playShuffled(tracks, name: current)
                }
            }
            .disabled(tracks.isEmpty)
        }
        .padding(.horizontal, 20)
        .padding(.top, 8)
    }

    private var subline: String {
        let seconds = tracks.compactMap(\.durationSeconds).reduce(0, +)
        var parts = ["\(releases.count) sortie\(releases.count > 1 ? "s" : "")", "\(tracks.count) titre\(tracks.count > 1 ? "s" : "")"]
        if seconds > 0 { parts.append("\(max(1, seconds / 60)) min") }
        return parts.joined(separator: " · ")
    }

    /// Une pastille par identité : on touche pour changer de page.
    private var tabs: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 10) {
                ForEach(personas, id: \.self) { name in
                    let mine = (discography?.releases ?? []).filter { $0.persona == name }
                    Button {
                        withAnimation(Motion.smooth) { current = name }
                        UserDefaults.standard.set(name, forKey: defaultsKey)
                    } label: {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(name).font(Typo.rowTitle)
                            Text("\(mine.count) · \(mine.reduce(0) { $0 + $1.tracks.count })")
                                .font(Typo.caption).opacity(0.6)
                        }
                        .foregroundStyle(name == current ? Color.black : Tone.primary)
                        .padding(.horizontal, 16).padding(.vertical, 10)
                        .background(Capsule().fill(name == current ? Color.white : Tone.surfaceStrong))
                    }
                    .buttonStyle(.pressable)
                }
            }
            .padding(.horizontal, 20)
        }
    }

    @ViewBuilder
    private func section(_ title: String, _ list: [ExclusiveRelease]) -> some View {
        if !list.isEmpty {
            VStack(alignment: .leading, spacing: 10) {
                HStack(alignment: .firstTextBaseline) {
                    Text(title).font(Typo.title).foregroundStyle(Tone.primary)
                    Spacer()
                    Text("\(list.count) sortie\(list.count > 1 ? "s" : "")").font(Typo.rowSubtitle).foregroundStyle(Tone.tertiary)
                }
                .padding(.horizontal, 20)
                LazyVStack(spacing: 2) {
                    ForEach(Array(list.enumerated()), id: \.element.id) { index, release in
                        releaseRow(release, number: index + 1)
                    }
                }
                .padding(.horizontal, 20)
            }
            .reveal(2)
        }
    }

    private func releaseRow(_ release: ExclusiveRelease, number: Int) -> some View {
        Button {
            path.append(Route.release(source: source, id: id, persona: release.persona, album: release.album))
        } label: {
            HStack(spacing: 12) {
                Text(String(format: "%02d", number)).font(Typo.mono).foregroundStyle(Tone.tertiary).frame(width: 24)
                Artwork(url: release.coverURL, cornerRadius: 6, symbol: "square.stack")
                    .frame(width: 54, height: 54)
                    .zoomSource(Route.release(source: source, id: id, persona: release.persona, album: release.album))
                VStack(alignment: .leading, spacing: 2) {
                    Text(release.title).font(Typo.rowTitle).foregroundStyle(Tone.primary).lineLimit(1)
                    Text(releaseSubtitle(release)).font(Typo.rowSubtitle).foregroundStyle(Tone.secondary).lineLimit(1)
                }
                Spacer(minLength: 0)
                Image(systemName: "chevron.right").font(.system(size: 13, weight: .semibold)).foregroundStyle(Tone.tertiary)
            }
            .padding(.vertical, 6)
        }
        .buttonStyle(.pressable)
        .contextMenu {
            Button { player.play(release.tracks[0], context: release.tracks, name: release.album) } label: {
                Label("Lecture", systemImage: "play.fill")
            }
            .disabled(release.tracks.isEmpty)
        }
    }

    private func releaseSubtitle(_ release: ExclusiveRelease) -> String {
        var parts = [release.kindLabel]
        if let feat = release.feat { parts.append("feat. \(feat)") }
        parts.append("\(release.trackCount) titre\(release.trackCount > 1 ? "s" : "")")
        return parts.joined(separator: " · ")
    }

    /// « Aussi chez les autres identités » : le même morceau, sous un autre nom.
    @ViewBuilder
    private func sharedSection(_ discography: ExclusiveDiscography) -> some View {
        let rows = ArchiveShared.rows(for: tracks, in: discography, persona: current)
        if !rows.isEmpty {
            VStack(alignment: .leading, spacing: 10) {
                SectionHeader(title: "Aussi chez les autres identités").padding(.horizontal, 20)
                ForEach(rows) { row in
                    VStack(alignment: .leading, spacing: 6) {
                        Text(FeatSplit.split(row.track.title).title).font(Typo.rowTitle).foregroundStyle(Tone.primary)
                        ScrollView(.horizontal, showsIndicators: false) {
                            HStack(spacing: 8) {
                                ForEach(row.others) { other in
                                    Button {
                                        withAnimation(Motion.smooth) { current = other.persona }
                                        UserDefaults.standard.set(other.persona, forKey: defaultsKey)
                                    } label: {
                                        Text("\(other.persona) · \(other.title)")
                                            .font(Typo.rowSubtitle).foregroundStyle(Tone.primary)
                                            .padding(.horizontal, 12).padding(.vertical, 6)
                                            .background(Capsule().fill(Tone.surface))
                                    }
                                    .buttonStyle(.pressable)
                                }
                            }
                        }
                    }
                    .padding(.horizontal, 20)
                }
            }
            .reveal(3)
        }
    }

    private func load() async {
        do {
            let loaded = try await APIClient.shared.artistDiscography(source: source, id: id)
            withAnimation(Motion.smooth) { discography = loaded }
            if !loaded.personas.isEmpty, !loaded.personas.contains(current) { current = loaded.personas[0] }
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

/// Les titres qui existent chez plusieurs identités (par nom, sans le feat).
enum ArchiveShared {
    static func index(_ discography: ExclusiveDiscography) -> [String: [ExclusiveRelease]] {
        var map: [String: [ExclusiveRelease]] = [:]
        for release in discography.releases {
            for track in release.tracks { map[FeatSplit.key(track.title), default: []].append(release) }
        }
        return map
    }

    struct Row: Identifiable {
        let track: Track
        let others: [ExclusiveRelease]
        var id: String { track.id }
    }

    /// Les titres de `tracks` qui existent aussi chez une autre identité.
    static func rows(for tracks: [Track], in discography: ExclusiveDiscography, persona: String) -> [Row] {
        let map = index(discography)
        return tracks.compactMap { track in
            let others = elsewhere(map, track: track, persona: persona)
            return others.isEmpty ? nil : Row(track: track, others: others)
        }
    }

    /// Les sorties d'une autre identité qui contiennent le même morceau.
    static func elsewhere(_ index: [String: [ExclusiveRelease]], track: Track, persona: String) -> [ExclusiveRelease] {
        var seen = Set<String>()
        return (index[FeatSplit.key(track.title)] ?? []).filter { $0.persona != persona && seen.insert($0.id).inserted }
    }
}

// MARK: - Page d'une sortie

struct ExclusiveReleaseView: View {
    let source: String
    let id: String
    let persona: String
    let album: String
    @Binding var path: NavigationPath

    @EnvironmentObject private var player: PlayerManager
    @Environment(\.addToPlaylist) private var addToPlaylist
    @State private var discography: ExclusiveDiscography?
    @State private var errorMessage: String?

    private var release: ExclusiveRelease? {
        discography?.releases.first { $0.persona == persona && $0.album == album }
    }

    var body: some View {
        ScrollView {
            if let release {
                VStack(alignment: .leading, spacing: 22) {
                    header(release)
                    LazyVStack(spacing: 0) {
                        ForEach(Array(release.tracks.enumerated()), id: \.element.id) { index, track in
                            TrackRow(
                                track: track,
                                index: track.trackNumber ?? index + 1,
                                showsArtwork: false,
                                isCurrent: player.current?.id == track.id,
                                isPlaying: player.isPlaying
                            ) {
                                player.play(track, context: release.tracks, name: release.album)
                            }
                            .padding(.vertical, 4)
                            if index < release.tracks.count - 1 {
                                Divider().overlay(Tone.separator).padding(.leading, 40)
                            }
                        }
                    }
                    .padding(.horizontal, 20)
                    also(release)
                }
                .padding(.bottom, 28)
            } else if let errorMessage {
                EmptyState(systemImage: "exclamationmark.triangle", title: "Sortie indisponible", message: errorMessage)
                    .padding(.top, 80)
            } else {
                ProgressView().tint(.white).frame(maxWidth: .infinity).padding(.top, 120)
            }
        }
        .scrollIndicators(.hidden)
        .background(Tone.background)
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
    }

    private func header(_ release: ExclusiveRelease) -> some View {
        VStack(spacing: 16) {
            Artwork(url: release.coverURL, cornerRadius: 12, symbol: "square.stack")
                .frame(width: 240, height: 240)
                .shadow(color: .black.opacity(0.5), radius: 30, y: 16)
                .padding(.top, 12)
            VStack(spacing: 5) {
                Text("\(release.kindLabel.uppercased()) · \(release.persona.uppercased())")
                    .font(Typo.caption).tracking(0.6).foregroundStyle(Tone.tertiary)
                Text(release.title)
                    .font(.system(size: 24, weight: .bold)).foregroundStyle(Tone.primary)
                    .multilineTextAlignment(.center)
                Text(meta(release)).font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
            }
            .padding(.horizontal, 24)
            HStack(spacing: 12) {
                PillButton(title: "Lecture", systemImage: "play.fill") {
                    if let first = release.tracks.first { player.play(first, context: release.tracks, name: release.album) }
                }
                PillButton(title: "Aléatoire", systemImage: "shuffle", kind: .secondary) {
                    player.playShuffled(release.tracks, name: release.album)
                }
                if let addToPlaylist {
                    Button { addToPlaylist(release.tracks) } label: {
                        Image(systemName: "text.badge.plus")
                            .font(Typo.headline).foregroundStyle(Tone.primary)
                            .frame(width: 50, height: 50)
                            .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Tone.surfaceStrong))
                    }
                    .buttonStyle(.pressable)
                }
            }
            .padding(.horizontal, 20)
            .disabled(release.tracks.isEmpty)
        }
        .frame(maxWidth: .infinity)
    }

    private func meta(_ release: ExclusiveRelease) -> String {
        var parts: [String] = []
        if let feat = release.feat { parts.append("feat. \(feat)") }
        if let year = release.year { parts.append(year) }
        parts.append("\(release.trackCount) titre\(release.trackCount > 1 ? "s" : "")")
        if release.durationSeconds > 0 { parts.append("\(max(1, release.durationSeconds / 60)) min") }
        return parts.joined(separator: " · ")
    }

    /// « Ce morceau existe aussi » sous un autre nom : un saut vers l'autre sortie.
    @ViewBuilder
    private func also(_ release: ExclusiveRelease) -> some View {
        if let discography {
            let rows = ArchiveShared.rows(for: release.tracks, in: discography, persona: persona)
            if !rows.isEmpty {
                VStack(alignment: .leading, spacing: 10) {
                    SectionHeader(title: "Ce morceau existe aussi").padding(.horizontal, 20)
                    ForEach(rows) { row in
                        VStack(alignment: .leading, spacing: 6) {
                            Text(FeatSplit.split(row.track.title).title).font(Typo.rowTitle).foregroundStyle(Tone.primary)
                            ScrollView(.horizontal, showsIndicators: false) {
                                HStack(spacing: 8) {
                                    ForEach(row.others) { other in
                                        Button {
                                            path.append(Route.release(source: source, id: id, persona: other.persona, album: other.album))
                                        } label: {
                                            Text("\(other.persona) · \(other.title)")
                                                .font(Typo.rowSubtitle).foregroundStyle(Tone.primary)
                                                .padding(.horizontal, 12).padding(.vertical, 6)
                                                .background(Capsule().fill(Tone.surface))
                                        }
                                        .buttonStyle(.pressable)
                                    }
                                }
                            }
                        }
                        .padding(.horizontal, 20)
                    }
                }
            }
        }
    }

    private func load() async {
        do {
            let loaded = try await APIClient.shared.artistDiscography(source: source, id: id)
            withAnimation(Motion.smooth) { discography = loaded }
            if release == nil { errorMessage = "Cette sortie n'existe pas (ou plus)." }
            // La page de l'artiste s'ouvrira sur cette identité.
            UserDefaults.standard.set(persona, forKey: "sona.persona.\(source):\(id)")
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
