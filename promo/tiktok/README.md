# Sona — motion design TikTok (1080×1920, 60 i/s, 32 s)

> Pour mettre **les vraies paroles synchronisées** : le plus simple est de donner `PROMPT-LOCAL.md` à Claude Code en local (voir plus bas « Paroles »).

| Fichier | Contenu |
|---|---|
| `sona-tiktok-v6.mp4` *(non versionné : il contient le morceau)* | **v6** : le vrai morceau (« Goutte d'eau », Ninho — fichier fourni par toi, 138 BPM) comme musique, montage calé sur ses temps (le drop tombe sur la lueur du logo), **caméra en travelling avant** (l'appareil entier se rapproche, cadre compris), **lecteur plein écran de l'app iOS**, vraies interfaces de Sona (accueil, Appareils, récap) et rap français réel. |
| `sona-tiktok-v6-sans-son.mp4` | Même vidéo sans son : pour ajouter le morceau depuis la bibliothèque de sons de TikTok (un son du commerce incrusté dans un fichier peut être coupé ou bloqué). |
| `demo-paroles-camera.mp4` | Démo (muette) de la caméra qui suit les paroles mot par mot, avec des paroles du domaine public. |
| `sona-tiktok-v1.mp4` | v1 : version sobre, 100 % typographique. |

Le morceau (`_assets/song/`), les paroles et les pochettes ne sont **jamais** dans le dépôt (`.gitignore`).

## La caméra
`motion.html` : `camera([[temps, zoom, cx, cy, durée], …])` — chaque cible est un point de l'écran (en fraction) vers lequel la caméra avance. Ce n'est pas l'image qui grossit dans l'écran : tout l'appareil se rapproche sous la perspective (translation en profondeur), le point visé vient au centre, l'appareil se redresse face à l'objectif, les légendes s'effacent, léger flou de mouvement. Les mouvements claquent sur les temps (`timeline.js`).

## Le lecteur iOS
`ios-player.html` reproduit le lecteur plein écran de l'app iOS (`ios/Encre/Sources/Features/Player/FullPlayerView.swift`) : pochette immersive qui se fond dans le fond « vivant » (maillage 4×4 calculé comme `ArtworkPalette.meshColors`), qui respire sur le tempo, barre de progression, gros boutons, et la vue **paroles** (lignes floues autour de la ligne chantée, remplissage mot à mot). Police : Inter (SF Pro n'existe pas hors Apple). La page est pilotée par `setT(temps du morceau)` : chaque image est reproductible, et la position affichée suit la vraie position dans le morceau.

## Paroles synchronisées (nécessite des paroles que TU fournis)
Sans paroles, la scène montre le lecteur iOS plein écran. Avec des paroles horodatées :
```bash
node lrc2json.cjs paroles.lrc                 # → mock/lyrics.local.json (non versionné)
# timeline.js : "lyrics_clip": "ioslyrics"
node clips.cjs _clips ioslyrics               # filme la vue paroles iOS + relève la position du mot chanté (track.js)
```
La caméra suit alors le mot en cours de chant, en même temps que le remplissage de Sona (`followLyrics`). `LYRICS_TITLE="Amazing Grace" node clips.cjs …` filme avec des paroles du domaine public (démo).

## Comment c'est fabriqué
0. `fetch-catalog.cjs` : vrai catalogue de rap français (Deezer) + pochettes + photos dans `_assets/`.
1. `mock/server.cjs` : faux serveur (sert `web/`, simule l'API, sert `ios-player.html`). Les chiffres des stats sont fictifs.
2. `appcap.cjs` + `clips.cjs` : filment l'app web (horloge simulée, rendu déterministe) et le lecteur iOS, à 60 i/s, haute résolution (téléphone ×3, ordinateur ×2).
3. `timeline.js` : plan de montage en temps (tempo, `song_start`, durée des scènes), lu par l'image et le son.
4. `motion.html` : montage + caméra. `?guides` : zones masquées par TikTok.
5. `beat.py` : beat d'attente original, ou `--fx-only` (whooshes) ; `mixaudio.cjs` : extrait du vrai morceau (fondus, −14 LUFS) + effets.
6. `render.cjs` + `ffmpeg`.

```bash
node fetch-catalog.cjs
(cd mock && node server.cjs &)                                  # http://localhost:8765
node clips.cjs _clips iosplayer,home,devices,recap              # ≈ 25 min en haute résolution
mkdir -p _covers   # _covers/0.jpg … 8.jpg = 9 premières pochettes de _assets/catalog.json
python3 beat.py fx.wav --fx-only
node mixaudio.cjs _assets/song/song.m4a fx.wav audio.m4a       # le morceau est celui que tu fournis
node render.cjs motion.html _frames 60 3                        # ≈ 10 min  (FROM=… TO=… : une plage d'images)
ffmpeg -framerate 60 -i _frames/f%05d.png -i audio.m4a -c:v libx264 -preset slow -crf 15 -pix_fmt yuv420p \
  -vf "noise=alls=2:allf=t" -colorspace bt709 -color_primaries bt709 -color_trc bt709 -c:a copy -shortest -movflags +faststart sona-tiktok-v6.mp4
```
Les textes sont dans `motion.html` ; « Lien en bio » est à adapter ou retirer.
