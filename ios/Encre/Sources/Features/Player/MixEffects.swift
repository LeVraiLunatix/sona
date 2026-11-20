import Foundation

/// Réglage du passe-haut d'un titre pendant un enchaînement AutoMix (échange des
/// basses) : écrit par le lecteur (fil principal), lu par le traitement audio du
/// titre (voir `AudioEffects`). Un tampon fixe de flottants plutôt que des propriétés
/// Swift, qu'on ne peut pas partager entre deux fils sans risque : une lecture
/// qui date d'un tic ne s'entend pas, un accès concurrent à une propriété si.
///
/// Il n'y a plus ni écho ni filtre passe-bas : ces effets étouffaient ou hachaient un
/// des deux titres au beau milieu du fondu, ce qui s'entendait comme une coupure.
final class MixControl {
    private let values: UnsafeMutablePointer<Float>

    private enum Slot: Int {
        case active, highpass, attached
    }

    init() {
        values = .allocate(capacity: 4)
        values.initialize(repeating: 0, count: 4)
    }

    deinit { values.deallocate() }

    private func read(_ slot: Slot) -> Float { values[slot.rawValue] }
    private func write(_ slot: Slot, _ value: Float) { values[slot.rawValue] = value }

    /// Le traitement audio traite les échantillons de ce titre (effet en cours).
    var isActive: Bool {
        get { read(.active) > 0.5 }
        set { write(.active, newValue ? 1 : 0) }
    }
    /// Le titre passe bien par un traitement capable d'appliquer l'effet
    /// (format stéréo flottant) : sinon, simple fondu.
    var isAttached: Bool {
        get { read(.attached) > 0.5 }
        set { write(.attached, newValue ? 1 : 0) }
    }
    var highpass: Float { get { read(.highpass) } set { write(.highpass, newValue) } }

    func apply(_ fx: MixFX) {
        highpass = fx.highpass
        isActive = true
    }

    /// Plus d'effet : le traitement laisse le son tel quel.
    func reset() {
        isActive = false
        highpass = 0
    }
}

/// État du traitement du passe-haut d'un titre, propre à son tap.
struct MixFXState {
    var highpass: Float = 0
    /// Mémoires du filtre : x1 x2 y1 y2 pour chaque canal.
    var highMemory = [Float](repeating: 0, count: 8)

    /// Prêt à servir (mémoires à zéro) ; jamais d'allocation sur le fil audio.
    mutating func prepare(sampleRate: Float) {
        highpass = 0
        highMemory = [Float](repeating: 0, count: 8)
    }
}

private struct FilterCoefficients {
    var b0: Float, b1: Float, b2: Float, a1: Float, a2: Float

    /// Biquad passe-haut du second ordre (formules RBJ), Q = 0,707.
    init(highpassFrequency frequency: Float, rate: Float) {
        let w0 = 2 * Float.pi * min(frequency, rate * 0.45) / rate
        let cosW = cosf(w0)
        let alpha = sinf(w0) / (2 * 0.7071)
        let a0 = 1 + alpha
        b0 = (1 + cosW) / 2 / a0
        b1 = -(1 + cosW) / a0
        b2 = (1 + cosW) / 2 / a0
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

/// Applique le passe-haut d'enchaînement à un bloc d'échantillons. Le réglage suit sa cible
/// en ~30 ms (pas de claquement quand le lecteur le change). Quand le filtre n'agit pas, ses
/// mémoires sont remises à zéro : à sa reprise, pas de reste d'un ancien signal.
func processMixFX(
    _ fx: inout MixFXState, control: MixControl,
    left: UnsafeMutablePointer<Float>, right: UnsafeMutablePointer<Float>, count: Int, sampleRate: Float
) {
    guard count > 0, sampleRate > 0 else { return }
    let follow = min(1, Float(count) / (sampleRate * 0.03))
    fx.highpass += (control.highpass - fx.highpass) * follow
    if fx.highpass > 25 {
        run(FilterCoefficients(highpassFrequency: fx.highpass, rate: sampleRate),
            memory: &fx.highMemory, left: left, right: right, count: count)
    } else {
        for index in 0..<8 { fx.highMemory[index] = 0 }
    }
}
