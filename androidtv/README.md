# Alyra pour Android TV

Port Android TV de l'app iOS (Encre / Alyra) : même API privée de Sona, même
design sombre (Source Serif 4, cyan/magenta). Java pur sans AndroidX ni
Gradle, comme le launcher `D:\Code\tvlauncher`.

## Fonctions

- Rail de navigation (Écouter, Rechercher, Bibliothèque, Radios, Réglages),
  entièrement pilotable à la télécommande (D-pad, OK, Retour, touches média).
- Recherche titres / albums / artistes + lien collé (Spotify, Deezer, YouTube…),
  fiches album et artiste, radios, bibliothèque (♥).
- Lecteur plein écran, mini-lecteur, file d'attente, radio infinie, lecture en
  arrière-plan (service + MediaSession).
- Le serveur prépare le morceau (quelques secondes) : l'app le télécharge en
  entier dans un cache de 48 Mo, et préchauffe le suivant.

## Serveur

L'app parle à `run_api.py` (voir le README principal, section « API »). Pour
l'atteindre depuis la TV :

```
API_TOKEN=<jeton>  API_HOST=0.0.0.0  API_PORT=8000  python run_api.py
```

Puis dans **Réglages** de l'app : `http://<ip-du-serveur>:8000` + le jeton.
Les deux se règlent aussi en ADB : `--es url … --es token …`.

## Construire / installer

```
powershell -File build.ps1          # -> Alyra.apk (SDK dans D:\Code\_assets\tv\sdk)
adb connect 192.168.1.55:5555
adb install -r Alyra.apk
```

Test à distance (la capture système de la TV sort noire, `snap.ps1` dessine
l'app dans un PNG) : extras `screen` (search|library|radios|settings), `q`
(recherche), `play` (cherche et joue le premier résultat), `now` (lecteur plein
écran), `open` (`album:deezer:ID` / `artist:deezer:ID`).

## Pièges

- d8 plante sur les classes qui ont une méthode pont générique (sous-classe de
  `LruCache`, classe implémentant une interface générique…) : lambdas
  uniquement.
- Sur cette TV (MediaTek), `MediaPlayer` lit le m4a/AAC comme « terminé » au
  bout de quelques ms (décodeur passthrough) : l'app demande donc `format=mp3`.
- Stockage interne quasi plein (~4 Go) : garder le cache audio petit.
- La TV se met en veille vite : `input keyevent KEYCODE_WAKEUP` avant un test,
  sinon le système n'a plus de fenêtre focalisée (faux « ANR »).
