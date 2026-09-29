import AVFoundation
import AVKit
import SwiftUI

/// Sortie audio actuelle de l'iPhone (AirPods, enceinte Bluetooth, AirPlay,
/// haut-parleur…), suivie en direct : son nom et son symbole s'affichent en
/// bas du lecteur, comme dans Musique.
@MainActor
final class AudioRoute: ObservableObject {
    static let shared = AudioRoute()

    @Published private(set) var name = "iPhone"
    @Published private(set) var icon = "iphone"
    /// Autre chose que le haut-parleur de l'iPhone.
    @Published private(set) var isExternal = false

    private init() {
        refresh()
        NotificationCenter.default.addObserver(
            forName: AVAudioSession.routeChangeNotification, object: nil, queue: .main
        ) { _ in
            Task { @MainActor in AudioRoute.shared.refresh() }
        }
    }

    func refresh() {
        guard let port = AVAudioSession.sharedInstance().currentRoute.outputs.first else {
            set("iPhone", "iphone", external: false)
            return
        }
        switch port.portType {
        case .builtInSpeaker, .builtInReceiver:
            set("iPhone", "iphone", external: false)
        case .bluetoothA2DP, .bluetoothLE, .bluetoothHFP:
            set(port.portName, Self.headphonesIcon(port.portName), external: true)
        case .airPlay:
            let lower = port.portName.lowercased()
            set(port.portName, lower.contains("homepod") ? "homepod.fill" : lower.contains("tv") ? "appletv.fill" : "airplay.audio", external: true)
        case .headphones, .usbAudio:
            set(port.portType == .headphones ? "Écouteurs" : port.portName, "headphones", external: true)
        case .carAudio:
            set(port.portName, "car.fill", external: true)
        case .HDMI:
            set(port.portName, "tv", external: true)
        default:
            set(port.portName, "hifispeaker.fill", external: true)
        }
    }

    private func set(_ name: String, _ icon: String, external: Bool) {
        if self.name != name { self.name = name }
        if self.icon != icon { self.icon = icon }
        if isExternal != external { isExternal = external }
    }

    static func headphonesIcon(_ name: String) -> String {
        let lower = name.lowercased()
        if lower.contains("airpods max") { return "airpodsmax" }
        if lower.contains("airpods pro") { return "airpodspro" }
        if lower.contains("airpods") { return "airpods" }
        if lower.contains("beats") || lower.contains("powerbeats") { return "beats.headphones" }
        return "headphones"
    }
}

/// Le sélecteur AirPlay / Bluetooth du système, invisible, posé sur un
/// élément : un toucher ouvre la liste des sorties d'iOS.
struct RoutePickerOverlay: UIViewRepresentable {
    func makeUIView(context: Context) -> AVRoutePickerView {
        let picker = AVRoutePickerView()
        picker.prioritizesVideoDevices = false
        // Quasi transparent mais toujours tapable.
        picker.alpha = 0.02
        return picker
    }

    func updateUIView(_ uiView: AVRoutePickerView, context: Context) {}
}

/// « Écouter sur » : tout ce qui décide où sort la musique, trié —
/// l'iPhone et ses sorties (AirPods, AirPlay, Bluetooth), tes autres
/// appareils Sona (PC…), la PS5 et la TV.
struct OutputSheet: View {
    @ObservedObject private var route = AudioRoute.shared
    @ObservedObject private var cast = CastManager.shared
    @ObservedObject private var flag = RemoteFlag.shared
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                Section {
                    HStack(spacing: 14) {
                        Image(systemName: route.icon)
                            .font(.system(size: 19, weight: .semibold))
                            .foregroundStyle(onThisPhone ? .white : Tone.secondary)
                            .frame(width: 42, height: 42)
                            .background(RoundedRectangle(cornerRadius: 11, style: .continuous)
                                .fill(onThisPhone ? Color.accentColor : Tone.surfaceStrong))
                        VStack(alignment: .leading, spacing: 2) {
                            Text(route.isExternal ? route.name : "Cet iPhone").font(Typo.rowTitle).foregroundStyle(Tone.primary)
                            Text(route.isExternal ? "Sortie de cet iPhone" : "Haut-parleur")
                                .font(Typo.caption).foregroundStyle(Tone.secondary)
                        }
                        Spacer()
                        if onThisPhone { Image(systemName: "checkmark").foregroundStyle(Color.accentColor) }
                    }
                    ZStack {
                        HStack(spacing: 14) {
                            Image(systemName: "airplay.audio")
                                .font(.system(size: 18, weight: .semibold))
                                .frame(width: 42, height: 42)
                                .background(RoundedRectangle(cornerRadius: 11, style: .continuous).fill(Tone.surfaceStrong))
                            Text("AirPlay et Bluetooth").font(Typo.rowTitle)
                            Spacer()
                            Image(systemName: "chevron.right").font(.system(size: 13, weight: .semibold)).foregroundStyle(Tone.tertiary)
                        }
                        .foregroundStyle(Tone.primary)
                        RoutePickerOverlay()
                    }
                } header: {
                    Text("Cet iPhone")
                } footer: {
                    Text("AirPods, enceinte, HomePod, voiture : la liste des sorties d'iOS.")
                }

                ConnectDevicesSection()
                TVCastSections()
            }
            .navigationTitle("Écouter sur")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("OK") { dismiss() } } }
        }
        .onAppear { route.refresh() }
    }

    private var onThisPhone: Bool { cast.active == nil && !flag.isRemote }
}

/// Bouton de sortie du lecteur (en bas, entre paroles et file d'attente) :
/// le symbole et le nom de la sortie en cours — AirPods, PS5, PC — ou
/// l'icône AirPlay quand la musique sort de l'iPhone lui-même.
struct OutputButton: View {
    @ObservedObject private var route = AudioRoute.shared
    @ObservedObject private var cast = CastManager.shared
    @ObservedObject private var flag = RemoteFlag.shared
    @State private var showing = false

    var body: some View {
        let (icon, label) = current
        Button { showing = true } label: {
            VStack(spacing: 3) {
                Image(systemName: icon)
                    .font(.system(size: 19, weight: .semibold))
                    .foregroundStyle(label == nil ? Tone.secondary : Color.accentColor)
                    .contentTransition(.symbolEffect(.replace))
                if let label {
                    Text(label)
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(Color.accentColor)
                        .lineLimit(1)
                        .transition(.opacity)
                }
            }
            .frame(minWidth: 44, maxWidth: 190, minHeight: 36)
            .animation(Motion.smooth, value: label)
        }
        .buttonStyle(.pressable(scale: 0.88))
        .accessibilityLabel(label.map { "Sortie : \($0)" } ?? "Écouter sur…")
        .sheet(isPresented: $showing) {
            OutputSheet().presentationDetents([.medium, .large])
        }
        .onAppear { route.refresh() }
    }

    private var current: (String, String?) {
        if let screen = cast.active { return ("tv.fill", screen.name) }
        if flag.isRemote, let device = ConnectManager.shared.remoteTarget {
            return (device.kind == "iphone" ? "iphone" : "laptopcomputer", device.name)
        }
        if route.isExternal { return (route.icon, route.name) }
        return ("airplay.audio", nil)
    }
}
