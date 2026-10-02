/* Mises à jour de Sona pour Windows (comme celles de CordLauncher).

   Chaque fusion sur master publie la version « windows » du dépôt avec un
   `latest.json` : numéro de version, installateur et son empreinte SHA-256.
   L'app le lit au démarrage puis toutes les 6 heures :

   - « Rechercher automatiquement » (par défaut) : prévient une fois par
     version (notification + Réglages) ;
   - « Installer sans demander » : télécharge, vérifie l'empreinte, lance
     l'installateur en silence et Sona redémarre à jour.

   Version portable : pas d'installateur à relancer, on ouvre la page de
   téléchargement. */

const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { spawn } = require("node:child_process");
const { app, net, shell } = require("electron");
const settings = require("./settings");
const { compareVersions } = require("./iphone");

const MANIFEST_URL = "https://github.com/LeVraiLunatix/sona/releases/download/windows/latest.json";
const RELEASE_PAGE = "https://github.com/LeVraiLunatix/sona/releases/tag/windows";
const EVERY = 6 * 3_600_000;

const portable = !!process.env.PORTABLE_EXECUTABLE_FILE;

const model = {
  current: app.getVersion(),
  latest: null,        // { version, notes, date, setup: { url, sha256, size } }
  available: false,
  checking: false,
  lastCheck: null,
  downloading: null,   // 0 → 1
  error: null,
  portable,
};

let push = () => {};
let notify = () => {};
let beforeInstall = () => {};

function update(values) {
  Object.assign(model, values);
  push({ ...model, autoCheck: settings.get("updatesCheck") !== false, autoInstall: !!settings.get("updatesInstall") });
}

async function check({ manual = false } = {}) {
  if (model.checking) return model;
  update({ checking: true, error: null });
  try {
    const res = await net.fetch(`${MANIFEST_URL}?t=${Date.now()}`, { cache: "no-store" });
    if (!res.ok) throw new Error(res.status === 404 ? "Aucune version publiée pour l'instant." : `Serveur de mises à jour indisponible (code ${res.status}).`);
    const latest = await res.json();
    if (!latest?.version || !latest.setup?.url) throw new Error("Fichier de mise à jour illisible.");
    const available = compareVersions(latest.version, model.current) > 0;
    update({ latest, available, lastCheck: Date.now() });
    if (available) {
      if (!manual && settings.get("updatesInstall") && !portable) {
        install().catch(() => {});
      } else if (settings.get("updatesAnnounced") !== latest.version) {
        settings.set("updatesAnnounced", latest.version);
        notify(`Sona ${latest.version} est disponible`, portable ? "Télécharge la nouvelle version portable depuis Réglages › Sona pour Windows." : "Réglages › Sona pour Windows › Mettre à jour (une minute, Sona redémarre).");
      }
    }
  } catch (e) {
    const message = /^net::|fetch failed/i.test(e.message) ? "Impossible de joindre GitHub : vérifie ta connexion Internet, puis réessaie." : e.message;
    update({ error: manual ? message : null, lastCheck: Date.now() });
  } finally {
    update({ checking: false });
  }
  return model;
}

/** Télécharge l'installateur, vérifie son empreinte, l'exécute en silence et quitte. */
async function install() {
  if (portable) { shell.openExternal(RELEASE_PAGE); return; }
  if (model.downloading != null) return;
  const latest = model.latest;
  if (!latest?.setup?.url || !/^https:\/\//.test(latest.setup.url)) throw new Error("Aucune mise à jour à installer.");
  const dest = path.join(app.getPath("temp"), "Sona", `Sona-Setup-${latest.version}.exe`);
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  update({ downloading: 0, error: null });
  try {
    const res = await net.fetch(latest.setup.url);
    if (!res.ok || !res.body) throw new Error(`Téléchargement impossible (code ${res.status}).`);
    const total = Number(res.headers.get("content-length")) || latest.setup.size || 0;
    const hash = crypto.createHash("sha256");
    const out = fs.createWriteStream(dest);
    let received = 0;
    let last = 0;
    for await (const chunk of res.body) {
      hash.update(chunk);
      received += chunk.length;
      if (!out.write(chunk)) await new Promise((r) => out.once("drain", r));
      if (total && Date.now() - last > 150) { last = Date.now(); update({ downloading: received / total }); }
    }
    await new Promise((resolve, reject) => out.end((err) => (err ? reject(err) : resolve())));
    const digest = hash.digest("hex");
    if (latest.setup.sha256 && digest.toLowerCase() !== String(latest.setup.sha256).toLowerCase()) {
      fs.rmSync(dest, { force: true });
      throw new Error("Le fichier téléchargé ne correspond pas à la version publiée : mise à jour annulée.");
    }
    update({ downloading: 1 });
    // L'installateur ferme l'ancienne version, s'installe au même endroit
    // et relance Sona (`--force-run`).
    spawn(dest, ["/S", "--force-run"], { detached: true, stdio: "ignore", windowsHide: true }).unref();
    beforeInstall();
    setTimeout(() => app.quit(), 300);
  } catch (e) {
    update({ downloading: null, error: e.message });
    throw e;
  }
}

function setOption(key, value) {
  settings.set(key, !!value);
  update({});
}

function init({ onState, onNotify, onBeforeInstall }) {
  push = onState;
  notify = onNotify;
  beforeInstall = onBeforeInstall;
  if (!app.isPackaged) return;
  setTimeout(() => settings.get("updatesCheck") !== false && check(), 20_000);
  setInterval(() => settings.get("updatesCheck") !== false && check(), EVERY);
}

const snapshot = () => ({ ...model, autoCheck: settings.get("updatesCheck") !== false, autoInstall: !!settings.get("updatesInstall") });

module.exports = { init, check, install, setOption, snapshot, RELEASE_PAGE };
