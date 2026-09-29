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

/// Volume de l'iPhone réglé par l'app (Sona Connect : depuis le PC). iOS n'a
/// pas d'API publique pour ça ; le curseur système de `MPVolumeView`, lui,
/// règle le vrai volume — un curseur invisible, posé hors de l'écran, sert
/// de télécommande.
@MainActor
enum SystemVolume {
    private static var volumeView: MPVolumeView?

    /// Volume actuel (0…1), celui des boutons physiques.
    static var current: Double { Double(AVAudioSession.sharedInstance().outputVolume) }

    static func set(_ value: Double) {
        let view = volumeView ?? makeView()
        guard let slider = view.subviews.compactMap({ $0 as? UISlider }).first else { return }
        slider.setValue(Float(min(1, max(0, value))), animated: false)
        slider.sendActions(for: .valueChanged)
    }

    private static func makeView() -> MPVolumeView {
        let view = MPVolumeView(frame: CGRect(x: -1000, y: -1000, width: 100, height: 40))
        view.alpha = 0.01
        view.isUserInteractionEnabled = false
        // Dans une fenêtre, sinon le curseur ne répond pas.
        let window = UIApplication.shared.connectedScenes
            .compactMap { ($0 as? UIWindowScene)?.keyWindow }
            .first
        window?.addSubview(view)
        volumeView = view
        return view
    }
}
