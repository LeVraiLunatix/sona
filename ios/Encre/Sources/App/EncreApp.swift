import SwiftUI

@main
struct EncreApp: App {
    init() {
        // Pochettes et photos d'artistes rechargées sans cesse en défilant :
        // un cache HTTP généreux (mémoire + disque) rend les listes fluides
        // et les allers-retours instantanés.
        URLCache.shared = URLCache(memoryCapacity: 64 * 1024 * 1024, diskCapacity: 300 * 1024 * 1024)
        // Téléchargements intelligents de la nuit : à déclarer avant la fin
        // du lancement, sinon iOS refuse la tâche.
        SmartDownloads.registerBackgroundTask()
        // Notifications (récaps, défi du jour, parties des amis).
        NotificationManager.registerBackgroundTask()
        NotificationManager.shared.setUp()
    }

    var body: some Scene {
        WindowGroup {
            AppGate()
                .preferredColorScheme(.dark)
        }
    }
}

/// Aiguillage selon le compte : connexion, attente de validation par un
/// admin, accès refusé, ou l'app elle-même.
struct AppGate: View {
    @StateObject private var auth = AuthManager.shared
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        ZStack {
            switch auth.state {
            case .checking:
                Tone.background.ignoresSafeArea()
                ProgressView().tint(.white)
            case .signedOut:
                LoginView().transition(.opacity)
            case .unreachable(let message):
                if auth.offline {
                    // Hors ligne : l'app quand même, pour les téléchargements.
                    RootTabView(startTab: .library).transition(.opacity)
                } else {
                    ServerUnreachableView(message: message).transition(.opacity)
                }
            case .pending(let account):
                AccessPendingView(account: account, rejected: false).transition(.opacity)
            case .rejected(let account):
                AccessPendingView(account: account, rejected: true).transition(.opacity)
            case .approved:
                RootTabView().transition(.opacity.combined(with: .scale(scale: 0.98)))
            }
        }
        .animation(Motion.smooth, value: auth.state)
        .environmentObject(auth)
        .task { await auth.refresh() }
        .onChange(of: scenePhase) { _, phase in
            // Au retour dans l'app : un accès accordé (ou révoqué) entre-temps
            // est pris en compte sans relancer l'app.
            if phase == .active {
                Task { await auth.refresh() }
                SmartDownloads.shared.runIfDue()
            }
            if phase == .background {
                SmartDownloads.shared.schedule()
                NotificationManager.shared.scheduleRefresh()
            }
        }
    }
}
