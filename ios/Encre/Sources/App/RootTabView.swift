import SwiftUI

/// Coquille de l'app : vraie `TabView` système plutôt qu'une barre "verre
/// liquide" maison — depuis iOS 26, `TabView` rend déjà nativement en Liquid
/// Glass, et `tabViewBottomAccessory` est le mécanisme officiel pour un
/// mini-lecteur qui flotte au-dessus de la barre et partage son verre (celui
/// qu'utilisent Musique/Podcasts). Notre ancienne pastille maison ne pouvait
/// que l'imiter d'assez loin ; là, c'est le même rendu système.
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
        // barre de Musique/Podcasts — encore un comportement système plutôt
        // qu'une reproduction manuelle.
        .tabBarMinimizeBehavior(.onScrollDown)
        .tabViewBottomAccessory {
            if player.current != nil {
                MiniPlayerView(player: player) { showingPlayerSheet = true }
            }
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
