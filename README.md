# Sona

Bot Telegram musical privé : recherche et écoute de musique directement dans
Telegram, avec une interface pensée pour ressembler à une application plutôt
qu'à une liste de commandes.

Voir [docs/UX_FLOW.md](docs/UX_FLOW.md) pour le détail complet du parcours
utilisateur (écrans, navigation, callbacks).

## Fonctionnement

- **Métadonnées** (recherche, covers, tracklists, infos artiste) : API
  publique Deezer, iTunes/Apple Music, et l'API Spotify (ou son oEmbed public
  si aucune credential n'est configurée).
- **Recherche** : Deezer en premier (métadonnées riches, vraie pagination),
  puis iTunes et YouTube Music en secours si Deezer ne répond pas ou ne
  connaît pas le titre. La source qui a répondu est conservée pour toute la
  pagination de la recherche.
- **Audio** : le morceau trouvé (Deezer/Spotify/Apple/YouTube) est résolu vers
  son équivalent YouTube — plusieurs formulations de requête sont essayées sur
  YouTube Music (`ytmusicapi`), puis sur la recherche de `yt-dlp` si besoin —
  téléchargé avec `yt-dlp`, puis tagué (titre/artiste/album/cover) avec
  `mutagen` avant d'être envoyé comme fichier audio Telegram natif. Le
  téléchargement réessaie avec plusieurs clients YouTube (défaut, `tv`,
  `web_safari`, puis sans cookies) : quand l'un est cassé, un autre passe
  généralement.
- **Bot privé** : seuls les `user_id` Telegram listés dans `ALLOWED_USER_IDS`
  (les admins de départ) et les personnes qu'ils ont ajoutées depuis le bot
  peuvent l'utiliser. Voir [Inviter quelqu'un](#inviter-quelquun).
- **Cache** : une fois un morceau envoyé, son `file_id` Telegram est mis en
  cache (par source/format/qualité) — les demandes suivantes du même morceau
  sont donc instantanées, sans re-télécharger.

## Prérequis

- Python 3.11–3.13 (le projet a été développé et testé avec **3.12** ; les
  dépendances comme `pydantic`/`aiohttp` n'ont pas encore de wheels pour
  Python 3.14, évite cette version pour l'instant).
- [FFmpeg](https://ffmpeg.org/) installé et accessible (dans le PATH, ou via
  `FFMPEG_PATH` dans `.env`).
- Un bot Telegram créé via [@BotFather](https://t.me/BotFather) (token).
- Ton `user_id` Telegram (demande-le par exemple à [@userinfobot](https://t.me/userinfobot)).

## Installation

```bash
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
```

Édite `.env` :

```
BOT_TOKEN=<token @BotFather>
ALLOWED_USER_IDS=<ton_user_id>,<autre_user_id_si_besoin>
```

`SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` sont optionnels : sans eux, les
liens Spotify collés sont quand même reconnus mais avec des métadonnées plus
limitées (titre + cover, pas d'artiste/album fiables). Avec des identifiants
[Spotify for Developers](https://developer.spotify.com/dashboard) (Client
Credentials Flow, gratuit), la recherche et les pages morceau/album/artiste
Spotify deviennent aussi complètes que Deezer.

### Cookies YouTube (quasi obligatoire en hébergement VPS)

Depuis un serveur (IP de datacenter), YouTube bloque presque systématiquement
les téléchargements avec *"Sign in to confirm you're not a bot"* — ça ne se
voit généralement pas en local (IP résidentielle) mais ça bloque tout en
production. Le contournement documenté par `yt-dlp` est de fournir des
cookies d'un compte YouTube connecté.

**L'export doit suivre une procédure précise.** Si le navigateur continue à
se servir de la session après l'export, Google fait tourner ses cookies et
invalide ceux du fichier. Le fichier reste en place, mais YouTube traite Sona
comme un visiteur anonyme et tout retombe sur le mur anti-bot : c'est ce qui
s'est produit le 2026-09-15. Procédure du
[wiki yt-dlp](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies) :

1. Installe une extension d'export au format Netscape, par exemple
   [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)
   (Chrome/Edge) ou un équivalent Firefox, et **autorise-la en navigation
   privée** (réglage de l'extension).
2. Ouvre une **nouvelle fenêtre de navigation privée** et connecte-toi sur
   [youtube.com](https://www.youtube.com) avec le compte Google du bot.
3. **Dans le même onglet**, ouvre
   [youtube.com/robots.txt](https://www.youtube.com/robots.txt).
4. Exporte **uniquement les cookies de youtube.com** (l'export du site
   courant). **Pas** « Export All Cookies », qui embarque ceux de tous les
   sites.
5. **Ferme la fenêtre privée** tout de suite, et **ne la rouvre jamais** : la
   session exportée ne doit plus servir à aucun navigateur.
6. Place le fichier dans `data/cookies.txt` (déjà exclu de git), sur le VPS
   pour la production, puis redémarre Sona.

Sona le détecte automatiquement à ce chemin (ou via `YOUTUBE_COOKIES_FILE`
dans `.env` pour un autre emplacement). Une session finit quand même par
expirer : refais alors un export avec la même procédure.

#### Vérifier que la session est connectée

Au démarrage, puis quand un téléchargement bute sur le mur anti-bot à toutes
les tentatives (au plus une fois par quart d'heure), Sona charge une copie
temporaire de `cookies.txt` dans `yt-dlp`, ouvre youtube.com et lit
l'indicateur `"LOGGED_IN"` de la page. Dans les logs (`pm2 logs sona`) :

- `Session YouTube active` : les cookies sont bons ;
- `Cookies YouTube déconnectés` : YouTube renvoie `"LOGGED_IN": false`
  malgré le fichier. La session Google est morte, refais un export.

Pas besoin de surveiller les logs : dès que la session tombe, **chaque
administrateur reçoit un message privé de Sona** avec la marche à suivre, puis
un rappel toutes les 12 h tant que rien ne change, et un message quand tout
est rentré dans l'ordre. Le message ne contient jamais la moindre valeur de
cookie.

Les avertissements de `yt-dlp` liés aux cookies (par exemple *"The provided
YouTube account cookies are no longer valid"*) apparaissent aussi dans les
logs, sous le nom `yt_dlp`.

Pour vérifier à la main sans redémarrer le bot, par exemple juste après avoir
déposé un nouvel export, lance depuis le dossier de Sona avec le Python du
venv :

```bash
.venv/bin/python -m app.services.youtube_session
```

(`.venv\Scripts\python` sous Windows.) Code de sortie : `0` connecté, `1`
déconnecté ou indéterminé, `2` aucun fichier de cookies.

**Ne teste pas avec la vidéo `dQw4w9WgXcQ`** (Rick Astley) : elle se
télécharge depuis le VPS même quand tout le reste est bloqué, cookies morts
compris. La voir passer ne prouve rien : teste un autre morceau, ou la
commande ci-dessus.

**Avec des cookies, `yt-dlp` a aussi besoin d'un moteur JavaScript** (pour
déchiffrer les flux YouTube — voir le
[wiki EJS de yt-dlp](https://github.com/yt-dlp/yt-dlp/wiki/EJS)), sans quoi
le téléchargement échoue avec *"Requested format is not available"*. Le plus
simple est [Deno](https://deno.com/) (détecté automatiquement s'il est dans
le `PATH`, aucune configuration `yt-dlp` supplémentaire nécessaire) :

```bash
curl -fsSL https://deno.land/install.sh | sh
sudo ln -sf ~/.deno/bin/deno /usr/local/bin/deno   # pour qu'il soit trouvable par tous les process (ex: PM2)
```

`requirements.txt` installe déjà `yt-dlp[default]`, qui inclut les scripts de
déchiffrement (EJS) nécessaires — pas d'étape supplémentaire côté Python.

Même avec cookies + Deno, le déchiffrement échoue parfois de façon
intermittente (observé en usage réel) ; Sona réessaie automatiquement
jusqu'à 3 fois avant d'afficher "indisponible".

## Lancer le bot

```bash
.venv\Scripts\python run.py
```

Le bot tourne en *polling* (pas besoin de serveur public / webhook). Arrête-le
avec Ctrl+C.

## Déploiement

Une fusion sur `master` lance les tests, puis — s'ils passent — le
déploiement sur le VPS : GitHub se connecte en SSH et le serveur exécute
`~/sona/deploy.sh`. La marche à suivre (clé dédiée, commande forcée dans
`authorized_keys`, empreinte du serveur, secrets du dépôt) est dans
[docs/DEPLOIEMENT.md](docs/DEPLOIEMENT.md). Tant que les secrets ne sont pas
créés, l'étape de déploiement est ignorée avec un avertissement.

## Sauvegardes de la base

`data/sona.db` porte les accès, la bibliothèque, l'historique et le cache des
`file_id` Telegram : la perdre, ce sont toutes les invitations à refaire et
tous les morceaux à retélécharger. Sona en fait donc une copie par jour, dans
`data/backups/` (modifiable avec `BACKUP_DIR` dans `.env`) :

- la copie passe par l'API `backup` de SQLite, qui sait copier une base
  ouverte — un `cp` pendant une écriture donnerait un fichier tronqué ;
- les fichiers sont en `600`, les 7 plus récents sont conservés ;
- la première copie part dès le démarrage si la dernière date de plus de 24 h ;
- chaque sauvegarde et chaque échec sont journalisés (`pm2 logs sona`), et un
  échec n'arrête jamais le bot.

Pour restaurer, bot arrêté : remplace `data/sona.db` par la sauvegarde
choisie, puis redémarre (`pm2 restart sona`).

## Commandes

| Commande | Qui | Effet |
|---|---|---|
| `/start` | tout le monde | Ouvre l'accueil ; hors whitelist, utilise le jeton d'invitation ou envoie une demande d'accès |
| `/search` | autorisés | Ouvre l'écran de recherche |
| `/search <requête>` | autorisés | Affiche directement le menu des morceaux trouvés |
| `@<bot> <requête>` | autorisés | Suggestions en direct au-dessus du champ de saisie (voir ci-dessous) |
| `/help` | autorisés | Revient à l'accueil |
| `/id` | tout le monde | Affiche son identifiant Telegram |
| `/invite` | admins | Crée un lien d'invitation |
| `/allow <id>` | admins | Autorise un identifiant Telegram directement |

Ces commandes sont déclarées auprès de Telegram au démarrage : elles
apparaissent dans le bouton « Menu » de la conversation (les deux dernières
uniquement pour les admins).

## Suggestions en direct (mode inline)

Sona peut afficher un **panneau de suggestions au-dessus du champ de saisie**,
rafraîchi à chaque lettre tapée — comme la recherche de GIF de Telegram. C'est
le chemin le plus rapide : on tape, on touche le morceau, c'est fini.

Ça demande une activation côté Telegram, une seule fois :

1. Ouvre [@BotFather](https://t.me/BotFather) → `/setinline`
2. Choisis ton bot
3. Entre le texte d'invite affiché dans le champ, par exemple
   `Un titre, un artiste…`

Ensuite, dans la conversation avec Sona :

- soit tu touches **« 🔍 Suggestions en direct »** sur l'écran Recherche
  (bouton « Rechercher » ou `/search`) — Telegram pré-remplit le champ et
  ouvre le panneau ;
- soit tu tapes `@<nom_du_bot> ` suivi de ta recherche, depuis n'importe
  quelle conversation.

Un morceau déjà envoyé une fois (donc présent dans le cache) apparaît
directement comme fichier audio prêt à envoyer : un seul tap et il arrive,
sans re-téléchargement. Les autres renvoient leur lien, que Sona redétecte
aussitôt pour ouvrir l'écran Morceau.

Le mode inline est soumis à la même whitelist que le reste : quelqu'un qui
n'est pas autorisé ne voit aucun résultat, juste un bouton pour demander
l'accès.

Sans cette activation, rien n'est cassé — le bouton « Suggestions en direct »
renvoie simplement une erreur Telegram, et la recherche classique (taper le
titre dans la conversation, ou `/search <titre>`) fonctionne comme avant.

## Inviter quelqu'un

Trois chemins, à utiliser dans cet ordre :

1. **Lien d'invitation.** Paramètres > Gestion des accès > « Inviter
   quelqu'un » (ou `/invite`). Le lien vaut 7 jours, en usage unique ou pour
   10 personnes. Si l'invité a **déjà une conversation ouverte** avec le bot,
   Telegram n'envoie pas toujours le paramètre du lien et son `/start` arrive
   sans jeton : il peut alors simplement **coller le lien dans la
   conversation**, Sona le reconnaît.
2. **Demande d'accès.** L'invité envoie `/start` : Sona enregistre sa demande
   et notifie les admins en message direct, avec un bouton « Autoriser ».
   Validée, la personne reçoit un message et arrive sur l'accueil.
3. **Ajout manuel.** L'invité envoie `/id` et communique le nombre affiché ;
   l'admin fait `/allow <id>`.

Un refus explique toujours sa raison (lien inconnu, expiré, déjà utilisé) —
jamais un simple « bot privé » qui laisserait croire à une panne.

## Tests

```bash
.venv\Scripts\python -m pytest
```

Ils tournent aussi sur GitHub (`.github/workflows/tests.yml`) à chaque *pull
request* et sur `master`, sous Python 3.12 comme le VPS.

Les tests couvrent la détection de liens (Deezer/Spotify/Apple Music/YouTube),
le cycle de vie des invitations et des demandes d'accès (y compris la
migration d'une base créée par une version antérieure), la sélection du
meilleur résultat YouTube pour un morceau, la cascade de recherche
Deezer → iTunes → YouTube Music, la gestion des fichiers téléchargés, la
détection d'une cascade de téléchargement entièrement bloquée par le mur
anti-bot, la vérification de session YouTube (copie temporaire du fichier de
cookies, lecture de `"LOGGED_IN"`) et le tri des avertissements de `yt-dlp`.
Les providers et le pipeline de téléchargement ont été vérifiés manuellement
en conditions réelles pendant le développement (recherche Deezer, résolution
YouTube Music, téléchargement + tag ffmpeg/mutagen, lecture/écriture SQLite) —
voir la session de build pour le détail, aucun test automatisé ne fait
d'appel réseau réel pour rester rapide et déterministe en CI.

## Limitations connues

- **Playlists** : seules les playlists YouTube sont affichées (gabarit
  Album). Les playlists Deezer/Spotify/Apple Music ne sont pas prises en
  charge (endpoints non implémentés) — le lien est reconnu mais annoncé
  comme indisponible.
- **Recherche de la source** : si aucun résultat YouTube ne ressemble
  suffisamment au morceau (titre *et* durée), Sona préfère annoncer « Aucune
  source audio trouvée » plutôt que d'envoyer un autre morceau. Sur un titre
  rare, essayer une autre version (album, live) aboutit souvent.
- **yt-dlp se périme vite** : YouTube change régulièrement ses mécanismes
  anti-bot, ce qui casse les vieilles versions de `yt-dlp` (erreur type *"The
  page needs to be reloaded"*). Si l'audio devient indisponible partout,
  commence par `pip install -U yt-dlp`.
- **"Sign in to confirm you're not a bot" en hébergement VPS** : voir la
  section Cookies YouTube ci-dessus — quasi systématique depuis une IP de
  datacenter tant qu'aucun `cookies.txt` n'est fourni.
- **Qualité audio** : "Meilleure disponible" vs "Standard (débit réduit)"
  changent réellement le flux demandé à YouTube ; il n'y a pas de FLAC ou de
  qualité supérieure à ce que YouTube fournit (cohérent avec la contrainte du
  brief : ne jamais inventer une qualité qui n'existe pas côté source).
- **État de navigation en mémoire** : la pile de navigation par utilisateur
  vit en RAM (pas en base). Un redémarrage du bot ramène chaque utilisateur à
  l'écran d'accueil au prochain clic — acceptable pour un usage privé à
  quelques utilisateurs.
