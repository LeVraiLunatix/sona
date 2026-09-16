# Sona — Flux UX

Ce document décrit l'intégralité du parcours utilisateur avant implémentation.
Règle d'or : Sona doit ressembler à une application, pas à une liste de commandes.
Chaque écran est un message unique, mis à jour par édition (`edit_message_text` /
`edit_message_caption`) plutôt que par empilement de nouveaux messages.

## Principes transverses

- **Un écran = un message.** On édite le message existant à chaque navigation.
  On n'envoie un nouveau message que lorsque Telegram l'exige (ex: premier
  `/start`, envoi d'un fichier audio, changement texte→photo qui force un
  nouveau message car Telegram ne peut pas convertir un message texte en
  message photo par simple édition — dans ce cas l'ancien message est supprimé
  puis remplacé).
- **Navigation = pile d'écrans.** Chaque utilisateur a une pile en mémoire
  (`NavigationStack`, voir [`app/bot/navigation.py`](../app/bot/navigation.py)).
  Ouvrir un écran empile son état ; "Retour" dépile et réaffiche l'écran
  précédent (pas systématiquement l'Accueil).
- **Chargement visible.** Aucune action ne reste sans retour visuel : le bouton
  cliqué déclenche immédiatement une édition du message vers un état
  "Préparation…" avant le résultat final.
- **Erreurs propres.** Jamais de trace technique affichée. Toujours un message
  court + `[ Réessayer ]` + `[ ← Retour ]`.
- **Tout en français, pensé mobile, un minimum d'étapes.**

## Table des écrans

| Écran | État de nav | Déclenché par |
|---|---|---|
| Accueil | `home` | `/start`, bouton "Accueil" |
| Recherche (prompt) | `search_prompt` | bouton "Rechercher", `/search` |
| Suggestions en direct | *(hors pile, mode inline)* | bouton "🔍 Suggestions en direct", `@<bot> …` |
| Résultats de recherche | `search_results(query, page)` | texte libre envoyé, pagination |
| Morceau | `track(id)` | clic sur un résultat / lien collé |
| Écoute (préparation → audio) | *(transitoire, ne s'empile pas)* | bouton "Écouter" |
| Album | `album(id)` | bouton "Album", clic tracklist |
| Artiste | `artist(id)` | bouton "Artiste" |
| Lien collé (auto-détection) | `track/album/artist(id)` | message contenant une URL reconnue |
| Bibliothèque | `library(tab)` | bouton "Bibliothèque" |
| Historique | `history` | bouton "Historique" |
| Paramètres | `settings` | bouton "Paramètres" |
| Erreur | *(remplace l'écran courant)* | échec réseau/source indisponible |
| Accès (hors whitelist) | *(hors pile)* | message d'un utilisateur non autorisé |
| Demandes d'accès | `admin_requests` | Paramètres > Gestion des accès |

## 1. Accueil

```
Bienvenue sur Sona
Trouve et écoute facilement ta musique.

[ Rechercher ]
[ Coller un lien ]
[ Bibliothèque ] [ Historique ]
[ Paramètres ]
```

- "Rechercher" → écran Recherche (prompt).
- "Coller un lien" → message d'aide expliquant qu'on peut coller un lien
  Deezer/Spotify/Apple Music/YouTube directement, sans passer par un menu
  (couvre les nouveaux utilisateurs qui ne savent pas qu'ils peuvent le faire
  spontanément).
- Accueil est le fond de pile : "Retour" depuis Accueil ne fait rien (bouton
  absent sur cet écran).

## 2. Recherche — prompt

```
Que veux-tu écouter ?

Envoie un titre, un artiste, ou les deux — par exemple « daft punk
instant crush ». Tu peux aussi utiliser /search directement.

Reprendre une écoute récente :
[ Daft Punk — Instant Crush ]
[ Saif — Jefe ]
...jusqu'à 5
[ ← Retour ]
```

- L'utilisateur tape directement ; tout message texte reçu quand aucun autre
  contexte n'est actif (ou dans cet état) est traité comme une requête de
  recherche — il n'a pas besoin de passer par le bouton.
- L'écran n'est jamais vide : les 5 derniers morceaux consultés sont proposés
  en boutons, un clic ouvre l'écran Morceau sans rien retaper.
- `/search` ouvre cet écran ; `/search <requête>` saute directement aux
  résultats. La commande est déclarée via `setMyCommands` pour apparaître dans
  le menu de la conversation.
- "Rechercher chez cet artiste" réutilise le même écran avec un `scope_name` :
  la recherche est alors limitée à cet artiste (pas de suggestions).

### 2bis. Suggestions en direct (mode inline)

Le bouton `[ 🔍 Suggestions en direct ]` porte un
`switch_inline_query_current_chat` vide : Telegram pré-remplit le champ de
saisie avec `@<bot> ` et ouvre son panneau de résultats **au-dessus du
clavier**, rafraîchi à chaque frappe (`inline_query`, voir
[`app/bot/handlers/inline.py`](../app/bot/handlers/inline.py)).

- Moins de 2 caractères → panneau vide avec une invite ; jamais de panneau
  muet, qui donnerait l'impression d'un bot en panne.
- Morceau déjà dans le cache audio → proposé en `CachedAudio` : un tap envoie
  le fichier, sans re-téléchargement. Le cache est interrogé en un seul appel
  pour toute la page (`cache_get_many`), l'événement se répétant à chaque
  lettre.
- Sinon → `Article` (titre, artiste • album • durée, pochette) dont le message
  est l'URL du morceau. Sona la redétecte via le pipeline de liens existant et
  ouvre l'écran Morceau : c'est pourquoi `track_url` doit toujours produire une
  URL relisible par `resolve_link`.
- Le défilement charge la page suivante (`next_offset`).
- Ce mode est soumis à la même whitelist : hors liste, panneau vide + bouton
  « Demander l'accès à Sona ». Sans ce filtre, la recherche fuirait à
  quiconque connaît le nom du bot.
- Demande une activation unique côté @BotFather (`/setinline`) ; sans elle,
  seul ce bouton est inopérant, tout le reste fonctionne.

## 3. Résultats de recherche

```
Résultats pour « Saif »

1. Titre du morceau
   Saif • Album • 3:14
2. Autre morceau
   Saif • Album • 2:48
...jusqu'à 5

[1] [2] [3] [4] [5]
[ ← ]  [ 2/3 ]  [ → ]
[ Nouvelle recherche ]
[ Accueil ]
```

- 5 résultats max par page, boutons numérotés pour sélection directe.
- Pagination édite le même message (`search:page:<query_id>:<page>`).
- `query_id` = identifiant court vers la requête mise en cache côté serveur
  (pas de texte de recherche dans le `callback_data`).
- Résultat vide → écran "Aucun résultat pour « … »" avec `[ Nouvelle recherche ]`
  et `[ Accueil ]`.
- Sources interrogées en cascade : Deezer (principale, vraie pagination), puis
  iTunes, puis YouTube Music. La source qui a répondu est mémorisée avec la
  requête pour que la pagination reste cohérente. Toutes injoignables → écran
  d'erreur avec `[ Réessayer ]`, ce qui n'est pas la même chose que zéro
  résultat.
- Retour → Accueil (c'est un point d'entrée direct, rien avant dans la pile
  sauf si on vient d'un écran morceau/album/artiste via "Rechercher chez cet
  artiste", auquel cas Retour revient à cet écran).

## 4. Morceau

```
[COVER]
Titre du morceau
Saif
Album • 2026
3:14

[ Écouter ]
[ Album ] [ Artiste ]
[ Ajouter à la bibliothèque ]
[ ← Retour ]
```

- Photo = cover (edit_message_caption si on vient d'un autre écran avec photo,
  sinon nouveau message photo + suppression de l'ancien message texte).
- "Ajouter à la bibliothèque" devient "Retirer de la bibliothèque" si déjà
  présent (état lu depuis la DB à chaque rendu).
- "Album"/"Artiste" absents si l'info n'est pas disponible (ex: résultat
  YouTube brut sans album identifié).
- Retour → écran précédent exact (résultats de recherche à la bonne page,
  tracklist d'album, page artiste, ou historique/bibliothèque).

### 4bis. Écoute (transitoire)

Séquence d'édition du **même** message morceau :

1. `Préparation du morceau…`
2. (si nécessaire, traitement > ~1.5s) `Recherche de la source…`
3. (si nécessaire) `Préparation de l'audio…`
4. (si nécessaire) `Envoi…`
5. Envoi du fichier audio (`sendAudio`, métadonnées + thumbnail intégrées) en
   réponse dans le même fil, puis le message morceau est restauré à son état
   normal (boutons réactivés).

Pas de pourcentage inventé. Si le fichier est déjà en cache (`file_id`
Telegram connu), on saute directement à l'envoi.

Si indisponible → écran erreur (voir section Erreurs), en édition du même
message, avec `[ Réessayer ]` qui relance "Écouter" et `[ ← Retour ]` qui
revient à l'écran morceau normal.

## 5. Album

```
[COVER]
Nom de l'album
Artiste
2026 • 14 titres • 42 min

1. Titre
2. Titre
3. Titre
...

[ Tout écouter ]
[ Ajouter à la bibliothèque ]
[ ← Retour ]
```

- Tracklist paginée si > 10 titres (limite de boutons Telegram par ligne/total)
  avec les mêmes contrôles `[ ← ] [ page ] [ → ]` que la recherche.
- Chaque ligne de titre est un bouton → écran Morceau (empile Album comme
  précédent).
- "Tout écouter" : envoie les morceaux un par un (avec anti-spam / lock par
  album), message de progression `Envoi 3/14…` édité en place.
- Retour → écran précédent (Artiste, Résultats de recherche, ou lien direct →
  Accueil).

## 6. Artiste

```
[PHOTO]
Saif

[ Titres populaires ]
[ Albums ]
[ Singles & EP ]
[ Rechercher chez cet artiste ]
[ ← Retour ]
```

- "Titres populaires" → liste directement sélectionnable (même gabarit que
  Résultats de recherche, sans champ recherche), avec un bouton
  `[ Tout écouter ]` en bas qui envoie tous les titres de la liste, comme sur
  l'écran Album (même progression `Envoi 3/10…`, même bilan en cas d'échec).
  Pas de bouton quand la liste est vide.
- "Albums" / "Singles & EP" → grille/liste de couvertures → Album.
- "Rechercher chez cet artiste" → écran Recherche (prompt) avec la recherche
  scopée à cet artiste (indiqué dans le message : `Rechercher chez Saif`).
- Retour → écran précédent (Morceau, Album, ou Résultats de recherche).

## 7. Lien collé

Détection automatique (regex par domaine) dès réception d'un message
contenant une URL Deezer/Spotify/Apple Music/YouTube :

1. Édition/envoi immédiat : `Analyse du lien…`
2. Résolution du type de contenu + métadonnées via le provider correspondant.
3. Affichage direct de l'écran Morceau / Album / Artiste / (Playlist → traité
   comme une liste de morceaux façon Album sans cover d'album unique).
4. Lien non reconnu ou contenu indisponible → écran erreur dédié :
   `Lien non reconnu ou contenu indisponible.` + `[ Nouvelle recherche ]` +
   `[ Accueil ]`.

Empile directement l'écran résultant (pas d'écran intermédiaire dans la pile).

## 8. Bibliothèque

```
Ma bibliothèque

[ Morceaux ]
[ Albums ]
[ Artistes ]
[ ← Accueil ]
```

- Chaque onglet → liste paginée (gabarit Résultats de recherche) des éléments
  sauvegardés, triés du plus récent au plus ancien ajout.
- Liste vide → `Ta bibliothèque de morceaux est vide.` + bouton `[ Rechercher ]`.
- Sur chaque item de liste, un bouton compact "✕" permet un retrait direct
  sans ouvrir l'écran complet ; ouvrir l'item mène à l'écran normal
  (Morceau/Album/Artiste) où "Retirer de la bibliothèque" est aussi disponible.
- Retour → Accueil (point d'entrée direct depuis le menu principal).

## 9. Historique

```
Récemment

1. Saif — Titre
2. Ninho — Titre
3. Gazo — Titre
...

[ Effacer l'historique ]
[ ← Accueil ]
```

- Alimenté à chaque ouverture d'écran Morceau (pas seulement écoute) ;
  dédupliqué (un même morceau remonte en tête plutôt que d'être dupliqué).
- Limité aux N derniers (ex: 20), pagination si besoin selon le même gabarit.
- Clic sur un item → écran Morceau.
- "Effacer l'historique" → écran de confirmation :
  ```
  Effacer tout l'historique ?
  [ Confirmer ]  [ Annuler ]
  ```
  Confirmer vide la table historique de l'utilisateur puis réaffiche
  l'historique (vide). Annuler revient à l'historique sans rien faire.

## 10. Paramètres

```
Paramètres

Qualité audio : Meilleure disponible
Format : Automatique
Notifications : Activées
Lecture automatique : Activée

[ Qualité audio ]
[ Format ]
[ Notifications ]
[ Lecture automatique ]
[ ← Accueil ]
```

- "Qualité audio" → liste des qualités réellement disponibles pour la source
  utilisée (jamais de FLAC ou qualité supérieure à ce que la source fournit).
- "Format" → `Automatique` (recommandé, coché par défaut) vs formats
  explicites si l'utilisateur veut forcer une conversion.
- "Notifications" → bascule Activé/Désactivé en un clic (édition immédiate).
- "Lecture automatique" → même bascule. Activée (par défaut), choisir un
  morceau (liste, album, historique, suggestion, lien collé) ouvre sa carte
  *et* envoie le son. Désactivée, seule la carte s'ouvre : c'est le bouton
  `[ Écouter ]` qui déclenche l'envoi.
- Chaque sous-écran a son propre `[ ← Retour ]` vers Paramètres.

## 11. Erreurs

Gabarit unique, quel que soit le point d'échec :

```
Morceau indisponible pour le moment.

[ Réessayer ]
[ ← Retour ]
```

(ou `Impossible de récupérer ce morceau.` / `Lien non reconnu ou contenu
indisponible.` selon le cas — jamais de détail technique). Le détail réel
(exception, code HTTP, traceback) part uniquement dans les logs serveur.

Pour l'écoute, le message dit *quelle* étape a échoué, parce que la suite
n'est pas la même pour l'utilisateur :

| Cause | Message |
|---|---|
| Aucune vidéo ne correspond au morceau | `Aucune source audio trouvée pour ce morceau.` + invitation à essayer une autre version |
| Moteurs de recherche injoignables | `Recherche de la source impossible pour le moment.` |
| Téléchargement / conversion en échec | `Le téléchargement de ce morceau a échoué.` |
| Envoi Telegram en échec | `L'envoi du fichier a échoué.` |

Un écran ne doit jamais rester bloqué sur « Préparation… » : toute exception
imprévue pendant l'écoute retombe sur l'écran d'erreur générique.

"Réessayer" ré-exécute exactement l'action qui a échoué (même callback).
"Retour" restaure l'écran dans l'état où il était juste avant l'action
déclenchante (pas de perte de contexte).

## 12. Accès : invitations et demandes

Sona est un bot privé : hors whitelist, aucun écran n'est accessible. Le
filtre d'accès (`app/bot/middlewares.py`) ne se contente pas d'ignorer ces
utilisateurs — un silence donne l'impression d'un bot en panne. Tout message
reçu d'un non-autorisé est confié à `app/bot/access.py`, qui répond toujours.

**Entrer par invitation.** Un admin génère un lien depuis Paramètres >
Gestion des accès (ou avec `/invite`). Telegram ne transmet pas toujours le
paramètre `?start=` — notamment quand l'invité a déjà une conversation
ouverte avec le bot, qui se retrouve à taper `/start` tout court. Le jeton est
donc accepté sous toutes ses formes :

- `/start invite_<jeton>` (ouverture normale du lien) ;
- le lien complet collé dans la conversation ;
- le jeton brut.

Chaque refus dit *pourquoi* (`inconnu`, `expiré`, `déjà utilisé`, `annulé`) —
« bot privé » sur un lien périmé laisse croire que le bot est cassé. Une
invitation vaut 7 jours, en usage unique ou pour 10 personnes au choix de
l'admin.

**Entrer par demande.** Sans invitation, `/start` (ou le bouton
`[ Demander l'accès ]`) enregistre une demande et notifie les admins en
message direct, avec `[ ✓ Autoriser ]` / `[ ✕ Refuser ]`. À la validation,
l'invité reçoit un message et arrive directement sur l'Accueil. Les demandes
en attente sont aussi listées dans Paramètres > Gestion des accès.

**Filet de secours.** `/id` donne son identifiant Telegram à n'importe qui
(même non autorisé) ; l'admin l'ajoute avec `/allow <id>`, sans lien ni
demande.

## Navigation "Retour" — exemples de pile

```
Accueil
 → Recherche résultats "Saif" (page 1)
    → Morceau A                     Retour ⇒ Résultats "Saif" p.1
       → Album de A                 Retour ⇒ Morceau A
          → Morceau B (tracklist)   Retour ⇒ Album de A
             → Artiste de B         Retour ⇒ Morceau B
                → Albums de l'artiste   Retour ⇒ Artiste de B
```

Chaque niveau ne connaît que "comment revenir d'un cran", jamais "revenir à
l'accueil" — sauf pour les écrans qui sont eux-mêmes des points d'entrée
directs du menu principal (Recherche, Bibliothèque, Historique, Paramètres),
où Retour va à Accueil faute d'écran précédent dans la pile.

## Callback data (aperçu, détail dans le code)

Aucune donnée métier dans `callback_data` — uniquement des identifiants
courts résolus côté serveur (cache mémoire/DB) :

- `nav:home`, `nav:back`
- `search:page:<qid>:<page>`, `search:pick:<qid>:<idx>`, `search:new`
- `track:view:<tid>`, `track:play:<tid>`, `track:lib:<tid>`
- `album:view:<aid>`, `album:page:<aid>:<page>`, `album:playall:<aid>`, `album:lib:<aid>`
- `artist:view:<arid>`, `artist:top:<arid>`, `artist:albums:<arid>`, `artist:singles:<arid>`, `artist:search:<arid>`
- `library:tab:<kind>:<page>`, `library:remove:<kind>:<id>`
- `history:open:<hid>`, `history:clear`, `history:clear:confirm`
- `settings:quality`, `settings:quality:set:<value>`, `settings:format`, `settings:format:set:<value>`, `settings:notif:toggle`
- `retry:<action_token>`

## Objectif de rapidité

```
Utilisateur : "Saif Jefe"
 → Sona affiche les résultats (édition d'un seul message)
 → Utilisateur touche le morceau        (1 interaction)
 → Écran Morceau
 → "Écouter"                             (2e interaction)
 → Audio envoyé dans Telegram
```

Deux interactions après la recherche quand le morceau est disponible.
