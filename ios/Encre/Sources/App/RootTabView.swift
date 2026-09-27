import SwiftUI

/// Coquille de l'app : bascule entre les 3 onglets avec une barre "verre
/// liquide" maison (voir `EncreTabBar`) plutôt que le chrome natif d'un
/// `TabView`, et une pastille de mini-lecteur posée juste au-dessus quand un
/// morceau joue. La fusion animée des deux (repli en bulle au défilement)
/// reste une prochaine étape — voir le README.
struct RootTabView: View {
    @StateObject private var player = PlayerManager.shared
    @State private var selectedTab: AppTab = .home
    @State private var homePath = NavigationPath()
    @State private var libraryPath = NavigationPath()
    @State private var searchPath = NavigationPath()
    @State private var showingSettings = false
    @State private var showingOnboarding = false
    @State private var showingPlayerSheet = false

    var body: some View {
        ZStack(alignment: .bottom) {
            // Les 3 onglets restent montés en permanence, seule l'opacité
            // change — comme `vis(k)` dans le prototype (Encre.dc.html).
            // Un `switch` qui démonterait l'onglet inactif perdrait le
            // défilement et redéclencherait tous ses appels réseau à chaque
            // retour dessus.
            ZStack {
                tab(path: $homePath) { HomeView(path: $homePath) }
                    .opacity(selectedTab == .home ? 1 : 0)
                    .allowsHitTesting(selectedTab == .home)
                tab(path: $libraryPath) { LibraryView(path: $libraryPath) }
                    .opacity(selectedTab == .library ? 1 : 0)
                    .allowsHitTesting(selectedTab == .library)
                tab(path: $searchPath) { SearchView(path: $searchPath) }
                    .opacity(selectedTab == .search ? 1 : 0)
                    .allowsHitTesting(selectedTab == .search)
            }

            VStack(spacing: 10) {
                if player.current != nil {
                    MiniPlayerView(player: player) { showingPlayerSheet = true }
                }
                EncreTabBar(selected: $selectedTab)
            }
            .padding(.horizontal, 16)
            .padding(.bottom, 6)
        }
        .environmentObject(player)
        .sheet(isPresented: $showingPlayerSheet) {
            NowPlayingSheet(player: player)
        }
        .sheet(isPresented: $showingSettings) {
            NavigationStack { ServerSettingsView() }
        }
        .fullScreenCover(isPresented: $showingOnboarding) {
            OnboardingView { showingOnboarding = false }
        }
        .task {
            if !APIConfig.shared.isConfigured { showingOnboarding = true }
        }
    }

    @ViewBuilder
    private func tab<Content: View>(path: Binding<NavigationPath>, @ViewBuilder content: () -> Content) -> some View {
        NavigationStack(path: path) {
            content()
                .toolbar {
                    ToolbarItem(placement: .topBarTrailing) {
                        Button { showingSettings = true } label: {
                            Image(systemName: "gearshape").foregroundStyle(EncreColor.text)
                        }
                    }
                }
                .navigationDestination(for: Route.self) { route in
                    switch route {
                    case .album(let source, let id):
                        AlbumDetailView(source: source, id: id, path: path)
                    case .artist(let source, let id):
                        ArtistDetailView(source: source, id: id, path: path)
                    }
                }
        }
    }
}
