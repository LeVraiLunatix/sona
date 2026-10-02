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
- **Télécommande du téléphone** (à la Cider Remote) : bouton téléphone en
  haut de la fenêtre (ou Réglages → Télécommande du téléphone) → un QR code.
  Le téléphone le scanne et ouvre Sona Remote : pochette en grand, lecture,
  position, volume, paroles synchronisées, file d'attente et recherche (le
  titre choisi se lance sur le PC). Aucune app à installer : c'est une page
  servie par le PC ; on peut l'ajouter à l'écran d'accueil.
- **Mini-lecteur** : une petite fenêtre en verre (le vrai verre acrylique de
  Windows 11), toujours au premier plan.
- **Barre des tâches** : boutons précédent / lecture / suivant dans l'aperçu
  de la fenêtre ; menu de la zone de notification avec le titre en cours.
- **Touches multimédia** du clavier et panneau multimédia de Windows (avec la
  pochette), via la Media Session de la page.
- **Lancer avec Windows** (option) : Sona démarre discrètement dans la zone
  de notification, prêt à recevoir la musique de l'iPhone.

## Installer

Chaque fusion sur `master` qui touche `desktop/` ou `web/` fabrique
l'installateur sur GitHub Actions (workflow **Windows**) et le publie dans la
version **« Sona pour Windows »** du dépôt (onglet *Releases*) :

- `Sona-Setup-x.y.z.exe` : installateur (menu Démarrer, raccourci bureau,
  désinstallation depuis les Paramètres de Windows) ;
- `Sona-Portable-x.y.z.exe` : version qui se lance sans rien installer.

Sur une *pull request*, les mêmes fichiers sont dans les **artefacts** du
workflow (onglet *Actions* → l'exécution → *Sona-Windows*).

L'exécutable n'est pas signé (un certificat de signature est payant) : au
premier lancement, Windows SmartScreen affiche « Windows a protégé votre
ordinateur ». Clique sur **Informations complémentaires**, puis **Exécuter
quand même**.

À la première activation de la télécommande, le **pare-feu Windows** demande
s'il faut autoriser Sona : accepte pour les **réseaux privés** (le Wi-Fi de
la maison), sinon le téléphone ne peut pas joindre le PC.

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
| `src/mini/` | Mini-lecteur |
| `remote/` | Page Sona Remote, servie au téléphone |
| `../web/desktop.css` | Habillage verre liquide de Sona web dans l'app |

Côté page, tout passe par la section « Sona pour Windows » de `web/app.js` :
sans `window.sonaDesktop` (un navigateur), rien ne change.
