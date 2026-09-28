import SwiftUI

enum AppTab: Hashable {
    case home, library, search
}

/// Coquille de l'app : vraie `TabView` système (Liquid Glass natif,
/// onglet Recherche intégré à la barre), mini-lecteur flottant au-dessus,
/// et lecteur plein écran qui *grandit* depuis le mini-lecteur (transition
/// zoom système, fermeture interactive en glissant vers le bas).
struct RootTabView: View {
    @StateObject private var player = PlayerManager.shared
    @State private var selectedTab: AppTab = .home
    @State private var homePath = NavigationPath()
    @State private var libraryPath = NavigationPath()
    @State private var searchPath = NavigationPath()
    @State private var showingSettings = false
    @State private var showingOnboarding = false
    @State private var showingPlayer = false
    @Namespace private var zoomNamespace
    @Namespace private var playerNamespace

    var body: some View {
        TabView(selection: $selectedTab) {
            Tab("Écouter", systemImage: "play.circle.fill", value: AppTab.home) {
                tab(path: $homePath) { HomeView(path: $homePath) }
            }
            Tab("Bibliothèque", systemImage: "square.stack.fill", value: AppTab.library) {
                tab(path: $libraryPath) { LibraryView(path: $libraryPath) }
            }
            Tab(value: AppTab.search, role: .search) {
                tab(path: $searchPath) { SearchView(path: $searchPath) }
            } label: {
                Label("Rechercher", systemImage: "magnifyingglass")
            }
        }
        .tint(.white)
        .tabBarMinimizeBehavior(.onScrollDown)
        // Mini-lecteur en `safeAreaInset` plutôt qu'en
        // `tabViewBottomAccessory` : ce dernier laisse une pastille de verre
        // vide visible même sans morceau en cours.
        .safeAreaInset(edge: .bottom) {
            if player.current != nil {
                MiniPlayerView(player: player) { showingPlayer = true }
                    .matchedTransitionSource(id: "player", in: playerNamespace)
                    .padding(.horizontal, 14)
                    .padding(.bottom, 6)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
        }
        .animation(Motion.bouncy, value: player.current != nil)
        .environmentObject(player)
        .environment(\.zoomNamespace, zoomNamespace)
        .fullScreenCover(isPresented: $showingPlayer) {
            FullPlayerView(player: player, onOpenRoute: openRoute(_:))
                .navigationTransition(.zoom(sourceID: "player", in: playerNamespace))
        }
        .sheet(isPresented: $showingSettings) {
            NavigationStack { ServerSettingsView() }
                .presentationDetents([.medium, .large])
        }
        .fullScreenCover(isPresented: $showingOnboarding) {
            OnboardingView { showingOnboarding = false }
        }
        .task {
            if !APIConfig.shared.isConfigured { showingOnboarding = true }
        }
    }

    /// Ferme le lecteur plein écran et pousse la fiche sur la pile de
    /// l'onglet actif.
    private func openRoute(_ route: Route) {
        showingPlayer = false
        switch selectedTab {
        case .home: homePath.append(route)
        case .library: libraryPath.append(route)
        case .search: searchPath.append(route)
        }
    }

    @ViewBuilder
    private func tab<Content: View>(path: Binding<NavigationPath>, @ViewBuilder content: () -> Content) -> some View {
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
                        }
                    }
                    .zoomDestination(route)
                }
        }
        .environment(\.zoomNamespace, zoomNamespace)
    }
}
