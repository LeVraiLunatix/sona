"""Analyse du morceau (celui que tu fournis) pour caler l'image sur ses VRAIS kicks et basses, pas seulement sur le tempo.
usage : python3 analyze-song.py           (lit _assets/song/song.wav, timeline.js)  →  _assets/song/audio.js
  - bass  : énergie des basses (30–150 Hz), une valeur par image vidéo (60 i/s), normalisée 0–1
  - kicks : instants des coups de grosse caisse/808 (secondes de la VIDÉO) avec leur force 0–1
Le fichier produit (window.AUDIO) est chargé par motion.html ; il reste dans _assets/ (ignoré par git)."""
import json, os, re, sys, wave
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "timeline.js")).read()
tl = json.loads(re.sub(r"//[^\n]*", "", src[src.index("window.TIMELINE =") + len("window.TIMELINE ="):src.rindex(";")]))
BPM, START = tl["bpm"], tl["song_start"]
HB, HS = tl.get("hook_beats", 0), tl.get("hook_song_start", 0); HDUR = HB * 60 / BPM if HS else 0   # teaser : les premiers temps jouent un autre extrait
BEATS = max(s["b0"] + s["beats"] for s in tl["scenes"]); DUR = BEATS * 60 / BPM + 0.6; FPS = 60

w = wave.open(os.path.join(HERE, "_assets/song/song.wav")); sr = w.getframerate()
x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(float) / 32768

# énergie des basses : STFT 2048 / saut 128 (5,8 ms), bande 30–150 Hz
n, hop = 2048, 128; win = np.hanning(n); F = np.fft.rfftfreq(n, 1 / sr); band = (F >= 30) & (F <= 150)
frames = (len(x) - n) // hop
E = np.array([np.sqrt((np.abs(np.fft.rfft(x[i * hop:i * hop + n] * win))[band] ** 2).mean()) for i in range(frames)])
tt = (np.arange(frames) * hop + n / 2) / sr                      # temps (s) du centre de chaque fenêtre

# kicks : montées rapides de l'énergie des basses (flux positif sur log), pics espacés d'au moins 0,16 s
L = np.log1p(E * 40); flux = np.maximum(0, L[3:] - L[:-3]); flux = np.concatenate([np.zeros(3), flux])
thr = np.median(flux) + 2.2 * np.median(np.abs(flux - np.median(flux)))
peaks = []
for i in range(2, len(flux) - 2):
    if flux[i] > thr and flux[i] == flux[i - 2:i + 3].max(): peaks.append(i)
kicks = []
for i in peaks:
    t = tt[i]
    if kicks and t - kicks[-1][0] < 0.16:
        if flux[i] > kicks[-1][2]: kicks[-1] = (t, E[i], flux[i])
        continue
    kicks.append((t, E[i], flux[i]))
ks = np.array([k[2] for k in kicks]); kmax = np.percentile(ks, 95)
# précision : on cherche l'attaque EXACTE dans le signal des basses (passe-bas 30–150 Hz, enveloppe à 3 ms, pente maximale)
X = np.fft.rfft(x); Fx = np.fft.rfftfreq(len(x), 1 / sr); X[(Fx < 30) | (Fx > 150)] = 0
lp = np.fft.irfft(X, len(x)); env = np.convolve(np.abs(lp), np.ones(int(sr * 0.003)) / int(sr * 0.003), "same")
slope = np.diff(env, prepend=env[0])
def refine(t0):
    a, b = int((t0 - 0.07) * sr), int((t0 + 0.03) * sr); a = max(a, 0)
    return (a + int(np.argmax(slope[a:b]))) / sr - 0.004
kicks = [(refine(k[0]), k[1], k[2]) for k in kicks]
# les montées se produisent un peu avant le pic d'énergie : on recale sur le début de l'attaque (≈ −12 ms)
kick_t = [k[0] for k in kicks]; kick_s = [min(1, k[2] / kmax) for k in kicks]

# enveloppe des basses par image vidéo
Es = np.convolve(E, np.ones(6) / 6, "same"); lo, hi = np.percentile(Es, 20), np.percentile(Es, 97)
def bass_at(t): return float(np.clip((np.interp(t, tt, Es) - lo) / (hi - lo), 0, 1))
N = int(DUR * FPS)
def song_t(t): return HS + t if t < HDUR else START + (t - HDUR)            # temps de la vidéo → temps du morceau
bass = [round(bass_at(song_t(i / FPS)), 3) for i in range(N)]
vk = []
for t, s in zip(kick_t, kick_s):
    if HDUR and HS - 0.05 <= t < HS + HDUR: vk.append((round(t - HS, 3), round(s, 2)))
    elif START - 0.05 <= t <= START + DUR - HDUR: vk.append((round(t - START + HDUR, 3), round(s, 2)))
vk.sort()

# cohérence avec la grille de tempo (1er temps du morceau à 0,209 s)
beat = 60 / BPM; off = [((song_t(t) - 0.209) / beat) % 1 for t, _ in vk]; on_grid = sum(1 for o in off if min(o, 1 - o) * beat < 0.045)
print(f"kicks détectés dans la vidéo : {len(vk)} (sur {len(kicks)} dans tout le morceau) · {on_grid} sont à ±45 ms de la grille de {BPM} BPM")
print("premiers kicks (s vidéo) :", [t for t, _ in vk[:10]])
out = os.path.join(HERE, "_assets/song/audio.js")
open(out, "w").write("window.AUDIO = " + json.dumps({"song_start": START, "fps": FPS, "bass": bass, "kicks": vk}) + ";")
print("→", out)
