import CoreLocation
import SwiftUI

/// Position du téléphone, demandée une fois (« pendant l'utilisation ») pour
/// trier les concerts par distance. Elle reste sur l'iPhone.
@MainActor
final class LocationProvider: NSObject, ObservableObject, CLLocationManagerDelegate {
    static let shared = LocationProvider()

    @Published private(set) var location: CLLocation?
    @Published private(set) var status: CLAuthorizationStatus = .notDetermined

    private let manager = CLLocationManager()

    override private init() {
        super.init()
        status = manager.authorizationStatus
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyKilometer
        if let saved = ConcertAlerts.lastLocation {
            location = CLLocation(latitude: saved.0, longitude: saved.1)
        }
    }

    func request() {
        switch manager.authorizationStatus {
        case .notDetermined: manager.requestWhenInUseAuthorization()
        case .authorizedWhenInUse, .authorizedAlways: manager.requestLocation()
        default: break
        }
    }

    nonisolated func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        let status = manager.authorizationStatus
        Task { @MainActor in
            self.status = status
            if status == .authorizedWhenInUse || status == .authorizedAlways { self.manager.requestLocation() }
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let last = locations.last else { return }
        Task { @MainActor in
            self.location = last
            ConcertAlerts.lastLocation = (last.coordinate.latitude, last.coordinate.longitude)
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {}
}

extension Concert {
    func distanceKm(from location: CLLocation?) -> Double? {
        guard let location, let latitude, let longitude else { return nil }
        return ConcertAlerts.distanceKm(location.coordinate.latitude, location.coordinate.longitude, latitude, longitude)
    }
}

/// Concerts à venir des artistes les plus écoutés : près de toi d'abord.
struct ConcertsView: View {
    @StateObject private var location = LocationProvider.shared
    @State private var concerts: [Concert] = []
    @State private var isLoading = true
    @State private var errorMessage: String?
    @State private var alerts = ConcertAlerts.enabled

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 18) {
                header
                if isLoading && concerts.isEmpty {
                    ProgressView().tint(.white).frame(maxWidth: .infinity).padding(.top, 60)
                } else if concerts.isEmpty {
                    EmptyState(
                        systemImage: "music.mic",
                        title: "Aucune date annoncée",
                        message: errorMessage ?? "Aucun des artistes que tu écoutes le plus n'a de concert prévu pour l'instant."
                    )
                } else {
                    if !near.isEmpty {
                        SectionHeader(title: "Près de toi")
                        ForEach(near) { ConcertRow(concert: $0, distance: $0.distanceKm(from: location.location)) }
                    }
                    SectionHeader(title: near.isEmpty ? "À venir" : "Ailleurs")
                    ForEach(elsewhere) { ConcertRow(concert: $0, distance: $0.distanceKm(from: location.location)) }
                }
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 24)
        }
        .scrollIndicators(.hidden)
        .background(Tone.background)
        .navigationTitle("Concerts")
        .navigationBarTitleDisplayMode(.large)
        .task {
            location.request()
            await load()
        }
        .refreshable { await load() }
    }

    private var near: [Concert] {
        concerts.filter { ($0.distanceKm(from: location.location) ?? .infinity) <= ConcertAlerts.radiusKm }
    }

    private var elsewhere: [Concert] {
        let nearIds = Set(near.map(\.id))
        return concerts.filter { !nearIds.contains($0.id) }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Les dates de tes artistes les plus écoutés.")
                .font(Typo.body)
                .foregroundStyle(Tone.secondary)
            if location.location == nil {
                Button { location.request() } label: {
                    Label("Utiliser ma position pour voir ce qui est près de moi", systemImage: "location.fill")
                        .font(Typo.rowSubtitle)
                        .foregroundStyle(Tone.primary)
                }
            }
            Toggle(isOn: $alerts) {
                Label("Me prévenir des nouvelles dates près de moi", systemImage: "bell.badge")
                    .font(Typo.rowSubtitle)
                    .foregroundStyle(Tone.primary)
            }
            .tint(.green)
            .onChange(of: alerts) { _, value in
                Task {
                    if value {
                        let granted = await ConcertAlerts.requestPermission()
                        if !granted {
                            alerts = false
                            return
                        }
                    }
                    ConcertAlerts.enabled = value
                    if value { location.request() }
                }
            }
        }
        .padding(16)
        .background(RoundedRectangle(cornerRadius: 20, style: .continuous).fill(Tone.surface))
    }

    private func load() async {
        isLoading = true
        do {
            concerts = try await APIClient.shared.concerts()
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
        isLoading = false
    }
}

struct ConcertRow: View {
    let concert: Concert
    let distance: Double?
    @Environment(\.openURL) private var openURL

    var body: some View {
        HStack(spacing: 14) {
            VStack(spacing: 0) {
                Text(day).font(.system(size: 22, weight: .heavy)).foregroundStyle(Tone.primary)
                Text(month).font(Typo.caption).foregroundStyle(Tone.secondary)
            }
            .frame(width: 54, height: 60)
            .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(Tone.surfaceStrong))

            Artwork(url: concert.artistPictureURL, cornerRadius: 24, symbol: "person.fill").frame(width: 48, height: 48)

            VStack(alignment: .leading, spacing: 3) {
                Text(concert.artist).font(Typo.rowTitle).foregroundStyle(Tone.primary).lineLimit(1)
                Text([concert.venue, concert.city].compactMap { $0 }.joined(separator: " · "))
                    .font(Typo.rowSubtitle)
                    .foregroundStyle(Tone.secondary)
                    .lineLimit(1)
                if let distance {
                    Text(distance < 1 ? "À côté" : "À \(Int(distance)) km")
                        .font(Typo.caption)
                        .foregroundStyle(distance <= ConcertAlerts.radiusKm ? Color.green : Tone.tertiary)
                }
            }
            Spacer(minLength: 4)
            if let link = concert.url.flatMap(URL.init(string:)) {
                Button { openURL(link) } label: {
                    Text("Billets")
                        .font(Typo.caption)
                        .foregroundStyle(.black)
                        .padding(.horizontal, 12)
                        .padding(.vertical, 8)
                        .background(Capsule().fill(.white))
                }
                .buttonStyle(.pressable(scale: 0.9))
            }
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 18, style: .continuous).fill(Tone.surface))
    }

    private var day: String {
        guard let date = concert.date else { return "?" }
        return String(Calendar.current.component(.day, from: date))
    }

    private var month: String {
        guard let date = concert.date else { return "" }
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "fr_FR")
        formatter.dateFormat = "MMM"
        return formatter.string(from: date).uppercased()
    }
}

/// Section « Tes artistes en concert » de l'accueil : les prochaines dates
/// (près de toi d'abord), et un lien vers la liste complète.
struct ConcertsTeaser: View {
    var onOpen: () -> Void
    @ObservedObject private var location = LocationProvider.shared
    @State private var concerts: [Concert] = []

    var body: some View {
        Group {
            if !concerts.isEmpty {
                VStack(alignment: .leading, spacing: 14) {
                    SectionHeader(title: "Tes artistes en concert", actionLabel: "Tout voir", action: onOpen)
                        .padding(.horizontal, 20)
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 12) {
                            ForEach(sorted.prefix(10)) { concert in
                                Button(action: onOpen) {
                                    ConcertCard(concert: concert, distance: concert.distanceKm(from: location.location))
                                }
                                .buttonStyle(.pressable(scale: 0.97))
                            }
                        }
                        .padding(.horizontal, 20)
                    }
                }
            }
        }
        .task {
            concerts = (try? await APIClient.shared.concerts()) ?? []
        }
    }

    private var sorted: [Concert] {
        concerts.sorted { a, b in
            let da = a.distanceKm(from: location.location) ?? .infinity
            let db = b.distanceKm(from: location.location) ?? .infinity
            let nearA = da <= ConcertAlerts.radiusKm, nearB = db <= ConcertAlerts.radiusKm
            if nearA != nearB { return nearA }
            return a.datetime < b.datetime
        }
    }
}

private struct ConcertCard: View {
    let concert: Concert
    let distance: Double?

    var body: some View {
        ZStack(alignment: .bottomLeading) {
            Artwork(url: concert.artistPictureURL, cornerRadius: 18, symbol: "music.mic")
            LinearGradient(colors: [.clear, .black.opacity(0.85)], startPoint: .center, endPoint: .bottom)
                .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
            VStack(alignment: .leading, spacing: 2) {
                if let date = concert.date {
                    Text(ConcertAlerts.dayLabel(date).capitalized)
                        .font(Typo.caption)
                        .foregroundStyle(.white.opacity(0.8))
                }
                Text(concert.artist).font(Typo.headline).foregroundStyle(.white).lineLimit(1)
                Text(concert.city ?? "").font(Typo.caption).foregroundStyle(.white.opacity(0.8))
                if let distance, distance <= ConcertAlerts.radiusKm {
                    Text("Près de toi").font(Typo.caption).foregroundStyle(.green)
                }
            }
            .padding(12)
        }
        .frame(width: 170, height: 200)
    }
}
