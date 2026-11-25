# Prompt à coller dans Claude Code, en local sur ton PC

(à lancer dans le dossier du dépôt `sona`, branche `claude/tiktok-motion-design-etmeel`)

```text
Contexte : dans ce dépôt, le dossier promo/tiktok/ contient un motion design TikTok de Sona (1080×1920, 60 i/s). Lis d'abord promo/tiktok/README.md puis promo/tiktok/timeline.js, motion.html, clips.cjs, appcap.cjs, mock/server.cjs et beat.py.
Le principe : la VRAIE app web de Sona (web/app.js + app.css) est filmée dans Chromium par Playwright, image par image (horloge simulée), branchée sur un faux serveur (mock/server.cjs) ; motion.html assemble le montage en 3D, calé sur le tempo défini dans timeline.js ; beat.py fabrique un beat d'attente. Aujourd'hui la vidéo (sona-tiktok-v5.mp4) utilise « Goutte d'eau » de Ninho (137,8 BPM) comme titre vedette dans l'interface, un beat original comme musique, et la scène « Paroles mot à mot » montre des paroles du domaine public (Amazing Grace) parce que le cloud n'a ni l'audio ni les paroles.

OBJECTIF : produire sona-tiktok-v6.mp4 où
 1. la VRAIE musique de « Goutte d'eau » (Ninho) est la musique de fond de toute la vidéo ;
 2. dans la scène « Paroles mot à mot » (lecteur Sona sur téléphone), s'affichent les VRAIES paroles du morceau, remplies mot à mot, EXACTEMENT synchronisées avec l'audio que l'on entend à cet instant de la vidéo ;
 3. le montage (cuts, mots des légendes, rebonds, lueurs) tombe sur les temps du VRAI morceau.

Avant de commencer, DEMANDE-MOI (ne devine pas) :
 - le chemin du fichier audio du morceau (mp3/wav/flac) que je possède ;
 - d'où viennent les paroles : (a) mon serveur Sona — l'app appelle GET /lyrics?title=…&artist=…&duration=… avec un jeton Bearer, l'adresse est dans <meta name="sona-server"> de web/index.html, et la réponse contient lines[{time,text,words[{time,end,text}]}] ; demande-moi l'adresse et le jeton, ou lance l'API en local selon le README racine — ou (b) un fichier .lrc, à convertir avec promo/tiktok/lrc2json.cjs ;
 - à quel moment du morceau je veux les paroles (le refrain, ex. « 1:05 ») et si je veux changer de morceau.

Étapes :
 1. Prépare l'environnement : Node 20+, `npm i playwright` puis `npx playwright install chromium` (les scripts font require("playwright")), ffmpeg, Python 3 + numpy. Lance `node fetch-catalog.cjs` (vrai catalogue Deezer, nécessite internet) ; recrée promo/tiktok/_covers/0.jpg…8.jpg à partir des 9 premières pochettes de _assets/catalog.json ; `_clips` = dossier de sortie de clips.cjs.
 2. Paroles : écris-les dans promo/tiktok/mock/lyrics.local.json (déjà ignoré par git) au format {"lines":[{"time":secondes,"text":"…","words":[{"time":…,"end":…,"text":"… "}]}]}, temps relatifs au début du MORCEAU. Si on n'a que des lignes horodatées (sans words), le serveur mock les renvoie en sync:"line" et l'app estime le remplissage mot à mot ; si mon serveur Sona fournit les mots, utilise-les (sync:"word"). Vérifie dans mock/server.cjs que, quand ce fichier existe, le titre affiché dans le lecteur est bien le titre vedette (TRACKS[0]).
 3. Tempo : mesure le vrai BPM et la phase du premier temps du fichier audio (détection d'onsets + peigne en numpy, ou ffmpeg/aubio si dispo), puis mets à jour timeline.js (bpm, éventuellement un « grid_offset » en secondes si le premier temps n'est pas à 0) et la HERO/bpm de fetch-catalog.cjs. Les durées des scènes sont en temps ; garde les scènes sur des mesures entières ; motion.html/beat.py lisent timeline.js.
 4. Synchronisation audio/paroles (le point critique) : soit Tc le temps du morceau où commence la phrase choisie, et A le temps de la vidéo où démarre la scène « s_ly » (A = b0 × 60/bpm). La bande son de la vidéo doit commencer à S = Tc − A − (lead voulu ≈ 0,3 s, le temps que la scène entre) dans le morceau ; s'il est négatif, choisis un Tc plus tardif ou cale les premiers temps en conséquence. Dans clips.cjs, le clip « lyrics » doit être filmé avec audio_start = Tc − 0,3 (la valeur passée à freeze(page, …)), secs ≥ la durée visible dans la scène ; motion.html lit ce clip à lt − 0,3 s : garde ces deux décalages cohérents pour que le mot rempli à l'écran corresponde au mot chanté dans l'audio. Si tu modifies les durées de clips, mets à jour les tailles dans l'objet CL de motion.html.
 5. Audio final : coupe le morceau (ffmpeg -ss S -t durée), fondu d'entrée/sortie, normalise (~ -14 LUFS), puis mixe par-dessus, très bas, les whooshes/impacts de beat.py (ajoute-lui une option --fx-only qui n'écrit que ces effets, sans batterie ni mélodie). Au lieu du beat.wav, mux ce fichier dans la vidéo (même commande ffmpeg que dans le README).
 6. Refais le rendu : `node clips.cjs _clips lyrics` (et `all` si le titre vedette a changé), puis `node render.cjs motion.html _frames 60 3` (≈ 8 min ; FROM/TO pour refaire une plage), puis ffmpeg.
 7. Vérifie, en extrayant des images de la vidéo finale : (a) le mot rempli à l'écran à un instant t correspond au mot chanté à t dans l'audio (compare avec l'enveloppe audio autour de ce mot) ; (b) avec ?guides, rien d'important ne tombe dans les zones masquées par TikTok ; (c) sortie 1080×1920, 60 i/s, H.264 yuv420p + AAC.
 8. Livre : sona-tiktok-v6.mp4 (avec le vrai morceau) ET sona-tiktok-v6-sans-son.mp4 (pour ajouter le son depuis la bibliothèque de TikTok, car un son du commerce incrusté peut être coupé ou bloqué). N'ajoute à git NI l'audio, NI les paroles, NI les pochettes (.gitignore) ; commit le code uniquement.

Pièges déjà rencontrés : appcap.cjs doit remettre lyricsClockState à zéro après freeze() ; garder la souris hors de la page (sinon un :hover éclaire une ligne de paroles) ; les animations CSS/WAAPI sont avancées à la main dans step() ; JPEG 60 i/s dans _clips/<clip>/f%04d.jpg ; un « clip » = une séquence filmée de l'app réelle.
```
