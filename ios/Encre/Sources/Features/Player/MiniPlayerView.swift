import SwiftUI

/// Mini-lecteur flottant en verre (vrai `glassEffect()` système) : pochette,
/// titre, lecture/pause, suivant, et une fine barre de progression en bas.
/// Tout le bloc ouvre le lecteur plein écran, qui en *grandit* (voir
/// `RootTabView`).
struct MiniPlayerView: View {
    @ObservedObject var player: PlayerManager
    var onExpand: () -> Void

    var body: some View {
        if let track = player.current {
            HStack(spacing: 12) {
                Artwork(url: track.coverURL, cornerRadius: 8)
                    .frame(width: 42, height: 42)
                    .scaleEffect(player.isPlaying ? 1 : 0.9)
                    .animation(Motion.bouncy, value: player.isPlaying)
                VStack(alignment: .leading, spacing: 1) {
                    Text(track.title)
                        .font(Typo.rowTitle)
                        .foregroundStyle(Tone.primary)
                        .lineLimit(1)
                    Text(track.artist)
                        .font(Typo.rowSubtitle)
                        .foregroundStyle(Tone.secondary)
                        .lineLimit(1)
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
                    .font(.system(size: 20, weight: .semibold))
                    .foregroundStyle(Tone.primary)
                    .frame(width: 40, height: 40)
                }
                .buttonStyle(.pressable(scale: 0.85))
                .sensoryFeedback(.impact(weight: .light), trigger: player.isPlaying)

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
            .padding(.leading, 8)
            .padding(.trailing, 8)
            .frame(height: 60)
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
            .contentShape(Capsule())
            .onTapGesture(perform: onExpand)
            .glassCapsule(interactive: true)
            .animation(Motion.snappy, value: track.id)
        }
    }
}
