import SwiftUI

@main
struct EncreApp: App {
    var body: some Scene {
        WindowGroup {
            RootTabView()
                .preferredColorScheme(.light) // le papier "Encre" n'a pas encore de variante sombre
        }
    }
}
