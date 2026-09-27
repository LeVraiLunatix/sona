import SwiftUI

/// Coquille à onglets. Version simplifiée de la barre "verre liquide" qui se
/// replie en bulle du prototype (Encre.dc.html) — la fusion animée avec le
/// mini-lecteur et le lecteur plein écran est prévue pour une étape
/// suivante ; pour l'instant, un `TabView` natif et une barre de lecture
/// posée juste au-dessus.
struct RootTabView: View {
    @StateObject private var player = PlayerManager.shared
    @State private var homePath = NavigationPath()
    @State private var libraryPath = NavigationPath()
    @State private var searchPath = NavigationPath()
    @State private var showingSettings = false
    @State private var showingPlayerSheet = false

    var body: some View {
        ZStack(alignment: .bottom) {
            TabView {
                tab(path: $homePath) { HomeView(path: $homePath) }
                    .tabItem { Label("Écouter", systemImage: "house") }

                tab(path: $libraryPath) { LibraryView(path: $libraryPath) }
                    .tabItem { Label("Bibliothèque", systemImage: "books.vertical") }

                tab(path: $searchPath) { SearchView(path: $searchPath) }
                    .tabItem { Label("Rechercher", systemImage: "magnifyingglass") }
            }
            .tint(EncreColor.spot)

            if player.current != nil {
                MiniPlayerView(player: player) { showingPlayerSheet = true }
                    .padding(.horizontal, 16)
                    .padding(.bottom, 58)
            }
        }
        .environmentObject(player)
        .sheet(isPresented: $showingPlayerSheet) {
            NowPlayingSheet(player: player)
        }
        .toolbarBackground(.hidden, for: .tabBar)
        .task {
            if !APIConfig.shared.isConfigured { showingSettings = true }
        }
        .sheet(isPresented: $showingSettings) {
            NavigationStack { ServerSettingsView() }
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
