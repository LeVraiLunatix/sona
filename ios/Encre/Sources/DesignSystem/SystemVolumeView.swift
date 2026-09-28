import AVKit
import MediaPlayer
import SwiftUI

/// Le *vrai* curseur de volume système (celui des boutons physiques et du
/// Centre de contrôle), épuré : sans pastille de défilement ni bouton de
/// sortie intégré — le choix AirPlay a son propre bouton (`AirPlayButton`).
struct SystemVolumeView: UIViewRepresentable {
    func makeUIView(context: Context) -> MPVolumeView {
        let view = MPVolumeView(frame: .zero)
        view.showsRouteButton = false
        view.tintColor = .white
        // Pastille minuscule et transparente : la barre seule, comme Musique.
        let thumb = UIGraphicsImageRenderer(size: CGSize(width: 6, height: 6)).image { _ in }
        view.setVolumeThumbImage(thumb, for: .normal)
        view.setVolumeThumbImage(thumb, for: .highlighted)
        return view
    }

    func updateUIView(_ uiView: MPVolumeView, context: Context) {}
}

/// Choix de la sortie audio (AirPlay, Bluetooth, haut-parleur) : le sélecteur
/// système `AVRoutePickerView`, rendu invisible et posé sur un symbole
/// épuré — son icône d'origine ne se personnalise pas.
struct AirPlayButton: View {
    var body: some View {
        ZStack {
            Image(systemName: "airplay.audio")
                .font(.system(size: 19, weight: .semibold))
                .foregroundStyle(Tone.secondary)
            RoutePicker()
        }
        .frame(width: 44, height: 36)
    }

    private struct RoutePicker: UIViewRepresentable {
        func makeUIView(context: Context) -> AVRoutePickerView {
            let picker = AVRoutePickerView()
            picker.prioritizesVideoDevices = false
            // Quasi transparent mais toujours tapable (en dessous de 0,01,
            // UIKit ne lui transmet plus les touchers).
            picker.alpha = 0.02
            return picker
        }

        func updateUIView(_ uiView: AVRoutePickerView, context: Context) {}
    }
}
