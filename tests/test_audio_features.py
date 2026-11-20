"""Tempo, grille de temps et tonalité : signaux synthétiques (grosse caisse et
charley à tempo connu, accords connus), aucun fichier réel."""

from __future__ import annotations

import shutil
import wave
from pathlib import Path

import numpy as np
import pytest

from app.services import audio_analysis, audio_features as f

SR = f.SAMPLE_RATE


def kick(n: int) -> np.ndarray:
    t = np.arange(n) / SR
    return np.sin(2 * np.pi * (120 * np.exp(-t * 30) + 45) * t) * np.exp(-t * 12)


def hat(n: int) -> np.ndarray:
    return np.random.RandomState(0).randn(n) * np.exp(-np.arange(n) / SR * 60) * 0.3


def beat_track(bpm: float, offset: float, seconds: float = 60, loud_slot: int = 0) -> np.ndarray:
    x = np.zeros(int(SR * seconds), dtype=np.float32)
    period, k = 60 / bpm, 0
    while offset + k * period < seconds - 1:
        t = offset + k * period
        i = int(t * SR)
        x[i : i + int(0.25 * SR)] += (1.0 if k % 4 == loud_slot else 0.55) * kick(int(0.25 * SR))
        j = int((t + period / 2) * SR)
        x[j : j + int(0.05 * SR)] += hat(int(0.05 * SR))
        k += 1
    return x


def circular_gap(a: float, b: float, period: float) -> float:
    return abs((a - b + period / 2) % period - period / 2)


@pytest.mark.parametrize("bpm,offset", [(120, 0.25), (128, 0.1), (90, 0.4), (140, 0.2), (100, 0.3)])
def test_tempo_and_beat_grid(bpm, offset):
    tempo = f.detect_tempo(beat_track(bpm, offset))
    assert tempo is not None
    assert tempo.bpm == pytest.approx(bpm, abs=0.6)
    # Les temps tombent à moins de 60 ms de ceux du signal.
    assert circular_gap(tempo.beat_offset, offset, 60 / bpm) < 0.06


def test_downbeat_is_the_beat_with_the_most_kick():
    tempo = f.detect_tempo(beat_track(120, 0.25, loud_slot=2))
    assert circular_gap(tempo.downbeat, 0.25 + 2 * 0.5, 2.0) < 0.06  # mesure de 4 × 0,5 s


@pytest.mark.parametrize("bpm", [127.9, 100.13, 140.07, 92.4])
def test_tempo_is_refined_below_the_coarse_step(bpm):
    """Pas de 0,25 BPM seul : 0,12 BPM d'erreur, 0,2 s de dérive de la grille sur trois minutes."""
    tempo = f.detect_tempo(beat_track(bpm, 0.2, seconds=150), end=148)
    assert tempo.bpm == pytest.approx(bpm, abs=0.05)


@pytest.mark.parametrize("bpm", [127.9, 100.13, 140.07])
def test_grid_near_the_end_follows_the_real_beats(bpm):
    """La grille de la fin est mesurée là où l'enchaînement a lieu : elle tombe sur les vrais
    temps de la fin, pas sur ceux d'un tempo moyen extrapolé depuis le début."""
    period = 60 / bpm
    tempo = f.detect_tempo(beat_track(bpm, 0.2, seconds=150), end=148)
    # Heure absolue, vers 10 s avant la fin ; les vrais temps sont à 0,2 + k × période.
    assert 130 <= tempo.out_beat_offset <= 140
    drift = circular_gap(tempo.out_beat_offset, 0.2, period)
    assert drift < 0.06
    # Même grille que celle du début (les deux mesures concordent) à quelques dizaines de ms près.
    assert circular_gap(tempo.out_beat_offset, tempo.beat_offset, period) < 0.06


def test_downbeat_near_the_end_keeps_the_bar_position():
    # Le temps fort est le 3e temps de chaque mesure : celui de la fin tombe sur la même place.
    tempo = f.detect_tempo(beat_track(120, 0.25, loud_slot=2, seconds=90), end=88)
    assert 70 <= tempo.out_downbeat <= 90
    assert circular_gap(tempo.out_downbeat, 0.25 + 2 * 0.5, 2.0) < 0.06
    assert tempo.downbeat_confidence is not None and 0 <= tempo.downbeat_confidence <= 1


def test_silence_has_no_tempo():
    assert f.detect_tempo(np.zeros(SR * 30, dtype=np.float32)) is None


def test_too_short_to_analyse():
    assert f.detect_tempo(beat_track(120, 0.0, seconds=5)) is None
    assert f.detect_key(np.ones(SR * 5, dtype=np.float32)) is None


def note(pc: int, octave: int) -> float:
    return 440 * 2 ** ((pc - 9) / 12 + (octave - 4))


def progression(tonic: int, minor: bool) -> np.ndarray:
    """I – IV – V – I de la tonalité, en accords de quatre notes avec harmoniques."""
    pieces = []
    for offset, chord_minor in ((0, minor), (5, minor), (7, False), (0, minor)):
        root = (tonic + offset) % 12
        third = (root + (3 if chord_minor else 4)) % 12
        t = np.arange(int(SR * 6)) / SR
        signal = np.zeros_like(t)
        for pitch, octave in ((root, 3), (third, 3), ((root + 7) % 12, 3), (root, 2)):
            for harmonic in range(1, 7):
                signal += 0.7 ** (harmonic - 1) * np.sin(2 * np.pi * note(pitch, octave) * harmonic * t)
        pieces.append(signal)
    return np.concatenate(pieces).astype(np.float32)


@pytest.mark.parametrize("tonic,minor", [(0, False), (9, True), (7, False), (2, True), (5, False), (11, True)])
def test_key_detection(tonic, minor):
    key = f.detect_key(progression(tonic, minor))
    assert key is not None
    assert key.camelot == f.camelot(tonic, minor)


def test_camelot_wheel():
    assert f.camelot(0, False) == "8B"  # do majeur
    assert f.camelot(9, True) == "8A"  # la mineur : sa relative
    assert f.camelot(7, False) == "9B"  # sol majeur : voisin
    assert f.camelot(2, True) == "7A"  # ré mineur
    assert f.camelot(11, False) == "1B"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg absent")
def test_full_analysis_of_a_file(tmp_path: Path):
    """Passe complète : ffmpeg décode, sonie + tempo + tonalité."""
    samples = (beat_track(128, 0.3, seconds=40) * 0.4 + np.tile(progression(9, True), 2)[: SR * 40] * 0.02).clip(-1, 1)
    path = tmp_path / "morceau.wav"
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SR)
        out.writeframes((samples * 32767).astype("<i2").tobytes())
    result = audio_analysis.analyze(path, shutil.which("ffmpeg"))
    assert result is not None
    assert result.bpm == pytest.approx(128, abs=0.6)
    assert result.key is not None and result.beat_offset is not None and result.downbeat is not None
