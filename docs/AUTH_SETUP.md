# Comptes, social et administration : mise en route pas à pas

Ce guide liste **ce que tu dois faire à la main**. Tout le reste (code, migrations, tests) est dans le dépôt.
Architecture et décisions : [COMPTES_AUDIT_ET_PLAN.md](COMPTES_AUDIT_ET_PLAN.md). Ce que le serveur musique doit
brancher : [INTEGRATION_SERVEUR_MUSIQUE.md](INTEGRATION_SERVEUR_MUSIQUE.md).

> Je n'ai pas pu consulter la documentation Supabase depuis l'environnement où ce travail a été fait (réseau fermé
> vers supabase.com). Les noms de réglages ci-dessous viennent de ma connaissance du produit et de `supabase/config.toml` ;
> si un intitulé a changé dans le tableau de bord, la logique reste la même. Les points à vérifier sont marqués **(à vérifier)**.

## Ce qui tourne où

| Brique | Où | Secrets |
|---|---|---|
| Site / PWA (`web/`) | Vercel (statique) et/ou le serveur musique (`/web/`) | **aucun** (l'URL du projet et la clé « anon » sont publiques) |
| Auth, base, stockage des photos | Supabase | clés OAuth, SMTP, captcha (dans Supabase) |
| `sona-accounts` (Rust) | ton VPS, derrière HTTPS | `.env` du VPS : base, Last.fm, clé de chiffrement… |
| Serveur musique | ton VPS | `INTERNAL_API_SECRET` partagé |

## 1. Créer le projet Supabase

1. [supabase.com](https://supabase.com) → **New project**. Région : **Europe** (RGPD). Garde le mot de passe de la base.
2. **Project Settings › API** : note l'**URL du projet** et la clé **anon** (publiques) ; la clé **service_role** reste sur le VPS seulement.
3. Installe le [CLI Supabase](https://supabase.com/docs/guides/cli), puis dans le dépôt :
   ```bash
   supabase login
   supabase link --project-ref <ref>
   supabase db push          # applique supabase/migrations/*.sql, dans l'ordre
   ```
   (Sans CLI : colle les 6 fichiers de `supabase/migrations/` dans **SQL Editor**, dans l'ordre des noms.)
4. Vérifie : **Table Editor** montre `profiles`, `friendships`, `reports`… avec le cadenas « RLS enabled » partout. Le schéma
   `private` n'est pas exposé (il ne figure pas dans **Settings › API › Exposed schemas**).
5. **Database › Extensions** : active **pg_cron** (optionnel mais recommandé : purge quotidienne, détection de pics d'inscriptions).
   Après l'avoir activée, rejoue la fin de `20261126000500_maintenance.sql` (le bloc « Tâches planifiées »). Le service `sona-accounts`
   fait aussi la purge chaque heure : pg_cron n'est qu'un filet.

## 2. Réglages d'authentification

Le plus simple : `supabase config push` (lit `supabase/config.toml`, variables `env(...)` à exporter avant). Sinon, à la main dans
**Authentication** :

| Réglage | Valeur |
|---|---|
| **Sign In / Providers › Allow new users to sign up** | **activé** (aucune liste d'invités, aucune validation) |
| Email › Confirm email | activé ; longueur du code (OTP) **6** |
| **Allow anonymous sign-ins** (mode invité) | activé |
| **Manual linking** (lier / délier des méthodes) | activé |
| Password › minimum length / requirements | **10**, minuscules + majuscules + chiffres |
| Sessions | rotation des jetons de rafraîchissement activée ; durée du jeton d'accès 3600 s |
| **Redirect URLs** | voir la liste ci-dessous |
| Templates d'e-mails | collés depuis `supabase/templates/*.html` (ils affichent **le code** et le lien) |
| **Attack Protection › Captcha** | activé, fournisseur **Cloudflare Turnstile** (étape 6) |
| **SMTP Settings** | ton SMTP (étape 7) |
| **Hooks › Before user created** | HTTP : `https://<ton-accounts>/hooks/before-user-created`, secret `v1,whsec_…` **(à vérifier : l'emplacement de ce hook dans le tableau de bord)** |

### Redirect URLs à ajouter (liste exhaustive)

Site URL : `https://trysona.fr`

```
https://trysona.fr/**
https://www.trysona.fr/**               (seulement si tu sers ce domaine)
https://141-253-108-13.sslip.io/web/**   (le site servi par le serveur musique)
http://localhost:8000/**                 (développement)
http://127.0.0.1:8000/**
sona://auth/callback                     (application Windows : lien profond)
```

C'est la **seule** protection contre une redirection ouverte côté Auth : ne mets jamais `**` seul ni un domaine que tu ne contrôles pas.
Android = la PWA (mêmes adresses que le site). Pas de « Se connecter avec Apple » (pas de compte développeur payant).

## 3. Premier administrateur

Crée-toi un compte normalement (inscription dans l'app), puis dans **SQL Editor** (rôle `postgres`, le seul autorisé) :

```sql
update public.profiles
   set role = 'admin'
 where id = (select id from auth.users where email = 'toi@exemple.fr');
```

Le rôle ne se modifie **jamais** depuis le client : colonnes protégées (droits par colonne + déclencheur) ; ensuite les promotions
passent par l'onglet Utilisateurs du panneau (`/admin`), réservées aux admins, et le service vérifie le rôle en base à chaque requête.
Pour retirer un modérateur ou un admin : même panneau (jamais le dernier admin).

## 4. Applications OAuth (publiques, sans mode « test »)

Dans chaque console, l'**URL de rappel** est celle de **Supabase** (pas celle de Sona) :
`https://<ref>.supabase.co/auth/v1/callback`. C'est Supabase qui renvoie ensuite vers `sona://auth/callback` ou le site (liste ci-dessus).

### Google
1. [console.cloud.google.com](https://console.cloud.google.com) → crée un projet « Sona » → **APIs & Services › OAuth consent screen**.
2. Type d'utilisateur **External**. Nom, e-mail d'assistance, logo, **page d'accueil** `https://trysona.fr`, **politique de confidentialité**
   `https://trysona.fr/confidentialite`, **conditions** `https://trysona.fr/conditions`, domaine autorisé `trysona.fr` (et `supabase.co`).
3. **Scopes : seulement** `openid`, `.../auth/userinfo.email`, `.../auth/userinfo.profile` (scopes de base : **pas de vérification Google** requise).
4. **Publishing status : « In production »** (bouton *Publish app*). **Ne laisse pas « Testing »** : seuls 100 comptes de test pourraient se connecter.
5. **Credentials › Create credentials › OAuth client ID › Web application** ; **Authorized redirect URIs** : l'URL de rappel Supabase.
6. Copie *Client ID* et *Client secret* → Supabase (**Providers › Google**) ou variables `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`.

### Discord
1. [discord.com/developers/applications](https://discord.com/developers/applications) → **New Application** « Sona ».
2. **OAuth2 › Redirects** : l'URL de rappel Supabase. **Scopes demandés par Sona** : `identify` + `email` (rien d'autre).
3. Copie *Client ID* et *Client Secret* → Supabase. L'application est publique d'office : pas de liste d'utilisateurs.

### GitHub
1. GitHub › **Settings › Developer settings › OAuth Apps › New OAuth App** (compte ou organisation `trysona`).
2. *Homepage URL* `https://trysona.fr` ; *Authorization callback URL* : l'URL de rappel Supabase.
3. Scopes demandés par Sona : `read:user` + `user:email`. Copie *Client ID* et génère un *Client secret* → Supabase.

> **Spotify n'est pas une méthode de connexion** : son mode développeur est limité à quelques utilisateurs et demande une approbation.
> L'import de playlists Spotify / Deezer est marqué « Bientôt » dans l'app (rien n'est simulé).

## 5. Last.fm (facultatif pour les utilisateurs)

1. [last.fm/api/account/create](https://www.last.fm/api/account/create) : nom « Sona », description, **Callback URL** `https://trysona.fr/`.
   Aucune approbation n'est nécessaire : l'authentification officielle est ouverte à tous.
2. Mets la **clé** et le **secret** dans `.env` de `sona-accounts` (`LASTFM_API_KEY`, `LASTFM_API_SECRET`). Le secret ne va **nulle part** ailleurs.
3. Génère la clé de chiffrement des clés de session : `openssl rand -base64 32` → `SECRETS_ENCRYPTION_KEY`.

Flux : site web → redirection vers Last.fm avec l'adresse de retour (autorisée par `ALLOWED_RETURN_URLS`) ; application installée / Windows →
le service obtient un jeton, l'app ouvre Last.fm et attend. Dans les deux cas, l'échange `auth.getSession` se fait **côté serveur seulement**.

## 6. Anti-robot invisible (Cloudflare Turnstile)

1. [dash.cloudflare.com](https://dash.cloudflare.com) › **Turnstile › Add widget**, domaines `trysona.fr` (+ ceux de test), mode **Invisible** (ou *Managed*).
2. **Site key** → `<meta name="sona-turnstile-sitekey">` dans `web/index.html` (publique).
3. **Secret key** → Supabase **Attack Protection › Captcha** (variable `TURNSTILE_SECRET`).

Il protège l'inscription, la connexion, le code par e-mail, le mot de passe oublié et le mode invité.

## 7. E-mails (SMTP personnalisé)

Le SMTP par défaut de Supabase est limité à quelques e-mails par heure : inutilisable pour un lancement public. Prends un fournisseur
(Resend, Brevo, Mailjet, Postmark…), **vérifie ton domaine** (SPF, DKIM, DMARC) puis renseigne **Authentication › SMTP Settings**
(`SMTP_HOST`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM`). Monte ensuite **Rate Limits › emails per hour** à la mesure de ton quota.

## 8. Déployer `sona-accounts` (Rust)

```bash
cd rust && cargo build --release -p sona-accounts        # binaire : rust/target/release/sona-accounts
cp sona-accounts/.env.example /etc/sona-accounts.env      # puis remplis-le (chmod 600)
```

Exemple d'unité systemd (`/etc/systemd/system/sona-accounts.service`) :

```ini
[Unit]
Description=Sona accounts
After=network-online.target

[Service]
EnvironmentFile=/etc/sona-accounts.env
ExecStart=/opt/sona/sona-accounts
Restart=always
User=sona
NoNewPrivileges=true
ProtectSystem=strict
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

Caddy (HTTPS) : `accounts.trysona.fr { reverse_proxy 127.0.0.1:8100 }`. Puis :
- `<meta name="sona-accounts" content="https://accounts.trysona.fr">` dans `web/index.html` ;
- l'URL du hook « avant création d'utilisateur » dans Supabase ; le secret `v1,whsec_…` identique des deux côtés (`AUTH_HOOK_SECRET`) ;
- `CORS_ORIGINS=https://trysona.fr,app://sona`.

Le service doit se connecter à Postgres avec le rôle **`postgres`** (il appelle des fonctions réservées au rôle serveur et supprime des comptes).
Utilise le *pooler* Supabase (mode session) si ta connexion directe est en IPv6 seulement **(à vérifier selon ton hébergeur)**.

## 9. Variables d'environnement : récapitulatif

| Où | Variable | Rôle |
|---|---|---|
| Site (`index.html`, **publiques**) | `sona-supabase-url`, `sona-supabase-key`, `sona-accounts`, `sona-turnstile-sitekey` | configuration du client |
| Vercel | *aucune requise* (site statique) | — |
| Supabase (`config push` / tableau de bord) | `GOOGLE_CLIENT_ID/SECRET`, `DISCORD_CLIENT_ID/SECRET`, `GITHUB_CLIENT_ID/SECRET`, `SMTP_HOST/USER/PASS/FROM`, `TURNSTILE_SECRET`, `AUTH_HOOK_SECRET`, `ACCOUNTS_URL` | fournisseurs, e-mails, anti-robot, hook |
| VPS `sona-accounts` | voir `rust/sona-accounts/.env.example` | base, Last.fm, chiffrement, alertes, passkeys |
| VPS serveur musique (`.env`) | `SONA_ACCOUNTS_URL` (adresse interne de `sona-accounts`), `INTERNAL_API_SECRET` (le **même** que celui du service), `SUPABASE_URL` + `SUPABASE_ANON_KEY` (valeurs **publiques**, pour l'app iPhone) | jetons Supabase, amis, scrobbling, export / suppression |
| VPS `sona-accounts` | `MUSIC_INTERNAL_URL` | adresse du serveur musique, pour l'export, la suppression et la modération |

Rien de secret n'est dans le dépôt : `.gitignore` exclut `.env`, et `rust/sona-accounts/.env.example` ne contient que des gabarits.

## 10. Alertes de modération

Nouveau signalement, nouvelle contestation, quarantaine automatique, pic d'inscriptions (≥ 30 en une heure), inscriptions en rafale d'une même IP :
1. Crée un salon Discord **privé** → *Paramètres du salon › Intégrations › Webhooks › Nouveau webhook* → copie l'URL.
2. `ALERTS_DISCORD_WEBHOOK=<url>` dans `.env` de `sona-accounts` ; redémarre. Les alertes arrivent en moins de 20 s.

Les messages ne contiennent ni e-mail ni texte écrit par un utilisateur, et aucun `@` ne notifie personne par accident. (Pas d'alerte par e-mail
dans cette version : un webhook Discord suffit pour une équipe d'une personne.)

## 11. Limites et capacité d'un lancement public

À vérifier sur la page **Pricing** de Supabase (les quotas changent) ; ordres de grandeur du plan gratuit : environ 50 000 utilisateurs actifs
par mois, 500 Mo de base, 1 Go de stockage de fichiers, 5 Go de transfert, **mise en pause du projet après une semaine sans activité**.

- Les photos de profil sont réduites à 256 px et limitées à 200 Ko (bucket `avatars`) : ~10 000 photos par Go.
- La base ne contient ni musique ni historique d'écoute (ils restent sur le serveur musique) : elle grossit surtout avec les comptes, amitiés, notifications
  et le journal d'audit (purge automatique, 12 mois).
- Pagination : les listes d'admin sont limitées à 100 lignes par appel ; index sur `created_at`, `status`, `role`, paires d'amis, destinataires de notifications,
  signalements par statut. Les compteurs de débit (`private.rate_limits`) sont purgés au bout de 2 jours.
- Limites anti-abus : 20 demandes d'amis par jour (6 par minute), 500 amis, 100 demandes en attente par personne, 3 signalements par heure et 10 par jour,
  3 contestations par jour, 40 vérifications de pseudo par minute, passkeys : 30 essais par minute et par IP.
- Montée en charge : le service Rust vérifie les jetons **sans appeler Supabase** (JWKS en cache) et relit le statut d'un compte au plus toutes les 5 s.

## 12. Checklist « Passer en production »

- [ ] Projet Supabase en région **Europe**, migrations appliquées, RLS visible partout.
- [ ] **Allow new users to sign up** activé ; aucune liste d'invités ni « allowlist ».
- [ ] **Google : écran de consentement « In production »** (pas « Testing »), scopes de base seulement, liens confidentialité et conditions renseignés.
- [ ] Discord et GitHub : applications créées, scopes minimaux, URL de rappel Supabase, **aucune restriction d'utilisateurs**.
- [ ] Last.fm : clé et secret dans `.env` du service ; `ALLOWED_RETURN_URLS` correct ; essai d'une connexion Last.fm.
- [ ] Turnstile actif (clé de site dans `index.html`, secret dans Supabase) ; inscription testée avec captcha.
- [ ] SMTP personnalisé configuré, domaine vérifié (SPF/DKIM) ; e-mails de confirmation, de code et de réinitialisation reçus.
- [ ] Redirect URLs : exactement la liste de l'étape 2 (rien de plus).
- [ ] Hook « avant création d'utilisateur » branché (test : une adresse `@mailinator.com` est refusée).
- [ ] Premier admin créé (étape 3) ; panneau `/admin` ouvert depuis ton iPhone.
- [ ] Alertes Discord reçues (crée un signalement de test).
- [ ] **Inscription d'un compte tout neuf**, jamais utilisé comme testeur (nouvelle adresse Google/Discord/GitHub), de bout en bout : inscription → onboarding →
      connexion depuis un second appareil → export des données → suppression du compte.
- [ ] Mentions légales, conditions et confidentialité relues (région Supabase, fournisseur d'e-mails, coordonnées).
- [ ] Sauvegardes Supabase vérifiées (plan payant : sauvegardes quotidiennes ; plan gratuit : fais un `pg_dump` régulier).

## 13. Passkeys : à savoir

Je n'ai pas pu vérifier si Supabase Auth propose aujourd'hui des passkeys natifs. Elles sont implémentées avec **WebAuthn** dans `sona-accounts` (bibliothèque
`webauthn-rs`) ; la session est ensuite émise par Supabase via un lien magique fabriqué côté serveur. L'aller-retour d'enregistrement et de connexion est testé
avec un authentificateur logiciel. À essayer sur de vrais appareils (iPhone, Windows Hello) : `WEBAUTHN_RP_ID` doit être le domaine exact du site.

## 14. iPhone : ce qui marche, ce qui ne marche pas

- **Dans Safari** : tout (OAuth, code par e-mail, clés d'accès).
- **Dans l'app installée sur l'écran d'accueil** : le stockage de la PWA est séparé de celui de Safari. La connexion **par code à 6 chiffres** (e-mail) et par **clé d'accès**
  fonctionnent entièrement dans l'app ; les boutons Google / Discord / GitHub s'ouvrent dans Safari et ne reviennent pas dans l'app (l'interface le dit).
  Astuce : crée le compte dans Safari, puis connecte-toi dans l'app avec le même e-mail (même compte).
- **App iOS native (`ios/Encre`)** : connexion par compte Sona (e-mail + mot de passe, Google / Discord / GitHub) sans bibliothèque tierce : `Sources/Networking/SupabaseAuth.swift`
  (PKCE, feuille système `ASWebAuthenticationSession`, retour sur `sona://auth/callback`, jeton de renouvellement dans le Trousseau). L'adresse du projet et la clé publique viennent de
  `GET /auth/config` du serveur musique (`SUPABASE_URL`, `SUPABASE_ANON_KEY`) : rien n'est écrit en dur dans l'app. Les comptes banni / suspendu voient un écran dédié
  (`SanctionView`). Pas de « Se connecter avec Apple ». La connexion Last.fm d'avant reste disponible. **Cette partie n'a pas pu être compilée dans l'environnement de développement
  (Linux) : la CI macOS (`.github/workflows/ios.yml`) la compile ; teste la connexion sur un iPhone avant de la diffuser.**

## 15. Dépannage

| Symptôme | Cause probable |
|---|---|
| « Les comptes ne sont pas encore configurés » | les 3 balises `<meta>` de `index.html` sont vides |
| Retour de Google sur « redirect_uri_mismatch » | l'URL de rappel de la console Google n'est pas celle de Supabase |
| Retour sur le site avec `error=...redirect` | adresse absente de la liste des Redirect URLs |
| « Database error saving new user » | inscription refusée par le garde-fou (adresse jetable, banni, rafale d'IP) — voir les journaux Postgres |
| Les actions d'admin répondent 403 | rôle absent en base (étape 3) ou compte sanctionné |
| La clé d'accès échoue | `WEBAUTHN_RP_ID` / `WEBAUTHN_ORIGIN` ne correspondent pas au domaine exact |
| Aucun e-mail reçu | SMTP, SPF/DKIM, ou limite « emails per hour » |
