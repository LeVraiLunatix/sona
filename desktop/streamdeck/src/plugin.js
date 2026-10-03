/* Plugin Stream Deck de Sona : pilote Sona pour Windows depuis les touches
   (et les molettes du Stream Deck +). Chaque touche suit l'état en direct :
   pochette du titre en cours, lecture/pause, j'aime, aléatoire, répéter.

   Chaque touche a un réglage « Appareil » (panneau de la touche dans le
   logiciel Stream Deck) : ce PC, ou un autre appareil Sona Connect du
   compte — l'iPhone, un autre ordinateur. Sona pour Windows relaie alors
   les commandes à cet appareil. */

import streamDeck, { SingletonAction } from "@elgato/streamdeck";
import { coverSvg, dataUrl, keySvg } from "./art.js";
import { SonaClient } from "./sona.js";

const sona = new SonaClient();
const UUID = "app.sona.remote";

const OFFLINE_TITLE = { absent: "Sona\nabsent", off: "Télé-\ncommande\ncoupée", offline: "Sona\nfermé" };

/** Texte court sur 3 lignes au plus, pour le titre d'une touche. */
function keyText(message) {
  const lines = [];
  for (const word of String(message || "Erreur").split(/\s+/)) {
    const last = lines[lines.length - 1];
    if (last && (last + " " + word).length <= 9) lines[lines.length - 1] = `${last} ${word}`;
    else lines.push(word);
  }
  return lines.slice(0, 3).join("\n");
}

// ── Appareil de chaque touche ──────────────────────────────────────────

/** Réglages de chaque touche (par contexte) : `device` vide = ce PC. */
const settingsOf = new Map();
const deviceOf = (action) => settingsOf.get(action.id)?.device || "";

/**
 * L'état à montrer pour une touche : celui de ce PC, ou celui de l'appareil
 * réglé (relayé par Sona). `null` : appareil éteint ou inconnu.
 */
function stateFor(device) {
  const st = sona.state || {};
  if (!device) return st;
  const d = (st.devices || []).find((x) => x.id === device);
  if (!d) return null;
  return { track: d.track, paused: !d.playing, volume: d.volume ?? 1, shuffle: !!d.shuffle,
    repeat: d.repeat && d.repeat !== "off", liked: !!d.liked, position: d.position || 0, duration: d.track?.duration_seconds || 0 };
}

/** Pourquoi la touche ne peut rien faire (ou "" si tout va bien). */
function problemFor(device) {
  if (sona.status !== "online") return OFFLINE_TITLE[sona.status] || "Sona\nfermé";
  if (device && !stateFor(device)) return keyText(`${deviceName(device) || "Appareil"} éteint`);
  return "";
}

/** Nom connu d'un appareil (réglage enregistré, sinon liste de Sona). */
const knownNames = new Map();
function deviceName(id) {
  return (sona.state?.devices || []).find((d) => d.id === id)?.name || knownNames.get(id) || "";
}

const command = (action, device, extra = {}) => sona.command(action, { ...extra, ...(device ? { target: device } : {}) });

/** Touches qui affichent une erreur : l'état en direct ne l'efface pas. */
const flashes = new Map();

/**
 * Un appui : attend Sona un instant s'il vient d'ouvrir, lance l'action, et
 * en cas d'échec écrit la raison sur la touche pendant 4 s (en plus de
 * l'alerte), pour savoir ce qui cloche sans fouiller les journaux.
 */
async function press(singleton, action, run) {
  let problem = null;
  if (!(await sona.ready())) problem = OFFLINE_TITLE[sona.status] || "Sona\nfermé";
  else if ((problem = problemFor(deviceOf(action)))) {
    // Appareil éteint : rien à envoyer.
  } else {
    try {
      await run();
      return;
    } catch (e) {
      streamDeck.logger.warn(`${singleton.manifestId} : ${e.message}`);
      problem = keyText(e.message);
    }
  }
  await action.showAlert().catch(() => {});
  if (action.isDial()) {
    await action.setFeedback({ title: problem.replace(/\n/g, " ") }).catch(() => {});
  } else {
    await action.setTitle(problem).catch(() => {});
  }
  clearTimeout(flashes.get(action.id));
  flashes.set(action.id, setTimeout(() => {
    flashes.delete(action.id);
    singleton.render(action, true).catch(() => {});
  }, 4000));
}

/** Base des actions : réglages par touche, liste des appareils pour le panneau. */
class SonaAction extends SingletonAction {
  onWillAppear(ev) {
    settingsOf.set(ev.action.id, ev.payload.settings || {});
    rememberName(ev.payload.settings);
    return this.render(ev.action, true);
  }

  onWillDisappear(ev) {
    settingsOf.delete(ev.action.id);
  }

  onDidReceiveSettings(ev) {
    settingsOf.set(ev.action.id, ev.payload.settings || {});
    rememberName(ev.payload.settings);
    return this.render(ev.action, true);
  }

  onPropertyInspectorDidAppear() {
    return sendDevices();
  }

  onSendToPlugin() {
    return sendDevices();
  }
}

function rememberName(settings) {
  if (settings?.device && settings.deviceName) knownNames.set(settings.device, settings.deviceName);
}

/** Le panneau de la touche : « Ce PC » et les appareils Sona Connect allumés. */
function sendDevices() {
  const devices = (sona.state?.devices || []).map((d) => ({ id: d.id, name: d.name, kind: d.kind }));
  return streamDeck.ui.sendToPropertyInspector({ devices, online: sona.status === "online" }).catch(() => {});
}

/** Les touches, chacune avec son dessin selon l'état de l'appareil. */
class SonaKey extends SonaAction {
  constructor(id, { glyph, on, run }) {
    super();
    this.manifestId = `${UUID}.${id}`;
    this.glyph = glyph;
    this.on = on || (() => false);
    this.run = run;
  }

  async render(action) {
    if (!action.isKey()) return;
    const device = deviceOf(action);
    const problem = problemFor(device);
    const st = stateFor(device) || {};
    const glyph = typeof this.glyph === "function" ? this.glyph(st) : this.glyph;
    await action.setImage(dataUrl(keySvg(glyph, { on: !problem && this.on(st), dim: !!problem || (!st.track && this.needsTrack) })));
    if (!flashes.has(action.id)) await action.setTitle(problem);
  }

  onKeyDown(ev) {
    const device = deviceOf(ev.action);
    return press(this, ev.action, () => this.run(stateFor(device) || {}, device));
  }
}

const setVolume = (v, device) => {
  const volume = Math.round(Math.max(0, Math.min(1, v)) * 100) / 100;
  const st = stateFor(device);
  if (!device && sona.state) sona.state.volume = volume;
  else if (st) {
    const d = (sona.state?.devices || []).find((x) => x.id === device);
    if (d) d.volume = volume;
  }
  return command("volume", device, { volume });
};

const keys = [
  new SonaKey("playpause", { glyph: (st) => (st.track && !st.paused ? "pause" : "play"), run: (st, d) => command("toggle", d) }),
  new SonaKey("next", { glyph: "next", run: (st, d) => command("next", d) }),
  new SonaKey("previous", { glyph: "previous", run: (st, d) => command("previous", d) }),
  new SonaKey("like", { glyph: (st) => (st.liked ? "heartFill" : "heart"), on: (st) => !!st.liked, run: (st, d) => command("like", d) }),
  new SonaKey("shuffle", { glyph: "shuffle", on: (st) => !!st.shuffle, run: (st, d) => command("shuffle", d) }),
  new SonaKey("repeat", { glyph: "repeat", on: (st) => !!st.repeat, run: (st, d) => command("repeat", d) }),
  new SonaKey("volumeup", { glyph: "volumeUp", run: (st, d) => setVolume((st.volume ?? 1) + 0.1, d) }),
  new SonaKey("volumedown", { glyph: "volumeDown", run: (st, d) => setVolume((st.volume ?? 1) - 0.1, d) }),
];
for (const k of keys.filter((k) => ["like"].includes(k.manifestId.split(".").pop()))) k.needsTrack = true;

// ── Pochettes ──────────────────────────────────────────────────────────

const covers = new Map();

/** Pochette en image intégrée (Stream Deck n'ouvre pas les adresses web). */
async function cover(url) {
  if (!url) return null;
  // Deezer : la taille est dans l'adresse ; 250 px suffisent pour une touche.
  const small = url.replace(/\/(\d+)x\1(-\d+-\d+-\d+-\d+)?\.jpg$/, "/250x250$2.jpg");
  if (covers.has(small)) return covers.get(small);
  const job = fetch(small, { signal: AbortSignal.timeout(8000) })
    .then(async (res) => {
      if (!res.ok) return null;
      const type = res.headers.get("content-type") || "image/jpeg";
      return `data:${type};base64,${Buffer.from(await res.arrayBuffer()).toString("base64")}`;
    })
    .catch(() => null);
  covers.set(small, job);
  if (covers.size > 30) covers.delete(covers.keys().next().value);
  return job;
}

/** Touche « En cours » : la pochette du titre ; appui = lecture/pause. */
class NowPlaying extends SonaAction {
  manifestId = `${UUID}.nowplaying`;
  last = new Map();

  async render(action, force = false) {
    if (!action.isKey()) return;
    const device = deviceOf(action);
    const problem = problemFor(device);
    const st = stateFor(device) || {};
    const t = problem ? null : st.track;
    const key = JSON.stringify([problem, t?.source, t?.source_id, st.paused]);
    if (!force && key === this.last.get(action.id)) return;
    this.last.set(action.id, key);
    const image = t ? await cover(t.cover_url) : null;
    await action.setImage(dataUrl(coverSvg({ image, paused: !t || st.paused, title: t?.title, artist: t?.artist })));
    if (!flashes.has(action.id)) await action.setTitle(problem);
  }

  onKeyDown(ev) {
    return press(this, ev.action, () => command("toggle", deviceOf(ev.action)));
  }
}

const fmt = (s) => `${Math.floor(Math.max(0, s) / 60)}:${String(Math.floor(Math.max(0, s) % 60)).padStart(2, "0")}`;

/** Position actuelle de l'appareil d'une molette (elle avance pendant la lecture). */
function positionFor(device) {
  if (!device) return sona.position();
  const st = stateFor(device);
  if (!st) return 0;
  const p = st.position + (st.paused ? 0 : (Date.now() - sona.receivedAt) / 1000);
  return st.duration ? Math.min(p, st.duration) : p;
}

/** Molette (Stream Deck +) : tourner = volume, appuyer = lecture/pause, toucher = suivant. */
class Dial extends SonaAction {
  manifestId = `${UUID}.dial`;
  timer = null;

  async render(action) {
    if (!action.isDial() || flashes.has(action.id)) return;
    const device = deviceOf(action);
    const problem = problemFor(device);
    const st = stateFor(device) || {};
    const volume = Math.round((st.volume ?? 1) * 100);
    await action.setFeedback({
      title: problem ? problem.replace(/\n/g, " ") : (st.track?.title || deviceName(device) || "Sona"),
      value: problem ? "" : `${volume} %`,
      indicator: { value: problem ? 0 : volume },
      icon: dataUrl(keySvg(st.track && !st.paused ? "speaker" : "pause", { size: 72, dim: !!problem })),
    });
  }

  onDialRotate(ev) {
    const device = deviceOf(ev.action);
    if (problemFor(device)) return press(this, ev.action, async () => {});
    // Les crans s'accumulent : un envoi toutes les 80 ms au plus.
    const st = stateFor(device);
    const volume = Math.max(0, Math.min(1, (st?.volume ?? 1) + ev.payload.ticks * 0.02));
    if (!device && sona.state) sona.state.volume = volume;
    else {
      const d = (sona.state?.devices || []).find((x) => x.id === device);
      if (d) d.volume = volume;
    }
    this.render(ev.action);
    clearTimeout(this.timer);
    this.timer = setTimeout(() => setVolume(volume, device).catch(() => {}), 80);
  }

  onDialDown(ev) {
    return press(this, ev.action, () => command("toggle", deviceOf(ev.action)));
  }

  onTouchTap(ev) {
    return press(this, ev.action, () => command("next", deviceOf(ev.action)));
  }
}

/** Molette « Position » (Stream Deck +) : tourner = avancer/reculer de 5 s par cran, appuyer = lecture/pause. */
class SeekDial extends SonaAction {
  manifestId = `${UUID}.seekdial`;
  pending = new Map();
  timers = new Map();

  async render(action) {
    if (!action.isDial() || flashes.has(action.id)) return;
    const device = deviceOf(action);
    const problem = problemFor(device);
    const st = stateFor(device) || {};
    const dur = st.duration || st.track?.duration_seconds || 0;
    const pos = this.pending.get(action.id) ?? positionFor(device);
    await action.setFeedback({
      title: problem ? problem.replace(/\n/g, " ") : (st.track?.title || "Sona"),
      value: problem || !st.track ? "" : `${fmt(pos)} / ${fmt(dur)}`,
      indicator: { value: !problem && dur ? Math.round((pos / dur) * 100) : 0 },
      icon: dataUrl(keySvg(st.track && !st.paused ? "pause" : "play", { size: 72, dim: !!problem })),
    });
  }

  onDialRotate(ev) {
    const action = ev.action;
    const device = deviceOf(action);
    const st = stateFor(device);
    if (problemFor(device) || !st?.track) return press(this, action, async () => { throw new Error("Rien en lecture"); });
    const dur = st.duration || st.track.duration_seconds || 0;
    const from = this.pending.get(action.id) ?? positionFor(device);
    const to = Math.max(0, dur ? Math.min(dur - 1, from + ev.payload.ticks * 5) : from + ev.payload.ticks * 5);
    this.pending.set(action.id, to);
    this.render(action);
    // Un seul envoi quand on arrête de tourner.
    clearTimeout(this.timers.get(action.id));
    this.timers.set(action.id, setTimeout(() => {
      command("seek", device, { position: to }).catch(() => {}).finally(() => {
        setTimeout(() => { this.pending.delete(action.id); this.render(action); }, 1200);
      });
    }, 250));
  }

  onDialDown(ev) {
    return press(this, ev.action, () => command("toggle", deviceOf(ev.action)));
  }

  onTouchTap(ev) {
    return press(this, ev.action, () => command("toggle", deviceOf(ev.action)));
  }
}

const nowPlaying = new NowPlaying();
const dial = new Dial();
const seekDial = new SeekDial();
const all = [...keys, nowPlaying, dial, seekDial];

function renderAll() {
  for (const singleton of all) {
    for (const action of singleton.actions) singleton.render(action).catch(() => {});
  }
}

for (const singleton of all) streamDeck.actions.registerAction(singleton);
streamDeck.logger.info(`Plugin Sona démarré (Node ${process.version}, Stream Deck ${streamDeck.info.application.version})`);
sona.on("state", renderAll);
sona.on("log", (message) => streamDeck.logger.info(message));
sona.on("status", (status) => {
  streamDeck.logger.info(`Sona : ${status}`);
  renderAll();
});
// La molette « Position » avance avec la lecture.
setInterval(() => {
  for (const action of seekDial.actions) seekDial.render(action).catch(() => {});
}, 1000);

// Sans ça, le SDK refuse de démarrer sous Stream Deck 7.1 (plugin mort :
// icônes par défaut et ⚠ à chaque appui). Les réglages des touches sont lus
// à leur apparition et à chaque changement (onDidReceiveSettings).
streamDeck.settings.useLegacySettingsBehavior = true;
streamDeck.connect().catch((e) => streamDeck.logger.error(`Connexion à Stream Deck impossible : ${e.stack || e}`));
sona.start();
