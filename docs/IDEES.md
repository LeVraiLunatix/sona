# Idées pour plus tard

Des fonctionnalités validées sur le principe, gardées de côté.

## Karaoké : fait

La vraie séparation voix / instru est en place (voir `app/services/karaoke.py`
côté serveur, `Karaoke.swift` et le bouton « Chante » côté iOS).

- **Modèle** : UVR-MDX-NET-Inst_HQ_4 (Ultimate Vocal Remover, ONNX), exécuté
  avec numpy + onnxruntime. Téléchargé une fois dans `data/models/` (60 Mo).
- **Temps mesuré** : 3 min de musique séparées en ≈ 5 min sur 2 cœurs ARM
  récents (Neoverse N2) ; compter 5 à 8 min sur le serveur Oracle (Neoverse
  N1), avec ≈ 2,4 Go de mémoire pendant le calcul.
- **Pistes** : ≈ 7 Mo par titre (voix + instru en AAC), dans `data/karaoke/`
  (1,5 Go max, les moins écoutées partent d'abord).

Pistes pour plus tard :

- Lecteur web : proposer le mode chant avec les deux pistes
  (`/stream/…/karaoke/vocals` et `/instrumental`, déjà lisibles avec le jeton
  dans l'adresse).
- Téléchargements hors ligne : garder aussi les pistes séparées des titres
  téléchargés (aujourd'hui dans le cache de l'iPhone, que iOS peut vider).
