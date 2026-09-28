# Sona (app iOS)

App SwiftUI native branchée sur l'[API privée de Sona](../../README.md#api-backend-pour-une-app-iphone).
Usage strictement personnel, comme le reste du projet.

L'app s'appelle **Sona** sur l'iPhone (nom affiché et icône) ; le projet
Xcode garde son nom interne `Encre` (dossier `ios/Encre`, cible `Encre`), sans
effet visible. Icône et logo de lancement : `python Scripts/make_icon.py`.

## Direction artistique

Sobre et sombre, dans l'esprit de Musique : noir profond, blanc, gris par
transparence, police système (SF Pro). Aucune couleur d'interface — la
couleur vient des pochettes (fond vivant du lecteur, halo des fiches
album). Les jetons sont dans `DesignSystem/Theme.swift` (`Tone`, `Typo`,
`Motion`), les composants dans `DesignSystem/Components.swift`.

Animations : transitions zoom système (la pochette tapée devient la fiche,
le lecteur grandit depuis le mini-lecteur), apparition en cascade des
sections, vignettes qui respirent au défilement, boutons qui s'enfoncent,
symboles qui rebondissent, retours haptiques.

## Fonctionnalités

- **Connexion avec Last.fm**, sur invitation : un nouveau compte attend
  qu'un admin l'accepte (écran d'attente qui se met à jour tout seul). Les
  admins gèrent les accès depuis Réglages → Administration (accepter,
  refuser, révoquer, nommer admin) et sont prévenus sur Telegram à chaque
  demande. Chaque compte a ses propres bibliothèque, historique et stats, et
  peut envoyer ses écoutes sur son profil Last.fm.
- **Écouter** : reprendre l'écoute, écouté récemment, radios, vos artistes,
  vos titres.
- **Bibliothèque** : titres (joués comme une liste, suivant/précédent
  compris), albums, artistes ; appui long pour retirer.
- **Rechercher** (champ natif de la barre d'onglets) : meilleur résultat,
  artistes (tolérant aux fautes : « eiak » → Ziak), albums, titres avec
  chargement de la suite au défilement, liens Deezer/Spotify/Apple
  Music/YouTube collés ; champ vide → radios thématiques par genre.
- **Fiches** album/playlist (halo de couleur, Lecture/Aléatoire, ajout à la
  bibliothèque) et artiste (photo étirable en parallaxe, populaires, radio,
  albums, singles, artistes similaires, suivre).
- **Lecteur plein écran** : fond maillé animé aux couleurs de la pochette,
  pochette qui se rétracte en pause, barre de progression qui s'épaissit
  sous le doigt, paroles synchronisées (LRCLIB) floutées autour de la ligne
  chantée, file d'attente, menu (artiste, album, radio de l'artiste).
- **Radios** sans fin : le lecteur redemande un tirage au serveur quand
  « À suivre » s'épuise.
- Lecture en fond, écran verrouillé, Centre de contrôle, AirPlay.

**Certaines adaptations honnêtes par rapport au design** : l'API Sona n'a pas
de "Mix de la semaine" éditorial ni de classement par popularité — l'accueil
reprend donc le dernier morceau écouté ("Reprendre l'écoute") et la
bibliothèque plutôt que d'inventer des données qui n'existent pas côté
serveur.

## Installer sans Mac (Sideloadly / AltStore)

`.github/workflows/ios.yml` compile l'app sur un runner macOS et publie un
`.ipa` non signé en artefact à chaque exécution — inutile d'avoir Xcode ou
un Mac pour l'obtenir :

1. Onglet **Actions** du dépôt GitHub → workflow **iOS** → l'exécution la
   plus récente sur `master` (ou lance-la à la main avec **Run workflow**).
2. Télécharge l'artefact **Sona-ipa** (zip contenant `Sona.ipa`).
3. Installe-le sur ton iPhone avec [Sideloadly](https://sideloadly.io/)
   (Windows/Mac) : branche l'iPhone en USB, glisse `Sona.ipa` dans
   Sideloadly, renseigne un identifiant Apple (gratuit ou payant) — c'est
   Sideloadly qui signe l'app à l'installation, pas la CI.
4. Avec un identifiant Apple **gratuit**, l'app expire au bout de 7 jours
   (limite d'Apple, pas de Sideloadly) : il suffit de relancer Sideloadly
   avec le même `.ipa` pour la réinstaller. Un compte développeur payant
   (99 $/an) lève cette limite (1 an) — pas nécessaire pour un usage perso
   occasionnel.
5. Sur l'iPhone, la première ouverture demande de faire confiance au
   développeur : **Réglages > Général > VPN et gestion de l'appareil**.

## Construire le projet (avec un Mac)

Avec Xcode 26+ et [XcodeGen](https://github.com/yonaskolb/XcodeGen), pour
développer plutôt que juste installer :

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
  App/            Point d'entrée, coquille à onglets (TabView système), routes
  DesignSystem/   Jetons (Tone/Typo/Motion), pochettes + couleurs extraites, composants
  Networking/     Client de l'API Sona (APIClient, modèles, réglages serveur)
  Features/
    Onboarding/   Bienvenue + configuration du serveur (premier lancement)
    Home/         Onglet Écouter
    Library/      Onglet Bibliothèque
    Search/       Onglet Rechercher
    Detail/       Fiches Album / Artiste
    Player/       Lecture audio (+ contexte de lecture, stations radio), mini-lecteur, plein écran
    Settings/     Adresse serveur + jeton API (accessible après l'onboarding)
```

## Limites connues

- Paroles : seulement ce que LRCLIB connaît (base collaborative) — bonne
  couverture des sorties connues, plus inégale pour les artistes
  underground, qui tombent alors sur « Paroles indisponibles ».
- Cible **iOS 26** minimum (Liquid Glass système) : un iPhone resté sous
  une version antérieure ne peut pas installer l'app.
- Écrit sans accès à un compilateur Swift dans cette session : relu à la main
  mais jamais compilé avant que GitHub Actions (`.github/workflows/ios.yml`)
  ne le fasse sur un runner macOS. Si ce workflow est rouge sur une PR qui
  touche `ios/`, corrige avant de fusionner — c'est exactement le filet que
  cette session n'avait pas.
