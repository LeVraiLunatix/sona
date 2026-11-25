# Sona — motion design TikTok (1080×1920, 60 i/s, 32 s)

| Fichier | Contenu |
|---|---|
| `sona-tiktok-v4.mp4` | **v4** : montage dynamique calé sur le tempo de « Le monde ou rien » (PNL, 102,85 BPM). Vraies interfaces de Sona, vrais titres/artistes/pochettes de rap français, avec un **beat d'attente original** (`beat.py`). |
| `sona-tiktok-v4-sans-son.mp4` | Même vidéo **sans son** : à utiliser pour ajouter le vrai morceau depuis la bibliothèque de sons de TikTok (licenciée). |
| `sona-tiktok-v1.mp4` | v1 : version sobre, 100 % typographique. |

## Pourquoi le morceau n'est pas dans le fichier
Le MP4 ne contient ni l'enregistrement de PNL ni ses paroles : ce sont des œuvres protégées, et un son « de commerce » incrusté dans une vidéo est le meilleur moyen de la voir coupée ou bloquée. Le montage est en revanche **calé sur le tempo du morceau** (1 temps = 0,583 s, 1 mesure = 2,33 s) : cuts, mots, rebonds et lueurs tombent sur les temps. Dans TikTok, ajoute le son de ton choix sur `sona-tiktok-v4-sans-son.mp4` et cale son premier temps sur le début de la vidéo (la vidéo ne bouge pas, c'est le son qu'on décale).

## Paroles synchronisées d'un vrai titre
Sans fichier, la scène « Paroles mot à mot » montre « Amazing Grace » (paroles de 1779, domaine public). Pour afficher le titre de ton choix, fournis **toi-même** des paroles horodatées :
```bash
node lrc2json.cjs paroles.lrc      # → mock/lyrics.local.json (non versionné) ; option : décalage en secondes
node clips.cjs _clips lyrics        # refilme la scène avec le titre vedette (PNL) dans le lecteur
```
Puis refais le rendu (voir ci-dessous). L'app de Sona estime elle-même le remplissage mot à mot à partir des lignes horodatées.

## Comment c'est fabriqué
Les écrans sont **la vraie app web** (`web/app.js`, `web/app.css`) filmée dans Chromium, branchée sur un faux serveur.

0. `fetch-catalog.cjs` : vrai catalogue de rap français (Deezer) + pochettes + photos d'artistes dans `_assets/` (non versionné).
1. `mock/server.cjs` : faux serveur (sert `web/` et simule l'API avec ce catalogue). Les chiffres des stats et du récap sont fictifs.
2. `appcap.cjs` + `clips.cjs` : filment l'app image par image à 60 i/s, de façon déterministe (horloge de la page simulée, `audio.currentTime` virtuel, animations CSS avancées à la main).
3. `timeline.js` : le plan de montage **en temps** (tempo + durée de chaque scène), lu par l'image et par le son.
4. `motion.html` : le montage (légendes sur les demi-temps, panneaux 3D qui rebondissent au kick, cuts « coup de fouet », lueurs qui pulsent). Aperçu dans un navigateur ; `?guides` : zones masquées par l'interface TikTok.
5. `beat.py` : beat d'attente original (aucun échantillon) + whooshes et impacts sur les cuts.
6. `render.cjs` + `ffmpeg` : export.

```bash
node fetch-catalog.cjs
(cd mock && node server.cjs &)                       # http://localhost:8765
node clips.cjs _clips all                            # filme les 4 écrans (≈ 15 min)
mkdir -p _covers && # copier les 9 premières pochettes de _assets/catalog.json en _covers/0.jpg … 8.jpg
python3 beat.py beat.wav
node render.cjs motion.html _frames 60 3             # ≈ 7 min  (FROM=… TO=… : ne refaire qu'une plage d'images)
ffmpeg -framerate 60 -i _frames/f%05d.png -i beat.wav -c:v libx264 -preset slow -crf 15 -pix_fmt yuv420p \
  -vf "noise=alls=2:allf=t" -colorspace bt709 -color_primaries bt709 -color_trc bt709 -c:a aac -b:a 192k -shortest -movflags +faststart sona-tiktok-v4.mp4
```
(`_assets`, `_clips`, `_frames`, `_covers` et `mock/lyrics.local.json` ne sont pas versionnés.) Les textes sont dans `motion.html` ; « Lien en bio » est à adapter ou retirer.
