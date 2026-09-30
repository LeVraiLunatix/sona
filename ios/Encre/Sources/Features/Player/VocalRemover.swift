import AVFoundation
import MediaToolbox

/// Traitement du son en direct, branché sur l'`AVPlayerItem` (« tap » audio) :
///
/// - **Mode « chante »** : baisse la voix du titre pour chanter par-dessus.
///   La voix principale est presque toujours mixée au centre (identique à
///   gauche et à droite) — mais la prod aussi, en bonne partie : retirer tout
///   le centre étouffait le morceau. On ne baisse donc que la bande de la voix
///   (≈ 150 Hz – 6,5 kHz) du centre ; les basses (kick, 808) et les aigus
///   (charley, cymbales) restent, comme tout ce qui est sur les côtés. Sur un
///   mix presque mono, on en retire moins pour garder un son plein.
/// - **Karaoké séparé par IA** (voir `KaraokeMix`) : deux pistes, voix et
///   instru, chacune avec son propre traitement. Celui de la voix applique
///   son volume (`vocalGain`) ; les deux passent par l'égaliseur (un filtre
///   linéaire : égaliser chaque piste revient à égaliser leur somme), et le
///   visualiseur additionne l'énergie des deux (voix et instru ne sont
///   presque pas corrélées : leurs énergies s'ajoutent).
/// - **Égaliseur** : 5 bandes (60 Hz, 250 Hz, 1 kHz, 4 kHz, 12 kHz), filtres
///   « biquad » classiques, avec une marge automatique contre la saturation.
enum AudioEffects {
    /// 0 : son normal, 1 : voix baissée. Changement en douceur (voir `process`).
    static var singAmount: Float = 0

    /// Volume de la piste voix en karaoké séparé (0 : instru seule, 1 :
    /// titre normal). Suivi en douceur par le fil audio (voir `process`).
    static var vocalGain: Float = 0
    /// Les pistes séparées sont en lecture : le visualiseur ajoute
    /// l'énergie de la voix (mesurée par son propre traitement).
    static var stemsActive = false

    static let bands: [Float] = [60, 250, 1000, 4000, 12000]
    static let bandLabels = ["60", "250", "1k", "4k", "12k"]
    /// Gains de l'égaliseur, en dB (−12…+12), un par bande.
    static var eqGains: [Float] = UserDefaults.standard.array(forKey: "encre.eq") as? [Float] ?? [0, 0, 0, 0, 0] {
        didSet {
            eqVersion += 1
            UserDefaults.standard.set(eqGains, forKey: "encre.eq")
        }
    }
    /// Change à chaque réglage : le fil audio recalcule alors ses filtres.
    static var eqVersion = 0

    static var isEQActive: Bool { eqGains.contains { abs($0) > 0.05 } }

    // MARK: Visualiseur

    /// Visualiseur du lecteur : le fil audio mesure alors le niveau de
    /// `levelBands` bandes de fréquence (des basses aux aigus), lu par
    /// `VisualizerBars` à chaque image.
    static var visualizerOn = UserDefaults.standard.bool(forKey: "encre.visualizer") {
        didSet { UserDefaults.standard.set(visualizerOn, forKey: "encre.visualizer") }
    }
    static let levelBands = 8
    /// Fréquences de coupure entre deux bandes voisines.
    static let levelSplits: [Float] = [90, 220, 500, 1100, 2400, 5000, 10000]
    /// Niveaux (0…1) écrits par le fil audio, lus par l'interface : un
    /// tampon fixe plutôt qu'un tableau Swift, qu'on ne peut pas partager
    /// entre deux fils sans risque.
    static let levels: UnsafeMutablePointer<Float> = {
        let pointer = UnsafeMutablePointer<Float>.allocate(capacity: levelBands)
        pointer.initialize(repeating: 0, count: levelBands)
        return pointer
    }()

    static func level(_ band: Int) -> Float { levels[band] }

    /// Énergie moyenne par bande de la piste voix (après son volume),
    /// écrite par son traitement et ajoutée par celui de l'instru.
    static let vocalEnergy: UnsafeMutablePointer<Float> = {
        let pointer = UnsafeMutablePointer<Float>.allocate(capacity: levelBands)
        pointer.initialize(repeating: 0, count: levelBands)
        return pointer
    }()

    /// Rôle d'un traitement, passé à sa création (`clientInfo`).
    fileprivate enum Role: Int {
        case normal = 0, stemInstrumental = 1, stemVocals = 2
    }

    private static func makeTap(_ role: Role) -> MTAudioProcessingTap? {
        var callbacks = MTAudioProcessingTapCallbacks(
            version: kMTAudioProcessingTapCallbacksVersion_0,
            clientInfo: UnsafeMutableRawPointer(bitPattern: role.rawValue),
            init: tapInit,
            finalize: tapFinalize,
            prepare: tapPrepare,
            unprepare: nil,
            process: tapProcess
        )
        var tap: MTAudioProcessingTap?
        let status = MTAudioProcessingTapCreate(
            kCFAllocatorDefault, &callbacks, kMTAudioProcessingTapCreationFlag_PostEffects, &tap
        )
        return status == noErr ? tap : nil
    }

    /// Mixage des pistes séparées : un traitement par piste.
    static func stemsMix(instrumental: AVAssetTrack, vocals: AVAssetTrack) -> AVAudioMix? {
        guard let instrumentalTap = makeTap(.stemInstrumental), let vocalsTap = makeTap(.stemVocals) else { return nil }
        let instrumentalParameters = AVMutableAudioMixInputParameters(track: instrumental)
        instrumentalParameters.audioTapProcessor = instrumentalTap
        let vocalsParameters = AVMutableAudioMixInputParameters(track: vocals)
        vocalsParameters.audioTapProcessor = vocalsTap
        let mix = AVMutableAudioMix()
        mix.inputParameters = [instrumentalParameters, vocalsParameters]
        return mix
    }

    /// Mixage à poser sur l'item (`item.audioMix`), ou nil si l'item n'a
    /// pas encore de piste audio.
    static func audioMix(for item: AVPlayerItem) async -> AVAudioMix? {
        guard let track = try? await item.asset.loadTracks(withMediaType: .audio).first,
              let tap = makeTap(.normal) else { return nil }
        let parameters = AVMutableAudioMixInputParameters(track: track)
        parameters.audioTapProcessor = tap
        let mix = AVMutableAudioMix()
        mix.inputParameters = [parameters]
        return mix
    }
}

/// Réglages de l'égaliseur prêts à l'emploi.
struct EQPreset: Identifiable, Hashable {
    let name: String
    let gains: [Float]
    var id: String { name }

    static let all: [EQPreset] = [
        EQPreset(name: "Normal", gains: [0, 0, 0, 0, 0]),
        EQPreset(name: "Basses", gains: [6, 3, 0, 0, 1]),
        EQPreset(name: "Grosses basses", gains: [9, 5, -1, 0, 2]),
        EQPreset(name: "Voix", gains: [-2, -1, 3, 4, 1]),
        EQPreset(name: "Soirée", gains: [5, 2, -1, 2, 4]),
        EQPreset(name: "Voiture", gains: [4, 1, 0, 2, 3]),
        EQPreset(name: "Aigus", gains: [0, 0, 0, 3, 6]),
        EQPreset(name: "Doux", gains: [2, 1, 0, -2, -3]),
    ]
}

/// Coefficients normalisés d'un biquad (b0, b1, b2, a1, a2).
private struct Biquad {
    var b0: Float = 1, b1: Float = 0, b2: Float = 0, a1: Float = 0, a2: Float = 0

    enum Kind { case lowShelf, peak, highShelf }

    init() {}

    init(kind: Kind, frequency: Float, gain: Float, rate: Float) {
        let a = powf(10, gain / 40)
        let w0 = 2 * Float.pi * min(frequency, rate * 0.45) / rate
        let cosW = cosf(w0), sinW = sinf(w0)
        let n0, n1, n2, d0, d1, d2: Float
        switch kind {
        case .peak:
            let alpha = sinW / 2  // Q = 1
            n0 = 1 + alpha * a; n1 = -2 * cosW; n2 = 1 - alpha * a
            d0 = 1 + alpha / a; d1 = -2 * cosW; d2 = 1 - alpha / a
        case .lowShelf:
            let alpha = sinW / 2 * sqrtf(2)
            let rootA = sqrtf(a)
            n0 = a * ((a + 1) - (a - 1) * cosW + 2 * rootA * alpha)
            n1 = 2 * a * ((a - 1) - (a + 1) * cosW)
            n2 = a * ((a + 1) - (a - 1) * cosW - 2 * rootA * alpha)
            d0 = (a + 1) + (a - 1) * cosW + 2 * rootA * alpha
            d1 = -2 * ((a - 1) + (a + 1) * cosW)
            d2 = (a + 1) + (a - 1) * cosW - 2 * rootA * alpha
        case .highShelf:
            let alpha = sinW / 2 * sqrtf(2)
            let rootA = sqrtf(a)
            n0 = a * ((a + 1) + (a - 1) * cosW + 2 * rootA * alpha)
            n1 = -2 * a * ((a - 1) + (a + 1) * cosW)
            n2 = a * ((a + 1) + (a - 1) * cosW - 2 * rootA * alpha)
            d0 = (a + 1) - (a - 1) * cosW + 2 * rootA * alpha
            d1 = 2 * ((a - 1) - (a + 1) * cosW)
            d2 = (a + 1) - (a - 1) * cosW - 2 * rootA * alpha
        }
        b0 = n0 / d0; b1 = n1 / d0; b2 = n2 / d0; a1 = d1 / d0; a2 = d2 / d0
    }
}

/// État propre à un tap (format, filtres, largeur stéréo, niveaux appliqués).
private final class TapState {
    var role: AudioEffects.Role = .normal
    var usable = false
    // Karaoké séparé : volume appliqué à la voix (suit `vocalGain`).
    var gain: Float = 0
    var sampleRate: Float = 44_100
    // Mode « chante » : passe-bas à deux pôles sur le centre.
    var low1: Float = 0, low2: Float = 0
    var top1: Float = 0, top2: Float = 0
    var midEnergy: Float = 1e-6
    var sideEnergy: Float = 0
    var applied: Float = 0
    // Égaliseur : coefficients par bande, mémoires x1 x2 y1 y2 par canal.
    var eqVersion = -1
    var filters: [Biquad] = Array(repeating: Biquad(), count: 5)
    var memory: [Float] = Array(repeating: 0, count: 5 * 4 * 2)
    var eqOn = false
    var preamp: Float = 1
    // Visualiseur : passe-bas en cascade sur le mono.
    var splits: [Float] = Array(repeating: 0, count: AudioEffects.levelSplits.count)

    func refreshEQ() {
        let version = AudioEffects.eqVersion
        guard version != eqVersion else { return }
        eqVersion = version
        let gains = AudioEffects.eqGains
        eqOn = gains.contains { abs($0) > 0.05 }
        for index in 0..<5 {
            let kind: Biquad.Kind = index == 0 ? .lowShelf : (index == 4 ? .highShelf : .peak)
            filters[index] = Biquad(kind: kind, frequency: AudioEffects.bands[index], gain: gains[index], rate: sampleRate)
        }
        // Marge contre la saturation quand on monte des bandes.
        let boost = max(0, gains.max() ?? 0)
        preamp = powf(10, -boost * 0.6 / 20)
    }
}

private let tapInit: MTAudioProcessingTapInitCallback = { _, clientInfo, storageOut in
    let state = TapState()
    state.role = AudioEffects.Role(rawValue: Int(bitPattern: clientInfo)) ?? .normal
    state.gain = AudioEffects.vocalGain
    storageOut.pointee = Unmanaged.passRetained(state).toOpaque()
}

private let tapFinalize: MTAudioProcessingTapFinalizeCallback = { tap in
    Unmanaged<TapState>.fromOpaque(MTAudioProcessingTapGetStorage(tap)).release()
}

private let tapPrepare: MTAudioProcessingTapPrepareCallback = { tap, _, format in
    let state = Unmanaged<TapState>.fromOpaque(MTAudioProcessingTapGetStorage(tap)).takeUnretainedValue()
    let asbd = format.pointee
    let isFloat = asbd.mFormatFlags & kAudioFormatFlagIsFloat != 0
    let nonInterleaved = asbd.mFormatFlags & kAudioFormatFlagIsNonInterleaved != 0
    // Seul format traité : flottant 32 bits, stéréo, un tampon par canal
    // (celui qu'AVPlayer fournit en pratique). Sinon, son inchangé.
    state.usable = isFloat && nonInterleaved && asbd.mBitsPerChannel == 32 && asbd.mChannelsPerFrame == 2
    state.sampleRate = Float(asbd.mSampleRate)
    state.eqVersion = -1
}

private let tapProcess: MTAudioProcessingTapProcessCallback = { tap, frames, _, buffers, framesOut, flagsOut in
    let status = MTAudioProcessingTapGetSourceAudio(tap, frames, buffers, flagsOut, nil, framesOut)
    guard status == noErr else { return }
    let state = Unmanaged<TapState>.fromOpaque(MTAudioProcessingTapGetStorage(tap)).takeUnretainedValue()
    guard state.usable else { return }
    state.refreshEQ()
    let isVocals = state.role == .stemVocals
    // Pistes séparées : jamais de « voix baissée » par traitement, la voix
    // est déjà à part.
    let target: Float = state.role == .normal ? AudioEffects.singAmount : 0
    let singing = target > 0 || state.applied > 0
    let measuring = AudioEffects.visualizerOn
    guard isVocals || singing || state.eqOn || measuring else { return }

    let list = UnsafeMutableAudioBufferListPointer(buffers)
    guard list.count >= 2,
          let left = list[0].mData?.assumingMemoryBound(to: Float.self),
          let right = list[1].mData?.assumingMemoryBound(to: Float.self) else { return }
    let count = Int(framesOut.pointee)

    if isVocals {
        // Volume de la voix : suit le curseur en ~80 ms, sans claquement.
        let goal = AudioEffects.vocalGain
        let step: Float = 1 / max(1, state.sampleRate * 0.08)
        var gain = state.gain
        for i in 0..<count {
            gain += gain < goal ? min(step, goal - gain) : -min(step, gain - goal)
            left[i] *= gain
            right[i] *= gain
        }
        state.gain = gain
    }

    if singing {
        let rate = state.sampleRate
        let lowAlpha = 1 - expf(-2 * .pi * 150 / rate)
        let topAlpha = 1 - expf(-2 * .pi * 6500 / rate)
        let energyAlpha: Float = 1 / max(1, rate * 2)  // moyenne sur ~2 s
        let step: Float = 1 / max(1, rate * 0.4)       // bascule en ~0,4 s
        // 0 : mix mono, 1 : mix large (voix bien séparable du reste).
        let width = min(1, sqrtf(state.sideEnergy / max(state.midEnergy, 1e-9)) * 3)
        let maxDepth = 0.55 + 0.35 * width
        var applied = state.applied
        for i in 0..<count {
            applied += applied < target ? min(step, target - applied) : -min(step, applied - target)
            let l = left[i], r = right[i]
            let mid = (l + r) * 0.5
            let side = (l - r) * 0.5
            state.low1 += lowAlpha * (mid - state.low1)
            state.low2 += lowAlpha * (state.low1 - state.low2)
            state.top1 += topAlpha * (mid - state.top1)
            state.top2 += topAlpha * (state.top1 - state.top2)
            let lows = state.low2
            let voiceBand = state.top2 - lows
            let highs = mid - state.top2
            state.midEnergy += energyAlpha * (mid * mid - state.midEnergy)
            state.sideEnergy += energyAlpha * (side * side - state.sideEnergy)
            let depth = applied * maxDepth
            // lows + voiceBand + highs == mid : son intact quand depth vaut 0.
            let keptMid = lows + highs + (1 - depth) * voiceBand
            let makeup = 1 + 0.2 * depth
            left[i] = (keptMid + side) * makeup
            right[i] = (keptMid - side) * makeup
        }
        state.applied = applied
    }

    if state.eqOn {
        let preamp = state.preamp
        let channels = [left, right]
        for channel in 0..<2 {
            let samples = channels[channel]
            for band in 0..<5 {
                let f = state.filters[band]
                let base = (channel * 5 + band) * 4
                var x1 = state.memory[base], x2 = state.memory[base + 1]
                var y1 = state.memory[base + 2], y2 = state.memory[base + 3]
                for i in 0..<count {
                    let x = band == 0 ? samples[i] * preamp : samples[i]
                    let y = f.b0 * x + f.b1 * x1 + f.b2 * x2 - f.a1 * y1 - f.a2 * y2
                    x2 = x1; x1 = x; y2 = y1; y1 = y
                    samples[i] = y
                }
                state.memory[base] = x1; state.memory[base + 1] = x2
                state.memory[base + 2] = y1; state.memory[base + 3] = y2
            }
        }
    }

    if measuring { measureLevels(state, left: left, right: right, count: count) }
}

/// Énergie par bande (différence de passe-bas successifs), ramenée à 0…1
/// en échelle de décibels ; montée immédiate, descente douce.
private func measureLevels(_ state: TapState, left: UnsafeMutablePointer<Float>, right: UnsafeMutablePointer<Float>, count: Int) {
    let splits = AudioEffects.levelSplits
    let bands = AudioEffects.levelBands
    let alphas = splits.map { 1 - expf(-2 * .pi * $0 / state.sampleRate) }
    var energy = [Float](repeating: 0, count: bands)
    var memory = state.splits
    for i in 0..<count {
        let mono = (left[i] + right[i]) * 0.5
        var previous: Float = 0
        for k in 0..<splits.count {
            memory[k] += alphas[k] * (mono - memory[k])
            let band = memory[k] - previous
            energy[k] += band * band
            previous = memory[k]
        }
        let top = mono - previous
        energy[bands - 1] += top * top
    }
    state.splits = memory
    let frames = Float(max(1, count))
    if state.role == .stemVocals {
        // Voix séparée : son énergie est ajoutée par le traitement de l'instru.
        for band in 0..<bands { AudioEffects.vocalEnergy[band] = energy[band] / frames }
        return
    }
    let withVocals = state.role == .stemInstrumental && AudioEffects.stemsActive
    for band in 0..<bands {
        let rms = sqrtf(energy[band] / frames + (withVocals ? AudioEffects.vocalEnergy[band] : 0))
        // −54 dB → 0, −6 dB → 1 (les aigus, plus faibles, un peu remontés).
        let db = 20 * log10f(max(rms, 1e-6)) + Float(band) * 1.5
        let value = min(1, max(0, (db + 54) / 48))
        let old = AudioEffects.levels[band]
        AudioEffects.levels[band] = value > old ? value : old * 0.82 + value * 0.18
    }
}
