import SwiftUI

/// Coquille de l'app : vraie `TabView` système (Liquid Glass natif depuis
/// iOS 26) plutôt qu'une barre "verre liquide" maison.
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
        TabView(selection: $selectedTab) {
            Tab("Écouter", systemImage: "house.fill", value: AppTab.home) {
                tab(path: $homePath) { HomeView(path: $homePath) }
            }
            Tab("Bibliothèque", systemImage: "books.vertical.fill", value: AppTab.library) {
                tab(path: $libraryPath) { LibraryView(path: $libraryPath) }
            }
            // `role: .search` : traitement spécial natif du dernier onglet
            // (champ de recherche intégré à la barre elle-même) — le même
            // que Musique, Podcasts ou l'App Store depuis iOS 26.
            Tab(value: AppTab.search, role: .search) {
                tab(path: $searchPath) { SearchView(path: $searchPath) }
            } label: {
                Label("Rechercher", systemImage: "magnifyingglass")
            }
        }
        .tint(EncreColor.spot)
        // Rétrécit en un bouton rond au défilement vers le bas, comme la
        // barre de Musique/Podcasts.
        .tabBarMinimizeBehavior(.onScrollDown)
        // `.tabViewBottomAccessory` (le mécanisme natif du mini-lecteur
        // fusionné à la barre) laissait une pastille de verre vide visible
        // même sans morceau en cours — le système semble réserver le
        // conteneur dès qu'une closure est fournie, contenu vide ou non.
        // `.safeAreaInset` avec notre propre verre (`glassCapsule`, vrai
        // `glassEffect()` système) donne le même résultat visuel sans cette
        // pastille fantôme : rien de dessiné tant que `player.current` est
        // `nil`.
        .safeAreaInset(edge: .bottom) {
            if player.current != nil {
                MiniPlayerView(player: player) { showingPlayerSheet = true }
                    .padding(.horizontal, 16)
                    .padding(.bottom, 6)
            }
        }
        .animation(.spring(duration: 0.35), value: player.current?.id)
        .environmentObject(player)
        .sheet(isPresented: $showingPlayerSheet) {
            NowPlayingSheet(player: player, onOpenRoute: openRoute(_:))
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

    /// Ferme le lecteur plein écran et pousse la destination sur la pile de
    /// l'onglet actif — plutôt que de donner au lecteur sa propre pile de
    /// navigation imbriquée dans la feuille, source de complexité pour un
    /// gain nul (fermer la feuille pour voir la fiche est un geste naturel).
    private func openRoute(_ route: Route) {
        showingPlayerSheet = false
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
