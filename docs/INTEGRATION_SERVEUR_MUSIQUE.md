# Brancher le serveur musique sur les comptes

Le serveur musique (FastAPI aujourd'hui, Rust en cours de migration) garde la musique, la bibliothèque, les playlists, les écoutes et les
sessions d'écoute. Il n'a plus de système de comptes : il s'appuie sur `sona-accounts` (`rust/sona-accounts`). Ce document est le contrat.

## 1. Authentifier une requête

Le site envoie `Authorization: Bearer <jeton d'accès Supabase>` (et `?token=` pour un flux audio, qui ne peut pas porter d'en-tête).

**Serveur Rust** : réutilise la crate.

```rust
use sona_accounts::{auth::Authenticator, jwt::JwtVerifier};
let auth = Authenticator::new(pool, Arc::new(JwtVerifier::new(secret, Some(jwks_url))), Duration::from_secs(5));
let profile = auth.authenticate(token).await?;   // Err(Sanctioned{..}) pour un compte banni ou suspendu
```

`authenticate` vérifie la signature (ES256 / RS256 via JWKS, ou HS256), l'expiration et l'audience, **puis relit le statut du compte** (cache de
5 s) : un compte banni ou suspendu est refusé à la requête suivante, même avec un jeton encore valable. Le rôle vient toujours de la base, jamais du jeton.

**Autre langage** : `POST {accounts}/internal/verify` avec `x-sona-internal: <INTERNAL_API_SECRET>` et `{ "token": "…" }` →
`{ user_id, username, role, status }`, ou `403 { "error": "sanctioned", "status", "reason", "until" }` (le site affiche l'écran de sanction), ou `401`.

L'identifiant du compte est un **UUID** (`user_id`). Les données musicales existantes (entiers) doivent être rattachées à cet UUID (table de correspondance
côté serveur musique). Un ancien compte Last.fm se rattache à un compte Supabase par une opération d'administration (non faite dans ce chantier).

## 2. Visibilité : une seule règle, côté Postgres

`POST /internal/relations { "viewer": uuid, "others": [uuid, …] }` (500 au plus) →

```json
{ "<uuid>": { "friend": true, "blocked": false, "visible": true,
              "presence": true, "history": false, "stats": false, "playlists": true, "profile": true } }
```

Les booléens `presence`, `history`, `stats`, `playlists`, `profile` sont **calculés par la base** (`private.can_view`) : amitié acceptée, blocage dans un sens ou
dans l'autre, compte actif (ni suspendu, ni banni, ni en quarantaine, ni invité), mode invisible, réglage de la personne. Le serveur musique ne recode rien.

| Besoin | Appel |
|---|---|
| Liste d'amis (acceptés, visibles) | `GET /internal/friends/{uid}` → `{ friends: [uuid] }` |
| Pseudo / photo / statut | `POST /internal/profiles { ids }` |
| Filtre de mots (chat, messages) | `POST /internal/text-check { text }` → `{ offensive }` |
| Invitation à une session | `POST /internal/notify/session-invite { user_id, payload: { code } }` |

À appliquer **côté serveur musique** (c'est la seule vraie protection) :
- `GET /friends` : uniquement les amis acceptés (`/internal/friends`), et pour chacun seulement ce que `relations` autorise (présence → `now_playing`, historique → `last_play`, etc.). **Supprimer toute logique « tous les comptes sont amis »** (`routers/friends.py`, `party.py /active`, `extras.py`, `public.py`).
- Présence « en train d'écouter » : ne publier que si le réglage de la personne l'autorise (`presence_visibility ≠ nobody`, pas `invisible_mode`). Défaut : rien.
- Fil d'activité, blends, classements : amis acceptés uniquement. Aucune route ne doit afficher un compte qui n'est ni ami ni de profil public.

## 3. Scrobbling Last.fm

Après avoir enregistré une écoute (le serveur musique reste la source de vérité de l'historique) :

`POST /internal/scrobble { user_id, kind: "scrobble"|"now_playing", artist, track, album?, duration?, timestamp }`

Le service ne met rien en file si Last.fm n'est pas connecté ou si le scrobbling est coupé. Sinon : file persistante, envoi par lots signé, réessais avec attente
croissante (30 s → 1 h), clé révoquée détectée et signalée à l'utilisateur. `GET /internal/lastfm/{uid}` → `{ username }` pour l'import d'historique
(`user.getRecentTracks`, public : la clé d'API suffit, pas la session).

## 4. Endpoints à exposer pour `sona-accounts` (secret `x-sona-internal`)

| Route | Rôle |
|---|---|
| `GET /internal/users/{uid}/export` | toutes les données musicales de la personne (JSON) |
| `DELETE /internal/users/{uid}` | supprime bibliothèque, playlists, historique, appareils, liens de partage… (**tout**) |
| `POST /internal/content/playlist/{id}/hide` · `…/delete` | masquage / suppression d'une playlist par la modération |
| `POST /internal/sessions/{code}/close` · `…/kick` · `…/delete_message` | actions de modération sur une session |

La suppression de compte et l'export appellent ces routes **avant** de toucher à Supabase : si elles échouent, le compte reste (pas de données orphelines).

## 5. Sessions d'écoute

Les règles sont dans `sona_accounts::sessions` (Rust pur, testé) : rôles (hôte, modérateur, auditeur), accès **amis (défaut)** / **invitation à jeton qui expire** /
**ouverte avec le code** (jamais par défaut), verrouillage, limite de participants (50 au plus), expulsion, bannissement de session, chat coupé ou par personne,
transfert d'hôte, droits d'ajout / changement de titre / pause, blocage entre utilisateurs (ni entrée, ni visibilité mutuelle), jetons conservés **hachés**, nettoyage à la fermeture.

Le serveur musique appelle `Session::join(user, |autre| relation, invite, now)` avec les relations venues de `/internal/relations` : tout refus renvoie le même
message neutre (« Cette session n'est pas disponible. »), qui ne révèle ni blocage ni bannissement.

Contrat attendu par l'interface (`web/accounts-party.js`) : le snapshot d'une session contient `access` (`friends|invite|link`), `locked`, `chat_enabled`,
`max_participants`, `permissions`, `role` (`host|moderator|listener`) ; chaque membre `uid` (UUID), `role`, `muted` ; chaque message `id`, `uid`. Si `access` est absent, l'interface se comporte comme avant.

| Requête | Effet |
|---|---|
| `POST /party/{code}/join { invite? }` | entrée (règles ci-dessus) |
| `POST /party/{code}/settings { access?, locked?, chat_enabled?, max_participants?, permissions? }` | hôte |
| `POST /party/{code}/invite { ttl_seconds }` → `{ token, expires_at }` · `DELETE /party/{code}/invite` | lien privé (1 h par défaut, 7 j au plus) / révocation |
| `POST /party/{code}/ban`, `/kick`, `/mute { member_id, muted? }`, `/moderator { member_id, moderator }`, `/transfer` | hôte / modérateurs |
| `DELETE /party/{code}/chat/{id}` | hôte / modérateurs |

Un blocage créé pendant une session (`Session::on_block`) retire la bonne personne ; un compte sanctionné disparaît des sessions et des listes dès la requête suivante.

## 6. État de l'intégration

**Fait dans le serveur musique actuel (FastAPI, `app/`)**, couvert par `tests/test_sona_accounts_bridge.py` (faux service de comptes, 25 tests) :
- `app/services/sona_accounts.py` : client du service (`/internal/verify` avec cache de 5 s, amis, relations, profils, filtre de mots, scrobbling).
- `app/api/auth.py` : un jeton en forme de JWT est vérifié par le service ; le compte de données est créé à la première requête (`supabase_links`) ; un compte banni / suspendu reçoit
  `403 {error: "sanctioned", …}` (écran de sanction du site) ; service injoignable → `503`. Les anciens jetons (`API_TOKEN`, sessions Last.fm) fonctionnent toujours.
- `app/services/social.py` : **fin du « tout le monde est ami »**. Amis, classements, moments, sessions actives, récap : uniquement les amis acceptés, et chaque information suit
  `presence` / `history` / `stats` / `playlists` calculés par la base. Service injoignable ou compte non rattaché → cercle **vide** (jamais « trop »).
- `app/services/party.py` + `routers/party.py` : accès amis (défaut) / invitation à jeton haché qui expire / lien ouvert, verrouillage, limite de participants, expulsion, bannissement de session,
  modérateurs, chat coupé (global ou par personne), filtre de mots, droits (ajouter, changer de titre, pause), blocage à l'entrée, refus au message **neutre**.
- `app/api/routers/internal.py` : `/internal/users/{uid}/export`, `DELETE /internal/users/{uid}`, `/internal/content/playlist/{id}/hide|delete`, `/internal/sessions/{code}/close|kick|delete_message`
  (secret `x-sona-internal`, comparaison en temps constant, **fermées** si aucun secret n'est configuré).
- Scrobbling : les écoutes des comptes Sona partent par `/internal/scrobble` (clé chiffrée, file persistante) ; les anciens comptes gardent l'envoi direct.
- **Ancien compte** : `POST /auth/link-legacy` rattache un ancien compte Last.fm (bibliothèque, playlists, historique) au compte connecté, après autorisation Last.fm. Réglages › Services connectés › « Récupérer mon ancien compte ».
- Import de playlists (Spotify, Deezer, Apple Music, YouTube, SoundCloud) : déjà en place côté serveur ; les lignes « Bientôt » des réglages sont remplacées par le vrai bouton.

**Reste, quand le serveur musique passera en Rust** : porter ces routes (le contrat ci-dessus ne change pas) ; la crate `sona_accounts` fournit déjà l'authentification et les règles de sessions
(`sona_accounts::sessions`), le modèle Python en est une transcription.
