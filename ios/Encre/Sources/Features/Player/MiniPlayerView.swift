import SwiftUI

/// Contenu du mini-lecteur — affiché tel quel dans le `tabViewBottomAccessory`
/// de `RootTabView` : pas de fond dessiné ici, `TabView` fournit déjà le
/// verre liquide système derrière (celui que partagent Musique et Podcasts),
/// donc y superposer un `.glassCapsule()` maison ferait double emploi.
struct MiniPlayerView: View {
    @ObservedObject var player: PlayerManager
    var onExpand: () -> Void

    var body: some View {
        if let track = player.current {
            Button(action: onExpand) {
                HStack(spacing: 12) {
                    CoverArt(url: track.coverURL, title: track.title)
                        .frame(width: 40, height: 40)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(track.title)
                            .font(EncreFont.heading(15))
                            .foregroundStyle(EncreColor.text)
                            .lineLimit(1)
                        Text(track.artist)
                            .font(EncreFont.bodyItalic(13))
                            .foregroundStyle(EncreColor.neutral600)
                            .lineLimit(1)
                    }
                    Spacer(minLength: 8)
                    Button {
                        withAnimation(.easeOut(duration: 0.15)) { player.togglePlayPause() }
                    } label: {
                        Image(systemName: player.isLoading ? "hourglass" : (player.isPlaying ? "pause.fill" : "play.fill"))
                            .font(.system(size: 18))
                            .foregroundStyle(EncreColor.text)
                            .frame(width: 34, height: 34)
                            .contentTransition(.symbolEffect(.replace))
                    }
                    .buttonStyle(.plain)
                }
                .padding(.horizontal, 6)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
        }
    }
}
