import SwiftUI

/// Ligne de morceau (bibliothèque, historique, classement, résultats de
/// recherche...) : pochette carrée, titre + artiste, durée. Reprend la
/// composition de la carte "morceau" du prototype (Encre.dc.html §1a).
struct TrackRow: View {
    let track: Track
    var showDuration: Bool = true
    var rank: Int?
    var isCurrent: Bool = false
    /// Ouvre la fiche artiste/album du morceau — absent (`nil`) si l'appelant
    /// ne peut pas naviguer (pas de `NavigationPath` sous la main) ou si le
    /// serveur n'a pas fourni l'identifiant correspondant. Sans ça, un
    /// morceau isolé (résultat de recherche...) n'a aucun moyen de mener à
    /// une vraie fiche artiste — juste "un son en vrac".
    /// Déclarés avant `action` : la syntaxe "trailing closure" des appels
    /// existants (`TrackRow(...) { player.play(...) }`) doit continuer de
    /// cibler `action`, le dernier paramètre de type fonction.
    var onOpenArtist: (() -> Void)? = nil
    var onOpenAlbum: (() -> Void)? = nil
    var action: () -> Void

    var body: some View {
        HStack(spacing: 14) {
            if let rank {
                Text("\(rank)")
                    .font(EncreFont.heading(28))
                    .frame(width: 30, alignment: .leading)
                    .foregroundStyle(EncreColor.text)
            }
            CoverArt(url: track.coverURL, title: track.title)
                .frame(width: 54, height: 54)
            VStack(alignment: .leading, spacing: 2) {
                Text(track.title)
                    .font(EncreFont.heading(17))
                    .foregroundStyle(isCurrent ? EncreColor.spotDeep : EncreColor.text)
                    .lineLimit(1)
                // Un `Button` visible ici plutôt qu'enfoui dans le menu
                // contextuel : sur Apple Music, taper le nom de l'artiste
                // sous un morceau ouvre sa fiche — un geste qu'on ne découvre
                // pas par hasard s'il faut d'abord penser à l'appui long.
                if let onOpenArtist {
                    Button(action: onOpenArtist) {
                        Text(track.artist)
                            .font(EncreFont.bodyItalic(14))
                            .foregroundStyle(EncreColor.spotDeep)
                            .lineLimit(1)
                    }
                    .buttonStyle(.plain)
                } else {
                    Text(track.artist)
                        .font(EncreFont.bodyItalic(14))
                        .foregroundStyle(EncreColor.neutral600)
                        .lineLimit(1)
                }
            }
            Spacer(minLength: 8)
            if showDuration {
                Text(track.durationLabel)
                    .font(EncreFont.body(14))
                    .foregroundStyle(EncreColor.neutral600)
                    .monospacedDigit()
            }
        }
        .contentShape(Rectangle())
        // `onTapGesture` sur le conteneur plutôt qu'un `Button` autour de
        // tout : un `Button` imbriqué (le nom d'artiste ci-dessus) perdrait
        // sinon son propre tap, absorbé par celui du parent.
        .onTapGesture(perform: action)
        .contextMenu {
            if let onOpenAlbum {
                Button { onOpenAlbum() } label: { Label("Voir l'album", systemImage: "square.stack.fill") }
            }
        }
    }
}

/// Vignette carrée (accueil : "À la une" / "Écoutés récemment").
struct TrackTile: View {
    let track: Track
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 8) {
                CoverArt(url: track.coverURL, title: track.title)
                    .frame(width: 150, height: 150)
                    .encreShadow(EncreShadow.sm)
                VStack(alignment: .leading, spacing: 2) {
                    Text(track.title).font(EncreFont.heading(16)).foregroundStyle(EncreColor.text).lineLimit(1)
                    Text(track.artist).font(EncreFont.bodyItalic(14)).foregroundStyle(EncreColor.neutral600).lineLimit(1)
                }
            }
            .frame(width: 150, alignment: .leading)
        }
        .buttonStyle(.plain)
    }
}

/// Vignette d'album (résultats de recherche) : pochette carrée, titre et
/// artiste — même gabarit que `TrackTile` pour s'aligner dans une rangée.
struct AlbumTile: View {
    let album: Album
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 8) {
                CoverArt(url: album.coverURL, title: album.title)
                    .frame(width: 150, height: 150)
                    .encreShadow(EncreShadow.sm)
                VStack(alignment: .leading, spacing: 2) {
                    Text(album.title).font(EncreFont.heading(16)).foregroundStyle(EncreColor.text).lineLimit(1)
                    Text([album.artist, album.year].compactMap { $0 }.joined(separator: " · "))
                        .font(EncreFont.bodyItalic(14)).foregroundStyle(EncreColor.neutral600).lineLimit(1)
                }
            }
            .frame(width: 150, alignment: .leading)
        }
        .buttonStyle(.plain)
    }
}

/// Vignette de radio thématique (onglet Recherche, champ vide) : l'image
/// Deezer de la station avec son nom posé dessus, façon carte de genre
/// d'Apple Music. `isLoading` pendant le premier tirage de la station.
struct RadioTile: View {
    let radio: RadioStation
    var isLoading: Bool = false
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            ZStack(alignment: .bottomLeading) {
                CoverArt(url: radio.pictureURL, title: radio.title)
                LinearGradient(colors: [.clear, .black.opacity(0.65)], startPoint: .center, endPoint: .bottom)
                Text(radio.title)
                    .font(EncreFont.heading(16))
                    .foregroundStyle(.white)
                    .lineLimit(2)
                    .padding(10)
                if isLoading {
                    ProgressView()
                        .tint(.white)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            }
            .frame(width: 140, height: 140)
            .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
            .encreShadow(EncreShadow.sm)
        }
        .buttonStyle(.plain)
    }
}

/// Portrait circulaire d'artiste (accueil : "Vos artistes").
struct ArtistBubble: View {
    let name: String
    let coverURL: String?
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(spacing: 8) {
                CoverArt(url: coverURL, title: name, cornerRadius: 1000)
                    .frame(width: 104, height: 104)
                    .clipShape(Circle())
                    .encreShadow(EncreShadow.sm)
                Text(name)
                    .font(EncreFont.heading(15))
                    .foregroundStyle(EncreColor.text)
                    .multilineTextAlignment(.center)
                    .lineLimit(2)
                    .frame(width: 104)
            }
        }
        .buttonStyle(.plain)
    }
}

/// Titre de section ("Écoutés récemment", "Vos artistes"...), avec un
/// bouton "Tout voir" optionnel.
struct SectionHeader: View {
    let title: String
    var actionLabel: String?
    var action: (() -> Void)?

    var body: some View {
        HStack(alignment: .lastTextBaseline) {
            Text(title).font(EncreFont.heading(22)).foregroundStyle(EncreColor.text)
            Spacer()
            if let actionLabel, let action {
                Button(actionLabel, action: action)
                    .font(EncreFont.body(15))
                    .foregroundStyle(EncreColor.spotDeep)
            }
        }
    }
}
