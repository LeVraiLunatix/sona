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
- **Audio** : le morceau trouvé (Deezer/Spotify/Apple/YouTube) est résolu vers
  son équivalent sur YouTube Music (`ytmusicapi`), téléchargé avec `yt-dlp`,
  puis tagué (titre/artiste/album/cover) avec `mutagen` avant d'être envoyé
  comme fichier audio Telegram natif.
- **Bot privé** : seuls les `user_id` Telegram listés dans `ALLOWED_USER_IDS`
  peuvent utiliser le bot ; tous les autres sont rejetés silencieusement.
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
cookies d'un compte YouTube connecté :

1. Installe une extension navigateur du type
   [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)
   (Chrome/Edge) ou équivalent Firefox.
2. Connecte-toi sur [youtube.com](https://youtube.com) avec un compte Google.
3. Exporte les cookies du site en format Netscape (`cookies.txt`).
4. Place le fichier dans `data/cookies.txt` (déjà exclu de git).

Sona le détecte automatiquement à ce chemin (ou via `YOUTUBE_COOKIES_FILE`
dans `.env` pour un autre emplacement). Ces cookies expirent au bout d'un
moment ("Sign in to confirm..." qui revient après avoir fonctionné) — il
suffit de refaire un export.

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

## Tests

```bash
.venv\Scripts\python -m pytest
```

Les tests couvrent la détection de liens (Deezer/Spotify/Apple Music/YouTube).
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
