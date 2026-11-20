"""Tempo, grille de temps et tonalité d'un titre, pour caler l'AutoMix.

Le titre est décodé en mono à 11 025 Hz (ffmpeg), puis analysé avec numpy seul :

- **Tempo** : « flux spectral » (là où l'énergie monte, donc les attaques) ; le
  tempo est la fréquence qui revient le plus dans cette courbe (transformée de
  Fourier de la courbe, harmoniques comprises), cherchée entre 70 et 180 BPM.
- **Grille de temps** : la phase de cette même fréquence donne le premier temps ;
  parmi les quatre temps d'une mesure, celui qui porte le plus de grosse caisse
  (basses) est le premier temps de la mesure (`downbeat`).
- **Tonalité** : énergie par note (« chroma »), comparée aux profils de
  Krumhansl-Schmuckler majeur et mineur ; rendue en code Camelot (« 8B » = do
  majeur, « 8A » = la mineur), l'échelle des DJ : deux tonalités voisines sur la
  roue se mélangent sans fausse note.

Tout est mesuré sur le titre entier mais reste léger (quelques centaines de ms).
"""

from __future__ import annotations

import logging
import math
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

SAMPLE_RATE = 11_025
MAX_SECONDS = 600
MIN_SECONDS = 20

# Courbe d'attaques : 1024 points de FFT, un point tous les 256 échantillons.
ONSET_FFT = 1024
ONSET_HOP = 256
MIN_BPM = 70.0
MAX_BPM = 180.0
# Le tempo est d'abord cherché par pas de 0,25 BPM, puis affiné par pas de 0,02 :
# 0,12 BPM d'erreur (la moitié d'un pas) fait dériver la grille de 0,2 s sur trois
# minutes, et deux titres calés sur ces tempos ne battent plus ensemble.
BPM_STEP = 0.25
BPM_FINE_STEP = 0.02
BPM_FINE_SPAN = 0.4
# Fenêtres où la grille est mesurée : début et fin du titre.
GRID_WINDOW = 45.0
# Tempo habituel : on préfère, à score voisin, celui qui s'en rapproche. Centré
# sur 130 (rap, trap, pop et électro) et assez serré pour trancher l'octave :
# mesuré sur 400 boucles étiquetées + des titres réels, 115 / 0,6 donnait 65 %
# de bons tempos, 130 / 0,4 avec les harmoniques ci-dessous 83 %.
PRIOR_BPM = 130.0
PRIOR_WIDTH = 0.4  # en octaves
# (facteur de fréquence, poids) : tempo, croches, triolets / tierces, doubles-croches, moitié.
FAST_FROM = 160.0
FAST_PENALTY = 0.5  # facteur appliqué à MAX_BPM
TEMPO_HARMONICS = ((1.0, 1.0), (2.0, 0.5), (3.0, 0.3), (4.0, 0.3), (0.5, 0.3))

# Poids du profil des basses face à celui des médiums (somme de chacun = 1).
# Mesuré sur 7 titres réels de tonalité connue : 3 bonnes tonalités sans basse,
# 5 avec 0,6 (au-delà, la basse écrase l'harmonie et les titres sans 808 se perdent).
BASS_WEIGHT = 0.6

NOTES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
# Profils de Krumhansl-Schmuckler (importance de chaque note dans la gamme).
_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


@dataclass(slots=True)
class Tempo:
    bpm: float
    beat_offset: float  # un temps, mesuré sur le début du titre (secondes depuis le début du fichier)
    downbeat: float  # un premier temps de mesure (modulo 4 temps), même repère
    confidence: float  # 0…1
    # Mêmes grandeurs mesurées sur la fin du titre (là où se fait l'enchaînement), en
    # heures absolues vers la fin : un tempo qui dérive de 0,1 % décale la grille de
    # 0,2 s après trois minutes.
    out_beat_offset: float | None = None
    out_downbeat: float | None = None
    # Fiabilité du premier temps de mesure (0…1) : les basses et les accords
    # départagent mal certains titres (≈ 66 % de bons premiers temps mesurés).
    downbeat_confidence: float | None = None


@dataclass(slots=True)
class Key:
    camelot: str  # « 8B »
    name: str  # « C major »
    confidence: float  # 0…1


def decode_mono(path: Path, ffmpeg_path: str, sample_rate: int = SAMPLE_RATE) -> np.ndarray | None:
    command = [
        ffmpeg_path, "-nostdin", "-v", "error", "-i", str(path), "-t", str(MAX_SECONDS),
        "-ac", "1", "-ar", str(sample_rate), "-f", "f32le", "-",
    ]
    if shutil.which("nice"):
        command = ["nice", "-n", "10", *command]
    try:
        result = subprocess.run(command, capture_output=True, timeout=120, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.info("Décodage impossible pour %s : %s", path.name, exc)
        return None
    if result.returncode != 0 or len(result.stdout) < 4 * sample_rate * MIN_SECONDS:
        return None
    return np.frombuffer(result.stdout, dtype="<f4").astype(np.float32, copy=False)


def _frames(samples: np.ndarray, size: int, hop: int) -> np.ndarray:
    count = 1 + (len(samples) - size) // hop
    if count <= 0:
        return np.zeros((0, size), dtype=np.float32)
    strides = (samples.strides[0] * hop, samples.strides[0])
    return np.lib.stride_tricks.as_strided(samples, shape=(count, size), strides=strides, writeable=False)


def _spectrogram(samples: np.ndarray, size: int, hop: int) -> np.ndarray:
    window = np.hanning(size).astype(np.float32)
    return np.abs(np.fft.rfft(_frames(samples, size, hop) * window, axis=1))


def onset_curves(samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> tuple[np.ndarray, np.ndarray, float]:
    """(attaques de toute la bande, attaques des basses, images par seconde)."""
    mag = _spectrogram(samples, ONSET_FFT, ONSET_HOP)
    logmag = np.log1p(mag * 30.0)
    flux = np.maximum(0.0, np.diff(logmag, axis=0, prepend=logmag[:1]))
    bin_hz = sample_rate / ONSET_FFT
    top = int(4000 / bin_hz)
    kick = int(160 / bin_hz) + 1
    return flux[:, :top].sum(axis=1), flux[:, 1:kick].sum(axis=1), sample_rate / ONSET_HOP


def _beat_phase(curve: np.ndarray, bpm: float, fps: float, begin: float, end: float, centre: float) -> float:
    """Place d'un temps (secondes depuis le début du fichier, dans [0, période[), d'après la
    phase du tempo sur la fenêtre [begin, end] de la courbe d'attaques."""
    period = 60.0 / bpm
    lo = max(0, int(begin * fps))
    hi = max(lo + 8, min(len(curve), int(end * fps)))
    piece = curve[lo:hi]
    component = _fourier(piece - piece.mean(), np.array([bpm / 60.0]), fps)[0]
    # `_fourier` date la fenêtre depuis son premier point : on remet l'origine du fichier.
    angle = np.angle(component) - 2 * math.pi * (bpm / 60.0) * (lo / fps)
    return float(((-angle / (2 * math.pi)) % 1.0 * period + centre) % period)


def _detrend(curve: np.ndarray, fps: float) -> np.ndarray:
    """Retire la moyenne locale (~0,5 s) : ne restent que les attaques."""
    width = max(3, int(fps * 0.5))
    kernel = np.ones(width) / width
    local = np.convolve(curve, kernel, mode="same")
    return np.maximum(0.0, curve - local)


def _fourier(curve: np.ndarray, frequencies: np.ndarray, fps: float) -> np.ndarray:
    """Composante de la courbe à chaque fréquence (Hz) : nombres complexes."""
    times = np.arange(len(curve)) / fps
    out = np.empty(len(frequencies), dtype=np.complex128)
    for start in range(0, len(frequencies), 64):
        chunk = frequencies[start : start + 64]
        out[start : start + 64] = (curve[None, :] * np.exp(-2j * np.pi * chunk[:, None] * times[None, :])).sum(axis=1)
    return out


def detect_tempo(samples: np.ndarray, sample_rate: int = SAMPLE_RATE, end: float | None = None) -> Tempo | None:
    """`end` : fin réelle du son (secondes) quand on la connaît : la grille de la fin
    se mesure juste avant, pas dans le silence final."""
    if len(samples) < sample_rate * MIN_SECONDS:
        return None
    full, kick, fps = onset_curves(samples, sample_rate)
    full, kick = _detrend(full, fps), _detrend(kick, fps)
    if full.max() <= 0:
        return None
    # La musique entière n'est pas nécessaire : une fenêtre de 2 min au milieu suffit.
    span = int(fps * 120)
    if len(full) > span:
        begin = (len(full) - span) // 2
        window = slice(begin, begin + span)
    else:
        window = slice(0, len(full))
    base = full[window] - full[window].mean()

    bpms = np.arange(MIN_BPM, MAX_BPM + 0.01, BPM_STEP)
    freqs = bpms / 60.0
    # Le tempo ressort aussi à ses multiples (croches, doubles-croches) et à sa
    # moitié (la mesure en deux) : on additionne ces harmoniques. Sans elles, un
    # 140 BPM à charleys en triolets se lisait « 105 » (3/4 du tempo).
    score = sum(weight * np.abs(_fourier(base, freqs * factor, fps)) for factor, weight in TEMPO_HARMONICS)
    prior = np.exp(-0.5 * (np.log2(bpms / PRIOR_BPM) / PRIOR_WIDTH) ** 2)
    # Au-delà de 160, un tempo est plus souvent le double d'un 80-90 (boom bap,
    # r'n'b) que la réalité : on le pénalise (jusqu'à moitié moins à 180).
    prior *= 1.0 - (1.0 - FAST_PENALTY) * np.clip((bpms - FAST_FROM) / (MAX_BPM - FAST_FROM), 0.0, 1.0)
    ranked = score * prior
    best = int(np.argmax(ranked))
    bpm = float(bpms[best])
    confidence = float(min(1.0, max(0.0, (ranked[best] - np.median(ranked)) / (ranked[best] + 1e-9))))

    # Affinage : même score, pas de 0,02 BPM autour du meilleur pas (le vainqueur
    # est déjà choisi, l'a priori ne joue plus).
    fine = np.arange(bpm - BPM_FINE_SPAN, bpm + BPM_FINE_SPAN + 1e-9, BPM_FINE_STEP)
    fine_score = sum(weight * np.abs(_fourier(base, fine / 60.0 * factor, fps)) for factor, weight in TEMPO_HARMONICS)
    bpm = float(fine[int(np.argmax(fine_score))])

    # Phase de la grille. Les basses (grosse caisse) tombent sur les temps, alors que
    # les charleys tombent entre : sur la courbe de toute la bande, ils inverseraient
    # la phase. On pondère donc les basses en priorité.
    period = 60.0 / bpm
    phase_curve = kick / max(kick.max(), 1e-9) * 2.0 + full / max(full.max(), 1e-9) * 0.5
    phase_curve = phase_curve - phase_curve.mean()
    # Une image d'analyse date de son milieu, pas de son début.
    centre = ONSET_FFT / 2 / sample_rate
    duration = len(samples) / sample_rate
    # Début du titre (là où entre le titre qui arrive) et fin (là où il sort).
    beat_offset = _beat_phase(phase_curve, bpm, fps, 0.0, GRID_WINDOW, centre)
    out_end = min(duration, end) if end else duration
    out_beat = _beat_phase(phase_curve, bpm, fps, max(0.0, out_end - GRID_WINDOW), out_end, centre)

    # Premier temps de mesure : le temps (sur 4) dont la grosse caisse est la plus
    # forte, en valeur médiane sur les mesures (une attaque tient en une ou deux
    # images : le pic compte, pas une moyenne qui la dilue ; la médiane ignore
    # les breaks et les roulements).
    beats = np.arange(max(int((duration - beat_offset) / period) - 1, 0))
    index = np.round((beat_offset + beats * period - centre) * fps).astype(int)
    valid = (index >= 2) & (index < len(kick) - 2)
    peaks = {int(k): kick[i - 2 : i + 3].max() for k, i in zip(beats[valid], index[valid])}
    weights = np.array([np.median([v for k, v in peaks.items() if k % 4 == slot] or [0.0]) for slot in range(4)])
    # Les accords changent le plus souvent sur le premier temps d'une mesure : le
    # changement de notes autour de chaque temps départage les titres dont la
    # grosse caisse tombe sur tous les temps (mesuré sur 168 boucles de départ
    # connu : 53 % de bons premiers temps avec la seule grosse caisse, 66 % avec).
    kicked = beats[valid]
    change = _harmonic_change(samples, sample_rate, beat_offset + kicked * period, period)
    novelty = np.array([change[kicked % 4 == slot].mean() if np.any(kicked % 4 == slot) else 0.0 for slot in range(4)])
    evidence = weights / max(weights.max(), 1e-9) + novelty / max(novelty.max(), 1e-9)
    slot = int(np.argmax(evidence))
    downbeat = float((beat_offset + slot * period) % (4 * period))
    # Fiabilité : écart entre le meilleur temps et le suivant, rapporté au meilleur.
    ordered = np.sort(evidence)
    downbeat_confidence = float(min(1.0, max(0.0, (ordered[-1] - ordered[-2]) / max(ordered[-1], 1e-9) * 2.0)))
    # Le premier temps de mesure de la fin : même place dans la mesure que celui du
    # début (un titre ne change pas de mesure en route), sur la grille de la fin.
    # Heures absolues, 10 s avant la fin : l'enchaînement s'y place, et une grille
    # recalée juste à côté ne cumule pas l'erreur de tempo de tout le titre.
    reference = max(0.0, out_end - 10.0)
    out_beat = out_beat + math.floor((reference - out_beat) / period) * period
    out_index = round((out_beat - beat_offset) / period)
    out_downbeat = float(out_beat + ((slot - out_index) % 4) * period)
    return Tempo(
        bpm=round(bpm, 2), beat_offset=round(beat_offset, 3), downbeat=round(downbeat, 3),
        confidence=round(confidence, 2), out_beat_offset=round(out_beat, 3), out_downbeat=round(out_downbeat, 3),
        downbeat_confidence=round(downbeat_confidence, 2),
    )


def _harmonic_change(samples: np.ndarray, sample_rate: int, times: np.ndarray, period: float) -> np.ndarray:
    """Pour chaque instant (s), distance entre les notes jouées juste avant et
    juste après (0 = mêmes notes, 1 = rien en commun)."""
    size, hop = 2048, 1024
    mag = _spectrogram(samples, size, hop)
    freqs = np.fft.rfftfreq(size, 1 / sample_rate)
    usable = (freqs >= 80) & (freqs <= 1000)
    pitch = np.round(12 * np.log2(freqs[usable] / 440.0) + 9).astype(int) % 12
    chroma = np.stack([mag[:, usable][:, pitch == note].sum(axis=1) for note in range(12)], axis=1)
    sums = np.vstack([np.zeros(12), np.cumsum(chroma, axis=0)])
    fps = sample_rate / hop

    def mean_chroma(begin: np.ndarray, end: np.ndarray) -> np.ndarray:
        i = np.clip(np.round(begin * fps).astype(int), 0, len(chroma) - 1)
        j = np.clip(np.maximum(np.round(end * fps).astype(int), i + 1), 1, len(chroma))
        return (sums[j] - sums[i]) / np.maximum(j - i, 1)[:, None]

    before = mean_chroma(times - 0.9 * period, times - 0.1 * period)
    after = mean_chroma(times + 0.1 * period, times + 0.9 * period)
    norm = np.linalg.norm(before, axis=1) * np.linalg.norm(after, axis=1)
    return np.where(norm > 0, 1.0 - (before * after).sum(axis=1) / np.maximum(norm, 1e-12), 0.0)


def camelot(pitch: int, minor: bool) -> str:
    """Code Camelot d'une tonalité (pitch : 0 = do)."""
    major_pitch = (pitch + 3) % 12 if minor else pitch
    number = (major_pitch * 7) % 12
    number = (number + 7) % 12 + 1
    return f"{number}{'A' if minor else 'B'}"


def bass_chroma(samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Notes jouées dans les basses (38–150 Hz), somme sur tout le titre, total = 1.

    Le profil de gamme seul confond souvent la tonique et sa quinte (la mineur
    pour ré mineur) : les accords sont les mêmes, mais la basse (808, basse
    synthé) joue la tonique. Fenêtre longue pour séparer les notes graves (une
    case = 0,7 Hz, un demi-ton à 40 Hz = 2,4 Hz) ; traité par lots pour ne pas
    dépasser quelques dizaines de Mo sur un titre de dix minutes.
    """
    size, hop = 16384, 4096
    freqs = np.fft.rfftfreq(size, 1 / sample_rate)
    usable = (freqs >= 38) & (freqs <= 150)
    pitch = np.round(12 * np.log2(freqs[usable] / 440.0) + 9).astype(int) % 12
    window = np.hanning(size).astype(np.float32)
    frames = _frames(samples, size, hop)
    total = np.zeros(12)
    for start in range(0, len(frames), 128):
        mag = np.abs(np.fft.rfft(frames[start : start + 128] * window, axis=1))[:, usable]
        for note in range(12):
            total[note] += mag[:, pitch == note].sum()
    return total / max(total.sum(), 1e-9)


def detect_key(samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> Key | None:
    if len(samples) < sample_rate * MIN_SECONDS:
        return None
    size, hop = 4096, 2048
    mag = _spectrogram(samples, size, hop)
    if len(mag) < 8:
        return None
    freqs = np.fft.rfftfreq(size, 1 / sample_rate)
    # 80 Hz – 1 kHz : là où vivent les notes ; au-dessus, surtout des harmoniques.
    usable = (freqs >= 80) & (freqs <= 1000)
    # Note (0 = do) de chaque case de fréquence.
    pitch = np.round(12 * np.log2(freqs[usable] / 440.0) + 9).astype(int) % 12
    # Magnitude brute : toute compression (racine, log) aplatit le profil et
    # fait gagner le majeur à tort (mesuré sur 15 titres de référence : 11 bonnes
    # tonalités contre 8 avec la racine carrée, et ce quelle que soit la bande).
    magnitude = mag[:, usable]
    chroma = np.zeros((len(mag), 12))
    for note in range(12):
        chroma[:, note] = magnitude[:, pitch == note].sum(axis=1)
    # Chaque image compte pareil, qu'elle soit forte ou non.
    totals = chroma.sum(axis=1, keepdims=True)
    chroma = chroma / np.maximum(totals, 1e-9)
    profile = chroma.mean(axis=0) + BASS_WEIGHT * bass_chroma(samples, sample_rate)
    if profile.std() < 1e-6:
        return None
    best = (-2.0, 0, False)
    scores = []
    for minor, template in ((False, _MAJOR), (True, _MINOR)):
        for tonic in range(12):
            score = float(np.corrcoef(profile, np.roll(template, tonic))[0, 1])
            scores.append(score)
            if score > best[0]:
                best = (score, tonic, minor)
    score, tonic, minor = best
    runner_up = sorted(scores)[-2]
    return Key(
        camelot=camelot(tonic, minor),
        name=f"{NOTES[tonic]} {'minor' if minor else 'major'}",
        confidence=round(float(min(1.0, max(0.0, (score - runner_up) * 4 + 0.3))), 2),
    )


def analyze_features(path: Path, ffmpeg_path: str, end: float | None = None) -> tuple[Tempo | None, Key | None]:
    samples = decode_mono(path, ffmpeg_path)
    if samples is None:
        return None, None
    try:
        return detect_tempo(samples, end=end), detect_key(samples)
    except (ValueError, FloatingPointError, MemoryError) as exc:
        logger.info("Tempo / tonalité illisibles pour %s : %s", path.name, exc)
        return None, None
