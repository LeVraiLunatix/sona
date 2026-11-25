// Montage calé sur le tempo : « Goutte d'eau » (Ninho) = 138,0 BPM, mesuré sur le fichier audio. Durées en temps (beats) :
// 1 beat ≈ 0,4348 s ; 1 mesure = 4 beats ≈ 1,74 s. Le son (beat.py) et l'image (motion.html) lisent ce même fichier.
// Scènes : intro = le S se trace et « ona » (animation du site) · hero = « Ta musique, en clair. », un mot par temps · s_ly = paroles ·
// s_arc = arc de pochettes · s_home = accueil · s_dev = appareils · s_rc = récap · outro = final.
window.TIMELINE = {
  "bpm": 138.0,
  "song_start": 20.209,   // instant du morceau (s) joué à t = 0 de la vidéo : le 46e temps du morceau (1er temps à 0,209 s). La scène des paroles tombe sur « défoncer » (27,9 s) et le drop (33,69 s) sur le cut suivant
  "lyrics_clip": "ioslyrics", // "ioslyrics" = paroles mot à mot dans le lecteur iOS (il faut des paroles fournies : mock/lyrics.local.json) ; "iosplayer" = lecteur iOS plein écran ; "lyrics"/"player" = lecteur web
  "intro_start": 0.35, "intro_dur": 4.4,   // animation du site : le trait se remplit (lueur) à 0,35 + 4,4 × 0,42 ≈ 2,2 s = le 5e temps
  "scenes": [
    { "id": "intro", "b0": 0, "beats": 12 },
    { "id": "hero", "b0": 12, "beats": 4 },
    { "id": "s_ly", "b0": 16, "beats": 15 },
    { "id": "s_arc", "b0": 31, "beats": 4 },
    { "id": "s_home", "b0": 35, "beats": 8 },
    { "id": "s_dev", "b0": 43, "beats": 8 },
    { "id": "s_rc", "b0": 51, "beats": 8 },
    { "id": "outro", "b0": 59, "beats": 16 }
  ]
};
