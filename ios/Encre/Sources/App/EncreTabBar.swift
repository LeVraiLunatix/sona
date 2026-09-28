import SwiftUI

enum AppTab: Int, CaseIterable {
    case home, library, search

    var title: String {
        switch self {
        case .home: "Écouter"
        case .library: "Bibliothèque"
        case .search: "Rechercher"
        }
    }

    var icon: String {
        switch self {
        case .home: "house.fill"
        case .library: "books.vertical.fill"
        case .search: "magnifyingglass"
        }
    }
}

/// Barre d'onglets "verre liquide", en remplacement du `TabView` natif —
/// dont le chrome ne peut pas être stylé à ce point. Pas encore le repli en
/// bulle qui fusionne avec le mini-lecteur au défilement (Encre.dc.html) :
/// cette étape suit l'onboarding, une fois la coquille et la navigation
/// validées, plutôt que de risquer un suivi de défilement bas-niveau sans
/// pouvoir compiler pour le vérifier ici.
struct EncreTabBar: View {
    @Binding var selected: AppTab

    var body: some View {
        HStack(spacing: 4) {
            ForEach(AppTab.allCases, id: \.self) { tab in
                Button {
                    withAnimation(.easeOut(duration: 0.2)) { selected = tab }
                } label: {
                    VStack(spacing: 3) {
                        Image(systemName: tab.icon)
                            .font(.system(size: 22))
                        Text(tab.title)
                            .font(EncreFont.heading(11))
                    }
                    .foregroundStyle(selected == tab ? EncreColor.spot : EncreColor.text)
                    .frame(maxWidth: .infinity)
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.horizontal, 6)
        .frame(height: 64)
        .glassCapsule(interactive: true)
    }
}
