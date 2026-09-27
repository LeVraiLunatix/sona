import Foundation
import SwiftUI

/// Lecteur plein écran — version fonctionnelle minimale (pochette, transport,
/// défilement). Le habillage complet du prototype (verre liquide, paroles
/// synchronisées, file d'attente, geste de fermeture) est la prochaine étape
/// une fois cette coquille validée — voir Encre.dc.html §1a.
struct NowPlayingSheet: View {
    @ObservedObject var player: PlayerManager
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(spacing: 0) {
            Capsule()
                .fill(EncreColor.neutral400)
                .frame(width: 44, height: 5)
                .padding(.top, 10)
                .padding(.bottom, 20)

            if let track = player.current {
                CoverArt(url: track.coverURL, title: track.title)
                    .frame(width: 300, height: 300)
                    .encreShadow(EncreShadow.lg)
                    .padding(.horizontal, 36)

                VStack(spacing: 4) {
                    Text(track.title)
                        .font(EncreFont.heading(26))
                        .foregroundStyle(EncreColor.text)
                        .lineLimit(1)
                    Text(track.artist)
                        .font(EncreFont.bodyItalic(18))
                        .foregroundStyle(EncreColor.spotDeep)
                        .lineLimit(1)
                }
                .padding(.top, 24)
                .padding(.horizontal, 36)

                VStack(spacing: 6) {
                    Slider(
                        value: Binding(get: { player.progress }, set: { player.seek(toFraction: $0) }),
                        in: 0...1
                    )
                    .tint(EncreColor.text)
                    HStack {
                        Text(formatted(player.positionSeconds))
                        Spacer()
                        Text("-" + formatted(max(0, (track.durationSeconds ?? 0).doubleValue - player.positionSeconds)))
                    }
                    .font(EncreFont.body(13))
                    .foregroundStyle(EncreColor.neutral700)
                    .monospacedDigit()
                }
                .padding(.horizontal, 36)
                .padding(.top, 28)

                HStack(spacing: 40) {
                    Spacer()
                    Button { player.togglePlayPause() } label: {
                        Image(systemName: player.isPlaying ? "pause.fill" : "play.fill")
                            .font(.system(size: 40))
                            .frame(width: 90, height: 90)
                    }
                    .glassCircle()
                    .foregroundStyle(EncreColor.text)
                    Spacer()
                }
                .padding(.top, 32)

                if let message = player.errorMessage {
                    Text(message)
                        .font(EncreFont.body(14))
                        .foregroundStyle(EncreColor.accent2_700)
                        .padding(.top, 20)
                        .padding(.horizontal, 36)
                }
            }

            Spacer()
        }
        .frame(maxWidth: .infinity)
        .background(EncreColor.bg.ignoresSafeArea())
    }

    private func formatted(_ seconds: Double) -> String {
        let total = max(0, Int(seconds))
        return String(format: "%d:%02d", total / 60, total % 60)
    }
}

private extension Int {
    var doubleValue: Double { Double(self) }
}
