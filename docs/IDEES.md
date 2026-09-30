# Idées pour plus tard

Des fonctionnalités validées sur le principe, gardées de côté.

## Karaoké : fait

La vraie séparation voix / instru est en place (voir `app/services/karaoke.py`
côté serveur, `Karaoke.swift` et le bouton « Chante » côté iOS).

- **Modèles** : Ultimate Vocal Remover (MDX-Net, ONNX), exécutés avec numpy
  + onnxruntime. Téléchargés une fois dans `data/models/` (30 et 60 Mo).
- **Deux passes** : une passe rapide (UVR_MDXNET_9482) pour chanter vite,
  puis une passe fine (Inst_HQ_4) en arrière-plan, qui remplace les pistes
  rapides sans coupure.
- **Temps mesuré** (3 min de musique, 2 cœurs ARM Neoverse N2) : passe
  rapide ≈ 1 min 45 (1,5 Go de mémoire), passe fine ≈ 4 à 5 min (2,4 Go).
  Compter 20 à 50 % de plus sur le serveur Oracle (Neoverse N1).
- **Pistes** : ≈ 7 Mo par titre (voix + instru en AAC), dans `data/karaoke/`
  (1,5 Go max, les moins écoutées partent d'abord).
- **Hors ligne** : les pistes des titres téléchargés sont gardées avec eux
  sur l'iPhone.
- **Site web** : bouton « Chante » et curseur « Voix » dans le lecteur plein
  écran (les deux pistes passent par le Web Audio du navigateur).

Piste pour plus tard : passer le serveur Oracle à 4 cœurs (possible dans
l'offre gratuite) diviserait à peu près par deux le temps de séparation —
changer alors `KARAOKE_THREADS=4` dans `.env`.
