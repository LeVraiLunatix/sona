import Combine
import SwiftUI

/// Thème « archive » : quand on écoute un artiste à identités (FEMTOGO, baby hayabusa…), tout Sona
/// prend la direction artistique de trois.id, comme le mode `archive` du site (`web/app.css`) :
/// monospace, noir bleuté, filets fins, pochettes en noir et blanc et un seul accent doré.
enum ArchiveColor {
    static let canvas = Color(hex: 0x0B0B0E)
    static let panel = Color(hex: 0x0F0F13)
    static let line = Color(hex: 0x24242E)
    static let text = Color(hex: 0xD8D8D8)
    static let gold = Color(hex: 0xC8B890)
}

@MainActor
final class ArchiveTheme: ObservableObject {
    static let shared = ArchiveTheme()

    /// Thème actif : le titre qu'on entend est d'une identité d'archive, et le réglage est activé.
    @Published private(set) var on = false
    private var cancellables = Set<AnyCancellable>()

    private init() {
        PlayerManager.shared.$current
            .map { _ in () }
            .merge(with: ConnectManager.shared.objectWillChange.map { _ in () }.throttle(for: .milliseconds(400), scheduler: RunLoop.main, latest: true),
                   RemoteFlag.shared.objectWillChange.map { _ in () })
            .receive(on: DispatchQueue.main)
            .sink { [weak self] _ in self?.refresh() }
            .store(in: &cancellables)
    }

    /// À rappeler quand le réglage change.
    func refresh() {
        let enabled = UserDefaults.standard.object(forKey: Look.archiveKey) as? Bool ?? true
        let want = enabled && !(GtaTheme.listeningTrack?.persona ?? "").isEmpty
        guard want != on else { return }
        withAnimation(.easeInOut(duration: 0.5)) { on = want }
    }
}
