# Prompt à coller dans Claude Code, en local sur ton PC

(à lancer dans le dossier du dépôt `sona`, branche `claude/tiktok-motion-design-etmeel`)

```text
Contexte : dans ce dépôt, promo/tiktok/ contient un motion design TikTok de Sona (1080×1920, 60 i/s). Lis d'abord promo/tiktok/README.md, puis timeline.js, motion.html (la caméra : camera(), panel(), followLyrics()), clips.cjs, ios-player.html (réplique du lecteur plein écran de l'app iOS, vue « player » et vue « lyrics »), mock/server.cjs, mixaudio.cjs et beat.py.
Aujourd'hui (sona-tiktok-v6.mp4) : le VRAI morceau « Goutte d'eau » (Ninho, 138 BPM, fichier fourni par moi) est la musique ; le montage est calé sur ses temps ; la caméra fait un travelling avant dans l'appareil entier ; la scène « s_ly » montre le lecteur iOS plein écran SANS paroles (je n'avais pas de paroles).

OBJECTIF : produire sona-tiktok-v7.mp4 où la scène « Paroles mot à mot » montre, dans la vue paroles du lecteur iOS (ios-player.html?view=lyrics), les VRAIES paroles du morceau remplies mot à mot et EXACTEMENT synchronisées avec l'audio entendu, avec la caméra qui se rapproche puis SUIT le mot chanté (followLyrics lit le fichier track.js écrit par clips.cjs : position du mot en cours à chaque image).

Avant de commencer, DEMANDE-MOI (ne devine pas) :
 - le chemin du fichier audio du morceau (je l'ai déjà : _assets/song/song.m4a s'il est là ; sinon redemande-le) ;
 - d'où viennent les paroles : (a) mon serveur Sona — GET /lyrics?title=…&artist=…&duration= avec un jeton Bearer (adresse dans <meta name="sona-server"> de web/index.html), réponse lines[{time,text,words[{time,end,text}]}] ; demande-moi l'adresse et le jeton, ou lance l'API en local selon le README racine — ou (b) un fichier .lrc → `node lrc2json.cjs paroles.lrc` ;
 - le passage du morceau où je veux les paroles (ex. le refrain à 1:05).

Étapes :
 1. Environnement : Node 20+, `npm i playwright` + `npx playwright install chromium`, ffmpeg, Python 3 + numpy. `node fetch-catalog.cjs` (internet requis), recrée _covers/0.jpg…8.jpg.
 2. Paroles → mock/lyrics.local.json (ignoré par git), {"lines":[{"time":s,"text":"…","words":[{"time":…,"end":…,"text":"… "}]}]}, temps relatifs au début du MORCEAU. Sans words, ios-player.html estime les mots à partir des lignes.
 3. Calage (point critique) : mesure le vrai BPM et le 1er temps de l'audio, mets à jour timeline.js (bpm, song_start). Pour que la phrase choisie (instant Tc du morceau) tombe pendant la scène s_ly : song_start = Tc − (début de s_ly en secondes = b0·60/bpm) − 0,3 s, en gardant song_start sur un temps du morceau. clips.cjs filme le clip avec LY_AT = song_start + début de s_ly + 0,3 : motion.html lit ce clip à lt − 0,3 s, garde ces décalages cohérents. Mets "lyrics_clip": "ioslyrics" dans timeline.js.
 4. Refais : `node clips.cjs _clips ioslyrics` (filme la vue paroles iOS et écrit track.js), puis recale les cadrages caméra de s_ly si besoin ; `node mixaudio.cjs _assets/song/song.m4a fx.wav audio.m4a` (après `python3 beat.py fx.wav --fx-only`) ; `node render.cjs motion.html _frames 60 3` ; ffmpeg (commande du README).
 5. Vérifie sur des images extraites : le mot rempli à l'écran à l'instant t = le mot chanté à t (compare avec l'enveloppe audio) ; la caméra reste sur le mot ; rien d'important dans les zones masquées par TikTok (?guides) ; 1080×1920, 60 i/s, H.264 yuv420p + AAC.
 6. Livre sona-tiktok-v7.mp4 ET sona-tiktok-v7-sans-son.mp4. N'ajoute à git NI l'audio, NI les paroles, NI les pochettes ; commit le code uniquement.

Pièges déjà rencontrés : appcap.cjs doit remettre lyricsClockState à zéro après freeze() ; garder la souris hors de la page (un :hover éclaire une ligne) ; loudnorm change la fréquence d'échantillonnage (aresample avant amix) ; le lecteur iOS est piloté par setT(), pas par une horloge.
```
