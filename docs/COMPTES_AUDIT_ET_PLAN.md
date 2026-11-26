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

## 2. Décision d'architecture (prise à ta place, révisée : tout le serveur en Rust)

Le cahier des charges suppose Supabase partout (Auth, Postgres + RLS, Edge Functions). Réécrire le moteur musique sur Postgres n'est pas raisonnable, et Sona est en train de migrer vers Rust : **aucune ligne de Python ni d'Edge Function TypeScript n'est ajoutée**. Tout le code serveur de ce chantier est un service Rust (`rust/sona-accounts`, axum + sqlx) qui prend la place des Edge Functions.

```
 Navigateur / PWA / Windows
      │  supabase-js : auth, réglages, amis (RPC SQL), signalements
      ├────────────────────────────────────────────────────────────▶ Supabase : Auth + Postgres (RLS)
      │  Bearer <JWT Supabase>                                               ▲
      ├──────────▶ sona-accounts (Rust, VPS) : Last.fm, admin, export/suppression,  │ SQL direct (rôle serveur)
      │            passkeys, hook anti-inscription, alertes, /internal/*  ──────────┘
      │  Bearer <JWT Supabase>
      └──────────▶ serveur musique (Rust, en cours de migration) ── utilise la crate `sona_accounts::auth`
                   (vérif JWT + statut/ban à chaque requête) et `/internal/relations`
```

- **Supabase = identité + tout ce qui est social et modération** : `profiles`, rôles, sanctions, `audit_log`, amitiés, blocages, confidentialité, signalements, anti-abus, `connected_services`, passkeys. RLS sur toutes les tables. Les règles de visibilité vivent à un seul endroit : la fonction SQL `private.can_view`.
- **`sona-accounts` (Rust)** remplace les Edge Functions : vérification des JWT (ES256 via JWKS ou HS256), actions d'administration (le service REVÉRIFIE le rôle en base, et la base revérifie encore dans les fonctions SQL), échange Last.fm (secret côté serveur, clé de session chiffrée AES-256-GCM), file de scrobbling persistante avec réessais, export / suppression de compte, passkeys WebAuthn (`webauthn-rs`), hook « avant création d'utilisateur » (signature Standard Webhooks), alertes Discord, endpoints internes pour le serveur musique.
- **Serveur musique** : je ne le touche pas (il est en migration). La crate expose ce dont il a besoin : middleware d'authentification axum (JWT + ban vérifié à chaque requête avec un cache de 5 s), `Relations` (amis / bloqué / présence / historique visibles), et le modèle de **sessions d'écoute** (`sessions`) : rôles, accès amis / invitation à jeton expirant / lien ouvert, verrouillage, bannissement, chat coupé, limite de participants, blocage. File, votes et chat restent dans ton code.
- **Écart assumé avec la section 4** : `library`, `playlists`, `playlist_tracks`, `listening_history` restent dans le stockage du serveur musique (couplées au flux audio). Leur visibilité envers les amis passe par `can_view`. Tout le reste du schéma est dans Postgres.
- **Passkeys** : je n'ai pas pu consulter la doc Supabase (réseau fermé vers supabase.com), je ne les suppose donc pas natifs. WebAuthn côté Rust ; la session Supabase est émise via `generate_link(magiclink)` + `verifyOtp(token_hash)`.
- **iOS natif (`ios/Encre`)** : non modifié (impossible à compiler ici). Le site/PWA est la cible.
- **Anciens comptes** : le rattachement d'un ancien compte Last.fm (et de ses données) à un compte Supabase se fait côté serveur musique ; la colonne `app_accounts.supabase_uid` n'est plus nécessaire côté ce chantier.

## 3. Phases et commits (un seul push à la fin)

1. Base : migrations SQL, RLS, tests Postgres 16 locaux (écrits en Rust)
2. `sona-accounts` : JWT, ban à chaque requête, Last.fm, admin, compte, passkeys, hook, alertes, relations, sessions
3. Web : écran unique, invité, onboarding, réglages, amis, signalements, `/admin`, pages légales
4. Sidebar (3 variantes dans `docs/sidebar-variants/`, choix motivé, implémentation, tests navigateur)
5. Docs (`docs/AUTH_SETUP.md`), `.env.example`, CI, résumé final
