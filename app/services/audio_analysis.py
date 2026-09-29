"""Analyse d'un fichier audio pour l'AutoMix : sonie, début réel, moment où
le titre retombe (outro / fondu de fin) et fin réelle.

Une seule passe ffmpeg avec le filtre `ebur128` (norme de sonie EBU R128) :
il donne la sonie intégrée du titre (en LUFS) et, toutes les 100 ms, la
sonie instantanée (M, 400 ms) et à court terme (S, 3 s). De cette courbe :
- `start` : fin du silence de début (l'enchaînement ne commence pas par un
  blanc) ;
- `mix_out` : dernier moment où le titre est encore « plein » — après, c'est
  l'outro, le moment naturel pour faire entrer le suivant ;
- `end` : fin du son (le silence final ne compte pas).
Lancé en priorité basse (`nice`) : l'API reste réactive pendant l'analyse.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_FRAME_RE = re.compile(r"t:\s*([\d.]+).*?M:\s*(-?[\d.]+|-inf)\s+S:\s*(-?[\d.]+|-inf)")
_INTEGRATED_RE = re.compile(r"Integrated loudness:\s*\n\s*I:\s*(-?[\d.]+)\s*LUFS")
# En dessous : silence (ou presque).
SILENCE_LUFS = -45.0
# Écart à la sonie moyenne sous lequel le titre n'est plus « plein ».
OUTRO_DROP_LU = 6.0
MAX_INTRO_SKIP = 15.0


@dataclass(slots=True)
class Analysis:
    loudness: float
    start: float
    mix_out: float
    end: float
    duration: float


def _value(text: str) -> float:
    return -120.0 if text == "-inf" else float(text)


def parse_ebur128(stderr: str) -> Analysis | None:
    frames = [(float(t), _value(m), _value(s)) for t, m, s in _FRAME_RE.findall(stderr)]
    summary = _INTEGRATED_RE.findall(stderr)
    if len(frames) < 20 or not summary:
        return None
    integrated = float(summary[-1])
    duration = frames[-1][0]

    audible = [t for t, m, _ in frames if m > SILENCE_LUFS]
    if not audible:
        return None
    start = min(max(0.0, audible[0] - 0.3), MAX_INTRO_SKIP)
    end = min(duration, audible[-1] + 0.3)

    full = [t for t, _, s in frames if s >= integrated - OUTRO_DROP_LU and t <= end]
    last_full = full[-1] if full else end - 8
    # L'enchaînement se place dans les 30 dernières secondes, et dure au
    # moins 3 s : un titre qui s'arrête net laisse un court enchaînement.
    mix_out = min(max(last_full, end - 30.0), end - 3.0)
    return Analysis(
        loudness=round(integrated, 1), start=round(start, 1), mix_out=round(max(mix_out, start), 1),
        end=round(end, 1), duration=round(duration, 1),
    )


def analyze(path: Path, ffmpeg_path: str) -> Analysis | None:
    command = [ffmpeg_path, "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=framelog=info", "-f", "null", "-"]
    if shutil.which("nice"):
        command = ["nice", "-n", "10", *command]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=180, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.info("Analyse audio impossible pour %s : %s", path.name, exc)
        return None
    analysis = parse_ebur128(result.stderr)
    if analysis is None:
        logger.info("Analyse audio illisible pour %s", path.name)
    return analysis
