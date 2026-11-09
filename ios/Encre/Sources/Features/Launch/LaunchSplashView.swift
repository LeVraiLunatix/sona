import SwiftUI

/// Écran de démarrage animé : le logo (l'orbite : anneau, sphère de verre, lune) se trace au milieu
/// d'ondes qui se propagent, puis le nom et l'accroche montent. Il reste le temps que l'app soit
/// prête (compte vérifié), au moins un instant pour que l'animation s'achève ; puis, avec
/// `leaving`, le logo s'agrandit et se fond pendant que l'app apparaît dessous (voir `EncreApp`),
/// sans coupure.
///
/// Il prend le relais de l'écran de lancement système (même fond noir) : aucun saut visible.
struct LaunchSplashView: View {
    /// Passe à `true` pour lancer la sortie (fondu enchaîné avec l'app).
    var leaving = false
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
                    center: .center, startRadius: 0, endRadius: 280
                )
                .frame(width: 560, height: 560)
                .offset(y: -40)
            }

            // Ondes concentriques, comme une onde sonore qui part de la sphère.
            TimelineView(.animation) { timeline in
                let t = timeline.date.timeIntervalSince(started)
                ZStack {
                    ForEach(0..<4, id: \.self) { index in
                        let phase = (t * 0.5 + Double(index) * 0.25).truncatingRemainder(dividingBy: 1)
                        Circle()
                            .strokeBorder(Color.white.opacity((1 - phase) * 0.2), lineWidth: 1.2)
                            .frame(width: 110 + 380 * phase, height: 110 + 380 * phase)
                    }
                }
                .offset(y: -40)
                .opacity(min(1, max(0, (t - 0.5) / 0.8)))
            }

            VStack(spacing: 22) {
                OrbitLogo(size: 170, live: true, drawIn: 1.4)

                Text("Sona")
                    .font(.system(size: 46, weight: .bold))
                    .tracking(-1)
                    .foregroundStyle(Tone.primary)
                    .opacity(showsTitle ? 1 : 0)
                    .offset(y: showsTitle ? 0 : 14)
                    .blur(radius: showsTitle ? 0 : 6)

                Text("Ta musique, tes amis, tes stats.")
                    .font(.system(size: 16, weight: .medium))
                    .foregroundStyle(Tone.secondary)
                    .opacity(showsTagline ? 1 : 0)
                    .offset(y: showsTagline ? 0 : 10)
            }
            .offset(y: -40)

            VStack {
                Spacer()
                LoadingBar()
                    .frame(width: 120, height: 3)
                    .padding(.bottom, 70)
                    .opacity(showsTagline && !leaving ? 1 : 0)
            }
        }
        // Sortie : tout grandit doucement et se fond, l'app apparaît en dessous.
        .scaleEffect(leaving ? 1.35 : 1)
        .blur(radius: leaving ? 14 : 0)
        .opacity(leaving ? 0 : 1)
        .animation(.easeInOut(duration: 0.9), value: leaving)
        .onAppear {
            started = Date()
            withAnimation(.spring(response: 0.8, dampingFraction: 0.82).delay(1.0)) { showsTitle = true }
            withAnimation(.easeOut(duration: 0.7).delay(1.4)) { showsTagline = true }
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
