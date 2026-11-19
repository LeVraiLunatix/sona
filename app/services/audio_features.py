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
# Tempo habituel : on préfère, à score voisin, celui qui s'en rapproche.
PRIOR_BPM = 115.0
PRIOR_WIDTH = 0.6  # en octaves

NOTES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
# Profils de Krumhansl-Schmuckler (importance de chaque note dans la gamme).
_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


@dataclass(slots=True)
class Tempo:
    bpm: float
    beat_offset: float  # un temps (secondes depuis le début du fichier)
    downbeat: float  # un premier temps de mesure (modulo 4 temps)
    confidence: float  # 0…1


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


def detect_tempo(samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> Tempo | None:
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

    bpms = np.arange(MIN_BPM, MAX_BPM + 0.01, 0.25)
    freqs = bpms / 60.0
    fundamental = _fourier(base, freqs, fps)
    # Le tempo ressort aussi à son double : on additionne les harmoniques.
    double = _fourier(base, freqs * 2, fps)
    score = np.abs(fundamental) + 0.5 * np.abs(double)
    prior = np.exp(-0.5 * (np.log2(bpms / PRIOR_BPM) / PRIOR_WIDTH) ** 2)
    ranked = score * prior
    best = int(np.argmax(ranked))
    bpm = float(bpms[best])
    confidence = float(min(1.0, max(0.0, (ranked[best] - np.median(ranked)) / (ranked[best] + 1e-9))))

    # Phase sur le titre entier (la grille doit tenir du début à la fin). Les
    # basses (grosse caisse) tombent sur les temps, alors que les charleys
    # tombent entre : sur la courbe de toute la bande, ils inverseraient la
    # phase. On pondère donc les basses en priorité.
    period = 60.0 / bpm
    phase_curve = kick / max(kick.max(), 1e-9) * 2.0 + full / max(full.max(), 1e-9) * 0.5
    component = _fourier(phase_curve - phase_curve.mean(), np.array([bpm / 60.0]), fps)[0]
    # Une image d'analyse date de son milieu, pas de son début.
    centre = ONSET_FFT / 2 / sample_rate
    beat_offset = float(((-np.angle(component) / (2 * math.pi)) % 1.0 * period + centre) % period)
    # Premier temps de mesure : le temps (sur 4) qui porte le plus de grosse caisse.
    times = np.arange(len(kick)) / fps + centre
    beat_index = np.floor((times - beat_offset) / period + 0.5).astype(int)
    near = np.abs(times - (beat_offset + beat_index * period)) < period * 0.18
    weights = np.zeros(4)
    for slot in range(4):
        mask = near & (beat_index % 4 == slot)
        weights[slot] = kick[mask].sum() / max(1, mask.sum())
    downbeat = float((beat_offset + int(np.argmax(weights)) * period) % (4 * period))
    return Tempo(bpm=round(bpm, 2), beat_offset=round(beat_offset, 3), downbeat=round(downbeat, 3), confidence=round(confidence, 2))


def camelot(pitch: int, minor: bool) -> str:
    """Code Camelot d'une tonalité (pitch : 0 = do)."""
    major_pitch = (pitch + 3) % 12 if minor else pitch
    number = (major_pitch * 7) % 12
    number = (number + 7) % 12 + 1
    return f"{number}{'A' if minor else 'B'}"


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
    profile = chroma.mean(axis=0)
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


def analyze_features(path: Path, ffmpeg_path: str) -> tuple[Tempo | None, Key | None]:
    samples = decode_mono(path, ffmpeg_path)
    if samples is None:
        return None, None
    try:
        return detect_tempo(samples), detect_key(samples)
    except (ValueError, FloatingPointError, MemoryError) as exc:
        logger.info("Tempo / tonalité illisibles pour %s : %s", path.name, exc)
        return None, None
