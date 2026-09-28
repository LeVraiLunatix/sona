import SwiftUI

/// Barre de lecture minimale, ancrée au-dessus de la barre d'onglets.
/// Version simplifiée du mini-lecteur du prototype (pastille "verre
/// liquide" + pochette + titre/artiste + transport) : la fusion animée avec
/// la barre d'onglets et le lecteur plein écran (Encre.dc.html §1a) arrive
/// dans une prochaine étape.
struct MiniPlayerView: View {
    @ObservedObject var player: PlayerManager
    var onExpand: () -> Void

    var body: some View {
        if let track = player.current {
            Button(action: onExpand) {
                HStack(spacing: 12) {
                    CoverArt(url: track.coverURL, title: track.title)
                        .frame(width: 46, height: 46)
                        .encreShadow(EncreShadow.sm)
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
            .glassCapsule()
            .transition(.move(edge: .bottom).combined(with: .opacity))
        }
    }
}
