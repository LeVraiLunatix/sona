# Sona — motion design TikTok (1080×1920, 60 i/s, ~32 s)

`sona-tiktok.mp4` : la vidéo finale, sans musique (à ajouter dans TikTok).

- `index.html` : l'animation, entièrement pilotée par `seek(t)` (rendu déterministe). L'intro (S tracé, lueur, « ona », titre mot à mot) reprend le code de `web/presentation.html`. Ouvre-la dans un navigateur pour la voir en boucle ; `?guides` affiche les zones masquées par l'interface TikTok.
- `render.cjs` : capture les images avec Playwright.

```bash
node render.cjs /tmp/frames 60 3
ffmpeg -framerate 60 -i /tmp/frames/f%05d.png -c:v libx264 -preset slow -crf 14 -pix_fmt yuv420p \
  -vf "noise=alls=2:allf=t" -colorspace bt709 -color_primaries bt709 -color_trc bt709 -movflags +faststart sona-tiktok.mp4
```
Les textes sont dans `index.html` (français) ; « Lien en bio » est à adapter ou retirer.
