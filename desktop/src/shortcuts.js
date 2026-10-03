/* Raccourcis clavier globaux : actifs même quand Sona est en arrière-plan
   (ex. Ctrl+Alt+→ pour le titre suivant). Les touches multimédia du
   clavier marchent déjà sans rien régler. */

const { globalShortcut } = require("electron");

const ACTIONS = {
  toggle: "Lecture / pause",
  next: "Titre suivant",
  previous: "Titre précédent",
  volumeUp: "Volume +",
  volumeDown: "Volume −",
  like: "J'aime",
  lyrics: "Paroles en surimpression",
  show: "Afficher Sona",
};

/** Raccourci au format d'Electron (« CommandOrControl+Alt+Right »), raisonnable. */
function valid(accelerator) {
  return typeof accelerator === "string" && /^[\w+\-=[\];',./`\\ ]{1,60}$/.test(accelerator) && /\+/.test(accelerator);
}

/**
 * Enregistre les raccourcis (et retire les anciens). Renvoie ceux que
 * Windows a refusés : déjà pris par une autre app.
 */
function apply(map, run) {
  globalShortcut.unregisterAll();
  const refused = [];
  for (const [action, accelerator] of Object.entries(map || {})) {
    if (!ACTIONS[action] || !valid(accelerator)) continue;
    let ok = false;
    try { ok = globalShortcut.register(accelerator, () => run(action)); } catch {}
    if (!ok) refused.push(action);
  }
  return refused;
}

module.exports = { ACTIONS, apply, valid };
