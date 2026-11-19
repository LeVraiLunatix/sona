import Foundation

/// Réglages d'effets d'un titre pendant un enchaînement AutoMix : écrits par le
/// lecteur (fil principal), lus par le traitement audio du titre (voir
/// `AudioEffects`). Un tampon fixe de flottants plutôt que des propriétés
/// Swift, qu'on ne peut pas partager entre deux fils sans risque : une lecture
/// qui date d'un tic ne s'entend pas, un accès concurrent à une propriété si.
final class MixControl {
    private let values: UnsafeMutablePointer<Float>

    private enum Slot: Int {
        case active, highpass, lowpass, wet, delay, dry, attached
    }

    init() {
        values = .allocate(capacity: 8)
        values.initialize(repeating: 0, count: 8)
        reset()
        values[Slot.attached.rawValue] = 0
    }

    deinit { values.deallocate() }

    private func read(_ slot: Slot) -> Float { values[slot.rawValue] }
    private func write(_ slot: Slot, _ value: Float) { values[slot.rawValue] = value }

    /// Le traitement audio traite les échantillons de ce titre (effets en cours).
    var isActive: Bool {
        get { read(.active) > 0.5 }
        set { write(.active, newValue ? 1 : 0) }
    }
    /// Le titre passe bien par un traitement capable d'appliquer ces effets
    /// (format stéréo flottant) : sinon, simple fondu.
    var isAttached: Bool {
        get { read(.attached) > 0.5 }
        set { write(.attached, newValue ? 1 : 0) }
    }
    var highpass: Float { get { read(.highpass) } set { write(.highpass, newValue) } }
    var lowpass: Float { get { read(.lowpass) } set { write(.lowpass, newValue) } }
    var wet: Float { get { read(.wet) } set { write(.wet, newValue) } }
    var delay: Float { get { read(.delay) } set { write(.delay, newValue) } }
    var dry: Float { get { read(.dry) } set { write(.dry, newValue) } }

    func apply(_ fx: MixFX) {
        highpass = fx.highpass
        lowpass = fx.lowpass
        wet = fx.wet
        delay = fx.delay
        dry = fx.dry
        isActive = true
    }

    /// Plus d'effets : le traitement laisse le son tel quel.
    func reset() {
        isActive = false
        highpass = 0
        lowpass = 0
        wet = 0
        delay = 0.4
        dry = 1
    }
}

/// État du traitement d'effets d'un titre (filtres et écho), propre à son tap.
struct MixFXState {
    var highpass: Float = 0
    var lowpass: Float = 20_000
    var wet: Float = 0
    var dry: Float = 1
    /// Mémoires des filtres : x1 x2 y1 y2 pour chaque canal.
    var highMemory = [Float](repeating: 0, count: 8)
    var lowMemory = [Float](repeating: 0, count: 8)
    var echoLeft: [Float] = []
    var echoRight: [Float] = []
    var echoPosition = 0

    /// Tampons d'écho de 2 s (alloués ici, jamais sur le fil audio).
    mutating func prepare(sampleRate: Float) {
        let size = max(2, Int(sampleRate * 2) + 1)
        echoLeft = [Float](repeating: 0, count: size)
        echoRight = [Float](repeating: 0, count: size)
        echoPosition = 0
        highMemory = [Float](repeating: 0, count: 8)
        lowMemory = [Float](repeating: 0, count: 8)
    }
}

private struct FilterCoefficients {
    var b0: Float, b1: Float, b2: Float, a1: Float, a2: Float

    /// Biquad passe-haut ou passe-bas du second ordre (formules RBJ), Q = 0,707.
    init(highpass: Bool, frequency: Float, rate: Float) {
        let w0 = 2 * Float.pi * min(frequency, rate * 0.45) / rate
        let cosW = cosf(w0)
        let alpha = sinf(w0) / (2 * 0.7071)
        let a0 = 1 + alpha
        if highpass {
            b0 = (1 + cosW) / 2 / a0
            b1 = -(1 + cosW) / a0
            b2 = (1 + cosW) / 2 / a0
        } else {
            b0 = (1 - cosW) / 2 / a0
            b1 = (1 - cosW) / a0
            b2 = (1 - cosW) / 2 / a0
        }
        a1 = -2 * cosW / a0
        a2 = (1 - alpha) / a0
    }
}

private func run(
    _ c: FilterCoefficients, memory: inout [Float],
    left: UnsafeMutablePointer<Float>, right: UnsafeMutablePointer<Float>, count: Int
) {
    for channel in 0..<2 {
        let samples = channel == 0 ? left : right
        let base = channel * 4
        var x1 = memory[base], x2 = memory[base + 1], y1 = memory[base + 2], y2 = memory[base + 3]
        for i in 0..<count {
            let x = samples[i]
            let y = c.b0 * x + c.b1 * x1 + c.b2 * x2 - c.a1 * y1 - c.a2 * y2
            x2 = x1; x1 = x; y2 = y1; y1 = y
            samples[i] = y
        }
        memory[base] = x1; memory[base + 1] = x2; memory[base + 2] = y1; memory[base + 3] = y2
    }
}

/// Applique les effets d'enchaînement à un bloc d'échantillons : passe-haut,
/// passe-bas, puis écho en ping-pong et niveau du son direct. Les réglages
/// suivent leur cible en ~30 ms (pas de claquement quand le lecteur les change).
func processMixFX(
    _ fx: inout MixFXState, control: MixControl,
    left: UnsafeMutablePointer<Float>, right: UnsafeMutablePointer<Float>, count: Int, sampleRate: Float
) {
    guard count > 0, sampleRate > 0, !fx.echoLeft.isEmpty else { return }
    let follow = min(1, Float(count) / (sampleRate * 0.03))
    fx.highpass += (control.highpass - fx.highpass) * follow
    fx.lowpass += ((control.lowpass > 0 ? control.lowpass : 20_000) - fx.lowpass) * follow
    fx.wet += (control.wet - fx.wet) * follow
    fx.dry += (control.dry - fx.dry) * follow

    if fx.highpass > 25 {
        run(FilterCoefficients(highpass: true, frequency: fx.highpass, rate: sampleRate),
            memory: &fx.highMemory, left: left, right: right, count: count)
    }
    if fx.lowpass < 18_500 {
        run(FilterCoefficients(highpass: false, frequency: fx.lowpass, rate: sampleRate),
            memory: &fx.lowMemory, left: left, right: right, count: count)
    }

    guard fx.wet > 0.002 || abs(fx.dry - 1) > 0.002 || control.wet > 0 else { return }
    let size = fx.echoLeft.count
    let delay = max(1, min(size - 1, Int(control.delay * sampleRate)))
    let feedback: Float = 0.5
    let wet = fx.wet, dry = fx.dry
    var position = fx.echoPosition
    // Tampons sortis de la structure le temps du bloc (pas de copie : on la vide d'abord).
    var echoLeft = fx.echoLeft
    var echoRight = fx.echoRight
    fx.echoLeft = []
    fx.echoRight = []
    for i in 0..<count {
        var read = position - delay
        if read < 0 { read += size }
        let delayedLeft = echoLeft[read], delayedRight = echoRight[read]
        let inLeft = left[i], inRight = right[i]
        // Ping-pong : chaque canal alimente l'écho de l'autre.
        echoLeft[position] = inLeft + feedback * delayedRight
        echoRight[position] = inRight + feedback * delayedLeft
        left[i] = inLeft * dry + wet * delayedLeft
        right[i] = inRight * dry + wet * delayedRight
        position += 1
        if position == size { position = 0 }
    }
    fx.echoLeft = echoLeft
    fx.echoRight = echoRight
    fx.echoPosition = position
}
