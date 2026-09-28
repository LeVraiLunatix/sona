import MediaPlayer
import SwiftUI

/// Enrobe `MPVolumeView` : le *vrai* curseur de volume système (celui des
/// boutons physiques et du Centre de contrôle), pas un curseur maison qui ne
/// pilotait que le gain interne du lecteur — désynchronisé du volume réel de
/// l'iPhone. Inclut de fait le sélecteur AirPlay natif.
struct SystemVolumeView: UIViewRepresentable {
    func makeUIView(context: Context) -> MPVolumeView {
        let view = MPVolumeView(frame: .zero)
        view.showsRouteButton = true
        view.tintColor = .white
        return view
    }

    func updateUIView(_ uiView: MPVolumeView, context: Context) {
        uiView.tintColor = .white
    }
}
