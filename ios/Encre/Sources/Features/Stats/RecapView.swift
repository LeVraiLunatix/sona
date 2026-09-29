import SwiftUI

/// Récap façon Wrapped, en story : une page par chiffre marquant, qui défile
/// toute seule (toucher à droite : suivante, à gauche : précédente, appui
/// long : pause), et une carte finale à partager.
struct RecapView: View {
    let period: String
    let offset: Int

    @Environment(\.dismiss) private var dismiss
    @State private var recap: Recap?
    @State private var errorMessage: String?
    @State private var page = 0
    @State private var progress: Double = 0
    @State private var paused = false
    @State private var shareImage: UIImage?

    private static let pageSeconds: Double = 7

    private enum Page: Hashable {
        case intro, minutes, topArtist, artists, favourite, tracks, discoveries, habits, personality, friends, summary
    }

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            if let recap {
                let story = pages(for: recap)
                let current = story[min(page, story.count - 1)]
                ZStack {
                    background(for: current)
                        .ignoresSafeArea()
                    pageView(current, recap)
                        .id(current)
                        .transition(.asymmetric(
                            insertion: .opacity.combined(with: .scale(scale: 1.05)),
                            removal: .opacity
                        ))
                        .padding(.horizontal, 28)
                        .padding(.top, 70)
                        .padding(.bottom, 40)
                }
                .contentShape(Rectangle())
                .gesture(
                    SpatialTapGesture().onEnded { value in
                        let width = UIScreen.main.bounds.width
                        go(value.location.x < width * 0.3 ? -1 : 1, count: story.count)
                    }
                )
                .simultaneousGesture(
                    LongPressGesture(minimumDuration: 0.25)
                        .onChanged { _ in paused = true }
                        .onEnded { _ in paused = false }
                )
                .overlay(alignment: .top) { header(count: story.count) }
                .task(id: page) { await autoAdvance(count: story.count) }
                .animation(.easeInOut(duration: 0.45), value: page)
            } else if let errorMessage {
                VStack(spacing: 16) {
                    EmptyState(systemImage: "sparkles", title: "Récap indisponible", message: errorMessage)
                    PillButton(title: "Fermer", systemImage: "xmark") { dismiss() }
                }
                .padding(24)
            } else {
                VStack(spacing: 14) {
                    ProgressView().tint(.white)
                    Text("Préparation de ton récap…").font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
                }
            }
        }
        .statusBarHidden()
        .task { await load() }
    }

    // MARK: - Déroulé

    private func pages(for recap: Recap) -> [Page] {
        guard recap.plays > 0 else { return [.intro] }
        var pages: [Page] = [.intro, .minutes]
        if !recap.topArtists.isEmpty { pages += [.topArtist, .artists] }
        if recap.favouriteTrack != nil { pages.append(.favourite) }
        if recap.topTracks.count > 1 { pages.append(.tracks) }
        if !recap.discoveries.isEmpty { pages.append(.discoveries) }
        pages.append(.habits)
        if recap.personality != nil { pages.append(.personality) }
        if recap.friendsRank != nil { pages.append(.friends) }
        pages.append(.summary)
        return pages
    }

    private func go(_ delta: Int, count: Int) {
        let target = page + delta
        if target >= count {
            dismiss()
        } else {
            progress = 0
            page = max(0, target)
        }
    }

    private func autoAdvance(count: Int) async {
        progress = 0
        // La dernière page (partage) reste affichée.
        guard page < count - 1 else {
            progress = 1
            return
        }
        while !Task.isCancelled {
            try? await Task.sleep(for: .milliseconds(50))
            guard !Task.isCancelled else { return }
            if paused { continue }
            progress += 0.05 / Self.pageSeconds
            if progress >= 1 {
                go(1, count: count)
                return
            }
        }
    }

    private func load() async {
        do {
            let loaded = try await APIClient.shared.recap(period: period, offset: offset)
            withAnimation { recap = loaded }
            shareImage = renderShareCard(loaded)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func header(count: Int) -> some View {
        VStack(spacing: 10) {
            HStack(spacing: 4) {
                ForEach(0..<count, id: \.self) { index in
                    GeometryReader { proxy in
                        Capsule().fill(Color.white.opacity(0.25))
                            .overlay(alignment: .leading) {
                                Capsule().fill(Color.white)
                                    .frame(width: proxy.size.width * (index < page ? 1 : index == page ? progress : 0))
                            }
                    }
                    .frame(height: 3)
                }
            }
            HStack {
                Text("Sona · \(recap?.label ?? "")").font(Typo.caption).foregroundStyle(.white.opacity(0.8))
                Spacer()
                Button { dismiss() } label: {
                    Image(systemName: "xmark").font(.system(size: 17, weight: .bold)).foregroundStyle(.white)
                        .frame(width: 36, height: 36)
                }
            }
        }
        .padding(.horizontal, 14)
        .padding(.top, 8)
    }

    // MARK: - Pages

    @ViewBuilder
    private func pageView(_ current: Page, _ recap: Recap) -> some View {
        switch current {
        case .intro: intro(recap)
        case .minutes: minutes(recap)
        case .topArtist: topArtist(recap)
        case .artists: ranking(title: "Tes artistes", items: recap.topArtists, round: true)
        case .favourite: favourite(recap)
        case .tracks: ranking(title: "Tes titres", items: recap.topTracks, round: false)
        case .discoveries: discoveries(recap)
        case .habits: habits(recap)
        case .personality: personality(recap)
        case .friends: friends(recap)
        case .summary: summary(recap)
        }
    }

    private func bigTitle(_ text: String) -> some View {
        Text(text)
            .font(.system(size: 38, weight: .heavy))
            .foregroundStyle(.white)
            .multilineTextAlignment(.leading)
            .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func intro(_ recap: Recap) -> some View {
        VStack(alignment: .leading, spacing: 18) {
            Spacer()
            Text("🎧").font(.system(size: 80))
                .phaseAnimator([false, true]) { view, up in
                    view.offset(y: up ? -8 : 8).rotationEffect(.degrees(up ? -6 : 6))
                } animation: { _ in .easeInOut(duration: 1.2) }
            bigTitle(recap.plays == 0 ? "Pas encore d'écoute sur cette période." : "Ton récap\n\(recap.label.lowercased())")
            Text(recap.plays == 0 ? "Reviens après quelques sons !" : "Ce que tu as vraiment écouté. Touche pour avancer.")
                .font(Typo.body).foregroundStyle(.white.opacity(0.75))
            Spacer()
        }
    }

    private func minutes(_ recap: Recap) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            Spacer()
            Text("Tu as écouté").font(.system(size: 24, weight: .semibold)).foregroundStyle(.white.opacity(0.8))
            CountingText(value: recap.minutes)
                .font(.system(size: 84, weight: .black, design: .rounded))
                .foregroundStyle(.white)
            Text("minutes de musique").font(.system(size: 26, weight: .bold)).foregroundStyle(.white)
            if recap.minutes >= 120 {
                Text("Soit \(recap.minutes / 60) h \(recap.minutes % 60) min, \(recap.plays) écoutes et \(recap.artists) artistes.")
                    .font(Typo.body).foregroundStyle(.white.opacity(0.8))
            } else {
                Text("\(recap.plays) écoutes, \(recap.artists) artistes.").font(Typo.body).foregroundStyle(.white.opacity(0.8))
            }
            if recap.previousMinutes > 0 {
                let change = Double(recap.minutes - recap.previousMinutes) / Double(recap.previousMinutes)
                Label(
                    change >= 0 ? "+\(Int((change * 100).rounded())) % par rapport à la période d'avant"
                        : "\(Int((change * 100).rounded())) % par rapport à la période d'avant",
                    systemImage: change >= 0 ? "arrow.up.right" : "arrow.down.right"
                )
                .font(Typo.rowTitle)
                .foregroundStyle(.white)
                .padding(.horizontal, 14).padding(.vertical, 8)
                .background(Capsule().fill(.white.opacity(0.18)))
            }
            Spacer()
        }
    }

    private func topArtist(_ recap: Recap) -> some View {
        let artist = recap.topArtists[0]
        return VStack(spacing: 20) {
            Spacer()
            Text("Ton artiste n°1").font(.system(size: 22, weight: .semibold)).foregroundStyle(.white.opacity(0.85))
            ArtistPicture(source: artist.source, id: artist.sourceId, fallback: artist.coverURL)
                .frame(width: 240, height: 240)
                .clipShape(Circle())
                .shadow(color: .black.opacity(0.5), radius: 30, y: 14)
                .phaseAnimator([false, true]) { view, big in
                    view.scaleEffect(big ? 1.03 : 0.97)
                } animation: { _ in .easeInOut(duration: 1.6) }
            Text(artist.name).font(.system(size: 40, weight: .black)).foregroundStyle(.white)
                .multilineTextAlignment(.center).minimumScaleFactor(0.5).lineLimit(2)
            Text("\(artist.plays) écoutes · \(artist.minutes) min").font(Typo.headline).foregroundStyle(.white.opacity(0.8))
            Spacer()
        }
        .frame(maxWidth: .infinity)
    }

    private func ranking(title: String, items: [RankedStat], round: Bool) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            Spacer()
            bigTitle(title)
            ForEach(Array(items.prefix(5).enumerated()), id: \.element.id) { index, item in
                HStack(spacing: 14) {
                    Text("\(index + 1)").font(.system(size: 28, weight: .black)).foregroundStyle(.white).frame(width: 34)
                    Group {
                        if round {
                            ArtistPicture(source: item.source, id: item.sourceId, fallback: item.coverURL).clipShape(Circle())
                        } else {
                            Artwork(url: item.coverURL, cornerRadius: 8)
                        }
                    }
                    .frame(width: 56, height: 56)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(item.name).font(.system(size: 18, weight: .bold)).foregroundStyle(.white).lineLimit(1)
                        Text([item.subtitle, "\(item.plays) écoutes"].compactMap { $0 }.joined(separator: " · "))
                            .font(Typo.rowSubtitle).foregroundStyle(.white.opacity(0.75)).lineLimit(1)
                    }
                    Spacer(minLength: 0)
                }
                .modifier(StaggeredEntry(index: index))
            }
            Spacer()
        }
    }

    private func favourite(_ recap: Recap) -> some View {
        let track = recap.favouriteTrack!
        let plays = recap.topTracks.first?.plays ?? 0
        return VStack(spacing: 18) {
            Spacer()
            Text("Le son de ta période").font(.system(size: 22, weight: .semibold)).foregroundStyle(.white.opacity(0.85))
            Artwork(url: track.coverURL, cornerRadius: 16)
                .frame(width: 250, height: 250)
                .shadow(color: .black.opacity(0.5), radius: 30, y: 14)
                .rotation3DEffect(.degrees(8), axis: (x: 0, y: 1, z: 0))
            Text(track.title).font(.system(size: 34, weight: .black)).foregroundStyle(.white)
                .multilineTextAlignment(.center).lineLimit(2).minimumScaleFactor(0.6)
            Text(track.artist).font(Typo.headline).foregroundStyle(.white.opacity(0.8))
            Text("Écouté \(plays) fois").font(Typo.rowTitle).foregroundStyle(.white)
                .padding(.horizontal, 14).padding(.vertical, 8)
                .background(Capsule().fill(.white.opacity(0.18)))
            if !track.sourceId.isEmpty {
                Button {
                    PlayerManager.shared.play(track, context: [track], name: "Ton récap")
                } label: {
                    Label("Écouter", systemImage: "play.fill")
                        .font(Typo.headline).foregroundStyle(.black)
                        .padding(.horizontal, 22).padding(.vertical, 12)
                        .background(Capsule().fill(.white))
                }
            }
            Spacer()
        }
        .frame(maxWidth: .infinity)
    }

    private func discoveries(_ recap: Recap) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            Spacer()
            Text("Tu as découvert").font(.system(size: 24, weight: .semibold)).foregroundStyle(.white.opacity(0.85))
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                CountingText(value: recap.discoveredCount).font(.system(size: 72, weight: .black, design: .rounded))
                Text(recap.discoveredCount > 1 ? "nouveaux artistes" : "nouvel artiste").font(.system(size: 24, weight: .bold))
            }
            .foregroundStyle(.white)
            ForEach(Array(recap.discoveries.prefix(4).enumerated()), id: \.element.id) { index, item in
                HStack(spacing: 12) {
                    ArtistPicture(source: item.source, id: item.sourceId, fallback: item.coverURL)
                        .frame(width: 48, height: 48).clipShape(Circle())
                    Text(item.name).font(.system(size: 18, weight: .bold)).foregroundStyle(.white)
                    Spacer()
                    Text("\(item.plays) écoutes").font(Typo.rowSubtitle).foregroundStyle(.white.opacity(0.75))
                }
                .modifier(StaggeredEntry(index: index))
            }
            Spacer()
        }
    }

    private func habits(_ recap: Recap) -> some View {
        VStack(alignment: .leading, spacing: 18) {
            Spacer()
            bigTitle("Tes habitudes")
            if let hour = recap.topHour {
                habit("clock.fill", "Ton heure", "vers \(hour) h", hourComment(hour))
            }
            if let weekday = recap.topWeekday {
                habit("calendar", "Ton jour", "le \(weekday)", "C'est là que tu écoutes le plus.")
            }
            if let day = recap.biggestDay {
                habit("flame.fill", "Ton plus gros jour", day.label, "\(day.minutes) minutes d'affilée ou presque.")
            }
            if recap.streakDays >= 2 {
                habit("bolt.fill", "Ta série en cours", "\(recap.streakDays) jours", "Au moins un son chaque jour.")
            }
            Spacer()
        }
    }

    private func habit(_ icon: String, _ title: String, _ value: String, _ comment: String) -> some View {
        HStack(spacing: 14) {
            Image(systemName: icon).font(.system(size: 22, weight: .bold)).foregroundStyle(.white)
                .frame(width: 48, height: 48).background(Circle().fill(.white.opacity(0.18)))
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(Typo.caption).foregroundStyle(.white.opacity(0.7))
                Text(value).font(.system(size: 22, weight: .heavy)).foregroundStyle(.white)
                Text(comment).font(Typo.rowSubtitle).foregroundStyle(.white.opacity(0.75))
            }
        }
    }

    private func hourComment(_ hour: Int) -> String {
        switch hour {
        case 5..<10: "La musique te réveille."
        case 10..<14: "Ta matinée a une bande-son."
        case 14..<18: "L'après-midi, c'est ton moment."
        case 18..<22: "Le soir, tu montes le son."
        default: "Tu vis la nuit."
        }
    }

    private func personality(_ recap: Recap) -> some View {
        let p = recap.personality!
        return VStack(spacing: 18) {
            Spacer()
            Text("Ton profil d'écoute").font(.system(size: 22, weight: .semibold)).foregroundStyle(.white.opacity(0.85))
            Text(p.emoji).font(.system(size: 110))
                .phaseAnimator([false, true]) { view, big in
                    view.scaleEffect(big ? 1.1 : 0.95)
                } animation: { _ in .spring(response: 0.8, dampingFraction: 0.5) }
            Text(p.title).font(.system(size: 38, weight: .black)).foregroundStyle(.white).multilineTextAlignment(.center)
            Text(p.description).font(Typo.body).foregroundStyle(.white.opacity(0.85)).multilineTextAlignment(.center)
            VStack(spacing: 10) {
                ForEach(p.traits.sorted(by: { $0.key < $1.key }), id: \.key) { name, value in
                    HStack {
                        Text(name.capitalized).font(Typo.caption).foregroundStyle(.white).frame(width: 90, alignment: .leading)
                        GeometryReader { proxy in
                            Capsule().fill(.white.opacity(0.2))
                                .overlay(alignment: .leading) {
                                    Capsule().fill(.white).frame(width: proxy.size.width * min(1, max(0.04, value)))
                                }
                        }
                        .frame(height: 8)
                    }
                }
            }
            .padding(.top, 8)
            Spacer()
        }
    }

    private func friends(_ recap: Recap) -> some View {
        let rank = recap.friendsRank!
        return VStack(spacing: 18) {
            Spacer()
            Text("Parmi tes amis").font(.system(size: 22, weight: .semibold)).foregroundStyle(.white.opacity(0.85))
            Text(rank.rank == 1 ? "🏆" : rank.rank == 2 ? "🥈" : rank.rank == 3 ? "🥉" : "🎧").font(.system(size: 100))
            Text("\(rank.rank)\(rank.rank == 1 ? "er" : "e") sur \(rank.total)")
                .font(.system(size: 56, weight: .black, design: .rounded)).foregroundStyle(.white)
            Text(rank.rank == 1 ? "Personne n'a écouté plus de musique que toi. Respect."
                 : "au temps d'écoute. La prochaine fois, c'est la tienne.")
                .font(Typo.body).foregroundStyle(.white.opacity(0.85)).multilineTextAlignment(.center)
            Spacer()
        }
    }

    private func summary(_ recap: Recap) -> some View {
        VStack(spacing: 18) {
            Spacer(minLength: 10)
            if let shareImage {
                Image(uiImage: shareImage)
                    .resizable()
                    .scaledToFit()
                    .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
                    .shadow(color: .black.opacity(0.5), radius: 24, y: 10)
                ShareLink(item: Image(uiImage: shareImage), preview: SharePreview("Mon récap Sona", image: Image(uiImage: shareImage))) {
                    Label("Partager", systemImage: "square.and.arrow.up")
                        .font(Typo.headline).foregroundStyle(.black)
                        .padding(.horizontal, 24).padding(.vertical, 13)
                        .background(Capsule().fill(.white))
                }
            } else {
                RecapShareCard(recap: recap)
            }
            Spacer(minLength: 10)
        }
    }

    @MainActor
    private func renderShareCard(_ recap: Recap) -> UIImage? {
        let renderer = ImageRenderer(content: RecapShareCard(recap: recap).frame(width: 360, height: 640))
        renderer.scale = 3
        return renderer.uiImage
    }

    // MARK: - Fonds

    private func background(for page: Page) -> some View {
        let palettes: [Page: [Color]] = [
            .intro: [.purple, .indigo, .black],
            .minutes: [.pink, .orange, .purple],
            .topArtist: [.blue, .cyan, .indigo],
            .artists: [.indigo, .purple, .black],
            .favourite: [.orange, .red, .pink],
            .tracks: [.red, .purple, .black],
            .discoveries: [.green, .teal, .blue],
            .habits: [.teal, .blue, .black],
            .personality: [.yellow, .orange, .pink],
            .friends: [.mint, .green, .teal],
            .summary: [.purple, .pink, .black],
        ]
        return AnimatedGradient(colors: palettes[page] ?? [.purple, .black, .black])
    }
}

/// Dégradé en mouvement lent (fond des pages).
private struct AnimatedGradient: View {
    let colors: [Color]

    var body: some View {
        TimelineView(.animation) { context in
            let t = context.date.timeIntervalSinceReferenceDate
            let x = Float(0.5 + 0.3 * sin(t * 0.5))
            let y = Float(0.5 + 0.3 * cos(t * 0.4))
            MeshGradient(
                width: 3, height: 3,
                points: [
                    [0, 0], [0.5, 0], [1, 0],
                    [0, 0.5], [x, y], [1, 0.5],
                    [0, 1], [0.5, 1], [1, 1],
                ],
                colors: [
                    colors[0], colors[1], colors[0],
                    colors[1], colors[2], colors[1],
                    colors[2], colors[0], colors[2],
                ]
            )
            .overlay(Color.black.opacity(0.25))
        }
        .animation(.easeInOut(duration: 0.6), value: colors)
    }
}

/// Nombre qui défile jusqu'à sa valeur.
private struct CountingText: View {
    let value: Int
    @State private var shown = 0

    var body: some View {
        Text("\(shown.formatted())")
            .monospacedDigit()
            .contentTransition(.numericText(value: Double(shown)))
            .task {
                let steps = 30
                for step in 1...steps {
                    try? await Task.sleep(for: .milliseconds(35))
                    withAnimation(.snappy) { shown = value * step / steps }
                }
            }
    }
}

/// Apparition décalée des lignes d'un classement.
private struct StaggeredEntry: ViewModifier {
    let index: Int
    @State private var visible = false

    func body(content: Content) -> some View {
        content
            .opacity(visible ? 1 : 0)
            .offset(x: visible ? 0 : 40)
            .task {
                try? await Task.sleep(for: .milliseconds(150 * index + 200))
                withAnimation(.spring(response: 0.5, dampingFraction: 0.8)) { visible = true }
            }
    }
}

/// Carte du récap à partager (format story 9:16).
struct RecapShareCard: View {
    let recap: Recap

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("Sona").font(.system(size: 22, weight: .black)).foregroundStyle(.white)
                Spacer()
                Text(recap.label).font(.system(size: 14, weight: .semibold)).foregroundStyle(.white.opacity(0.8))
            }
            Spacer(minLength: 0)
            if let p = recap.personality {
                Text("\(p.emoji) \(p.title)").font(.system(size: 26, weight: .black)).foregroundStyle(.white)
            }
            HStack(alignment: .top, spacing: 18) {
                column("Top artistes", recap.topArtists.prefix(5).map(\.name))
                column("Top titres", recap.topTracks.prefix(5).map(\.name))
            }
            HStack(spacing: 18) {
                stat("Minutes", recap.minutes.formatted())
                stat("Artistes", "\(recap.artists)")
                stat("Écoutes", "\(recap.plays)")
            }
            Spacer(minLength: 0)
        }
        .padding(26)
        .frame(width: 360, height: 640)
        .background(
            LinearGradient(colors: [Color(red: 0.55, green: 0.2, blue: 0.95), Color(red: 0.95, green: 0.3, blue: 0.5), .black],
                           startPoint: .topLeading, endPoint: .bottomTrailing)
        )
    }

    private func column(_ title: String, _ names: [String]) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.system(size: 13, weight: .bold)).foregroundStyle(.white.opacity(0.7))
            ForEach(Array(names.enumerated()), id: \.offset) { index, name in
                Text("\(index + 1). \(name)").font(.system(size: 15, weight: .semibold)).foregroundStyle(.white).lineLimit(1)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func stat(_ title: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title).font(.system(size: 12, weight: .bold)).foregroundStyle(.white.opacity(0.7))
            Text(value).font(.system(size: 24, weight: .black)).foregroundStyle(.white)
        }
    }
}
