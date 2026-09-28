import SwiftUI

/// Barre de lecture minimale, posée au-dessus de la barre d'onglets via
/// `.safeAreaInset` (voir `RootTabView`) — dessine son propre verre liquide
/// (vrai `glassEffect()` système), n'étant plus dans le conteneur
/// `tabViewBottomAccessory` natif dont la pastille fantôme (visible même
/// sans morceau en cours) posait problème.
struct MiniPlayerView: View {
    @ObservedObject var player: PlayerManager
    var onExpand: () -> Void

    var body: some View {
        if let track = player.current {
            Button(action: onExpand) {
                HStack(spacing: 12) {
                    CoverArt(url: track.coverURL, title: track.title)
                        .frame(width: 46, height: 46)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(track.title)
                            .font(EncreFont.heading(16))
                            .foregroundStyle(EncreColor.text)
                            .lineLimit(1)
                        Text(track.artist)
                            .font(EncreFont.bodyItalic(14))
                            .foregroundStyle(EncreColor.neutral600)
                            .lineLimit(1)
                    }
                    Spacer(minLength: 8)
                    Button {
                        withAnimation(.easeOut(duration: 0.15)) { player.togglePlayPause() }
                    } label: {
                        Image(systemName: player.isLoading ? "hourglass" : (player.isPlaying ? "pause.fill" : "play.fill"))
                            .font(.system(size: 20))
                            .foregroundStyle(EncreColor.text)
                            .frame(width: 42, height: 42)
                            .contentTransition(.symbolEffect(.replace))
                    }
                    .buttonStyle(.plain)
                }
                .padding(.leading, 8)
                .padding(.trailing, 10)
                .frame(height: 64)
            }
            .buttonStyle(.plain)
            .glassCapsule(interactive: true)
            .transition(.move(edge: .bottom).combined(with: .opacity))
        }
    }
}
