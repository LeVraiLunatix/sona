import SwiftUI

@main
struct EncreApp: App {
    var body: some Scene {
        WindowGroup {
            RootTabView()
                .preferredColorScheme(.dark) // thème sombre et sobre, seule variante pour l'instant
        }
    }
}
