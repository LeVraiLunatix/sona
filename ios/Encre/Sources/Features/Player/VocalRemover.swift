import AVFoundation
import MediaToolbox

/// Mode « chante » : baisse la voix du titre en cours pour chanter par-dessus.
///
/// La voix principale est presque toujours mixée au centre (identique à
/// gauche et à droite) : on retire ce centre (« mid ») en gardant les côtés
/// (« side »). Les basses, elles aussi au centre, sont préservées grâce à un
/// filtre passe-bas sur le centre : la grosse caisse et la basse restent.
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

/// État propre à un tap (format, filtre, niveau appliqué).
private final class TapState {
    var usable = false
    var sampleRate: Float = 44_100
    var lowMid: Float = 0
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
    // Passe-bas d'environ 150 Hz sur le centre : les basses restent.
    let alpha = 1 - expf(-2 * .pi * 150 / state.sampleRate)
    var low = state.lowMid
    var applied = state.applied
    let step: Float = 1 / max(1, state.sampleRate * 0.4)  // bascule en ~0,4 s
    for i in 0..<count {
        applied += applied < target ? min(step, target - applied) : -min(step, applied - target)
        let l = left[i], r = right[i]
        let mid = (l + r) * 0.5
        let side = (l - r) * 0.5
        low += alpha * (mid - low)
        let keptMid = low + (1 - applied) * (mid - low)
        left[i] = keptMid + side
        right[i] = keptMid - side
    }
    state.lowMid = low
    state.applied = applied
}
