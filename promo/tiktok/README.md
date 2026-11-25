# Sona — motion design TikTok (1080×1920, 60 i/s)

| Fichier | Contenu |
|---|---|
| `sona-tiktok-v3.mp4` | **v3, ~39 s** : les vraies interfaces de Sona (paroles mot à mot, accueil, Appareils, récap du mois) en perspective 3D, avec de vrais titres, artistes et pochettes (classement Deezer). Sans musique (à ajouter dans TikTok). |
| `sona-tiktok-v1.mp4` | v1, ~32 s : version sobre, 100 % typographique. |

L'intro (S tracé, lueur, « ona », titre mot à mot) reprend le code de `web/presentation.html`.

## Comment la v3 est fabriquée

Les écrans ne sont pas des maquettes : c'est **la vraie app web** (`web/app.js`, `web/app.css`) filmée dans Chromium.

0. `fetch-catalog.cjs` : récupère un vrai catalogue (classement Deezer) et les pochettes dans `_assets/` (non versionné). Pour la scène des paroles : « Amazing Grace » (Aretha Franklin), dont les paroles (1779) sont dans le domaine public ; on ne reproduit pas les paroles d'une chanson sous droits.
1. `mock/server.cjs` : faux serveur (sert `web/` et simule l'API avec ce catalogue). Les chiffres des stats et du récap, eux, sont fictifs.
2. `appcap.cjs` + `clips.cjs` : filment l'app image par image à 60 i/s, de façon déterministe (horloge de la page simulée, `audio.currentTime` virtuel, animations CSS avancées à la main).
3. `motion.html` : le montage (légendes, panneaux 3D, arc de pochettes, final), piloté par `seek(t)`. Ouvre-le dans un navigateur pour l'aperçu (`?guides` : zones masquées par l'interface TikTok).
4. `render.cjs` + `ffmpeg` : export.

```bash
node fetch-catalog.cjs                               # vrai catalogue + pochettes (_assets/)
(cd mock && node server.cjs &)                       # http://localhost:8765
node clips.cjs _clips all                            # filme les 4 écrans (≈ 6 min)
node render.cjs motion.html _frames 60 3             # images du montage (≈ 9 min)
ffmpeg -framerate 60 -i _frames/f%05d.png -c:v libx264 -preset slow -crf 15 -pix_fmt yuv420p \
  -vf "noise=alls=2:allf=t" -colorspace bt709 -color_primaries bt709 -color_trc bt709 -movflags +faststart sona-tiktok-v3.mp4
```
(`_assets`, `_clips`, `_frames` et `_covers` ne sont pas versionnés ; `_covers/N.jpg` = les 9 premières pochettes de `_assets/catalog.json`.)

Les textes sont dans `motion.html` ; « Lien en bio » est à adapter ou retirer.
