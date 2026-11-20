# Sona pour Meta Quest

L'app Sona du casque : un vrai lecteur Android (Media3) qui se connecte à ton serveur Sona,
apparaît comme appareil « Meta Quest » dans **Sona Connect**, et se pilote depuis l'iPhone ou
le site comme n'importe quel autre appareil.

## Ce qu'elle fait

- **Connexion par QR code** : le casque affiche un QR code, tu l'autorises depuis ton iPhone
  (même flux que la TV, `/auth/device`). Aucun clavier à taper dans le casque.
- **Lecteur** : pochette, paroles synchronisées (un appui sur une ligne s'y place), file d'attente,
  aléatoire, répéter. Recherche dans le catalogue Sona.
- **Sona Connect** : le casque se signale (`kind: quest`), reçoit les commandes (lecture, pause,
  suivant, position, volume, « écouter ici »…) et peut piloter les autres appareils. L'onglet
  *Appareils* permet de reprendre ici la musique qui joue ailleurs.
- **Musique pendant les jeux VR** : un service de lecture au premier plan garde la musique quand tu
  changes de fenêtre ou lances un jeu. Réglage *Continuer pendant les jeux VR* (pas de focus audio).
- **Sona Paroles** : une seconde icône, un petit panneau (pochette, paroles, contrôles) à poser
  où tu veux dans la pièce.
- **Visualiseur** : barres et pulsation réagissant au son que Sona joue (analyse FFT de la sortie
  de l'app, jamais le micro).

## Installer

L'APK est fabriqué par GitHub Actions (`.github/workflows/quest.yml`) : fichier `Sona-Quest.apk`
de la version « Sona pour Meta Quest » (ou artefact `Sona-Quest` d'un build de PR).

```
adb install -r Sona-Quest.apk
```

Il faut le mode développeur sur le casque. L'APK est signé avec la clé de débogage d'Android
(`app/sona-debug.keystore`, publique par nature) : un APK plus récent se met à jour par-dessus.
Il n'est pas destiné au Store de Meta.

## Côté serveur

Seul changement : `kind` accepte `quest` dans `/connect/sync` (`app/api/routers/connect.py`).
Les autres clients affichent pour l'instant ce casque avec l'icône d'un ordinateur.

## Limites actuelles

- Le visualiseur est une fenêtre 2D : l'affichage dans la pièce (réalité mixte, passthrough)
  demande le SDK Meta Spatial, prévu dans un second temps.
- « J'aime » n'est pas branché sur le casque.

## Compiler à la main

JDK 17 + Android SDK (plateforme 35), puis `gradle assembleRelease` dans `quest/`.
