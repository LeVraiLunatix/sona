import CoreLocation
import SwiftUI

/// Position du téléphone, demandée une fois (« pendant l'utilisation ») pour
/// placer les écoutes sur la carte. Elle reste sur l'iPhone.
@MainActor
final class LocationProvider: NSObject, ObservableObject, CLLocationManagerDelegate {
    static let shared = LocationProvider()

    /// Dernière position connue (latitude, longitude), gardée sur l'appareil.
    static var lastLocation: (Double, Double)? {
        get {
            guard let values = UserDefaults.standard.array(forKey: "encre.concerts.location") as? [Double], values.count == 2 else { return nil }
            return (values[0], values[1])
        }
        set {
            if let newValue { UserDefaults.standard.set([newValue.0, newValue.1], forKey: "encre.concerts.location") }
        }
    }

    @Published private(set) var location: CLLocation?
    @Published private(set) var status: CLAuthorizationStatus = .notDetermined

    private let manager = CLLocationManager()

    override private init() {
        super.init()
        status = manager.authorizationStatus
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyKilometer
        if let saved = LocationProvider.lastLocation {
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
            LocationProvider.lastLocation = (last.coordinate.latitude, last.coordinate.longitude)
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {}
}
