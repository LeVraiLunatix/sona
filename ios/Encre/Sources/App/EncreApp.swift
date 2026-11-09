import SwiftUI

@main
struct EncreApp: App {
    @AppStorage(Look.accentKey) private var accent = LookAccent.neutre.rawValue
    @ObservedObject private var launchAuth = AuthManager.shared
    @State private var showsSplash = true

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
        // Widget « Mon PC » et Centre de contrôle : leurs boutons passent
        // par l'app (voir `PCRemoteButtonIntent`), même lancée en arrière-plan.
        RemoteIntentBridge.handler = { command in
            _ = await ConnectManager.shared.intentCommand(command)
        }
    }

    var body: some Scene {
        WindowGroup {
            ZStack {
                AppGate()
                if showsSplash {
                    LaunchSplashView()
                        .transition(.opacity.combined(with: .scale(scale: 1.06)))
                        .zIndex(1)
                }
            }
            .preferredColorScheme(.dark)
            .tint(LookAccent(rawValue: accent)?.color)
            .task {
                // Au moins le temps de l'animation, puis dès que le compte est vérifié (6 s au plus).
                let started = Date()
                try? await Task.sleep(for: .milliseconds(2300))
                while launchAuth.state == .checking, Date().timeIntervalSince(started) < 6 {
                    try? await Task.sleep(for: .milliseconds(150))
                }
                withAnimation(.easeInOut(duration: 0.55)) { showsSplash = false }
            }
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
        .task {
            LyricsActivity.shared.bind(PlayerManager.shared)
            await auth.refresh()
            // La qualité audio du compte (Réglages) : le serveur en dépend pour choisir le fichier.
            await PlaybackQuality.refresh()
        }
        .onChange(of: scenePhase) { _, phase in
            // Au retour dans l'app : un accès accordé (ou révoqué) entre-temps
            // est pris en compte sans relancer l'app.
            if phase == .active {
                Task { await auth.refresh() }
                SmartDownloads.shared.runIfDue()
            }
            if phase == .background {
                PlayerManager.shared.saveSession(force: true)
                SmartDownloads.shared.schedule()
                NotificationManager.shared.scheduleRefresh()
            }
        }
    }
}
