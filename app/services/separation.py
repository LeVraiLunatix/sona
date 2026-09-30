"""Séparation voix / instru par IA, pour le karaoké.

Modèle MDX-Net d'Ultimate Vocal Remover (format ONNX), exécuté avec numpy +
onnxruntime seulement. Le paquet `audio-separator` fait la même chose, mais
tire PyTorch et une dizaine de dépendances lourdes (dont certaines sans
version ARM fiable) : pour un seul type de modèle, reproduire son calcul ici
est bien plus léger et sûr à installer sur le serveur (ARM, 2 cœurs).

Lancé dans un sous-processus à part (`python -m app.services.separation`),
en priorité basse : le calcul occupe le processeur pendant une à quelques
minutes, l'API ne doit jamais attendre après lui. Il écrit sa progression
sur la sortie standard (« progress 0.42 ») pour que l'app puisse l'afficher.

Découpage fidèle à UVR : le titre est coupé en morceaux d'environ 6 s qui se
chevauchent, chaque morceau passe en spectrogramme (STFT), le modèle en
extrait l'instru, puis retour au son. La voix est ce qui reste : mix − instru.
Ainsi voix + instru redonne exactement le titre original — à 100 % de voix,
on entend le vrai morceau, sans aucune trace de traitement.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

SAMPLE_RATE = 44100
# Titre plus long (mix d'une heure…) : trop de mémoire et de temps de calcul
# pour un karaoké — la séparation est refusée, l'ancien mode reste.
MAX_SECONDS = 15 * 60


@dataclass(frozen=True)
class ModelSpec:
    """Réglages d'un modèle MDX-Net, tels que publiés par UVR
    (application_data/mdx_model_data/model_data_new.json)."""

    file: str
    n_fft: int
    dim_f: int
    dim_t: int
    compensate: float
    primary: str  # « instrumental » ou « vocals » : ce que le modèle sort
    size: int  # taille du fichier, pour vérifier un téléchargement complet


MODEL_URL = "https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/{file}"

# Meilleur modèle MDX-Net pour l'instru selon les mesures d'audio-separator
# (SDR instru médian 15,5 dB sur MUSDB18) : c'est l'instru qu'on entend en
# karaoké complet. Seuls des modèles bien plus lourds (Roformer, qui exigent
# PyTorch et prendraient 10 à 30 min par titre sur ce serveur) font mieux.
MODELS = {
    "inst_hq_4": ModelSpec("UVR-MDX-NET-Inst_HQ_4.onnx", 5120, 2560, 256, 1.019, "instrumental", 59074342),
    # Variante « voix » (SDR voix 10,2 dB, instru 15,4 dB), gardée au cas où.
    "kim_vocal_2": ModelSpec("Kim_Vocal_2.onnx", 7680, 3072, 256, 1.009, "vocals", 66759214),
}
DEFAULT_MODEL = "inst_hq_4"

HOP = 1024
# Recouvrement des morceaux : UVR prend 25 %. Mesuré sur un titre, 10 %
# donne une instru à ~29 dB de celle obtenue avec 50 % (32 dB pour 25 %) —
# un écart bien sous l'erreur du modèle lui-même (~15 dB), inaudible — pour
# 17 % de calcul en moins sur le petit serveur.
OVERLAP = 0.1


def decode(ffmpeg: str, path: Path):
    """Le fichier audio en tableau numpy (2, n) à 44,1 kHz, stéréo."""
    import numpy as np

    out = subprocess.run(
        [ffmpeg, "-nostdin", "-v", "error", "-i", str(path), "-vn", "-f", "f32le",
         "-acodec", "pcm_f32le", "-ac", "2", "-ar", str(SAMPLE_RATE), "-t", str(MAX_SECONDS + 1), "pipe:1"],
        capture_output=True, check=True,
    )
    wave = np.frombuffer(out.stdout, dtype=np.float32)
    if wave.size < SAMPLE_RATE * 2:
        raise ValueError("Audio vide ou trop court.")
    if wave.size >= SAMPLE_RATE * 2 * MAX_SECONDS:
        raise ValueError("Titre trop long pour la séparation.")
    return wave.reshape(-1, 2).T.copy()


def encode(ffmpeg: str, wave, dest: Path) -> None:
    """Écrit une piste en AAC (m4a), lisible par iOS et le navigateur.
    `+faststart` : l'index du fichier est au début, la lecture démarre sans
    attendre la fin du téléchargement."""
    import numpy as np

    data = np.ascontiguousarray(np.clip(wave, -1.0, 1.0).T, dtype=np.float32).tobytes()
    tmp = dest.with_name(dest.name + ".part")
    subprocess.run(
        [ffmpeg, "-nostdin", "-v", "error", "-y", "-f", "f32le", "-ar", str(SAMPLE_RATE), "-ac", "2",
         "-i", "pipe:0", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-f", "mp4", str(tmp)],
        input=data, check=True, capture_output=True,
    )
    tmp.replace(dest)


class _Stft:
    """STFT / iSTFT identiques à `torch.stft(center=True)` utilisés par UVR
    (fenêtre de Hann périodique, bord en miroir) : le modèle a appris sur
    exactement ce spectrogramme, le moindre écart dégraderait la séparation."""

    def __init__(self, n_fft: int, hop: int, dim_f: int) -> None:
        import numpy as np

        self.n_fft, self.hop, self.dim_f = n_fft, hop, dim_f
        self.window = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(n_fft) / n_fft)).astype(np.float32)

    def forward(self, chunk):
        """(2, n) → (1, 4, dim_f, trames) : parties réelle / imaginaire de
        chaque canal, comme l'attend le modèle."""
        import numpy as np

        pad = self.n_fft // 2
        padded = np.pad(chunk, ((0, 0), (pad, pad)), mode="reflect")
        frames = np.lib.stride_tricks.sliding_window_view(padded, self.n_fft, axis=-1)[:, :: self.hop]
        spec = np.fft.rfft(frames * self.window, axis=-1)  # (2, trames, bins)
        spec = spec[:, :, : self.dim_f].transpose(0, 2, 1)  # (2, dim_f, trames)
        out = np.empty((1, 4, self.dim_f, spec.shape[-1]), dtype=np.float32)
        out[0, 0::2] = spec.real
        out[0, 1::2] = spec.imag
        return out

    def inverse(self, spec, length: int):
        """(1, 4, dim_f, trames) → (2, length), par addition-recouvrement."""
        import numpy as np

        bins = self.n_fft // 2 + 1
        frames = spec.shape[-1]
        full = np.zeros((2, bins, frames), dtype=np.complex64)
        full[:, : self.dim_f] = spec[0, 0::2] + 1j * spec[0, 1::2]
        blocks = np.fft.irfft(full.transpose(0, 2, 1), n=self.n_fft, axis=-1) * self.window  # (2, trames, n_fft)
        total = self.n_fft + self.hop * (frames - 1)
        out = np.zeros((2, total), dtype=np.float32)
        norm = np.zeros(total, dtype=np.float32)
        square = self.window ** 2
        for i in range(frames):
            start = i * self.hop
            out[:, start : start + self.n_fft] += blocks[:, i]
            norm[start : start + self.n_fft] += square
        pad = self.n_fft // 2
        out, norm = out[:, pad : pad + length], norm[pad : pad + length]
        return out / np.maximum(norm, 1e-8)


def _session(model_path: Path, threads: int):
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    options.log_severity_level = 3
    return ort.InferenceSession(str(model_path), sess_options=options, providers=["CPUExecutionProvider"])


def separate(mix, spec: ModelSpec, model_path: Path, threads: int = 2, progress=None):
    """(voix, instru) à partir du mix (2, n). Reproduit `MDXSeparator.demix`
    d'UVR / audio-separator (morceaux fenêtrés qui se chevauchent un peu)."""
    import numpy as np

    session = _session(model_path, threads)
    stft = _Stft(spec.n_fft, HOP, spec.dim_f)
    # Le modèle attend un signal qui ne sature pas : ramené sous 0,9 si
    # besoin (comme UVR), puis remis à l'échelle à la fin.
    peak = float(np.abs(mix).max())
    scale = 0.9 / peak if peak > 0.9 else 1.0
    work = mix * scale

    trim = spec.n_fft // 2
    chunk = HOP * (spec.dim_t - 1)
    gen = chunk - 2 * trim
    n = work.shape[-1]
    pad = gen + trim - (n % gen)
    mixture = np.concatenate(
        (np.zeros((2, trim), np.float32), work, np.zeros((2, pad), np.float32)), axis=1
    ).astype(np.float32)
    step = int((1 - OVERLAP) * chunk)
    result = np.zeros((2, mixture.shape[-1]), dtype=np.float32)
    divider = np.zeros((2, mixture.shape[-1]), dtype=np.float32)
    starts = list(range(0, mixture.shape[-1], step))
    for index, start in enumerate(starts):
        end = min(start + chunk, mixture.shape[-1])
        part = mixture[:, start:end]
        if part.shape[-1] < chunk:
            part = np.concatenate((part, np.zeros((2, chunk - part.shape[-1]), np.float32)), axis=1)
        x = stft.forward(part)
        x[:, :, :3, :] = 0  # comme UVR : les 3 premières bandes (grave extrême) à zéro
        y = session.run(None, {"input": x})[0]
        wave = stft.inverse(y, chunk)[:, : end - start]
        window = np.hanning(end - start).astype(np.float32)
        result[:, start:end] += wave * window
        divider[:, start:end] += window
        if progress is not None:
            progress((index + 1) / len(starts))
    primary = (result / np.maximum(divider, 1e-8))[:, trim : trim + n] * spec.compensate / scale
    # L'autre piste est le reste : voix + instru = titre original, exactement.
    secondary = mix - primary
    if spec.primary == "instrumental":
        return secondary, primary
    return primary, secondary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Séparation voix / instru (karaoké)")
    parser.add_argument("input", type=Path)
    parser.add_argument("vocals", type=Path)
    parser.add_argument("instrumental", type=Path)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--spec", default=DEFAULT_MODEL, choices=sorted(MODELS))
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--threads", type=int, default=2)
    args = parser.parse_args(argv)

    def report(fraction: float) -> None:
        print(f"progress {fraction:.3f}", flush=True)

    try:
        mix = decode(args.ffmpeg, args.input)
        report(0.0)
        vocals, instrumental = separate(mix, MODELS[args.spec], args.model, args.threads, report)
        encode(args.ffmpeg, vocals, args.vocals)
        encode(args.ffmpeg, instrumental, args.instrumental)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or b"").decode(errors="replace").strip().splitlines()
        print(f"erreur Lecture ou écriture audio impossible ({detail[-1][:120] if detail else 'ffmpeg'})",
              file=sys.stderr, flush=True)
        return 1
    except (ValueError, OSError, MemoryError) as exc:
        # Une ligne lisible pour l'app (voir `karaoke.run_separation`).
        print(f"erreur {exc}", file=sys.stderr, flush=True)
        return 1
    print("done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
