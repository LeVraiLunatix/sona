import SwiftUI

/// Mini-lecteur, posé en accessoire de la barre d'onglets (le verre et la
/// place sont fournis par le système) : pochette, titre, lecture/pause,
/// suivant, et une fine barre de progression en bas. En version « rangée »
/// (barre d'onglets réduite au défilement), il se resserre. Tout le bloc
/// ouvre le lecteur plein écran, qui en *grandit* (voir `RootTabView`).
struct MiniPlayerView: View {
    @ObservedObject var player: PlayerManager
    var onExpand: () -> Void
    @Environment(\.tabViewBottomAccessoryPlacement) private var placement

    private var isInline: Bool { placement == .inline }

    var body: some View {
        if let track = player.current {
            HStack(spacing: 12) {
                Artwork(url: track.coverURL, cornerRadius: isInline ? 5 : 7)
                    .frame(width: isInline ? 28 : 34, height: isInline ? 28 : 34)
                    .scaleEffect(player.isPlaying ? 1 : 0.9)
                    .animation(Motion.bouncy, value: player.isPlaying)
                VStack(alignment: .leading, spacing: 1) {
                    Text(track.title)
                        .font(Typo.rowTitle)
                        .foregroundStyle(Tone.primary)
                        .lineLimit(1)
                    if !isInline {
                        Text(track.artist)
                            .font(.system(size: 13))
                            .foregroundStyle(Tone.secondary)
                            .lineLimit(1)
                    }
                }
                .id(track.id)
                .transition(.asymmetric(
                    insertion: .move(edge: .trailing).combined(with: .opacity),
                    removal: .move(edge: .leading).combined(with: .opacity)
                ))
                Spacer(minLength: 4)
                Button {
                    player.togglePlayPause()
                } label: {
                    Group {
                        if player.isLoading {
                            ProgressView().tint(.white)
                        } else {
                            Image(systemName: player.isPlaying ? "pause.fill" : "play.fill")
                                .contentTransition(.symbolEffect(.replace.downUp))
                        }
                    }
                    .font(.system(size: isInline ? 17 : 19, weight: .semibold))
                    .foregroundStyle(Tone.primary)
                    .frame(width: 40, height: 40)
                }
                .buttonStyle(.pressable(scale: 0.85))
                .sensoryFeedback(.impact(weight: .light), trigger: player.isPlaying)

                if !isInline {
                Button {
                    player.next()
                } label: {
                    Image(systemName: "forward.fill")
                        .font(.system(size: 18, weight: .semibold))
                        .foregroundStyle(player.upNext.isEmpty ? Tone.tertiary : Tone.primary)
                        .frame(width: 36, height: 40)
                }
                .buttonStyle(.pressable(scale: 0.85))
                .disabled(player.upNext.isEmpty)
                }
            }
            .padding(.leading, 8)
            .padding(.trailing, 8)
            .frame(maxHeight: .infinity)
            .overlay(alignment: .bottom) {
                GeometryReader { proxy in
                    Capsule()
                        .fill(Color.white.opacity(0.85))
                        .frame(width: proxy.size.width * player.progress, height: 2)
                        .animation(.linear(duration: 0.5), value: player.progress)
                }
                .frame(height: 2)
                .padding(.horizontal, 22)
                .padding(.bottom, 3)
            }
            .contentShape(Rectangle())
            .onTapGesture(perform: onExpand)
            .animation(Motion.snappy, value: track.id)
        }
    }
}
