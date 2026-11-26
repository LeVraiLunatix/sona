# Comptes, social, admin, sidebar : audit et plan

Document écrit avant de coder (étape « explore tout le repo »).

## 1. Ce que contient le dépôt

| Brique | Techno | Rôle |
|---|---|---|
| `app/api` | **FastAPI** + **SQLite** (aiosqlite), hébergé sur un VPS Oracle derrière Caddy | Moteur musique : recherche, catalogue, flux audio (yt-dlp), paroles, karaoké, bibliothèque, playlists, écoutes (`plays`), stats, Sona Connect, TV |
| `web/` | JS vanilla (un seul `app.js` de ~8 600 lignes), servi par Vercel (trysona.fr) **et** par FastAPI (`/web/`) | Site / PWA, aussi chargé dans l'app Windows |
| `desktop/` | Electron | App Windows (charge le site, jumelage appareils, Discord RPC…) |
| `ios/Encre` | SwiftUI natif (CI macOS, sideload `.ipa`) | App iPhone native, parle à la même API |
| `app/bot` | aiogram | Bot Telegram (historique, ne concerne pas ce chantier) |

Il n'y a **pas** de Supabase, pas de Postgres, pas d'Android natif (Android = PWA).

### Authentification actuelle
- `app/api/auth.py` : jeton unique `API_TOKEN` (admin) ou « session » maison (`app_sessions`, empreinte SHA-256) obtenue par `POST /auth/lastfm` (jeton Last.fm → `auth.getSession` **côté FastAPI**).
- Table `app_accounts` : `lastfm_username` (NOT NULL, UNIQUE) sert d'identité, `status` (`pending`/`approved`/`rejected`) = validation manuelle par un admin, `is_admin`, `user_id` (espace de données entier), `lastfm_session_key` **en clair**.
- Écran de connexion web : un seul bouton Last.fm, avec contournements pour l'app installée (iOS) et Electron.

### Social actuel (le problème)
- `routers/friends.py` : *« Amis = tous les comptes acceptés qui partagent leur écoute »*. Aucune table d'amitiés. `_friends()` renvoie tous les comptes `approved` avec `share_listening`.
- Même logique « tout le monde est visible » dans `routers/party.py` (`/party/active`), `routers/extras.py` (moments), `routers/public.py`, `routers/stats.py` (classement entre comptes).
- `services/presence.py` : « en train d'écouter » en mémoire, publié par défaut (`share_listening` = 1).
- `services/party.py` : sessions d'écoute **en mémoire** (code court, hôte, file proposée, votes, chat, expulsion, transfert d'hôte, `open_controls`). Ni verrouillage, ni liste de bannis, ni limite de participants, ni invitation à jeton, ni blocage entre utilisateurs, ni signalement.

### Sidebar actuelle
`renderShell()` (`app.js` ~568) + CSS réparti sur trois blocs de `app.css` (lignes ~83-135, ~1558-1610, ~1746-1790) qui se contredisent : largeur du rail animée (`width`, force le reflow), `:hover` qui agrandit le rail en repoussant la grille, labels en `max-width`, une dizaine d'entrées plus deux listes de playlists. Aucune bascule clavier, pas d'`aria-current` / `aria-expanded`.

## 2. Décision d'architecture (prise à ta place)

Le cahier des charges suppose Supabase partout (Auth, Postgres + RLS, Edge Functions). Réécrire le moteur musique sur Postgres (repository de 1 800 lignes, flux audio, 60 fichiers de tests) n'est pas raisonnable ni sûr. Architecture retenue : **hybride**.

```
 Navigateur / PWA / Windows / iOS
      │  supabase-js (auth, RPC amis, réglages, signalements)      ┌───────────────────────┐
      ├───────────────────────────────────────────────────────────▶│ Supabase              │
      │                                                            │  Auth (toutes méthodes)│
      │  Edge Functions : lastfm, admin, account, passkey          │  Postgres + RLS        │
      ├───────────────────────────────────────────────────────────▶│  Edge Functions (Deno) │
      │                                                            └──────────▲────────────┘
      │  Bearer <JWT Supabase>                                                │ service role (serveur seulement)
      ▼                                                                       │
 FastAPI (VPS) ── vérifie le JWT, lit statut/ban/confidentialité/amitiés ─────┘
   musique, bibliothèque, playlists, écoutes (SQLite), sessions d'écoute (mémoire)
```

- **Supabase = identité + tout ce qui est social et modération** : `profiles`, rôles, sanctions, `audit_log`, amitiés, blocages, confidentialité, signalements, anti-abus, `connected_services`, passkeys. **RLS sur toutes les tables.** Les règles de visibilité vivent à un seul endroit : la fonction SQL `public.can_view(viewer, owner, scope)`, appelée aussi par FastAPI (RPC) pour les données qu'il sert.
- **FastAPI reste le moteur musique**, mais n'a plus son propre système de comptes : il valide le JWT Supabase (ES256 via JWKS, ou HS256), rattache `sub` à un `app_accounts.supabase_uid` créé à la volée, et **interroge Supabase à chaque requête** (cache de 5 s) pour refuser un compte banni ou suspendu même avec un jeton encore valide.
- **Écart assumé avec la section 4 du cahier des charges** : `library`, `playlists`, `playlist_tracks`, `listening_history` (= `plays`) restent dans SQLite côté FastAPI (espace de données entier par compte), et non dans Postgres. Ce sont des données couplées au flux audio ; leur visibilité envers les amis passe par `can_view` (Supabase) puis le filtrage FastAPI. `user_settings`, `connected_services` et tout le reste du schéma sont dans Postgres. Migrer ces quatre tables plus tard est possible sans changer l'API.
- **Sessions d'écoute** : elles restent en mémoire dans FastAPI (état éphémère, nettoyé à la fermeture, ce que demande la spec) mais gagnent rôles, accès (amis / invitation à jeton expirant / ouvert avec lien), verrouillage, bannissement de session, coupure du chat, limite de participants, blocage entre utilisateurs et signalement de messages.
- **Last.fm** : l'échange `auth.getSession` et le secret API passent dans une Edge Function (`lastfm`). La session key est chiffrée (AES-GCM) dans `connected_services`. Le scrobbling est fait **par le serveur Sona** (file d'attente persistante + réessais dans SQLite) en appelant cette Edge Function avec un secret serveur à serveur : le client n'a rien à gérer hors-ligne. L'import d'historique utilise `user.getRecentTracks` (public, clé API seule) dans FastAPI, en tâche de fond (déjà existant).
- **Passkeys** : je n'ai pas pu consulter la doc Supabase (réseau du bac à sable fermé vers supabase.com) et je ne les suppose pas natifs. Implémentation WebAuthn avec SimpleWebAuthn dans une Edge Function ; la session Supabase est émise via `admin.generateLink(magiclink)` + `verifyOtp(token_hash)`. Si Supabase propose entre-temps le natif, on pourra le remplacer sans toucher au reste.
- **Compatibilité** : l'ancienne connexion Last.fm de FastAPI (`/auth/lastfm*`) et l'app iOS native continuent de fonctionner pour les comptes déjà approuvés ; elle ne crée plus que des comptes `pending` (inutilisables). Les comptes Supabase sont la voie principale. Un script `scripts/link_legacy_account.py` rattache un ancien compte (et ses données) à un compte Supabase.
- **iOS natif (`ios/Encre`)** : non modifié (impossible à compiler ici ; un Swift cassé fait échouer la CI). Il reste sur l'ancien flux. Le site/PWA (ce que tu testes sur iPhone) est la cible.

## 3. Phases et commits

1. Base : migrations SQL, RLS, tests Postgres 16 locaux (`tests/test_supabase_rls.py`)
2. Edge Functions + modules partagés (tests node)
3. FastAPI : JWT, bans, amis réels, présence, sessions, endpoints internes
4. Web : écran unique, invité, onboarding, réglages, amis, signalements, `/admin`, pages légales
5. Sidebar (3 variantes dans `docs/sidebar-variants/`, choix motivé, implémentation, tests navigateur)
6. Docs (`docs/AUTH_SETUP.md`), `.env.example`, CI, résumé final
