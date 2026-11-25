"""Beat d'attente ORIGINAL (rien d'échantillonné), calé sur timeline.js : trap sombre en fa mineur.
usage : python3 beat.py sortie.wav [--fx-only]   (--fx-only : uniquement les whooshes/montées, à mixer sous un vrai morceau)     — le vrai son (PNL…) s'ajoute ensuite dans TikTok, sur la même grille de tempo."""
import json, re, sys, numpy as np
FX_ONLY = "--fx-only" in sys.argv
ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]

SR = 44100
src = open("timeline.js").read()
import re as _re
tl = json.loads(_re.sub(r"//[^\n]*", "", src[src.index("window.TIMELINE =") + len("window.TIMELINE ="):src.rindex(";")]))
BPM = tl["bpm"]; BEAT = 60 / BPM
scenes = {s["id"]: s for s in tl["scenes"]}
total_beats = max(s["b0"] + s["beats"] for s in tl["scenes"])
DUR = total_beats * BEAT + 0.6
N = int(DUR * SR)
rng = np.random.default_rng(7)
L = np.zeros(N); R = np.zeros(N)

def put(buf, x, t0, gain=1.0):
    i = int(t0 * SR)
    if i >= N or i + len(x) <= 0: return
    a = max(0, -i); b = min(len(x), N - i)
    buf[i + a:i + b] += x[a:b] * gain

def both(x, t0, gain=1.0, pan=0.0):
    put(L, x, t0, gain * (1 - max(0, pan))); put(R, x, t0, gain * (1 + min(0, pan)))

def tt(d): return np.arange(int(d * SR)) / SR
def lowpass(x, fc):
    a = 1 - np.exp(-2 * np.pi * fc / SR); y = np.zeros_like(x); s = 0.0
    for i, v in enumerate(x): s += a * (v - s); y[i] = s
    return y
def highpass(x, fc): return x - lowpass(x, fc)

# ───── instruments ─────
def kick():
    t = tt(0.55); f = 46 + 120 * np.exp(-t / 0.035); ph = 2 * np.pi * np.cumsum(f) / SR
    return np.tanh(1.6 * np.sin(ph) * np.exp(-t / 0.2)) + 0.25 * rng.standard_normal(len(t)) * np.exp(-t / 0.004)
def clap():
    t = tt(0.32); n = rng.standard_normal(len(t)); n = highpass(lowpass(n, 6500), 900)
    env = sum(np.exp(-np.clip(t - d, 0, None) / 0.018) * (t >= d) for d in (0, 0.011, 0.023)) * 0.5 + np.exp(-t / 0.11) * 0.7
    return n * env * 0.8
def hat(open_=False):
    t = tt(0.28 if open_ else 0.05); n = highpass(rng.standard_normal(len(t)), 7000)
    return n * np.exp(-t / (0.09 if open_ else 0.012)) * 0.5
def s808(f, d):
    t = tt(d); fr = f * (1 + 0.35 * np.exp(-t / 0.05)); ph = 2 * np.pi * np.cumsum(fr) / SR
    env = np.minimum(1, t / 0.006) * np.exp(-t / (d * 0.55)); return np.tanh(2.4 * np.sin(ph) * env) * 0.9
def saw_pad(f, d):
    t = tt(d); x = sum(np.sin(2 * np.pi * f * k * (1 + dt) * t) / k for k in range(1, 7) for dt in (-0.004, 0.004))
    env = np.minimum(1, t / 0.5) * np.minimum(1, (d - t) / 0.9); return lowpass(x, 1800) * env * 0.5
def pluck(f, d=0.5):
    t = tt(d); x = sum(np.sin(2 * np.pi * f * k * t) / k ** 1.4 for k in range(1, 5))
    return x * np.exp(-t / 0.16) * np.minimum(1, t / 0.004)
def whoosh(d=0.5):
    t = tt(d); n = rng.standard_normal(len(t)); y = np.zeros_like(n); s = 0.0
    for i in range(len(n)):
        a = 1 - np.exp(-2 * np.pi * (300 + 7000 * (i / len(n)) ** 2) / SR); s += a * (n[i] - s); y[i] = s
    return highpass(y, 200) * np.sin(np.pi * np.clip(t / d, 0, 1)) ** 2 * 1.6
def riser(d):
    t = tt(d); f = 200 * (2 ** (3.5 * t / d)); ph = 2 * np.pi * np.cumsum(f) / SR
    return (np.sin(ph) * 0.5 + 0.4 * highpass(rng.standard_normal(len(t)), 2000)) * (t / d) ** 2 * 0.5

K, C = kick(), clap(); H, HO = hat(), hat(True)
# ───── partition ─────
def at(beat): return beat * BEAT
b = lambda s: scenes[s]["b0"]
drums_start = b("hero")                 # la batterie entre avec « Ta musique, en clair. »
full_start = b("s_ly")                  # tout entre sur les paroles
outro = b("outro")
roots = [43.65, 43.65, 69.30, 77.78]    # fa, fa, ré♭, mi♭ (une note par mesure)
chords = [(174.6, 207.7, 261.6, 311.1), (138.6, 174.6, 207.7, 261.6), (207.7, 261.6, 311.1, 392.0), (155.6, 196.0, 233.1, 311.1)]
penta = [349.2, 415.3, 466.2, 523.3, 622.3, 698.5]
kicks = np.zeros(N)
for bar in range(0 if FX_ONLY else total_beats // 4 + 1):
    b0 = bar * 4
    if b0 >= total_beats: break
    chord = chords[bar % 4]; pad_on = b0 >= 2
    if pad_on and b0 < outro + 8:
        for f in chord: both(saw_pad(f, BEAT * 4 + 0.6), at(b0), 0.12, pan=0.2 if f > 250 else -0.2)
    full = full_start <= b0 < outro; dr = drums_start <= b0 < outro + 4
    if dr:
        pat = [0, 2.5] if not full else [0, 1.75, 2.5]
        for p in pat: both(K, at(b0 + p), 0.95); kicks[int(at(b0 + p) * SR):int(at(b0 + p) * SR) + 1] = 1
        for p in (1, 3): both(C, at(b0 + p), 0.55 if full else 0.0)
        steps = np.arange(0, 4, 0.5) if not full else np.arange(0, 4, 0.25)
        for j, p in enumerate(steps):
            if full and rng.random() < 0.18: continue
            both(H, at(b0 + p), (0.34 if p % 1 == 0 else 0.2) * (1.0 if full else 0.5), pan=0.25 if j % 2 else -0.25)
        if full: both(HO, at(b0 + 3.5), 0.35, pan=0.3)
    if full or (dr and b0 >= drums_start):
        r = roots[bar % 4]
        both(s808(r, BEAT * 1.6), at(b0), 0.8); both(s808(r * (1 if bar % 2 else 1.5), BEAT * 1.2), at(b0 + 2.5), 0.7)
    if full:  # petite mélodie qui répond, deux fois par mesure
        for p, k in ((0.5, 3), (1.75, 5), (2.75, 2), (3.25, 4)):
            if rng.random() < 0.85: both(pluck(penta[k]), at(b0 + p), 0.16, pan=-0.2 if k % 2 else 0.2)
# écho/réverbération douce sur tout ce qui est mélodique : retard à 3/8 de temps, filtré
def echo(x, delay, fb, n):
    y = x.copy(); d = int(delay * SR)
    for k in range(1, n + 1):
        y[k * d:] += lowpass(x[:N - k * d], 3000) * (fb ** k) if k * d < N else 0
    return y
# côte à côte : sidechain léger du pad par la grosse caisse
duck = np.ones(N)
for i in np.nonzero(kicks)[0]:
    seglen = int(0.28 * SR); e = min(N, i + seglen); duck[i:e] = np.minimum(duck[i:e], 1 - 0.0 * np.exp(-np.arange(e - i) / (0.1 * SR)))
# ───── effets de montage : impact sur la lueur du logo, whoosh à chaque coup de fouet, riser, impact final ─────
glow_t = tl['intro_start'] + tl['intro_dur'] * 0.42
if not FX_ONLY: both(K, glow_t, 1.0); both(s808(43.65, 2.2), glow_t, 0.9)
both(whoosh(0.9)[::-1], glow_t - 0.9, 0.5)
both(riser(at(2)), at(b("hero") - 2), 0.5)                   # ça monte vers « Ta musique, en clair. »
for sid, sc in scenes.items():
    if sc["b0"] == 0: continue
    t = sc["b0"] * BEAT; both(whoosh(0.5), t - 0.32, 0.9 if sid != "outro" else 1.0, pan=0.0)
if not FX_ONLY: both(K, at(outro), 1.0); both(s808(43.65, 2.4), at(outro), 0.95)
both(whoosh(0.9)[::-1], at(outro) - 0.7, 0.55)
# ───── mixage final ─────
mix = np.stack([L, R], axis=1)
mix = mix + 0.0
# réverb légère (écho décroissant) sur la somme
for ch in (0, 1):
    wet = echo(mix[:, ch] * 0.0 + mix[:, ch], BEAT * 0.75 + ch * 0.013, 0.42, 3) - mix[:, ch]
    mix[:, ch] = mix[:, ch] + wet * 0.28
mix = np.tanh(mix * 0.95)
fade = np.ones(N); fi = int(0.02 * SR); fo = int(1.6 * SR); fade[:fi] = np.linspace(0, 1, fi); fade[-fo:] = np.linspace(1, 0, fo) ** 1.5
mix *= fade[:, None]
peak = np.abs(mix).max(); mix *= 0.62 / peak
rms = 20 * np.log10(np.sqrt((mix ** 2).mean()) + 1e-9)
print(f"durée {DUR:.2f}s · tempo {BPM} BPM · crête 0.62 · niveau moyen {rms:.1f} dBFS")
import wave
pcm = (mix * 32767).astype("<i2")
with wave.open(ARGS[0] if ARGS else "beat.wav", "wb") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())
