import SwiftUI

/// Ligne de morceau (bibliothèque, historique, classement, résultats de
/// recherche...) : pochette carrée, titre + artiste, durée. Reprend la
/// composition de la carte "morceau" du prototype (Encre.dc.html §1a).
struct TrackRow: View {
    let track: Track
    var showDuration: Bool = true
    var rank: Int?
    var isCurrent: Bool = false
    var action: () -> Void

    var body: some View {
        Button(action: action) {
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
                    Text(track.artist)
                        .font(EncreFont.bodyItalic(14))
                        .foregroundStyle(EncreColor.neutral600)
                        .lineLimit(1)
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
        }
        .buttonStyle(.plain)
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
