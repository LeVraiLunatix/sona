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

/// Façon d'enchaîner deux titres. Dans tous les cas, un fondu enchaîné à puissance
/// constante : jamais de filtre qui étouffe un titre ni d'écho qui répète, c'était
/// ce qui faisait « couper » le son.
enum MixStyle: Equatable {
    /// Fondu simple : analyse absente, tempos trop éloignés ou grilles inconnues.
    case plain
    /// Tempos calés (le suivant est ralenti ou accéléré d'au plus 6 %) : les grosses
    /// caisses des deux titres tombent ensemble, entrée sur un premier temps de mesure.
    case blend

    var label: String {
        switch self {
        case .plain: "AutoMix"
        case .blend: "AutoMix · calé"
        }
    }
}

/// Grille de temps d'un titre à l'endroit où elle sert (fin de A, début de B).
struct BeatGrid: Equatable {
    /// Tempo mesuré (battements par minute).
    var bpm: Double
    /// Un premier temps de mesure (secondes depuis le début du fichier).
    var downbeat: Double
    /// Fiabilité du premier temps de mesure (0…1) : les basses et les accords le
    /// départagent mal sur certains titres. Les temps, eux, sont sûrs.
    var barConfidence: Double

    var period: Double { 60 / bpm }
    var bar: Double { 4 * 60 / bpm }
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
    /// Durée d'un temps de A, en secondes (0 si inconnue).
    var beat: Double
    /// Les temps des deux titres tombent ensemble (tempos calés, grilles connues).
    var aligned: Bool
    /// Échange des basses (passe-haut qui glisse de l'un à l'autre) : seulement quand les
    /// temps sont calés et les tonalités compatibles.
    var bassSwap: Bool
}

struct MixInputs {
    /// Fin réelle de A (silence final ignoré).
    var aEnd: Double
    /// Début de l'enchaînement d'après l'outro de A, sans grille.
    var aBase: Double
    /// Position actuelle de A.
    var position: Double
    var a: TrackAnalysis?
    /// Tempo connu d'ailleurs (fiche Deezer) quand l'analyse n'en a pas : sert seulement
    /// à choisir une durée en mesures, jamais à caler.
    var aBPM: Double?
    var b: TrackAnalysis?
    var bBPM: Double?
    /// Durée imposée dans les réglages (0 / nil : automatique).
    var fixedLength: Double?
    var effects: Bool
    /// Le suivant ne vient pas du même album : rien ne lie les deux titres, fondu plus long.
    var albumBreak = false
    /// Repli : pas de calage, simple fondu (le suivant n'était pas prêt à temps).
    var forcePlain = false
    /// Délai minimal avant le début de l'enchaînement (secondes).
    var lead = 0.8
}

/// Calculs purs du calage (aucun accès au lecteur) : testés par `tests/automix_reference.py`,
/// qui en est la copie fidèle en Python.
enum MixMath {
    /// Plus petit `origin + k × step` supérieur ou égal à `t` (k entier, positif ou non).
    static func firstBoundary(atOrAfter t: Double, origin: Double, step: Double) -> Double {
        origin + ceil((t - origin) / step - 1e-9) * step
    }

    /// Vitesse à donner à B (tempo `bpmB`) pour tomber sur A (`bpmA`) : d'un temps, du double
    /// ou de la moitié (140 BPM se cale sur 70), dans l'écart toléré. `nil` : trop éloignés.
    static func tempoRatio(bpmA: Double, bpmB: Double, tolerance: Double) -> Double? {
        guard bpmA > 0, bpmB > 0 else { return nil }
        let candidates = [bpmA / bpmB, bpmA / (bpmB * 2), (bpmA * 2) / bpmB]
        guard let best = candidates.min(by: { abs($0 - 1) < abs($1 - 1) }), abs(best - 1) <= tolerance else { return nil }
        return abs(best - 1) < 0.0005 ? 1 : best
    }

    /// Gains (A qui sort, B qui entre) à puissance constante : cos² + sin² = 1, le volume
    /// perçu ne creuse ni ne gonfle au milieu du fondu.
    static func equalPower(_ rawT: Double) -> (a: Double, b: Double) {
        let t = min(1, max(0, rawT))
        return (cos(t * .pi / 2), sin(t * .pi / 2))
    }
}

enum MixPlanner {
    /// Le tempo ne se cale que dans cet écart : au-delà, le titre serait déformé.
    static let tempoTolerance = 0.06
    /// Sous cette confiance, la tonalité ou le tempo détecté ne sert pas.
    static let minConfidence = 0.3
    /// Sous cette confiance, on ne se fie pas au premier temps de mesure : les temps sont
    /// calés mais deux phrases musicales peuvent se contrarier, l'enchaînement reste court.
    static let minBarConfidence = 0.25
    /// Durée la plus courte d'un enchaînement calé sur des mesures.
    static let minLength = 2.5

    static func plan(_ input: MixInputs) -> MixPlan {
        let keyMatch = KeyMatch.between(confident(input.a), confident(input.b))
        let bpmA = input.a?.bpm ?? input.aBPM
        let gridA = outGrid(input.a)
        let gridB = inGrid(input.b)

        // Tempo : B est accéléré ou ralenti pour tomber sur A. Seules des grilles mesurées
        // permettent de caler (sans elles, on ne sait pas où tombent les temps).
        var rate = 1.0
        var aligned = false
        if !input.forcePlain, let gridA, let gridB,
           let ratio = MixMath.tempoRatio(bpmA: gridA.bpm, bpmB: gridB.bpm, tolerance: tempoTolerance) {
            rate = ratio
            aligned = true
        }
        let barsTrusted = (gridA?.barConfidence ?? 0) >= minBarConfidence && (gridB?.barConfidence ?? 0) >= minBarConfidence

        // Durée maximale d'après la façon d'enchaîner.
        let maxLength: Double
        if aligned {
            switch keyMatch {
            case .same, .relative, .adjacent: maxLength = barsTrusted ? 16 : 8
            case .unknown: maxLength = 8
            case .clash: maxLength = 6
            }
        } else {
            maxLength = input.albumBreak ? 12 : 8
        }

        let earliest = input.position + input.lead
        var start = max(input.aBase, input.aEnd - maxLength)
        var length = maxLength
        if let fixed = input.fixedLength, fixed > 0 {
            length = max(1, min(fixed, max(1, input.aEnd - earliest)))
            start = max(input.aBase, input.aEnd - length)
        }

        if let gridA, !input.forcePlain {
            // Départ sur un premier temps de mesure de A, durée en mesures entières (8, 4, 2
            // ou 1 : la plus longue qui tient avant la fin du titre).
            let lengths: [Double] = input.fixedLength.map { _ in [length] }
                ?? [8, 4, 2, 1].map { $0 * gridA.bar }.filter { $0 >= minLength && $0 <= maxLength + 0.01 }
            if let found = barPlacement(grid: gridA, lengths: lengths, aBase: input.aBase, aEnd: input.aEnd, earliest: earliest) {
                start = found.start
                length = found.length
            } else {
                start = MixMath.firstBoundary(atOrAfter: earliest - 0.05, origin: gridA.downbeat, step: gridA.bar)
                length = max(1.5, min(length, input.aEnd - start))
            }
        } else {
            // Sans grille : durée arrondie à des mesures entières si on connaît un tempo.
            if input.fixedLength == nil, let bpmA, bpmA > 0 {
                let bar = 240 / bpmA
                let bars = max(1, (maxLength / bar).rounded())
                length = min(maxLength + bar / 2, bars * bar)
                length = max(minLength, length)
            }
            // Le fondu se termine à peu près avec A, sans commencer avant son outro ni avant `earliest`.
            start = max(max(input.aBase, input.aEnd - length), earliest)
            length = max(1.5, min(length, input.aEnd - start))
        }

        // Entrée de B : son premier temps de mesure à partir de son début réel.
        let introEnd = input.b?.start ?? 0
        var bStart = introEnd
        if let gridB {
            let first = max(0, MixMath.firstBoundary(atOrAfter: introEnd - 0.15, origin: gridB.downbeat, step: gridB.bar))
            // Une grille trop loin du début du son n'est pas fiable : on garde le début.
            if first - introEnd <= 6 { bStart = first }
        }

        return MixPlan(
            aStart: start, bStart: bStart, length: length, rate: Float(rate),
            style: aligned ? .blend : .plain, keyMatch: keyMatch,
            beat: gridA?.period ?? bpmA.map { 60 / $0 } ?? 0, aligned: aligned,
            bassSwap: aligned && input.effects && keyMatch.blends
        )
    }

    /// Première mesure de A (premier temps) où loger l'enchaînement : la plus longue des
    /// `lengths` qui tient entre `earliest` et la fin de A, au plus près de `aBase` (début de
    /// l'outro) mais jamais assez tard pour que le suivant dépasse la fin du titre.
    static func barPlacement(
        grid: BeatGrid, lengths: [Double], aBase: Double, aEnd: Double, earliest: Double
    ) -> (start: Double, length: Double)? {
        for length in lengths {
            var start = MixMath.firstBoundary(atOrAfter: max(aBase, aEnd - length) - 0.05, origin: grid.downbeat, step: grid.bar)
            let overrun = start + length - (aEnd + 0.4)
            if overrun > 0 { start -= ceil(overrun / grid.bar) * grid.bar }
            if start >= earliest - 0.05 { return (start, length) }
        }
        return nil
    }

    /// Tonalité utilisable (assez sûre) d'une analyse.
    private static func confident(_ analysis: TrackAnalysis?) -> String? {
        guard let analysis, (analysis.keyConfidence ?? 0) >= minConfidence else { return nil }
        return analysis.key
    }

    /// Grille de la fin du titre (là où il sort) : mesurée sur sa fin quand le serveur la
    /// donne (le tempo dérive un peu sur trois minutes), sinon celle du début.
    static func outGrid(_ analysis: TrackAnalysis?) -> BeatGrid? {
        guard let analysis, let bpm = analysis.bpm, bpm > 30, (analysis.tempoConfidence ?? 0) >= minConfidence,
              let downbeat = analysis.outDownbeat ?? analysis.outBeatOffset ?? analysis.downbeat ?? analysis.beatOffset
        else { return nil }
        let measured = analysis.outDownbeat != nil
        return BeatGrid(bpm: bpm, downbeat: downbeat, barConfidence: measured ? analysis.downbeatConfidence ?? 0.5 : 0)
    }

    /// Grille du début du titre (là où il entre).
    static func inGrid(_ analysis: TrackAnalysis?) -> BeatGrid? {
        guard let analysis, let bpm = analysis.bpm, bpm > 30, (analysis.tempoConfidence ?? 0) >= minConfidence,
              let downbeat = analysis.downbeat ?? analysis.beatOffset else { return nil }
        return BeatGrid(bpm: bpm, downbeat: downbeat, barConfidence: analysis.downbeatConfidence ?? 0.5)
    }
}

/// Réglage des effets d'un titre à un instant de l'enchaînement : un seul passe-haut.
struct MixFX: Equatable {
    /// Passe-haut (Hz) : 0 = coupé.
    var highpass: Float = 0
}

/// Volumes et effets des deux titres à l'instant `t` (0…1) de l'enchaînement.
struct MixFrame {
    var volumeA: Float
    var volumeB: Float
    var fxA = MixFX()
    var fxB = MixFX()
}

enum MixAutomation {
    /// Fondu à puissance constante ; `fx` vrai et plan à échange des basses : passe-haut qui
    /// glisse (continu, jamais de coupure) — B n'entre avec ses basses qu'à mi-parcours, celles
    /// de A sortent ensuite.
    static func frame(plan: MixPlan, t rawT: Double, gainA: Float, gainB: Float, fx: Bool) -> MixFrame {
        let t = min(1, max(0, rawT))
        let gains = MixMath.equalPower(t)
        var frame = MixFrame(volumeA: gainA * Float(gains.a), volumeB: gainB * Float(gains.b))
        if fx && plan.bassSwap {
            frame.fxA.highpass = t < 0.4 ? 0 : logLerp(25, 320, (t - 0.4) / 0.5)
            frame.fxB.highpass = t < 0.5 ? 200 : (t < 0.72 ? logLerp(200, 25, (t - 0.5) / 0.22) : 0)
        }
        return frame
    }

    /// Interpolation exponentielle : la hauteur d'un filtre se perçoit en octaves.
    private static func logLerp(_ from: Double, _ to: Double, _ progress: Double) -> Float {
        let p = min(1, max(0, progress))
        return Float(from * pow(to / from, p))
    }
}
