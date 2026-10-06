# Sona pour Windows

L'app d'ordinateur de Sona : Sona web (dossier `web/` du dépôt, livré avec
l'app) dans une vraie fenêtre Windows, avec un habillage « verre liquide » et
ce qu'un navigateur ne sait pas faire.

## Ce qu'elle fait

- **Sona Connect** : le PC apparaît dans Sona Connect sous son nom (« PC
  Windows », ou celui choisi dans Réglages). L'iPhone le voit, y envoie la
  musique (« Écouter dessus ») et le pilote : lecture, pause, suivant,
  volume, position. Ça marche aussi fenêtre fermée : Sona reste dans la zone
  de notification et la musique continue.
- **Appareils** : sur l'iPhone (bouton en haut à gauche) ou le site, le PC
  apparaît tout seul (dès que Sona pour Windows s'ouvre avec le compte) et
  reste enregistré, même éteint ; on peut le renommer ou l'oublier. Un
  appui dessus et le téléphone le pilote — via le serveur Sona, donc aussi
  en 4G, sans QR code : lecture, volume, j'aime, aléatoire, répéter, et
  « À suivre » (un appui lance le titre sur le PC).
- **Télécommande du téléphone** (à la Cider Remote) : bouton téléphone en
  haut de la fenêtre (ou Réglages → Télécommande du téléphone) → un QR code.
  Le téléphone le scanne et ouvre Sona Remote : pochette en grand, lecture,
  position, volume, paroles synchronisées, file d'attente et recherche (le
  titre choisi se lance sur le PC). Aucune app à installer : c'est une page
  servie par le PC ; on peut l'ajouter à l'écran d'accueil.
- **Paroles en surimpression** : les paroles synchronisées par-dessus les
  autres fenêtres (jeu, navigateur…), en bas ou en haut de l'écran ; on
  clique au travers. Réglages, zone de notification ou raccourci clavier.
- **Statut Discord** : « Écoute Sona » sur ton profil, avec le titre, la
  pochette et la progression — aussi pour ce qui joue sur l'iPhone ou le
  site (Sona Connect), tant que Sona tourne sur le PC, même réduit près de
  l'horloge : Discord ne laisse que son app d'ordinateur recevoir un
  statut, un iPhone ou une page web ne peuvent pas lui parler. En pause
  plus de 5 min, le statut disparaît. Activé d'office, rien à créer : Sona
  a son application Discord (`1557013953190821979`, logo compris). Il faut
  seulement Discord (l'app d'ordinateur) ouvert sur le PC et, dans Discord,
  Paramètres → Confidentialité de l'activité → « Partager mon activité ».
  Réglages → Discord permet de mettre ta propre application à la place.
- **Pause automatique** : PC verrouillé ou en veille (la musique repart au
  déverrouillage), casque ou enceinte débranché.
- **Volume fin et préréglages** : le curseur suit l'oreille (beaucoup de
  finesse dans les volumes bas), molette ou flèches au pour cent près (5 %
  avec Maj), pourcentage affiché ; clic sur le haut-parleur → feuille
  « Volume » avec −/+ et quatre préréglages modifiables (En vocal, Calme,
  Normal, Fort ; le crayon enregistre le volume actuel). Aussi dans le
  lecteur plein écran, et en raccourci « Volume : préréglage suivant ».
- **Mode vocal automatique** : quand Discord (ou une autre app) prend le
  micro, la musique passe sur « En vocal », puis revient au volume d'avant
  à la fin de l'appel. Windows le note lui-même (l'icône de micro près de
  l'horloge, CapabilityAccessManager) : relu toutes les 3 s.
- **Fenêtre** : la taille minimale s'adapte à l'écran (zoom Windows
  125-150 %), le plein écran (F11) ressort comme on y était entré, le
  lecteur plein écran garde commandes et volume visibles à toute hauteur,
  et la barre du haut range dans « ⋯ » les boutons qui ne tiennent plus.
- **Barre des tâches** : dans l'aperçu, précédent / lecture / suivant et
  ♥ (plein quand le titre est dans ta bibliothèque) ; l'icône se remplit
  au fil du titre (orange en pause) ; clic droit sur l'icône : lecture /
  pause, suivant, précédent, mini-lecteur, paroles, mode focus.
- **Mode focus** (Pomodoro) : 25, 50 ou 90 min de concentration en musique
  (la tienne ou une radio calme), puis une pause où la musique s'arrête ;
  un chrono flotte en bas à droite, un « ding » et une notification à
  chaque changement. Aussi sur le web (tuile « Mode focus » de l'accueil).
- **Fond d'écran pochette** (coupé par défaut) : le fond d'écran de Windows
  devient la pochette en cours, floue et assombrie ; ton fond d'écran
  revient quand tu coupes l'option.
- **Commandes vocales « Sona… »** (coupées par défaut) : « Sona, pause »,
  « Sona, suivant », « Sona, plus fort », « Sona, j'aime », « Sona, mets du
  PNL ». Reconnaissance vocale de Windows, hors ligne ; il faut la voix
  française de Windows (Paramètres → Heure et langue → Voix / Langue →
  Français → Reconnaissance vocale).
- **Mode jeu** : un jeu (ou toute app) en plein écran → plus de
  notifications de Sona, paroles en surimpression sur une ligne, discrètes.
  Windows le signale lui-même (SHQueryUserNotificationState).
- **Visualiseur** (bouton ondes en haut) : spectre plein écran aux couleurs
  de la pochette ; F pour le plein écran, Échap pour fermer.
- **Raccourcis clavier globaux** (Réglages → Raccourcis clavier) : lecture,
  suivant, précédent, volume, j'aime, paroles, afficher Sona — même quand
  Sona est en arrière-plan.
- **Mini-lecteur** : une petite fenêtre en verre (le vrai verre acrylique de
  Windows 11), toujours au premier plan.
- **Barre des tâches** : boutons précédent / lecture / suivant dans l'aperçu
  de la fenêtre ; menu de la zone de notification avec le titre en cours.
- **Touches multimédia** du clavier et panneau multimédia de Windows (avec la
  pochette), via la Media Session de la page.
- **Lancer avec Windows** (option) : Sona démarre discrètement dans la zone
  de notification, prêt à recevoir la musique de l'iPhone.
- **Sona sur l'iPhone** (onglet « Sona sur l'iPhone » de la barre latérale),
  comme CordLauncher : voir plus bas.
- **Mises à jour** : l'app vérifie les nouvelles versions (Windows et
  iPhone) au démarrage puis toutes les 6 heures. Réglages › Mises à jour.
- **Plugin Stream Deck** : voir plus bas.

## Installer

Chaque fusion sur `master` qui touche `desktop/` ou `web/` fabrique
l'installateur sur GitHub Actions (workflow **Windows**) et le publie dans la
version **« Sona pour Windows »** du dépôt (onglet *Releases*) :

- `Sona-Setup-x.y.z.exe` : installateur (menu Démarrer, raccourci bureau,
  désinstallation depuis les Paramètres de Windows) ;
- `Sona-Portable-x.y.z.exe` : version qui se lance sans rien installer.
- `Sona-StreamDeck.streamDeckPlugin` : le plugin Stream Deck.

Sur une *pull request*, les mêmes fichiers sont dans les **artefacts** du
workflow (onglet *Actions* → l'exécution → *Sona-Windows*).

L'exécutable n'est pas signé (un certificat de signature est payant) : au
premier lancement, Windows SmartScreen affiche « Windows a protégé votre
ordinateur ». Clique sur **Informations complémentaires**, puis **Exécuter
quand même**.

À la première activation de la télécommande, le **pare-feu Windows** demande
s'il faut autoriser Sona : accepte pour les **réseaux privés** (le Wi-Fi de
la maison), sinon le téléphone ne peut pas joindre le PC.

## Sona sur l'iPhone

La même méthode que CordLauncher (même moteur, `isideload`) : Sona s'installe
sur l'iPhone depuis le PC, **signée avec ton compte Apple** (gratuit), sans
SideStore ni Sideloadly.

1. Installe **Appareils Apple** (Microsoft Store) ou **iTunes** : Windows en
   a besoin pour parler à l'iPhone (service *Apple Mobile Device*).
2. Branche l'iPhone, déverrouille-le, touche **Se fier**.
3. Onglet **Sona sur l'iPhone** → **Connecter mon compte Apple** (le code de
   vérification d'Apple s'affiche dans l'app) → **Installer Sona**.
4. Sur l'iPhone : Réglages › Général › **VPN et gestion de l'appareil** ›
   faire confiance à ton compte, puis activer le **mode développeur** si iOS
   le demande.

Ensuite, le **mode automatique** (activé par défaut) fait le reste, même
fenêtre fermée : chaque nouvelle version de Sona iOS (la source SideStore du
dépôt, `releases/latest/download/source.json`) est installée, et l'app est
**renouvelée deux jours avant d'expirer** (7 jours avec un compte gratuit).
Si l'iPhone n'est pas là, une notification prévient la veille. Avec le
**Wi-Fi** activé dans l'onglet (iPhone branché une fois), plus besoin du
câble : il suffit d'être sur le même réseau.

- Le mot de passe Apple n'est gardé que si tu coches « Mémoriser », dans le
  **coffre de Windows** ; il sert à renouveler sans rien redemander.
- Si Apple refuse en rafale (erreurs 429), Sona met le compte en pause dix
  minutes ; « Réinitialiser l'appareil Apple » (menu ⋯) repart de zéro.
- Les certificats Apple créés par Sona portent le nom de machine « Sona » :
  ce sont les seuls que Sona révoque quand la limite est atteinte (jamais
  ceux d'AltStore, de Sideloadly ou de CordLauncher).
- Compte gratuit : 3 apps au plus par iPhone, 10 identifiants d'app par
  semaine (limites d'Apple).
- Journal détaillé : menu ⋯ › Ouvrir le journal
  (`%APPDATA%\Sona\iphone\logs\iphone.log`).

Le travail est fait par `sona-iphone.exe` (dossier `iphone/`, en Rust), le
cœur iPhone de CordLauncher sans Tauri, piloté par l'app en JSON sur son
entrée/sortie standard.

## Mises à jour

Chaque fusion sur `master` publie la version « Sona pour Windows » avec un
`latest.json` (numéro de version, installateur, empreinte SHA-256). L'app le
lit au démarrage puis toutes les 6 heures :

- **Rechercher automatiquement** (par défaut) : une notification par
  nouvelle version, et « Mettre à jour » dans Réglages › Mises à jour ;
- **Installer sans demander** : téléchargement, vérification de
  l'empreinte, installation silencieuse, Sona redémarre à jour.

La version portable ne peut pas se remplacer elle-même : « Télécharger »
ouvre la page de la nouvelle version. L'iPhone, lui, suit le mode
automatique de l'onglet Sona sur l'iPhone.

## Plugin Stream Deck

`Sona-StreamDeck.streamDeckPlugin` (dans la version « Sona pour Windows ») :
double-clic pour l'installer dans le logiciel Stream Deck (6.5 ou plus).
Rien à configurer : il lit la clé de la télécommande dans les réglages de
Sona sur le même PC et lui parle en local.

| Action | Effet |
|---|---|
| En cours | La pochette du titre en cours ; un appui met en pause ou relance |
| Lecture / pause, Suivant, Précédent | La lecture, l'icône suit l'état |
| J'aime, Aléatoire, Répéter | En rose quand c'est activé |
| Volume +, Volume − | ±5 % |
| Molette Sona (Stream Deck +) | Tourner : volume (1 % par cran) · appuyer : lecture/pause · toucher : suivant |
| Position Sona (Stream Deck +) | Tourner : avancer/reculer de 5 s par cran · appuyer : lecture/pause |
| Ajouter à une playlist | Le titre en cours dans la playlist choisie (panneau de la touche) |
| Radio DJ | Une radio à partir du titre en cours |
| Paroles | Affiche ou masque les paroles en surimpression |
| Playlist | La pochette d'une playlist choisie (panneau de la touche) ; un appui la lance |
| Partager le titre | Copie « 🎧 titre — artiste » et un lien d'écoute, prêt à coller dans Discord |
| Préréglage de volume | Passe au préréglage suivant (En vocal, Calme, Normal, Fort), écrit sur la touche |

Chaque touche a un réglage **Appareil** (panneau de la touche dans le
logiciel Stream Deck) : « Ce PC », ou un autre appareil Sona Connect du
compte (l'iPhone, un autre ordinateur) allumé. Sona pour Windows relaie
alors les commandes à cet appareil ; éteint, la touche l'indique.

Sona fermé, ou télécommande coupée dans Sona : les touches l'indiquent. Un
appui qui échoue affiche l'alerte du Stream Deck et écrit la raison sur la
touche pendant 4 s ; le détail est dans le journal du plugin
(`%APPDATA%\Elgato\StreamDeck\Plugins\app.sona.remote.sdPlugin\logs`). Le code est dans `streamdeck/`
(`npm run build`, `npm test`, `npm run pack`).

## Connexion

La même que sur le web : « Se connecter avec Last.fm » ouvre une petite
fenêtre Last.fm ; une fois Sona autorisé, elle se ferme et l'app s'ouvre. Le
compte doit être validé par un administrateur, comme partout.

L'adresse du serveur est celle de `web/index.html` (`<meta
name="sona-server">`) ; elle se change dans Réglages → Sona pour Windows →
Serveur Sona si le serveur déménage.

## Télécommande : sécurité

- Le PC n'accepte que les adresses du **réseau local** (192.168.x, 10.x,
  172.16–31.x, et 100.64.x pour Tailscale) : même si le pare-feu laissait
  passer, Internet resterait dehors.
- Tout ce qui lit ou change la lecture demande la **clé d'association**
  (128 bits) contenue dans le QR code. Elle voyage après le `#` de l'adresse :
  jamais dans une requête ni dans un journal. Le téléphone la garde ensuite.
- « Nouveau code d'association » (dans la fenêtre du QR code) change la clé
  et déconnecte tous les téléphones : à faire si un téléphone ne doit plus
  piloter le PC.
- Désactivable entièrement (Réglages → Télécommande du téléphone).

Port par défaut : **7650** (le suivant libre jusqu'à 7655 s'il est pris).

## Développer

Node 22, depuis ce dossier :

```bash
npm install
npm start          # lance l'app (Sona web du dossier ../web, rechargé à chaque lancement)
cd iphone && cargo build --release   # module iPhone (trouvé tout seul par `npm start`)
npm test           # tests de la télécommande (node --test, sans Electron)
npm run check      # syntaxe de tous les scripts
npm run dist       # installateur + portable Windows dans dist/ (à lancer sous Windows)
```

`Ctrl+Maj+I` ouvre les outils de développement, `F5` recharge la page.

Organisation :

| Fichier | Rôle |
|---|---|
| `src/main.js` | Processus principal : fenêtre, zone de notification, barre des tâches, mini-lecteur, protocole `app://sona/` qui sert `web/` |
| `src/preload.js` | Pont `window.sonaDesktop` (seulement pour la page de l'app) |
| `src/remote-server.js` | Serveur de la télécommande (HTTP + Server-Sent Events) |
| `src/settings.js` | Réglages de l'app (`%APPDATA%\Sona\settings.json`) |
| `src/glyphs.js` | Icônes de la barre des tâches, dessinées en mémoire |
| `src/iphone.js` | Onglet iPhone : pilote `sona-iphone`, mode automatique, rappels |
| `src/updater.js` | Mises à jour de l'app (latest.json, SHA-256, installation silencieuse) |
| `iphone/` | `sona-iphone` (Rust) : compte Apple, signature, envoi câble/Wi-Fi |
| `streamdeck/` | Plugin Stream Deck |
| `src/mini/` | Mini-lecteur |
| `remote/` | Page Sona Remote, servie au téléphone |
| `../web/desktop.css` | Habillage verre liquide de Sona web dans l'app |

Côté page, tout passe par la section « Sona pour Windows » de `web/app.js` :
sans `window.sonaDesktop` (un navigateur), rien ne change.
