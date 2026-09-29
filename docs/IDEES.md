# Idées pour plus tard

Des fonctionnalités validées sur le principe, gardées de côté.

## Karaoké : vraie séparation voix / instru

- **Séparation par IA sur le serveur** : modèles d'Ultimate Vocal Remover
  (MDX-Net, format ONNX). Chaque titre est découpé en deux pistes, voix et
  instru. C'est fait une fois par titre, puis gardé en cache (environ 5 à 8 Mo).
- **Curseur « Voix » dans le bouton Chante** :
  - 0 % : karaoké complet ;
  - une valeur intermédiaire : voix en fond ;
  - 100 % : titre normal, le mode chant se désactive tout seul.
- **Lecture** : les deux pistes sont jouées ensemble et parfaitement calées.
  Seul le volume de la voix change, donc le curseur agit en direct sans couper
  le titre.
- **Temps de séparation** : estimé à 1 à 3 minutes par titre sur le serveur
  Oracle (2 cœurs ARM). À mesurer avant de se lancer.
  - Une seule séparation à la fois, en priorité basse.
  - En attendant qu'elle soit prête, l'ancien mode prend le relais :
    instru YouTube, ou voix baissée.
- **Préparation d'avance** : les titres suivants de la file sont séparés quand
  le mode chant est activé, et les titres les plus écoutés la nuit.
