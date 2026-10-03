/* Plugin Stream Deck de Sona : pilote Sona pour Windows depuis les touches
   (et la molette du Stream Deck +). Chaque touche suit l'état en direct :
   pochette du titre en cours, lecture/pause, j'aime, aléatoire, répéter. */

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
  else {
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

/** Les touches, chacune avec son dessin selon l'état de Sona. */
class SonaKey extends SingletonAction {
  constructor(id, { glyph, on, run }) {
    super();
    this.manifestId = `${UUID}.${id}`;
    this.glyph = glyph;
    this.on = on || (() => false);
    this.run = run;
  }

  async render(action) {
    if (!action.isKey()) return;
    const online = sona.status === "online";
    const st = sona.state || {};
    const glyph = typeof this.glyph === "function" ? this.glyph(st) : this.glyph;
    await action.setImage(dataUrl(keySvg(glyph, { on: online && this.on(st), dim: !online || (!st.track && this.needsTrack) })));
    if (!flashes.has(action.id)) await action.setTitle(online ? "" : OFFLINE_TITLE[sona.status] || "");
  }

  onWillAppear(ev) {
    return this.render(ev.action);
  }

  onKeyDown(ev) {
    return press(this, ev.action, () => this.run(sona.state || {}));
  }
}

const command = (action, extra) => sona.command(action, extra);
const setVolume = (v) => {
  const volume = Math.round(Math.max(0, Math.min(1, v)) * 100) / 100;
  if (sona.state) sona.state.volume = volume;
  return command("volume", { volume });
};

const keys = [
  new SonaKey("playpause", { glyph: (st) => (st.track && !st.paused ? "pause" : "play"), run: () => command("toggle") }),
  new SonaKey("next", { glyph: "next", run: () => command("next") }),
  new SonaKey("previous", { glyph: "previous", run: () => command("previous") }),
  new SonaKey("like", { glyph: (st) => (st.liked ? "heartFill" : "heart"), on: (st) => !!st.liked, run: () => command("like") }),
  new SonaKey("shuffle", { glyph: "shuffle", on: (st) => !!st.shuffle, run: () => command("shuffle") }),
  new SonaKey("repeat", { glyph: "repeat", on: (st) => !!st.repeat, run: () => command("repeat") }),
  new SonaKey("volumeup", { glyph: "volumeUp", run: (st) => setVolume((st.volume ?? 1) + 0.1) }),
  new SonaKey("volumedown", { glyph: "volumeDown", run: (st) => setVolume((st.volume ?? 1) - 0.1) }),
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
class NowPlaying extends SingletonAction {
  manifestId = `${UUID}.nowplaying`;
  last = "";

  async render(action, force = false) {
    if (!action.isKey()) return;
    const st = sona.state || {};
    const online = sona.status === "online";
    const t = online ? st.track : null;
    const key = JSON.stringify([online, t?.source, t?.source_id, st.paused, sona.status]);
    if (!force && key === this.last) return;
    this.last = key;
    const image = t ? await cover(t.cover_url) : null;
    await action.setImage(dataUrl(coverSvg({ image, paused: !t || st.paused, title: t?.title, artist: t?.artist })));
    if (!flashes.has(action.id)) await action.setTitle(online ? "" : OFFLINE_TITLE[sona.status] || "");
  }

  onWillAppear(ev) {
    return this.render(ev.action, true);
  }

  onKeyDown(ev) {
    return press(this, ev.action, () => command("toggle"));
  }
}

/** Molette (Stream Deck +) : tourner = volume, appuyer = lecture/pause, toucher = suivant. */
class Dial extends SingletonAction {
  manifestId = `${UUID}.dial`;
  pending = 0;
  timer = null;

  async render(action) {
    if (!action.isDial() || flashes.has(action.id)) return;
    const st = sona.state || {};
    const online = sona.status === "online";
    const volume = Math.round((st.volume ?? 1) * 100);
    await action.setFeedback({
      title: online ? (st.track?.title || "Sona") : (OFFLINE_TITLE[sona.status] || "Sona").replace(/\n/g, " "),
      value: online ? `${volume} %` : "",
      indicator: { value: online ? volume : 0 },
      icon: dataUrl(keySvg(st.track && !st.paused ? "speaker" : "pause", { size: 72, dim: !online })),
    });
  }

  onWillAppear(ev) {
    return this.render(ev.action);
  }

  onDialRotate(ev) {
    if (sona.status !== "online") return press(this, ev.action, async () => {});
    // Les crans s'accumulent : un envoi toutes les 80 ms au plus.
    this.pending += ev.payload.ticks;
    if (sona.state) sona.state.volume = Math.max(0, Math.min(1, (sona.state.volume ?? 1) + ev.payload.ticks * 0.02));
    this.render(ev.action);
    clearTimeout(this.timer);
    this.timer = setTimeout(() => { this.pending = 0; setVolume(sona.state?.volume ?? 1).catch(() => {}); }, 80);
  }

  onDialDown(ev) {
    return press(this, ev.action, () => command("toggle"));
  }

  onTouchTap(ev) {
    return press(this, ev.action, () => command("next"));
  }
}

const nowPlaying = new NowPlaying();
const dial = new Dial();
const all = [...keys, nowPlaying, dial];

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

// Sans ça, le SDK refuse de démarrer sous Stream Deck 7.1 (plugin mort :
// icônes par défaut et ⚠ à chaque appui). Les touches n'ont pas de réglages.
streamDeck.settings.useLegacySettingsBehavior = true;
streamDeck.connect().catch((e) => streamDeck.logger.error(`Connexion à Stream Deck impossible : ${e.stack || e}`));
sona.start();
