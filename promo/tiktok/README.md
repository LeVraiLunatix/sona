# Sona — motion design TikTok (1080×1920, 60 i/s, 32 s)

| Fichier | Contenu |
|---|---|
| `sona-tiktok-v10.mp4` *(non versionné : il contient le morceau)* | **v10** : une **accroche** de 1,7 s ouvre la vidéo (le drop du morceau, paroles en très gros qui s'allument mot à mot, « Tu connais vraiment les paroles ? »), puis un choc mène à l'**animation d'intro du site** ; ensuite le montage allégé avec une transition différente à chaque coupe, calé sur les vrais kicks (« Goutte d'eau », Ninho — fichier fourni par toi). |
| `sona-tiktok-v10-sans-son.mp4` | Même vidéo sans son : pour ajouter le morceau depuis la bibliothèque de sons de TikTok (un son du commerce incrusté dans un fichier peut être coupé ou bloqué). |
| `demo-paroles-camera.mp4` | Démo (muette) de la caméra qui suit les paroles mot par mot, avec des paroles du domaine public. |
| `sona-tiktok-v1.mp4` | v1 : version sobre, 100 % typographique. |

Le morceau (`_assets/song/`), les paroles et les pochettes ne sont **jamais** dans le dépôt (`.gitignore`).

## L'accroche
Les 4 premiers temps (`hook_beats` dans `timeline.js`) jouent **le drop** du morceau (`hook_song_start`) : `ios-player.html?bare` filme l'écran des paroles plein cadre (clip `ioshook`), `paintHook()` pousse la caméra sur le mot chanté et affiche la phrase d'accroche. Le son « rembobine » ensuite (fondu court) vers le début du morceau, et le drop revient comme point d'orgue au cut des pochettes. `analyze-song.py` et `mixaudio.cjs` gèrent ces deux extraits.

## Synchro sur les kicks et les basses
`analyze-song.py` analyse le morceau que tu fournis : énergie des basses à chaque image vidéo et instants exacts des kicks/808 (attaque repérée à quelques ms) → `_assets/song/audio.js` (non versionné). `motion.html` s'en sert pour les rebonds des appareils, les lueurs, les plans flottants, et **cale sur un vrai kick** le départ de chaque mouvement de caméra (`bk()`) et de chaque mot des légendes (`snapRel()`). Sans analyse, retour à la grille de tempo.
Le début du son (`song_start` dans `timeline.js`) est choisi pour que la scène des paroles tombe sur le passage voulu et que le drop coïncide avec un cut ; il reste sur un temps du morceau (grille de tempo conservée).

## La caméra
`camera([[temps, zoom, cx, cy, durée], …])` : chaque cible est un point de l'écran (en fraction) vers lequel la caméra avance, par une courbe très douce (smootherstep) ; les mouvements s'additionnent (continus même s'ils se chevauchent), l'état est lissé par une moyenne gaussienne (±0,12 s) et le flou de mouvement suit la vitesse réelle. Ce n'est pas l'image qui grossit dans l'écran : tout le « monde » se rapproche sous la perspective (translation en profondeur), le point visé vient au centre, l'appareil se redresse face à l'objectif, les légendes et les plans flottants s'effacent. Sur les paroles, la caméra suit le mot chanté (`followRaw`, glissement gaussien).

## Les transitions
Chaque coupe a sa transition (`TRANS` dans `motion.html`), de 0,7 s, centrée sur un kick : le plan sortant et le plan entrant bougent **ensemble**, floutés par la vitesse, et les éléments du plan entrant ont déjà commencé à s'animer (temps négatif) au lieu d'attendre la fin du fondu. `zoomthrough` : la caméra traverse le plan sortant (avec un halo) · `cube` : rotation 3D autour d'un axe commun · `slideUp` : poussée verticale · `drop` : au drop, le plan sortant est projeté en avant, flash, onde de choc, secousse de caméra, et le nouveau plan arrive en force. Le son (`beat.py --fx-only`) place un whoosh au départ de chaque transition.

## La 3D
Appareil qui orbite lentement, reflets qui suivent son orientation, lueur des bords qui bat avec les basses, **plans flottants** (pochettes et bokehs à différentes profondeurs, flou de profondeur de champ, orbite, gonflement sur les basses) qui reçoivent le même mouvement de caméra que l'appareil — d'où la parallaxe —, cuts qui filent en avant avec de la profondeur.

## Le lecteur iOS
`ios-player.html` reproduit le lecteur plein écran de l'app iOS (`ios/Encre/Sources/Features/Player/FullPlayerView.swift`) : pochette immersive qui se fond dans le fond « vivant » (maillage 4×4 calculé comme `ArtworkPalette.meshColors`), qui respire sur le tempo, barre de progression, gros boutons, et la vue **paroles** (lignes floues autour de la ligne chantée, remplissage mot à mot). Police : Inter (SF Pro n'existe pas hors Apple). La page est pilotée par `setT(temps du morceau)` : chaque image est reproductible, et la position affichée suit la vraie position dans le morceau.

## Paroles synchronisées
Elles viennent **du code de Sona** (`app/providers/lrclib.py`, `netease.py`), comme dans l'app :
```bash
pip install httpx                                           # dépendance de Sona
python3 fetch-lyrics.py "Goutte d'eau" "Ninho" "Destin" 157 # → mock/lyrics.local.json (non versionné) ; n'affiche que des statistiques
# timeline.js : "lyrics_clip": "ioslyrics"
node clips.cjs _clips ioslyrics                             # filme la vue paroles iOS + relève la position du mot chanté (track.js)
```
Le script interroge LRCLIB et NetEase (accès réseau à `lrclib.net` et `music.163.com` nécessaire), garde la source la plus fine et recale les temps de `LYRICS_SHIFT` secondes (0,15 par défaut, mesuré sur l'audio). Avec des lignes horodatées seulement, la page iOS estime le remplissage mot à mot comme le fait l'app. Un `.lrc` fourni à la main marche aussi : `node lrc2json.cjs paroles.lrc`.
La caméra suit le mot en cours de chant (`followLyrics`). Les paroles ne sont jamais dans le dépôt. `LYRICS_TITLE="Amazing Grace" node clips.cjs …` filme avec des paroles du domaine public (démo).

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
node clips.cjs _clips ioshook,ioslyrics,home,devices,recap              # ≈ 25 min en haute résolution
mkdir -p _covers   # _covers/0.jpg … 8.jpg = 9 premières pochettes de _assets/catalog.json
python3 beat.py fx.wav --fx-only
python3 analyze-song.py                                         # kicks et basses réels → _assets/song/audio.js
node mixaudio.cjs _assets/song/song.m4a fx.wav audio.m4a       # le morceau est celui que tu fournis
node render.cjs motion.html _frames 60 3                        # ≈ 10 min  (FROM=… TO=… : une plage d'images)
ffmpeg -framerate 60 -i _frames/f%05d.png -i audio.m4a -c:v libx264 -preset slow -crf 15 -pix_fmt yuv420p \
  -vf "noise=alls=2:allf=t" -colorspace bt709 -color_primaries bt709 -color_trc bt709 -c:a copy -shortest -movflags +faststart sona-tiktok-v10.mp4
```
Les textes sont dans `motion.html` ; « Lien en bio » est à adapter ou retirer.
