import Combine
import SwiftUI
import UIKit

enum AppTab: Hashable {
    case home, library, friends, stats, search
}

/// Coquille de l'app : vraie `TabView` système (Liquid Glass natif,
/// onglet Recherche intégré à la barre), mini-lecteur en accessoire de la
/// barre d'onglets (comme Musique : le système lui réserve sa place, rien
/// ne passe dessous, et il se range dans la barre quand on fait défiler),
/// et lecteur plein écran qui *grandit* depuis le mini-lecteur (transition
/// zoom système, fermeture interactive en glissant vers le bas).
struct RootTabView: View {
    @StateObject private var player = PlayerManager.shared
    @State private var selectedTab: AppTab

    init(startTab: AppTab = .home) {
        _selectedTab = State(initialValue: startTab)
    }
    @State private var homePath = NavigationPath()
    @State private var libraryPath = NavigationPath()
    @State private var statsPath = NavigationPath()
    @State private var friendsPath = NavigationPath()
    @State private var searchPath = NavigationPath()
    @State private var showingSettings = false
    @State private var showingPlayer = false
    @State private var playlistPick: PlaylistPickRequest?
    // Ouvertures depuis les widgets (liens `encre://`).
    @State private var showingBlindTest = false
    @State private var showingParty = false
    @State private var recap: RecapLaunch?
    @State private var live: LiveLaunch?
    @Namespace private var zoomNamespace
    @Namespace private var playerNamespace

    var body: some View {
        TabView(selection: $selectedTab) {
            Tab("Écouter", systemImage: "play.circle.fill", value: AppTab.home) {
                tab(.home, path: $homePath) { HomeView(path: $homePath) }
            }
            Tab("Bibliothèque", systemImage: "square.stack.fill", value: AppTab.library) {
                tab(.library, path: $libraryPath) { LibraryView(path: $libraryPath) }
            }
            Tab("Amis", systemImage: "person.2.fill", value: AppTab.friends) {
                tab(.friends, path: $friendsPath) { FriendsView(path: $friendsPath) }
            }
            Tab("Stats", systemImage: "chart.bar.fill", value: AppTab.stats) {
                tab(.stats, path: $statsPath) { StatsView(path: $statsPath) }
            }
            Tab(value: AppTab.search, role: .search) {
                tab(.search, path: $searchPath) { SearchView(path: $searchPath) }
            } label: {
                Label("Rechercher", systemImage: "magnifyingglass")
            }
        }
        .tabViewBottomAccessory(isEnabled: player.current != nil) {
            MiniPlayerView(player: player) { showingPlayer = true }
                .matchedTransitionSource(id: "player", in: playerNamespace)
        }
        .tabBarMinimizeBehavior(.onScrollDown)
        .tint(.white)
        .environmentObject(player)
        .environment(\.zoomNamespace, zoomNamespace)
        .fullScreenCover(isPresented: $showingPlayer) {
            FullPlayerView(player: player, onOpenRoute: openRoute(_:))
                .navigationTransition(.zoom(sourceID: "player", in: playerNamespace))
        }
        .environment(\.addToPlaylist, AddToPlaylistAction { playlistPick = PlaylistPickRequest(tracks: $0) })
        .sheet(item: $playlistPick) { request in
            AddToPlaylistSheet(tracks: request.tracks)
        }
        .sheet(isPresented: $showingSettings) {
            NavigationStack { SettingsView() }
                .environmentObject(AuthManager.shared)
        }
        .fullScreenCover(isPresented: $showingBlindTest) {
            BlindTestView()
        }
        .fullScreenCover(item: $recap) { launch in
            RecapView(period: launch.period, offset: launch.offset)
        }
        .sheet(isPresented: $showingParty) {
            PartyView().environmentObject(player)
        }
        .fullScreenCover(item: $live) { launch in
            BlindLiveView(joinCode: launch.code)
        }
        .onOpenURL { url in open(url) }
        .task {
            // Écoutes restées en attente (hors connexion au dernier usage).
            await Scrobbler.shared.flush()
        }
        .task { await NotificationManager.shared.start() }
        .task {
            // Le dernier titre, en pause, prêt à reprendre où on l'avait laissé.
            player.restoreSession()
            HeadGestures.shared.startIfEnabled()
        }
    }

    /// Liens `encre://…` des widgets, de la Live Activity et des notifications.
    private func open(_ url: URL) {
        guard url.scheme == "encre" else { return }
        showingPlayer = false
        showingSettings = false
        let query = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
        let code = query.first { $0.name == "code" }?.value
        switch url.host() {
        case "blindtest":
            showingBlindTest = true
        case "recap":
            // Dernière semaine ou dernier mois terminés.
            let period = query.first { $0.name == "period" }?.value == "week" ? "week" : "month"
            recap = RecapLaunch(period: period, offset: -1)
        case "live":
            if let code { live = LiveLaunch(code: code) }
        case "album":
            if let source = query.first(where: { $0.name == "source" })?.value,
               let id = query.first(where: { $0.name == "id" })?.value {
                selectedTab = .home
                homePath.append(Route.album(source: source, id: id))
            }
        case "party":
            if let code {
                Task {
                    await PartyManager.shared.join(code: code)
                    showingParty = true
                }
            } else {
                showingParty = true
            }
        case "player":
            if player.current != nil { showingPlayer = true }
        case "djradio":
            if let track = player.current {
                Task { try? await player.playDJRadio(from: track) }
                showingPlayer = true
            } else {
                selectedTab = .home
            }
        default:
            break
        }
    }

    /// Ferme le lecteur plein écran et pousse la fiche sur la pile de
    /// l'onglet actif.
    private func openRoute(_ route: Route) {
        showingPlayer = false
        switch selectedTab {
        case .home: homePath.append(route)
        case .library: libraryPath.append(route)
        case .stats: statsPath.append(route)
        case .friends: friendsPath.append(route)
        case .search: searchPath.append(route)
        }
    }

    @ViewBuilder
    private func tab<Content: View>(_ tab: AppTab, path: Binding<NavigationPath>, @ViewBuilder content: () -> Content) -> some View {
        NavigationStack(path: path) {
            content()
                .toolbar {
                    ToolbarItem(placement: .topBarTrailing) {
                        Button { showingSettings = true } label: {
                            Image(systemName: "gearshape")
                        }
                    }
                }
                .navigationDestination(for: Route.self) { route in
                    Group {
                        switch route {
                        case .album(let source, let id):
                            AlbumDetailView(source: source, id: id, path: path)
                        case .playlist(let source, let id):
                            AlbumDetailView(source: source, id: id, isPlaylist: true, path: path)
                        case .artist(let source, let id):
                            ArtistDetailView(source: source, id: id, path: path)
                        case .userPlaylist(let id):
                            UserPlaylistView(playlistId: id, path: path)
                        case .downloads:
                            DownloadsView(path: path)
                        case .mix(let id):
                            MixDetailView(mixId: id, path: path)
                        case .friend(let accountId):
                            FriendProfileView(accountId: accountId, path: path)
                        case .concerts:
                            ConcertsView()
                        }
                    }
                    .zoomDestination(route)
                }
        }
        .environment(\.zoomNamespace, zoomNamespace)
    }
}
