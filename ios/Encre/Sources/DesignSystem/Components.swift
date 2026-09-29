import SwiftUI

/// Ligne de morceau : pochette, titre, artiste (tapable vers sa fiche),
/// durée — et un égaliseur animé à la place du numéro/de la durée quand
/// c'est le morceau en cours.
struct TrackRow: View {
    let track: Track
    var index: Int?
    var showsArtwork = true
    var isCurrent = false
    var isPlaying = false
    /// Nom d'artiste tapable (vers sa fiche) et entrée « Voir l'album » du
    /// menu contextuel ; `nil` si l'écran ne peut pas naviguer ou si le
    /// serveur n'a pas l'identifiant. Déclarés avant `action` pour que la
    /// syntaxe `TrackRow(...) { lecture }` cible toujours `action`.
    var onOpenArtist: (() -> Void)? = nil
    var onOpenAlbum: (() -> Void)? = nil
    var onRemove: (() -> Void)? = nil
    var action: () -> Void
    @Environment(\.addToPlaylist) private var addToPlaylist
    @ObservedObject private var downloads = DownloadManager.shared

    var body: some View {
        Button(action: action) {
            HStack(spacing: 14) {
                if let index {
                    ZStack {
                        if isCurrent {
                            EqualizerBars(isAnimating: isPlaying).frame(width: 14, height: 14)
                        } else {
                            Text("\(index)").font(Typo.body).foregroundStyle(Tone.tertiary).monospacedDigit()
                        }
                    }
                    .frame(width: 26)
                }
                if showsArtwork {
                    ZStack {
                        Artwork(url: track.coverURL, cornerRadius: 6)
                        if isCurrent && index == nil {
                            Color.black.opacity(0.45)
                            EqualizerBars(isAnimating: isPlaying).frame(width: 16, height: 16)
                        }
                    }
                    .frame(width: 50, height: 50)
                }
                VStack(alignment: .leading, spacing: 3) {
                    Text(track.title)
                        .font(Typo.rowTitle)
                        .foregroundStyle(Tone.primary)
                        .lineLimit(1)
                    Text(track.artist)
                        .font(Typo.rowSubtitle)
                        .foregroundStyle(Tone.secondary)
                        .lineLimit(1)
                }
                Spacer(minLength: 8)
                downloadBadge
                Text(track.durationLabel)
                    .font(Typo.mono)
                    .foregroundStyle(Tone.tertiary)
            }
            .padding(.vertical, 6)
        }
        .buttonStyle(.pressable(scale: 0.98))
        .contextMenu {
            if PartyManager.shared.isGuest {
                Button { Task { await PartyManager.shared.propose(track) } } label: {
                    Label("Proposer à la session", systemImage: "person.2.wave.2")
                }
            }
            Button { PlayerManager.shared.playNext([track]) } label: {
                Label("Lire ensuite", systemImage: "text.line.first.and.arrowtriangle.forward")
            }
            Button { PlayerManager.shared.playLater([track]) } label: {
                Label("Lire après", systemImage: "text.line.last.and.arrowtriangle.forward")
            }
            if downloads.isDownloaded(track) {
                Button(role: .destructive) { downloads.remove(track) } label: {
                    Label("Supprimer le téléchargement", systemImage: "arrow.down.circle.dotted")
                }
            } else {
                Button { downloads.download([track]) } label: {
                    Label("Télécharger", systemImage: "arrow.down.circle")
                }
            }
            if let addToPlaylist {
                Button { addToPlaylist([track]) } label: {
                    Label("Ajouter à une playlist…", systemImage: "text.badge.plus")
                }
            }
            if let onOpenArtist {
                Button(action: onOpenArtist) { Label("Voir l'artiste", systemImage: "person.crop.circle") }
            }
            if let onOpenAlbum {
                Button(action: onOpenAlbum) { Label("Voir l'album", systemImage: "square.stack") }
            }
            if let onRemove {
                Button(role: .destructive, action: onRemove) { Label("Retirer de la bibliothèque", systemImage: "trash") }
            }
        }
    }
}

extension TrackRow {
    /// Pastille « téléchargé » (ou en cours) à côté de la durée.
    @ViewBuilder
    fileprivate var downloadBadge: some View {
        switch downloads.state(of: track) {
        case .done:
            Image(systemName: "arrow.down.circle.fill")
                .font(.system(size: 12))
                .foregroundStyle(Tone.tertiary)
        case .downloading:
            ProgressView().controlSize(.mini).tint(.white)
        case .queued:
            Image(systemName: "arrow.down.circle.dotted")
                .font(.system(size: 12))
                .foregroundStyle(Tone.tertiary)
        case .failed:
            Image(systemName: "exclamationmark.circle")
                .font(.system(size: 12))
                .foregroundStyle(Tone.danger)
        case .none:
            EmptyView()
        }
    }
}

/// Égaliseur trois barres du morceau en cours (figé en pause).
struct EqualizerBars: View {
    var isAnimating: Bool

    var body: some View {
        TimelineView(.animation(minimumInterval: 1 / 20, paused: !isAnimating)) { timeline in
            let t = timeline.date.timeIntervalSinceReferenceDate
            GeometryReader { proxy in
                HStack(alignment: .bottom, spacing: proxy.size.width * 0.18) {
                    ForEach(0..<3, id: \.self) { i in
                        let phase = t * (5.5 + Double(i) * 1.7) + Double(i) * 1.3
                        let level = isAnimating ? 0.3 + 0.7 * abs(sin(phase)) : 0.3
                        Capsule()
                            .fill(Tone.primary)
                            .frame(height: proxy.size.height * level)
                    }
                }
                .frame(maxHeight: .infinity, alignment: .bottom)
            }
        }
    }
}

/// Vignette carrée d'un morceau (accueil).
struct TrackTile: View {
    let track: Track
    var size: CGFloat = 150
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 8) {
                Artwork(url: track.coverURL, cornerRadius: 10)
                    .frame(width: size, height: size)
                VStack(alignment: .leading, spacing: 2) {
                    Text(track.title).font(Typo.rowTitle).foregroundStyle(Tone.primary).lineLimit(1)
                    Text(track.artist).font(Typo.rowSubtitle).foregroundStyle(Tone.secondary).lineLimit(1)
                }
            }
            .frame(width: size, alignment: .leading)
        }
        .buttonStyle(.pressable)
    }
}

/// Vignette d'album : pochette, titre, artiste · année.
struct AlbumTile: View {
    let album: Album
    var size: CGFloat = 150
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 8) {
                Artwork(url: album.coverURL, cornerRadius: 10, symbol: "square.stack")
                    .frame(width: size, height: size)
                    .zoomSource(.album(source: album.source, id: album.sourceId))
                VStack(alignment: .leading, spacing: 2) {
                    Text(album.title).font(Typo.rowTitle).foregroundStyle(Tone.primary).lineLimit(1)
                    Text([album.artist, album.year].compactMap { $0 }.joined(separator: " · "))
                        .font(Typo.rowSubtitle).foregroundStyle(Tone.secondary).lineLimit(1)
                }
            }
            .frame(width: size, alignment: .leading)
        }
        .buttonStyle(.pressable)
    }
}

/// Portrait circulaire d'artiste.
struct ArtistBubble: View {
    let name: String
    let pictureURL: String?
    var route: Route?
    var size: CGFloat = 110
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(spacing: 10) {
                Group {
                    if let route {
                        Artwork(url: pictureURL, cornerRadius: size / 2, symbol: "person.fill").zoomSource(route)
                    } else {
                        Artwork(url: pictureURL, cornerRadius: size / 2, symbol: "person.fill")
                    }
                }
                .frame(width: size, height: size)
                Text(name)
                    .font(Typo.rowTitle)
                    .foregroundStyle(Tone.primary)
                    .multilineTextAlignment(.center)
                    .lineLimit(2)
                    .frame(width: size)
            }
        }
        .buttonStyle(.pressable)
    }
}

/// Carte de radio thématique : image de la station, nom posé en bas.
struct RadioTile: View {
    let radio: RadioStation
    var size: CGFloat = 150
    var isLoading = false
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            ZStack(alignment: .bottomLeading) {
                Artwork(url: radio.pictureURL, cornerRadius: 12, symbol: "dot.radiowaves.left.and.right")
                LinearGradient(colors: [.clear, .black.opacity(0.75)], startPoint: .center, endPoint: .bottom)
                    .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                Text(radio.title)
                    .font(Typo.headline)
                    .foregroundStyle(.white)
                    .lineLimit(2)
                    .padding(12)
                if isLoading {
                    ProgressView()
                        .tint(.white)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .background(Color.black.opacity(0.35))
                        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                }
            }
            .frame(width: size, height: size)
        }
        .buttonStyle(.pressable)
    }
}

/// Titre de section, avec une action optionnelle à droite.
struct SectionHeader: View {
    let title: String
    var actionLabel: String?
    var action: (() -> Void)?

    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            Text(title).font(Typo.title).foregroundStyle(Tone.primary)
            Spacer()
            if let actionLabel, let action {
                Button(action: action) {
                    HStack(spacing: 2) {
                        Text(actionLabel)
                        Image(systemName: "chevron.right").font(.system(size: 12, weight: .semibold))
                    }
                    .font(Typo.rowSubtitle)
                    .foregroundStyle(Tone.secondary)
                }
                .buttonStyle(.pressable)
            }
        }
    }
}

/// Rangée horizontale défilante avec la marge de l'écran et l'effet de
/// respiration des vignettes (`carouselItem`).
struct Carousel<Item: Identifiable, Content: View>: View {
    let items: [Item]
    var spacing: CGFloat = 14
    @ViewBuilder var content: (Item) -> Content

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            LazyHStack(alignment: .top, spacing: spacing) {
                ForEach(items) { item in
                    content(item).carouselItem()
                }
            }
            .scrollTargetLayout()
            .padding(.horizontal, 20)
        }
        .scrollTargetBehavior(.viewAligned)
        .scrollClipDisabled()
    }
}

/// Message vide/erreur centré, sobre.
struct EmptyState: View {
    let systemImage: String
    let title: String
    var message: String?

    var body: some View {
        VStack(spacing: 10) {
            Image(systemName: systemImage)
                .font(.system(size: 34, weight: .light))
                .foregroundStyle(Tone.tertiary)
                .padding(.bottom, 4)
            Text(title).font(Typo.headline).foregroundStyle(Tone.primary)
            if let message {
                Text(message)
                    .font(Typo.rowSubtitle)
                    .foregroundStyle(Tone.secondary)
                    .multilineTextAlignment(.center)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.horizontal, 32)
        .padding(.vertical, 40)
    }
}
