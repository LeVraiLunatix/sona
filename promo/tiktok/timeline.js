// Montage calé sur le tempo : « Goutte d'eau » (Ninho) = 137,8 BPM (valeur Deezer). Durées en temps (beats) :
// 1 beat ≈ 0,435 s ; 1 mesure = 4 beats ≈ 1,74 s. Le son (beat.py) et l'image (motion.html) lisent ce même fichier.
// Scènes : intro = le S se trace et « ona » (animation du site) · hero = « Ta musique, en clair. », un mot par temps · s_ly = paroles ·
// s_arc = arc de pochettes · s_home = accueil · s_dev = appareils · s_rc = récap · outro = final.
window.TIMELINE = {
  "bpm": 137.8,
  "intro_start": 0.35, "intro_dur": 4.4,   // animation du site : le trait se remplit (lueur) à 0,35 + 4,4 × 0,42 ≈ 2,2 s = le 5e temps
  "scenes": [
    { "id": "intro", "b0": 0, "beats": 12 },
    { "id": "hero", "b0": 12, "beats": 4 },
    { "id": "s_ly", "b0": 16, "beats": 12 },
    { "id": "s_arc", "b0": 28, "beats": 4 },
    { "id": "s_home", "b0": 32, "beats": 8 },
    { "id": "s_dev", "b0": 40, "beats": 8 },
    { "id": "s_rc", "b0": 48, "beats": 8 },
    { "id": "outro", "b0": 56, "beats": 16 }
  ]
};
