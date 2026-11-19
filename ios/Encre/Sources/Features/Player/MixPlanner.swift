import Foundation

/// Compatibilité harmonique de deux tonalités sur la roue Camelot (« 8A »,
/// « 9B »…) : deux titres voisins sur la roue se mélangent sans fausse note.
enum KeyMatch: Equatable {
    /// Même tonalité.
    case same
    /// Même numéro, mode différent (do majeur / la mineur).
    case relative
    /// Numéro voisin, même mode (quinte au-dessus ou au-dessous).
    case adjacent
    case clash
    case unknown

    /// Les deux tonalités peuvent se superposer longtemps.
    var blends: Bool { self == .same || self == .relative || self == .adjacent }

    static func between(_ a: String?, _ b: String?) -> KeyMatch {
        guard let first = parse(a), let second = parse(b) else { return .unknown }
        if first.number == second.number { return first.minor == second.minor ? .same : .relative }
        let gap = min((first.number - second.number + 12) % 12, (second.number - first.number + 12) % 12)
        return gap == 1 && first.minor == second.minor ? .adjacent : .clash
    }

    private static func parse(_ code: String?) -> (number: Int, minor: Bool)? {
        guard let code, let letter = code.last, letter == "A" || letter == "B",
              let number = Int(code.dropLast()), (1...12).contains(number) else { return nil }
        return (number, letter == "A")
    }
}

/// Façon d'enchaîner deux titres.
enum MixStyle: Equatable {
    /// Fondu à puissance constante, rien d'autre (analyse absente ou effets coupés).
    case plain
    /// Tempos calés et tonalités compatibles : les deux titres se superposent,
    /// avec « échange des basses » (celles du suivant n'entrent qu'à mi-parcours,
    /// celles du précédent sortent juste après) — la technique des DJ.
    case blend
    /// Tempos calés mais tonalités qui s'entrechoquent : filtre qui se ferme sur le
    /// premier titre pendant qu'il s'ouvre sur le suivant (masque l'harmonie).
    case filter
    /// Tempos trop éloignés : le premier titre s'efface dans un écho, le suivant
    /// entre sur son premier temps.
    case echo

    var label: String {
        switch self {
        case .plain: "AutoMix"
        case .blend: "AutoMix · harmonique"
        case .filter: "AutoMix · filtre"
        case .echo: "AutoMix · écho"
        }
    }
}

/// Un enchaînement prêt à jouer : où il commence dans chaque titre, combien de
/// temps il dure, à quelle vitesse joue le suivant.
struct MixPlan: Equatable {
    /// Position de A (secondes) où commence l'enchaînement — un premier temps de
    /// mesure quand la grille de A est connue.
    var aStart: Double
    /// Position de B où il entre — son premier temps de mesure quand sa grille est connue.
    var bStart: Double
    /// Durée, en secondes de lecture de A.
    var length: Double
    /// Vitesse de B (1 : inchangée) pour tomber sur le tempo de A.
    var rate: Float
    var style: MixStyle
    var keyMatch: KeyMatch
    /// Durée d'un temps de A, en secondes (0 si inconnue) : cale l'écho.
    var beat: Double
    /// Les temps des deux titres tombent ensemble (tempos calés, grilles connues).
    var aligned: Bool
}

struct MixInputs {
    /// Fin réelle de A (silence final ignoré).
    var aEnd: Double
    /// Début de l'enchaînement d'après l'outro de A, sans grille.
    var aBase: Double
    /// Position actuelle de A.
    var position: Double
    var a: TrackAnalysis?
    /// Tempo connu d'ailleurs (fiche Deezer) quand l'analyse n'en a pas.
    var aBPM: Double?
    var b: TrackAnalysis?
    var bBPM: Double?
    /// Durée imposée dans les réglages (0 / nil : automatique).
    var fixedLength: Double?
    var effects: Bool
}

enum MixPlanner {
    /// Le tempo ne se cale que dans cet écart : au-delà, le titre serait déformé.
    static let tempoTolerance = 0.08
    /// Sous cette confiance, la tonalité ou le tempo détecté ne sert pas.
    static let minConfidence = 0.3

    static func plan(_ input: MixInputs) -> MixPlan {
        let bpmA = input.a?.bpm ?? input.aBPM
        let bpmB = input.b?.bpm ?? input.bBPM
        let keyA = confident(input.a), keyB = confident(input.b)
        let keyMatch = KeyMatch.between(keyA, keyB)

        // Tempo : B est accéléré ou ralenti pour tomber sur A, d'un temps, du
        // double ou de la moitié (140 BPM se cale sur 70).
        var rate = 1.0
        var matched = false
        if let bpmA, let bpmB, bpmA > 0, bpmB > 0 {
            for ratio in [bpmA / bpmB, bpmA / (bpmB * 2), (bpmA * 2) / bpmB] where abs(ratio - 1) <= tempoTolerance {
                rate = ratio
                matched = true
                break
            }
        }
        let tempoKnown = bpmA != nil && bpmB != nil

        let style: MixStyle
        if !input.effects {
            style = .plain
        } else if matched {
            style = keyMatch == .clash ? .filter : .blend
        } else if tempoKnown {
            style = .echo
        } else {
            style = keyMatch == .clash ? .filter : .plain
        }

        // Grille de A : ses premiers temps de mesure (analyse seulement — un tempo
        // de la fiche Deezer ne dit pas où tombent les temps).
        let gridA = grid(input.a)
        let gridB = grid(input.b)
        let beat = gridA.map { 60 / $0.bpm } ?? bpmA.map { 60 / $0 } ?? 0

        var start = input.aBase
        let available = max(2, input.aEnd - start)
        var length: Double
        if let fixed = input.fixedLength, fixed > 0 {
            length = max(1, min(fixed, available))
        } else {
            let maxLength: Double
            switch style {
            case .blend: maxLength = keyMatch.blends ? 16 : 12
            case .filter: maxLength = 8
            case .echo: maxLength = 5
            case .plain: maxLength = 12
            }
            if let gridA {
                // Mesures entières : 8, 4, 2 ou 1 (la plus longue qui tient).
                let bar = 4 * 60 / gridA.bpm
                let candidates = [8.0, 4, 2, 1].map { $0 * bar }.filter { $0 >= 2.5 && $0 <= maxLength }
                length = candidates.first { $0 <= available + 0.5 } ?? min(maxLength, max(2.5, available))
            } else {
                var legacy = input.a != nil ? min(12, max(4, available)) : 8
                if let bpmA, bpmA > 0 {
                    let bar = 240 / bpmA
                    legacy = min(16, max(bar * 2, (legacy / bar).rounded() * bar))
                }
                length = max(2, min(legacy, maxLength, available))
            }
        }

        // Départ sur un premier temps de mesure de A, jamais plus tard que la fin.
        let earliest = input.position + 0.6
        if let gridA {
            let bar = 4 * 60 / gridA.bpm
            start = gridA.downbeat + (ceil((start - gridA.downbeat) / bar)) * bar
            while start + length > input.aEnd + 0.4 && start - bar >= earliest { start -= bar }
            if start < earliest { start = gridA.downbeat + ceil((earliest - gridA.downbeat) / bar) * bar }
        } else if start < earliest {
            start = earliest
        }
        length = max(1.5, min(length, max(1.5, input.aEnd - start)))

        // Entrée de B : son premier temps de mesure à partir de son début réel.
        let introEnd = input.b?.start ?? 0
        var bStart = introEnd
        if let gridB {
            let bar = 4 * 60 / gridB.bpm
            let first = max(0, gridB.downbeat + ceil((introEnd - 0.15 - gridB.downbeat) / bar) * bar)
            // Une grille trop loin du début du son n'est pas fiable : on garde le début.
            if first - introEnd <= 6 { bStart = first }
        }

        return MixPlan(
            aStart: start, bStart: bStart, length: length, rate: Float(rate), style: style,
            keyMatch: keyMatch, beat: beat, aligned: matched && gridA != nil && gridB != nil
        )
    }

    /// Tonalité utilisable (assez sûre) d'une analyse.
    private static func confident(_ analysis: TrackAnalysis?) -> String? {
        guard let analysis, (analysis.keyConfidence ?? 0) >= minConfidence else { return nil }
        return analysis.key
    }

    /// Tempo et premier temps de mesure d'une analyse, quand la détection est assez sûre.
    private static func grid(_ analysis: TrackAnalysis?) -> (bpm: Double, downbeat: Double)? {
        guard let analysis, let bpm = analysis.bpm, bpm > 30, (analysis.tempoConfidence ?? 0) >= minConfidence,
              let downbeat = analysis.downbeat ?? analysis.beatOffset else { return nil }
        return (bpm, downbeat)
    }
}

/// Réglage des effets d'un titre à un instant de l'enchaînement.
struct MixFX: Equatable {
    /// Passe-haut (Hz) : 0 = coupé.
    var highpass: Float = 0
    /// Passe-bas (Hz) : 0 = coupé.
    var lowpass: Float = 0
    /// Niveau de l'écho (0…1) et son retard (secondes).
    var wet: Float = 0
    var delay: Float = 0.4
    /// Niveau du son direct (le titre qui s'efface dans son écho passe à 0).
    var dry: Float = 1
}

/// Volumes et effets des deux titres à l'instant `t` (0…1) de l'enchaînement.
struct MixFrame {
    var volumeA: Float
    var volumeB: Float
    var fxA = MixFX()
    var fxB = MixFX()
}

enum MixAutomation {
    /// `fx` faux : fondu à puissance constante seulement (effets coupés, ou
    /// traitement du son indisponible sur l'un des titres).
    static func frame(plan: MixPlan, t rawT: Double, gainA: Float, gainB: Float, fx: Bool) -> MixFrame {
        let t = min(1, max(0, rawT))
        // Puissance constante, avec un léger décalage façon DJ : B s'installe
        // avant que A ne s'efface vraiment.
        let tA = max(0, min(1, (t - 0.15) / 0.85))
        let tB = min(1, t / 0.85)
        var frame = MixFrame(
            volumeA: gainA * Float(cos(tA * .pi / 2)),
            volumeB: gainB * Float(sin(tB * .pi / 2))
        )
        guard fx else { return frame }

        switch plan.style {
        case .plain:
            break
        case .blend:
            // Échange des basses : celles de B n'entrent qu'à mi-parcours, celles de A sortent ensuite.
            frame.fxA.highpass = t < 0.4 ? 0 : logLerp(25, 320, (t - 0.4) / 0.5)
            frame.fxB.highpass = t < 0.5 ? 200 : (t < 0.72 ? logLerp(200, 25, (t - 0.5) / 0.22) : 0)
        case .filter:
            // Filtre qui se ferme sur A pendant qu'il s'ouvre sur B.
            frame.fxA.lowpass = logLerp(19_000, 450, smooth(t))
            frame.fxB.lowpass = t < 0.1 ? 450 : logLerp(450, 19_000, smooth((t - 0.1) / 0.8))
        case .echo:
            // A s'efface dans un écho (le volume du lecteur reste : seul le son direct baisse),
            // B entre sur son premier temps, filtre qui s'ouvre.
            let delay = plan.beat > 0 ? min(0.9, max(0.18, plan.beat * 0.75)) : 0.375
            frame.fxA.delay = Float(delay)
            frame.fxA.wet = Float(min(0.85, t / 0.35 * 0.85) * (1 - smooth((t - 0.7) / 0.3)))
            frame.fxA.dry = Float(cos(min(1, t / 0.55) * .pi / 2))
            frame.fxA.highpass = logLerp(25, 700, t)
            frame.volumeA = gainA
            frame.volumeB = gainB * Float(sin(min(1, max(0, (t - 0.15) / 0.5)) * .pi / 2))
            frame.fxB.lowpass = logLerp(2_500, 19_000, smooth(min(1, t / 0.6)))
        }
        return frame
    }

    /// Interpolation exponentielle : la hauteur d'un filtre se perçoit en octaves.
    private static func logLerp(_ from: Double, _ to: Double, _ progress: Double) -> Float {
        let p = min(1, max(0, progress))
        return Float(from * pow(to / from, p))
    }

    private static func smooth(_ progress: Double) -> Double {
        let p = min(1, max(0, progress))
        return p * p * (3 - 2 * p)
    }
}
