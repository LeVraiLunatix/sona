/* Réglages de l'app d'ordinateur (un fichier JSON dans le dossier de
   l'utilisateur, %APPDATA%\Sona sous Windows). Rien de secret côté compte :
   la session Sona reste dans le stockage de la page, comme sur le web. */

const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { app } = require("electron");

const DEFAULTS = {
  // Fermer la fenêtre la range dans la zone de notification : la musique
  // continue, l'iPhone et la télécommande peuvent toujours piloter le PC.
  closeToTray: true,
  launchAtLogin: false,
  // Télécommande sur le réseau local (téléphone qui scanne le QR code).
  remoteEnabled: true,
  remotePort: 7650,
  remoteKey: "",
  // Vide : l'adresse du serveur écrite dans web/index.html.
  serverUrl: "",
  // Nom dans Sona Connect ; vide : déduit du nom du PC.
  deviceName: "",
  bounds: null,
  maximized: false,
  miniBounds: null,
  trayHintShown: false,
  // Paroles en surimpression sur le bureau (en bas ou en haut de l'écran).
  lyricsOverlay: false,
  overlayPosition: "bottom",
  // Discord : « Écoute Sona » sur le profil. Vide : l'application Discord de Sona.
  discordEnabled: true,
  discordClientId: "",
  // Raccourcis clavier globaux : { action: "CommandOrControl+Alt+Right" }.
  shortcuts: {},
  // Pause automatique : PC verrouillé ou en veille, casque débranché.
  pauseOnLock: true,
  resumeOnUnlock: true,
  pauseOnHeadphones: true,
  // Mode jeu : discret quand une app est en plein écran.
  gameMode: true,
  // Mode vocal : Discord (ou autre) prend le micro → musique baissée.
  micWatch: true,
  // « Sona, suivant » : commandes vocales (micro toujours à l'écoute : coupé par défaut).
  voiceControl: false,
  // Fond d'écran de Windows = pochette floue du titre en cours.
  coverWallpaper: false,
  wallpaperOriginal: null,
  // Progression du titre sur l'icône de la barre des tâches.
  taskbarProgress: true,
};

let cache = null;
const file = () => path.join(app.getPath("userData"), "settings.json");

function load() {
  if (cache) return cache;
  let saved = {};
  try { saved = JSON.parse(fs.readFileSync(file(), "utf8")); } catch {}
  cache = { ...DEFAULTS, ...saved };
  // Avant l'application Discord de Sona, le statut était coupé tant qu'on
  // n'avait pas créé la sienne : il s'allume maintenant pour tout le monde.
  if (!saved.discordDefaultApp) {
    cache.discordDefaultApp = true;
    if (!cache.discordClientId) cache.discordEnabled = true;
    save();
  }
  if (!cache.remoteKey) { cache.remoteKey = newKey(); save(); }
  return cache;
}

function save() {
  try {
    fs.mkdirSync(path.dirname(file()), { recursive: true });
    // Écriture puis renommage : un arrêt brutal ne laisse jamais un fichier à moitié écrit.
    const tmp = `${file()}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(cache, null, 2));
    fs.renameSync(tmp, file());
  } catch {}
}

function get(key) { return load()[key]; }

function set(key, value) {
  load()[key] = value;
  save();
  return value;
}

/** Clé d'association de la télécommande : 128 bits, lisible dans une adresse. */
function newKey() {
  return crypto.randomBytes(16).toString("base64url");
}

module.exports = { get, set, load, newKey };
