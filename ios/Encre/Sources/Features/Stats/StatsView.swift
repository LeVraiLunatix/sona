import Charts
import SwiftUI

/// Onglet Stats : un « Wrapped » permanent, pour n'importe quelle période
/// (jour, semaine, mois, année, depuis toujours), calculé côté serveur à
/// partir des écoutes réelles (voir `Scrobbler`) et, si configuré, de
/// l'historique Last.fm importé.
struct StatsView: View {
    @StateObject private var viewModel = StatsViewModel()
    @EnvironmentObject private var player: PlayerManager
    @Binding var path: NavigationPath
    @State private var chartsVisible = false
    @State private var openingTrackId: String?
    @State private var recap: RecapLaunch?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 30) {
                LiveStatsSection()
                    .padding(.horizontal, 20)
                    .reveal(0)

                recapCard
                    .padding(.horizontal, 20)
                    .reveal(1)

                periodControls

                if let report = viewModel.report {
                    if report.plays == 0 {
                        EmptyState(
                            systemImage: "chart.bar",
                            title: "Aucune écoute \(report.period == "all" ? "pour l'instant" : "sur cette période")",
                            message: "Chaque morceau écouté au moins à moitié (ou 4 min) compte ici, comme sur Last.fm."
                        )
                        .reveal(0)
                    } else {
                        content(report)
                    }
                } else if viewModel.isLoading {
                    ProgressView().tint(.white).frame(maxWidth: .infinity).padding(.top, 80)
                }

                if let message = viewModel.errorMessage {
                    Text(message).font(Typo.rowSubtitle).foregroundStyle(Tone.danger).padding(.horizontal, 20)
                }

                lastfmCard
            }
            .padding(.top, 8)
            .padding(.bottom, 24)
        }
        .scrollIndicators(.hidden)
        .background(Tone.background)
        .navigationTitle("Stats")
        .navigationBarTitleDisplayMode(.large)
        .toolbar {
            ToolbarItem(placement: .topBarLeading) {
                NavigationLink { RecentPlaysView() } label: { Image(systemName: "clock.arrow.circlepath") }
            }
            ToolbarItem(placement: .topBarTrailing) {
                Button {
                    // La période affichée, en story (jour et « tout » : le mois).
                    switch viewModel.period {
                    case .week, .month, .year: recap = RecapLaunch(period: viewModel.period.rawValue, offset: viewModel.offset)
                    default: recap = RecapLaunch(period: "month", offset: 0)
                    }
                } label: {
                    Image(systemName: "sparkles")
                }
            }
        }
        .fullScreenCover(item: $recap) { launch in
            RecapView(period: launch.period, offset: launch.offset)
        }
        .task { await viewModel.load() }
        .refreshable { await viewModel.load() }
        .onChange(of: viewModel.report) { _, _ in replayCharts() }
    }

    // MARK: - Récap

    /// Début de mois : le récap du mois écoulé ; sinon celui du mois en cours.
    private var recapCard: some View {
        let day = Calendar.current.component(.day, from: Date())
        let lastMonth = day <= 7
        let reference = Calendar.current.date(byAdding: .month, value: lastMonth ? -1 : 0, to: Date()) ?? Date()
        let month = reference.formatted(.dateTime.month(.wide))
        return Button {
            recap = RecapLaunch(period: "month", offset: lastMonth ? -1 : 0)
        } label: {
            HStack(spacing: 14) {
                Image(systemName: "sparkles")
                    .font(.system(size: 22, weight: .bold))
                    .foregroundStyle(.white)
                    .symbolEffect(.pulse, options: .repeating)
                VStack(alignment: .leading, spacing: 2) {
                    Text(lastMonth ? "Ton récap de \(month) est prêt" : "Ton récap de \(month) (en cours)")
                        .font(Typo.headline).foregroundStyle(.white)
                    Text("Tes tops, ton profil d'écoute, ta place parmi tes amis")
                        .font(Typo.caption).foregroundStyle(.white.opacity(0.8)).lineLimit(1)
                }
                Spacer()
                Image(systemName: "play.fill").foregroundStyle(.white)
            }
            .padding(16)
            .background(
                RoundedRectangle(cornerRadius: 20, style: .continuous)
                    .fill(LinearGradient(colors: [Color(red: 0.55, green: 0.2, blue: 0.95), Color(red: 0.95, green: 0.3, blue: 0.5)],
                                         startPoint: .leading, endPoint: .trailing))
            )
        }
        .buttonStyle(.pressable(scale: 0.98))
    }

    // MARK: - Période

    private var periodControls: some View {
        VStack(spacing: 14) {
            Picker("Période", selection: $viewModel.period) {
                ForEach(StatsPeriod.allCases) { period in
                    Text(period.label).tag(period)
                }
            }
            .pickerStyle(.segmented)
            .sensoryFeedback(.selection, trigger: viewModel.period)

            HStack {
                stepButton("chevron.left", enabled: viewModel.canGoBack) { viewModel.step(-1) }
                Spacer()
                Text(viewModel.report?.label ?? " ")
                    .font(Typo.headline)
                    .foregroundStyle(Tone.primary)
                    .contentTransition(.opacity)
                    .animation(Motion.snappy, value: viewModel.report?.label)
                Spacer()
                stepButton("chevron.right", enabled: viewModel.canGoForward && viewModel.canGoBack) { viewModel.step(1) }
            }
            .sensoryFeedback(.impact(weight: .light), trigger: viewModel.offset)
        }
        .padding(.horizontal, 20)
    }

    private func stepButton(_ icon: String, enabled: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: icon)
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(enabled ? Tone.primary : Tone.tertiary)
                .frame(width: 36, height: 36)
                .background(Circle().fill(Tone.surface))
        }
        .buttonStyle(.pressable(scale: 0.85))
        .disabled(!enabled)
        .opacity(enabled ? 1 : 0.4)
    }

    // MARK: - Contenu

    @ViewBuilder
    private func content(_ report: StatsReport) -> some View {
        hero(report).padding(.horizontal, 20).reveal(0)
        metrics(report).padding(.horizontal, 20).reveal(1)
        timeline(report).padding(.horizontal, 20).reveal(2)
        if !report.topArtists.isEmpty { topArtists(report.topArtists).reveal(3) }
        if !report.topTracks.isEmpty { topTracks(report.topTracks).padding(.horizontal, 20).reveal(4) }
        if !report.topAlbums.isEmpty { topAlbums(report.topAlbums).reveal(5) }
        habits(report).padding(.horizontal, 20).reveal(6)
        if !report.discoveries.isEmpty { discoveries(report.discoveries).reveal(7) }
    }

    /// Le chiffre roi : temps d'écoute, qui défile jusqu'à sa valeur, et
    /// l'évolution par rapport à la période précédente.
    private func hero(_ report: StatsReport) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("TEMPS D'ÉCOUTE")
                .font(Typo.caption)
                .tracking(1.5)
                .foregroundStyle(Tone.secondary)
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(chartsVisible ? Self.durationValue(report.minutes) : "0")
                    .font(.system(size: 64, weight: .bold))
                    .foregroundStyle(Tone.primary)
                    .contentTransition(.numericText(value: Double(chartsVisible ? report.minutes : 0)))
                Text(Self.durationUnit(report.minutes))
                    .font(.system(size: 24, weight: .semibold))
                    .foregroundStyle(Tone.secondary)
            }
            if report.period != "all", let delta = Self.delta(report.plays, report.previousPlays) {
                HStack(spacing: 4) {
                    Image(systemName: delta >= 0 ? "arrow.up.right" : "arrow.down.right")
                    Text("\(abs(delta)) % d'écoutes vs la période précédente")
                }
                .font(Typo.rowSubtitle)
                .foregroundStyle(Tone.secondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(22)
        .background(
            ZStack {
                RoundedRectangle(cornerRadius: 24, style: .continuous).fill(Tone.surface)
                // Halo discret qui grandit avec le temps d'écoute de la période.
                RadialGradient(
                    colors: [Color(red: 0.45, green: 0.35, blue: 1).opacity(0.45), .clear],
                    center: .topTrailing, startRadius: 10, endRadius: chartsVisible ? 260 : 60
                )
                .clipShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
                .animation(.easeOut(duration: 1.2), value: chartsVisible)
            }
        )
    }

    private func metrics(_ report: StatsReport) -> some View {
        LazyVGrid(columns: [GridItem(.flexible(), spacing: 12), GridItem(.flexible(), spacing: 12)], spacing: 12) {
            metric("Écoutes", report.plays, icon: "play.fill")
            metric("Artistes", report.artists, icon: "person.2.fill")
            metric("Titres", report.tracks, icon: "music.note")
            metric("Série", report.streakDays, icon: "flame.fill", suffix: report.streakDays > 1 ? " jours" : " jour")
        }
    }

    private func metric(_ title: String, _ value: Int, icon: String, suffix: String = "") -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Image(systemName: icon).font(.system(size: 13, weight: .semibold)).foregroundStyle(Tone.tertiary)
            HStack(alignment: .firstTextBaseline, spacing: 0) {
                Text("\(chartsVisible ? value : 0)")
                    .font(.system(size: 28, weight: .bold))
                    .foregroundStyle(Tone.primary)
                    .contentTransition(.numericText(value: Double(chartsVisible ? value : 0)))
                Text(suffix).font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
            }
            Text(title).font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16)
        .background(RoundedRectangle(cornerRadius: 18, style: .continuous).fill(Tone.surface))
    }

    /// Courbe de la période : les barres poussent depuis zéro à chaque
    /// changement de période.
    private func timeline(_ report: StatsReport) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionHeader(title: "Au fil du temps")
            Chart(Array(report.timeline.enumerated()), id: \.offset) { _, bucket in
                BarMark(
                    x: .value("Période", bucket.label),
                    y: .value("Écoutes", chartsVisible ? bucket.plays : 0)
                )
                .foregroundStyle(
                    LinearGradient(
                        colors: [Color(red: 0.55, green: 0.45, blue: 1), .white],
                        startPoint: .bottom, endPoint: .top
                    )
                )
                .cornerRadius(4)
            }
            .chartYAxis {
                AxisMarks(position: .leading) { _ in
                    AxisGridLine().foregroundStyle(Tone.separator)
                    AxisValueLabel().foregroundStyle(Tone.tertiary)
                }
            }
            .chartXAxis {
                AxisMarks(values: .automatic(desiredCount: report.timeline.count > 12 ? 6 : report.timeline.count)) { _ in
                    AxisValueLabel().foregroundStyle(Tone.tertiary)
                }
            }
            .frame(height: 190)
        }
    }

    private func topArtists(_ artists: [RankedStat]) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionHeader(title: "Top artistes").padding(.horizontal, 20)
            if let first = artists.first {
                topArtistCard(first).padding(.horizontal, 20)
            }
            if artists.count > 1 {
                Carousel(items: Array(artists.dropFirst().prefix(15)), spacing: 16) { artist in
                    let rank = (artists.firstIndex(of: artist) ?? 0) + 1
                    VStack(spacing: 6) {
                        ArtistBubble(name: artist.name, pictureURL: artist.coverURL, route: artistRoute(artist), size: 96) {
                            if let route = artistRoute(artist) { path.append(route) }
                        }
                        Text("#\(rank) · \(artist.plays) écoute\(artist.plays > 1 ? "s" : "")")
                            .font(Typo.caption)
                            .foregroundStyle(Tone.tertiary)
                    }
                }
            }
        }
    }

    /// Artiste n°1 : grande carte, photo réelle chargée depuis sa fiche.
    private func topArtistCard(_ artist: RankedStat) -> some View {
        Button {
            if let route = artistRoute(artist) { path.append(route) }
        } label: {
            ZStack(alignment: .bottomLeading) {
                ArtistPicture(source: artist.source, id: artist.sourceId, fallback: artist.coverURL)
                    .frame(height: 220)
                LinearGradient(colors: [.clear, .black.opacity(0.85)], startPoint: .center, endPoint: .bottom)
                    .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
                VStack(alignment: .leading, spacing: 4) {
                    Text("N°1").font(Typo.caption).tracking(1.5).foregroundStyle(Tone.secondary)
                    Text(artist.name).font(Typo.largeTitle).foregroundStyle(Tone.primary).lineLimit(2)
                    Text("\(artist.plays) écoutes · \(Self.durationValue(artist.minutes)) \(Self.durationUnit(artist.minutes))")
                        .font(Typo.rowSubtitle)
                        .foregroundStyle(Tone.secondary)
                }
                .padding(20)
            }
        }
        .buttonStyle(.pressable(scale: 0.97))
        .disabled(artistRoute(artist) == nil)
    }

    private func topTracks(_ tracks: [RankedStat]) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(title: "Top titres")
            LazyVStack(spacing: 2) {
                ForEach(Array(tracks.prefix(10).enumerated()), id: \.element.id) { index, item in
                    Button { play(item) } label: {
                        HStack(spacing: 14) {
                            Text("\(index + 1)")
                                .font(.system(size: 17, weight: .bold))
                                .foregroundStyle(index < 3 ? Tone.primary : Tone.tertiary)
                                .frame(width: 26)
                                .monospacedDigit()
                            Artwork(url: item.coverURL, cornerRadius: 6).frame(width: 48, height: 48)
                            VStack(alignment: .leading, spacing: 3) {
                                Text(item.name).font(Typo.rowTitle).foregroundStyle(Tone.primary).lineLimit(1)
                                Text(item.subtitle ?? "").font(Typo.rowSubtitle).foregroundStyle(Tone.secondary).lineLimit(1)
                            }
                            Spacer(minLength: 8)
                            if openingTrackId == item.id {
                                ProgressView().tint(.white)
                            } else {
                                Text("\(item.plays)")
                                    .font(Typo.mono)
                                    .foregroundStyle(Tone.tertiary)
                            }
                        }
                        .padding(.vertical, 6)
                    }
                    .buttonStyle(.pressable(scale: 0.98))
                    .disabled(item.sourceId == nil)
                }
            }
        }
    }

    private func topAlbums(_ albums: [RankedStat]) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionHeader(title: "Top albums").padding(.horizontal, 20)
            Carousel(items: Array(albums.prefix(15))) { album in
                Button {
                    if let source = album.source, let id = album.sourceId {
                        path.append(Route.album(source: source, id: id))
                    }
                } label: {
                    VStack(alignment: .leading, spacing: 8) {
                        Artwork(url: album.coverURL, cornerRadius: 10, symbol: "square.stack")
                            .frame(width: 150, height: 150)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(album.name).font(Typo.rowTitle).foregroundStyle(Tone.primary).lineLimit(1)
                            Text("\(album.subtitle ?? "") · \(album.plays)")
                                .font(Typo.rowSubtitle).foregroundStyle(Tone.secondary).lineLimit(1)
                        }
                    }
                    .frame(width: 150, alignment: .leading)
                }
                .buttonStyle(.pressable)
            }
        }
    }

    /// Habitudes : à quelle heure et quel jour on écoute le plus.
    private func habits(_ report: StatsReport) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            SectionHeader(title: "Tes habitudes")
            if let hour = report.topHour, let day = report.topWeekday {
                Text("Surtout vers \(hour) h, et le \(day) plus que les autres jours.")
                    .font(Typo.body)
                    .foregroundStyle(Tone.secondary)
            }
            Chart(Array(report.hours.enumerated()), id: \.offset) { hour, count in
                BarMark(
                    x: .value("Heure", Double(hour)),
                    y: .value("Écoutes", chartsVisible ? count : 0),
                    width: .ratio(0.7)
                )
                .foregroundStyle(hour == report.topHour ? Color.white : Color.white.opacity(0.35))
                .cornerRadius(3)
            }
            .chartXScale(domain: -0.5...23.5)
            .chartXAxis {
                AxisMarks(values: [0.0, 6.0, 12.0, 18.0, 23.0]) { value in
                    AxisValueLabel {
                        if let hour = value.as(Double.self) { Text("\(Int(hour)) h").foregroundStyle(Tone.tertiary) }
                    }
                }
            }
            .chartYAxis(.hidden)
            .frame(height: 120)
        }
    }

    private func discoveries(_ artists: [RankedStat]) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            SectionHeader(title: "Découvertes").padding(.horizontal, 20)
            Text("Artistes écoutés pour la première fois sur cette période.")
                .font(Typo.rowSubtitle)
                .foregroundStyle(Tone.secondary)
                .padding(.horizontal, 20)
            Carousel(items: artists, spacing: 16) { artist in
                ArtistBubble(name: artist.name, pictureURL: artist.coverURL, route: artistRoute(artist), size: 90) {
                    if let route = artistRoute(artist) { path.append(route) }
                }
            }
        }
    }

    // MARK: - Last.fm

    @ViewBuilder
    private var lastfmCard: some View {
        if let status = viewModel.importStatus, status.configured {
            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 10) {
                    Image(systemName: "clock.arrow.2.circlepath")
                        .font(.system(size: 18, weight: .semibold))
                        .foregroundStyle(Tone.primary)
                    Text("Historique Last.fm").font(Typo.headline).foregroundStyle(Tone.primary)
                }
                if status.running {
                    ProgressView(value: Double(status.page), total: Double(max(status.totalPages, 1)))
                        .tint(.white)
                    Text("Import en cours… \(status.imported) écoutes ajoutées")
                        .font(Typo.rowSubtitle).foregroundStyle(Tone.secondary)
                } else {
                    Text(status.finishedAt == nil
                         ? "Ajoute tes écoutes passées sur Last.fm à tes stats. Relançable : seules les nouvelles sont importées."
                         : "Dernier import : \(status.imported) nouvelles écoutes.\(status.error.map { " \($0)" } ?? "")")
                        .font(Typo.rowSubtitle).foregroundStyle(status.error == nil ? Tone.secondary : Tone.danger)
                    PillButton(title: status.finishedAt == nil ? "Importer" : "Mettre à jour", systemImage: "arrow.down.circle", kind: .secondary) {
                        Task { await viewModel.startImport() }
                    }
                }
            }
            .padding(18)
            .background(RoundedRectangle(cornerRadius: 20, style: .continuous).fill(Tone.surface))
            .padding(.horizontal, 20)
            .animation(Motion.smooth, value: status)
        }
    }

    // MARK: - Actions

    private func artistRoute(_ artist: RankedStat) -> Route? {
        guard let source = artist.source, let id = artist.sourceId else { return nil }
        return .artist(source: source, id: id)
    }

    private func play(_ item: RankedStat) {
        guard let source = item.source, let id = item.sourceId else { return }
        openingTrackId = item.id
        Task {
            if let track = try? await APIClient.shared.track(source: source, id: id) {
                player.play(track)
            }
            openingTrackId = nil
        }
    }

    private func replayCharts() {
        chartsVisible = false
        withAnimation(Motion.smooth.delay(0.1)) { chartsVisible = true }
    }

    // MARK: - Formats

    static func durationValue(_ minutes: Int) -> String {
        minutes >= 120 ? "\(minutes / 60)" : "\(minutes)"
    }

    static func durationUnit(_ minutes: Int) -> String {
        minutes >= 120 ? "h" : "min"
    }

    static func delta(_ current: Int, _ previous: Int) -> Int? {
        guard previous > 0 else { return nil }
        return Int(((Double(current) - Double(previous)) / Double(previous) * 100).rounded())
    }
}

/// Photo d'un artiste chargée depuis sa fiche (les stats ne connaissent que
/// la pochette d'un de ses titres), mise en cache pour la session.
struct ArtistPicture: View {
    let source: String?
    let id: String?
    let fallback: String?
    @State private var url: String?

    @MainActor private static var cache: [String: String] = [:]

    var body: some View {
        Artwork(url: url ?? fallback, cornerRadius: 20, symbol: "person.fill")
            .task(id: id) { await load() }
    }

    private func load() async {
        guard let source, let id else { return }
        let key = "\(source):\(id)"
        if let cached = Self.cache[key] {
            url = cached
            return
        }
        if let artist = try? await APIClient.shared.artist(source: source, id: id), let picture = artist.pictureURL {
            Self.cache[key] = picture
            url = picture
        }
    }
}

/// Ouverture du récap en story.
struct RecapLaunch: Identifiable {
    let period: String
    let offset: Int
    var id: String { "\(period)\(offset)" }
}
