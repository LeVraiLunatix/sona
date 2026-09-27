# Encre (app iOS)

Port natif SwiftUI de la maquette **« Encre »** (Claude Design), branché sur
l'[API privée de Sona](../../README.md#api-backend-pour-une-app-iphone).
Usage strictement personnel, comme le reste du projet.

## État actuel — étape 2/3

- [x] Squelette SwiftUI (XcodeGen) + design system (couleurs, typographie
      Source Serif 4, effet "verre liquide") repris du handoff.
- [x] 3 onglets branchés sur l'API réelle : **Écouter** (historique +
      bibliothèque), **Bibliothèque** (titres/albums/artistes), **Rechercher**
      (recherche texte + liens collés).
- [x] Fiches Album / Artiste, lecture audio (`AVPlayer` sur `/stream/...`),
      avec un vrai contexte de lecture (l'album/l'artiste/la liste jouée
      enchaîne "suivant"/"précédent").
- [x] Lecteur plein écran : pochette avec clin d'œil CMJN, cœur (bibliothèque),
      défilement façon forme d'onde, transport, volume, mode Paroles (honnête :
      Sona n'a pas de source de paroles, donc un état vide plutôt qu'un texte
      inventé) et mode File d'attente (les morceaux à suivre dans le contexte
      en cours).
- [ ] Onboarding, barre d'onglets qui se replie en bulle et fusionne avec le
      mini-lecteur, finitions graphiques (halftone, geste `clip-path` de
      fermeture) — étape suivante.

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
lancement, l'app ouvre l'écran **Réglages** pour renseigner :

- l'adresse du serveur (`run_api.py` — voir le README principal, section
  « API ») : `http://127.0.0.1:8000` dans le simulateur si l'API tourne sur
  le même Mac, ou l'adresse locale du serveur (`http://192.168.1.x:8000`)
  sur un iPhone physique connecté au même réseau ;
- le jeton `API_TOKEN` défini dans le `.env` du serveur.

## Structure

```
Sources/
  App/            Point d'entrée, coquille à onglets, routes de navigation
  DesignSystem/   Couleurs/typographie/"verre liquide", composants partagés
  Networking/     Client de l'API Sona (APIClient, modèles, réglages serveur)
  Features/
    Home/         Onglet Écouter
    Library/      Onglet Bibliothèque
    Search/       Onglet Rechercher
    Detail/       Fiches Album / Artiste
    Player/       Lecture audio, mini-lecteur, plein écran
    Settings/     Adresse serveur + jeton API
  Resources/Fonts/  Source Serif 4 (SIL OFL — licence incluse)
```

## Limites connues (étape 2)

- Pas de mode sombre (le papier "Encre" n'en a pas encore dans le
  prototype).
- Pas de paroles (Sona n'en a jamais eu côté serveur — le prototype en
  affichait un texte d'exemple statique, ce que l'app ne reproduit pas
  volontairement).
- La barre d'onglets est un `TabView` natif, pas encore la pastille "verre
  liquide" qui se replie et fusionne avec le mini-lecteur ; la fermeture du
  lecteur plein écran utilise le geste natif de la feuille SwiftUI plutôt que
  l'animation `clip-path` du prototype.
- Écrit sans accès à un compilateur Swift dans cette session : à builder et
  corriger sur un Mac avant tout usage. Si Xcode signale des erreurs,
  transmets-les pour une correction rapide.
