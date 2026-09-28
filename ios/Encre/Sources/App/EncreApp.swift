import SwiftUI

@main
struct EncreApp: App {
    init() {
        // Pochettes et photos d'artistes rechargées sans cesse en défilant :
        // un cache HTTP généreux (mémoire + disque) rend les listes fluides
        // et les allers-retours instantanés.
        URLCache.shared = URLCache(memoryCapacity: 64 * 1024 * 1024, diskCapacity: 300 * 1024 * 1024)
    }

    var body: some Scene {
        WindowGroup {
            RootTabView()
                .preferredColorScheme(.dark)
        }
    }
}
