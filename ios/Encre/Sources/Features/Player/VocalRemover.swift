import AVFoundation
import MediaToolbox

/// Mode « chante » : baisse la voix du titre en cours pour chanter par-dessus.
///
/// La voix principale est presque toujours mixée au centre (identique à
/// gauche et à droite). Mais la prod aussi, en bonne partie : retirer tout
/// le centre étouffait le morceau. On ne baisse donc que la bande de la voix
/// (≈ 150 Hz – 6,5 kHz) du centre ; les basses (kick, 808) et les aigus
/// (charley, cymbales) du centre restent, comme tout ce qui est sur les côtés.
/// Sur un mix presque mono, la voix ne se sépare pas de la prod : on en
/// retire moins, pour garder un son plein.
/// Le traitement se fait dans un « tap » audio branché sur l'`AVPlayerItem`.
enum VocalRemover {
    /// 0 : son normal, 1 : voix retirée. Lu par le fil audio (changement en
    /// douceur, voir `process`).
    static var amount: Float = 0

    /// Mixage à poser sur l'item (`item.audioMix`), ou nil si l'item n'a
    /// pas encore de piste audio.
    static func audioMix(for item: AVPlayerItem) async -> AVAudioMix? {
        guard let track = try? await item.asset.loadTracks(withMediaType: .audio).first else { return nil }
        var callbacks = MTAudioProcessingTapCallbacks(
            version: kMTAudioProcessingTapCallbacksVersion_0,
            clientInfo: nil,
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
        guard status == noErr, let tap else { return nil }
        let parameters = AVMutableAudioMixInputParameters(track: track)
        parameters.audioTapProcessor = tap
        let mix = AVMutableAudioMix()
        mix.inputParameters = [parameters]
        return mix
    }
}

/// État propre à un tap (format, filtres, largeur stéréo, niveau appliqué).
private final class TapState {
    var usable = false
    var sampleRate: Float = 44_100
    // Passe-bas à deux pôles (deux 1er ordre en cascade) sur le centre.
    var low1: Float = 0, low2: Float = 0
    var top1: Float = 0, top2: Float = 0
    // Énergies moyennes du centre et des côtés : largeur du mix.
    var midEnergy: Float = 1e-6
    var sideEnergy: Float = 0
    var applied: Float = 0
}

private let tapInit: MTAudioProcessingTapInitCallback = { _, _, storageOut in
    storageOut.pointee = Unmanaged.passRetained(TapState()).toOpaque()
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
}

private let tapProcess: MTAudioProcessingTapProcessCallback = { tap, frames, _, buffers, framesOut, flagsOut in
    let status = MTAudioProcessingTapGetSourceAudio(tap, frames, buffers, flagsOut, nil, framesOut)
    guard status == noErr else { return }
    let state = Unmanaged<TapState>.fromOpaque(MTAudioProcessingTapGetStorage(tap)).takeUnretainedValue()
    let target = VocalRemover.amount
    guard state.usable, target > 0 || state.applied > 0 else { return }

    let list = UnsafeMutableAudioBufferListPointer(buffers)
    guard list.count >= 2,
          let left = list[0].mData?.assumingMemoryBound(to: Float.self),
          let right = list[1].mData?.assumingMemoryBound(to: Float.self) else { return }
    let count = Int(framesOut.pointee)
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
        let makeup = 1 + 0.2 * depth  // compense un peu le volume perdu
        left[i] = (keptMid + side) * makeup
        right[i] = (keptMid - side) * makeup
    }
    state.applied = applied
}
