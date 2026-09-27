# Encre (app iOS)

Port natif SwiftUI de la maquette **« Encre »** (Claude Design), branché sur
l'[API privée de Sona](../../README.md#api-backend-pour-une-app-iphone).
Usage strictement personnel, comme le reste du projet.

## État actuel — étape 3/3

- [x] Squelette SwiftUI (XcodeGen) + design system (couleurs, typographie
      Source Serif 4, effet "verre liquide") repris du handoff.
- [x] 3 onglets branchés sur l'API réelle : **Écouter** (historique +
      bibliothèque), **Bibliothèque** (titres/albums/artistes), **Rechercher**
      (recherche texte + liens collés) — tous les 3 restent montés en
      permanence (comme `vis(k)` dans le prototype) : changer d'onglet ne
      perd ni le défilement ni les données déjà chargées.
- [x] Fiches Album / Artiste, lecture audio (`AVPlayer` sur `/stream/...`),
      avec un vrai contexte de lecture (l'album/l'artiste/la liste jouée
      enchaîne "suivant"/"précédent").
- [x] Lecteur plein écran : pochette avec clin d'œil CMJN, cœur (bibliothèque),
      défilement façon forme d'onde, transport, volume, mode Paroles (honnête :
      Sona n'a pas de source de paroles, donc un état vide plutôt qu'un texte
      inventé) et mode File d'attente (les morceaux à suivre dans le contexte
      en cours).
- [x] Barre d'onglets "verre liquide" maison (`EncreTabBar`), à la place du
      chrome natif d'un `TabView`.
- [x] Onboarding au premier lancement : écran de bienvenue puis configuration
      du serveur — adapté honnêtement (pas de "quels artistes écoutez-vous ?"
      inventé : Sona n'a ni compte ni préférences à collecter, seule la
      connexion au serveur est vraiment nécessaire avant d'ouvrir l'app).
- [x] Trame de points ("halftone") sur les grandes pochettes mises en avant
      (lecteur plein écran, héros d'accueil, fiches Album/Artiste) — pas sur
      les petites vignettes de liste, par prudence de performance (voir
      Limites connues).

Les 3 étapes prévues sont posées. Reste des finitions plus avancées, pas
indispensables à un usage quotidien :

Le prototype propose aussi 3 lecteurs alternatifs (vinyle "Microsillon",
une de journal "Édition spéciale", plein cadre "Lentille") : pas repris pour
l'instant, le lecteur "intégré" (celui branché à toute la navigation) étant
la référence choisie.

**Certaines adaptations honnêtes par rapport au design** : l'API Sona n'a pas
de "Mix de la semaine" éditorial ni de classement par popularité — l'accueil
reprend donc le dernier morceau écouté ("Reprendre l'écoute") et la
bibliothèque plutôt que d'inventer des données qui n'existent pas côté
serveur.

## Construire le projet

Nécessite un Mac avec Xcode 15+ et [XcodeGen](https://github.com/yonaskolb/XcodeGen) :

```bash
brew install xcodegen
cd ios/Encre
xcodegen generate
open Encre.xcodeproj
```

Lance ensuite le build (⌘R) sur un simulateur ou un iPhone. Au premier
lancement, l'app ouvre l'écran de bienvenue puis demande :

- l'adresse du serveur (`run_api.py` — voir le README principal, section
  « API ») : `http://127.0.0.1:8000` dans le simulateur si l'API tourne sur
  le même Mac, ou l'adresse locale du serveur (`http://192.168.1.x:8000`)
  sur un iPhone physique connecté au même réseau ;
- le jeton `API_TOKEN` défini dans le `.env` du serveur.

Les deux restent modifiables ensuite depuis l'icône ⚙️ de chaque onglet.

## Structure

```
Sources/
  App/            Point d'entrée, coquille à onglets (+ EncreTabBar), routes
  DesignSystem/   Couleurs/typographie/"verre liquide"/halftone, composants
  Networking/     Client de l'API Sona (APIClient, modèles, réglages serveur)
  Features/
    Onboarding/   Bienvenue + configuration du serveur (premier lancement)
    Home/         Onglet Écouter
    Library/      Onglet Bibliothèque
    Search/       Onglet Rechercher
    Detail/       Fiches Album / Artiste
    Player/       Lecture audio (+ contexte de lecture), mini-lecteur, plein écran
    Settings/     Adresse serveur + jeton API (accessible après l'onboarding)
  Resources/Fonts/  Source Serif 4 (SIL OFL — licence incluse)
```

## Limites connues

- Pas de mode sombre (le papier "Encre" n'en a pas encore dans le
  prototype).
- Pas de paroles (Sona n'en a jamais eu côté serveur — le prototype en
  affichait un texte d'exemple statique, ce que l'app ne reproduit pas
  volontairement).
- La barre d'onglets ne se replie pas encore en bulle au défilement (fusion
  avec le mini-lecteur) : ça demande de suivre le décalage de scroll en
  continu, une API arrivée avec iOS 18 (`onScrollGeometryChange`) — notre
  cible est iOS 17. Faisable via l'ancienne méthode `PreferenceKey`, mais pas
  tenté sans pouvoir compiler pour le vérifier.
- La fermeture du lecteur plein écran utilise le geste natif de la feuille
  SwiftUI (glisser vers le bas) plutôt que l'animation `clip-path` du
  prototype.
- Pas de trame de points sur les petites vignettes de liste (résultats de
  recherche, lignes de bibliothèque...) : chacune redessinerait sa grille de
  points via `Canvas`, et je n'ai pas d'appareil ici pour vérifier que ça ne
  saccade pas au défilement d'une longue liste.
- Écrit sans accès à un compilateur Swift dans cette session : à builder et
  corriger sur un Mac avant tout usage. Si Xcode signale des erreurs,
  transmets-les pour une correction rapide.
