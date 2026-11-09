import SwiftUI

/// Écran de démarrage animé : le logo se dessine barre après barre au milieu
/// d'ondes qui se propagent, puis le nom et la phrase d'accroche montent. Il
/// reste le temps que l'app soit prête (compte vérifié), au moins un instant
/// pour que l'animation s'achève, puis s'efface en s'agrandissant.
///
/// Il prend le relais de l'écran de lancement système (fond noir et logo, voir
/// `UILaunchScreen`) : même fond, donc aucun saut au passage de l'un à l'autre.
struct LaunchSplashView: View {
    @State private var started = Date()
    @State private var showsTitle = false
    @State private var showsTagline = false

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()

            // Lueur douce qui respire derrière le logo.
            TimelineView(.animation) { timeline in
                let t = timeline.date.timeIntervalSince(started)
                let breathe = 0.5 + 0.5 * sin(t * 1.6)
                RadialGradient(
                    colors: [Color.white.opacity(0.10 + 0.05 * breathe), .clear],
                    center: .center, startRadius: 0, endRadius: 260
                )
                .frame(width: 520, height: 520)
                .offset(y: -40)
            }

            // Ondes concentriques, comme une onde sonore qui part du logo.
            TimelineView(.animation) { timeline in
                let t = timeline.date.timeIntervalSince(started)
                ZStack {
                    ForEach(0..<4, id: \.self) { index in
                        let phase = (t * 0.55 + Double(index) * 0.25).truncatingRemainder(dividingBy: 1)
                        Circle()
                            .strokeBorder(Color.white.opacity((1 - phase) * 0.22), lineWidth: 1.2)
                            .frame(width: 130 + 360 * phase, height: 130 + 360 * phase)
                            .scaleEffect(t > 0.6 ? 1 : 0.2)
                    }
                }
                .offset(y: -40)
                .opacity(min(1, t / 0.8))
            }

            VStack(spacing: 18) {
                SonaLogo(size: 128, live: true)
                    .offset(y: -40)

                Text("Sona")
                    .font(.system(size: 46, weight: .bold))
                    .tracking(-1)
                    .foregroundStyle(Tone.primary)
                    .opacity(showsTitle ? 1 : 0)
                    .offset(y: showsTitle ? -40 : -28)
                    .blur(radius: showsTitle ? 0 : 6)

                Text("Ta musique, tes amis, tes stats.")
                    .font(.system(size: 16, weight: .medium))
                    .foregroundStyle(Tone.secondary)
                    .opacity(showsTagline ? 1 : 0)
                    .offset(y: showsTagline ? -40 : -30)
            }

            VStack {
                Spacer()
                LoadingBar()
                    .frame(width: 120, height: 3)
                    .padding(.bottom, 70)
                    .opacity(showsTagline ? 1 : 0)
            }
        }
        .onAppear {
            started = Date()
            withAnimation(.spring(response: 0.8, dampingFraction: 0.82).delay(0.75)) { showsTitle = true }
            withAnimation(.easeOut(duration: 0.7).delay(1.15)) { showsTagline = true }
        }
        .accessibilityHidden(true)
    }
}

/// Barre fine dont un reflet va et vient : « ça charge », sans chiffre.
private struct LoadingBar: View {
    @State private var moving = false

    var body: some View {
        GeometryReader { proxy in
            ZStack(alignment: .leading) {
                Capsule().fill(Color.white.opacity(0.12))
                Capsule()
                    .fill(Color.white.opacity(0.85))
                    .frame(width: proxy.size.width * 0.35)
                    .offset(x: moving ? proxy.size.width * 0.65 : 0)
            }
            .clipShape(Capsule())
        }
        .onAppear {
            withAnimation(.easeInOut(duration: 0.9).repeatForever(autoreverses: true)) { moving = true }
        }
    }
}
