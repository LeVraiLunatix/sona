"""Copie Python fidèle du calage de l'AutoMix iPhone (`ios/Encre/Sources/Features/Player/MixPlanner.swift`).

Le projet iOS n'a pas de cible de tests et la CI iOS ne fait que compiler : la logique de
calage (où commencer l'enchaînement, sur quel premier temps entrer, à quelle vitesse jouer le
suivant, quelle courbe de fondu) est donc écrite ici à l'identique, en fonctions pures, et
testée par `tests/test_automix_planner.py`. Toute modification du Swift doit être reportée ici
(mêmes noms, mêmes constantes, mêmes formules), et inversement.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

TEMPO_TOLERANCE = 0.06
MIN_CONFIDENCE = 0.3
MIN_BAR_CONFIDENCE = 0.25
MIN_LENGTH = 2.5


@dataclass
class Analysis:
    """Ce que le serveur donne (`TrackAnalysis` côté Swift)."""

    start: float = 0.0
    mix_out: float = 0.0
    end: float = 0.0
    bpm: float | None = None
    beat_offset: float | None = None
    downbeat: float | None = None
    key: str | None = None
    key_confidence: float | None = None
    tempo_confidence: float | None = None
    out_beat_offset: float | None = None
    out_downbeat: float | None = None
    downbeat_confidence: float | None = None


@dataclass
class BeatGrid:
    bpm: float
    downbeat: float
    bar_confidence: float

    @property
    def period(self) -> float:
        return 60 / self.bpm

    @property
    def bar(self) -> float:
        return 4 * 60 / self.bpm


@dataclass
class MixPlan:
    a_start: float
    b_start: float
    length: float
    rate: float
    style: str  # "plain" | "blend"
    key_match: str
    beat: float
    aligned: bool
    bass_swap: bool


@dataclass
class MixInputs:
    a_end: float
    a_base: float
    position: float
    a: Analysis | None = None
    a_bpm: float | None = None
    b: Analysis | None = None
    b_bpm: float | None = None
    fixed_length: float | None = None
    effects: bool = True
    album_break: bool = False
    force_plain: bool = False
    lead: float = 0.8


# -- KeyMatch --------------------------------------------------------------------------------

def _parse_key(code: str | None) -> tuple[int, bool] | None:
    if not code or code[-1] not in "AB" or not code[:-1].isdigit():
        return None
    number = int(code[:-1])
    return (number, code[-1] == "A") if 1 <= number <= 12 else None


def key_match(a: str | None, b: str | None) -> str:
    first, second = _parse_key(a), _parse_key(b)
    if first is None or second is None:
        return "unknown"
    if first[0] == second[0]:
        return "same" if first[1] == second[1] else "relative"
    gap = min((first[0] - second[0]) % 12, (second[0] - first[0]) % 12)
    return "adjacent" if gap == 1 and first[1] == second[1] else "clash"


def blends(match: str) -> bool:
    return match in ("same", "relative", "adjacent")


# -- MixMath ---------------------------------------------------------------------------------

def first_boundary(at_or_after: float, origin: float, step: float) -> float:
    """Plus petit `origin + k × step` supérieur ou égal à `at_or_after` (k entier)."""
    return origin + math.ceil((at_or_after - origin) / step - 1e-9) * step


def tempo_ratio(bpm_a: float, bpm_b: float, tolerance: float) -> float | None:
    if bpm_a <= 0 or bpm_b <= 0:
        return None
    candidates = [bpm_a / bpm_b, bpm_a / (bpm_b * 2), (bpm_a * 2) / bpm_b]
    best = min(candidates, key=lambda r: abs(r - 1))
    if abs(best - 1) > tolerance:
        return None
    return 1.0 if abs(best - 1) < 0.0005 else best


def equal_power(raw_t: float) -> tuple[float, float]:
    t = min(1.0, max(0.0, raw_t))
    return math.cos(t * math.pi / 2), math.sin(t * math.pi / 2)


# -- MixPlanner ------------------------------------------------------------------------------

def _confident_key(a: Analysis | None) -> str | None:
    return a.key if a is not None and (a.key_confidence or 0) >= MIN_CONFIDENCE else None


def out_grid(a: Analysis | None) -> BeatGrid | None:
    if a is None or a.bpm is None or a.bpm <= 30 or (a.tempo_confidence or 0) < MIN_CONFIDENCE:
        return None
    for candidate in (a.out_downbeat, a.out_beat_offset, a.downbeat, a.beat_offset):
        if candidate is not None:
            downbeat = candidate
            break
    else:
        return None
    measured = a.out_downbeat is not None
    confidence = (a.downbeat_confidence if a.downbeat_confidence is not None else 0.5) if measured else 0.0
    return BeatGrid(a.bpm, downbeat, confidence)


def in_grid(a: Analysis | None) -> BeatGrid | None:
    if a is None or a.bpm is None or a.bpm <= 30 or (a.tempo_confidence or 0) < MIN_CONFIDENCE:
        return None
    downbeat = a.downbeat if a.downbeat is not None else a.beat_offset
    if downbeat is None:
        return None
    return BeatGrid(a.bpm, downbeat, a.downbeat_confidence if a.downbeat_confidence is not None else 0.5)


def bar_placement(
    grid: BeatGrid, lengths: list[float], a_base: float, a_end: float, earliest: float
) -> tuple[float, float] | None:
    """Première mesure de A où loger l'enchaînement : la plus longue des `lengths` qui tient
    entre `earliest` et la fin de A, au plus près du début de l'outro mais jamais assez tard
    pour que le suivant dépasse la fin du titre."""
    for length in lengths:
        start = first_boundary(max(a_base, a_end - length) - 0.05, grid.downbeat, grid.bar)
        overrun = start + length - (a_end + 0.4)
        if overrun > 0:
            start -= math.ceil(overrun / grid.bar) * grid.bar
        if start >= earliest - 0.05:
            return start, length
    return None


def plan(i: MixInputs) -> MixPlan:
    match = key_match(_confident_key(i.a), _confident_key(i.b))
    bpm_a = i.a.bpm if i.a is not None and i.a.bpm is not None else i.a_bpm
    grid_a, grid_b = out_grid(i.a), in_grid(i.b)

    rate, aligned = 1.0, False
    if not i.force_plain and grid_a and grid_b:
        ratio = tempo_ratio(grid_a.bpm, grid_b.bpm, TEMPO_TOLERANCE)
        if ratio is not None:
            rate, aligned = ratio, True
    bars_trusted = (grid_a.bar_confidence if grid_a else 0) >= MIN_BAR_CONFIDENCE and (
        grid_b.bar_confidence if grid_b else 0
    ) >= MIN_BAR_CONFIDENCE

    if aligned:
        if match in ("same", "relative", "adjacent"):
            max_length = 16.0 if bars_trusted else 8.0
        elif match == "unknown":
            max_length = 8.0
        else:
            max_length = 6.0
    else:
        max_length = 12.0 if i.album_break else 8.0

    earliest = i.position + i.lead
    start = max(i.a_base, i.a_end - max_length)
    length = max_length
    fixed = i.fixed_length if i.fixed_length and i.fixed_length > 0 else None
    if fixed is not None:
        length = max(1.0, min(fixed, max(1.0, i.a_end - earliest)))
        start = max(i.a_base, i.a_end - length)

    if grid_a is not None and not i.force_plain:
        lengths = [length] if fixed is not None else [
            n * grid_a.bar for n in (8, 4, 2, 1) if MIN_LENGTH <= n * grid_a.bar <= max_length + 0.01
        ]
        found = bar_placement(grid_a, lengths, i.a_base, i.a_end, earliest)
        if found is not None:
            start, length = found
        else:
            start = first_boundary(earliest - 0.05, grid_a.downbeat, grid_a.bar)
            length = max(1.5, min(length, i.a_end - start))
    else:
        if fixed is None and bpm_a and bpm_a > 0:
            bar = 240 / bpm_a
            bars = max(1.0, math.floor(max_length / bar + 0.5))  # Swift : .rounded() (demi vers le haut)
            length = max(MIN_LENGTH, min(max_length + bar / 2, bars * bar))
        start = max(max(i.a_base, i.a_end - length), earliest)
        length = max(1.5, min(length, i.a_end - start))

    intro_end = i.b.start if i.b is not None else 0.0
    b_start = intro_end
    if grid_b is not None:
        first = max(0.0, first_boundary(intro_end - 0.15, grid_b.downbeat, grid_b.bar))
        if first - intro_end <= 6:
            b_start = first

    beat = grid_a.period if grid_a else (60 / bpm_a if bpm_a else 0.0)
    return MixPlan(
        a_start=start, b_start=b_start, length=length, rate=rate,
        style="blend" if aligned else "plain", key_match=match, beat=beat, aligned=aligned,
        bass_swap=aligned and i.effects and blends(match),
    )


# -- MixAutomation ---------------------------------------------------------------------------

def _log_lerp(a: float, b: float, progress: float) -> float:
    return a * (b / a) ** min(1.0, max(0.0, progress))


@dataclass
class MixFrame:
    volume_a: float
    volume_b: float
    highpass_a: float = 0.0
    highpass_b: float = 0.0


def frame(p: MixPlan, t_raw: float, gain_a: float = 1.0, gain_b: float = 1.0, fx: bool = True) -> MixFrame:
    t = min(1.0, max(0.0, t_raw))
    a, b = equal_power(t)
    out = MixFrame(gain_a * a, gain_b * b)
    if fx and p.bass_swap:
        out.highpass_a = 0.0 if t < 0.4 else _log_lerp(25, 320, (t - 0.4) / 0.5)
        out.highpass_b = 200.0 if t < 0.5 else (_log_lerp(200, 25, (t - 0.5) / 0.22) if t < 0.72 else 0.0)
    return out


def fade_progress(position_a: float, position_b: float, p: MixPlan, a_start: float, b_running: bool) -> float:
    """Progression du fondu, comme la boucle de `beginMix` : celle du plus lent des deux titres,
    0 tant que B ne joue pas (A reste alors à plein volume)."""
    if not b_running:
        return 0.0
    t_a = (position_a - a_start) / p.length
    t_b = (position_b - p.b_start) / (p.length * p.rate)
    return max(0.0, min(t_a, t_b))
