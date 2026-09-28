import Combine
import SwiftUI
import UIKit

enum AppTab: Hashable {
    case home, library, stats, search
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
    @State private var statsPath = NavigationPath()
    @State private var searchPath = NavigationPath()
    @State private var showingSettings = false
    @State private var showingOnboarding = false
    @State private var showingPlayer = false
    @State private var keyboardVisible = false
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
            Tab("Stats", systemImage: "chart.bar.fill", value: AppTab.stats) {
                tab(.stats, path: $statsPath) { StatsView(path: $statsPath) }
            }
            Tab(value: AppTab.search, role: .search) {
                tab(.search, path: $searchPath) { SearchView(path: $searchPath) }
            } label: {
                Label("Rechercher", systemImage: "magnifyingglass")
            }
        }
        .tint(.white)
        .environmentObject(player)
        .environment(\.zoomNamespace, zoomNamespace)
        .fullScreenCover(isPresented: $showingPlayer) {
            FullPlayerView(player: player, onOpenRoute: openRoute(_:))
                .navigationTransition(.zoom(sourceID: playerSourceID(selectedTab), in: playerNamespace))
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
            // Écoutes restées en attente (hors connexion au dernier usage).
            await Scrobbler.shared.flush()
        }
        .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardWillShowNotification)) { _ in
            keyboardVisible = true
        }
        .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardWillHideNotification)) { _ in
            keyboardVisible = false
        }
    }

    /// Un mini-lecteur par onglet (chacun sous sa propre pile) : chacun sa
    /// source de zoom, pour que le lecteur grandisse depuis celui qui est
    /// réellement à l'écran.
    private func playerSourceID(_ tab: AppTab) -> String {
        switch tab {
        case .home: "player-home"
        case .library: "player-library"
        case .stats: "player-stats"
        case .search: "player-search"
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
                        }
                    }
                    .zoomDestination(route)
                }
        }
        // Posé sur la pile de l'onglet (et non sur la `TabView`) : la zone
        // sûre du contenu d'un onglet s'arrête déjà au-dessus de la barre
        // d'onglets, le mini-lecteur s'y pose donc au lieu de la recouvrir.
        // Caché pendant la saisie : il masquait le champ de recherche et le
        // clavier.
        .safeAreaInset(edge: .bottom, spacing: 0) {
            if player.current != nil && !keyboardVisible {
                MiniPlayerView(player: player) { showingPlayer = true }
                    .matchedTransitionSource(id: playerSourceID(tab), in: playerNamespace)
                    .padding(.horizontal, 14)
                    .padding(.bottom, 8)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
        }
        .animation(Motion.bouncy, value: player.current != nil && !keyboardVisible)
        .environment(\.zoomNamespace, zoomNamespace)
    }
}
