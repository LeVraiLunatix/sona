/* Onglet iPhone : installer Sona sur l'iPhone depuis le PC, comme CordLauncher.

   Le travail (compte Apple, signature, envoi par câble ou Wi-Fi) est fait par
   `sona-iphone`, le cœur iPhone de CordLauncher en Rust (dossier iphone/),
   piloté ici en JSON (une ligne par message). Ce module tient l'état montré
   dans l'onglet et fait tourner le mode automatique, même fenêtre fermée :

   - nouvelle version de Sona iOS (source SideStore du dépôt) → installée ;
   - signature qui expire dans 2 jours ou moins → renouvelée avec l'IPA gardée ;
   - iPhone absent la veille de l'expiration → notification de rappel. */

const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const { app, net, Notification } = require("electron");
const settings = require("./settings");

const SOURCE_URL = "https://github.com/LeVraiLunatix/sona/releases/latest/download/source.json";
const BUNDLE_ID = "com.sona.encre";
const APP_ID = "sona";
const DAY = 86_400_000;
const AUTO_EVERY = 30 * 60_000;

const model = {
  available: true,      // le programme d'aide est présent
  status: { active: null, profiles: [], busy: false },
  devices: [],
  devicesError: null,
  apps: [],
  latest: null,         // { version, url, size, notes, date }
  lastCheck: null,
  checking: false,
  scanning: false,
  busy: null,           // ce qui est en cours (« Installation de Sona… »)
  progress: null,       // { phase, progress }
  twoFactor: null,
  error: null,
  auto: true,
};

let push = () => {};
let notify = () => {};
let helper = null;
let seq = 0;
const pending = new Map();

function helperPath() {
  const exe = process.platform === "win32" ? "sona-iphone.exe" : "sona-iphone";
  const candidates = app.isPackaged
    ? [path.join(process.resourcesPath, exe)]
    : [path.join(__dirname, "..", "iphone", "target", "release", exe), path.join(__dirname, "..", "iphone", "target", "debug", exe)];
  return candidates.find((p) => fs.existsSync(p)) || null;
}

function update(values) {
  Object.assign(model, values);
  push(snapshot());
}

function snapshot() {
  return { ...model, now: Date.now() };
}

// ── Programme d'aide ───────────────────────────────────────────────────

function start() {
  if (helper) return helper;
  const exe = helperPath();
  if (!exe) { model.available = false; return null; }
  const dir = path.join(app.getPath("userData"), "iphone");
  fs.mkdirSync(dir, { recursive: true });
  helper = spawn(exe, [], { env: { ...process.env, SONA_IPHONE_DIR: dir }, windowsHide: true, stdio: ["pipe", "pipe", "pipe"] });
  let buffer = "";
  helper.stdout.setEncoding("utf8");
  helper.stdout.on("data", (chunk) => {
    buffer += chunk;
    let i;
    while ((i = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, i).trim();
      buffer = buffer.slice(i + 1);
      if (line) onMessage(line);
    }
  });
  helper.stderr.on("data", () => {});
  helper.on("exit", () => {
    helper = null;
    for (const p of pending.values()) p.reject(new Error("Le module iPhone s'est arrêté. Réessaie."));
    pending.clear();
    update({ busy: null, progress: null, twoFactor: null });
  });
  helper.on("error", () => { helper = null; model.available = false; });
  return helper;
}

function onMessage(line) {
  let msg;
  try { msg = JSON.parse(line); } catch { return; }
  if (msg.event) return onEvent(msg);
  const p = pending.get(msg.id);
  if (!p) return;
  pending.delete(msg.id);
  msg.ok ? p.resolve(msg.result) : p.reject(new Error(msg.error || "Erreur"));
}

function onEvent(e) {
  if (e.event === "2fa") update({ twoFactor: { ...e, receivedAt: Date.now() } });
  else if (e.event === "signed-in") update({ twoFactor: null });
  else if (e.event === "progress") update({ progress: { phase: e.phase, progress: e.progress } });
}

function call(cmd, args = {}) {
  const h = start();
  if (!h) return Promise.reject(new Error("Le module iPhone n'est pas inclus dans cette version de Sona."));
  const id = ++seq;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    h.stdin.write(`${JSON.stringify({ id, cmd, ...args })}\n`);
  });
}

// ── Lecture de l'état ──────────────────────────────────────────────────

const activeProfile = () => model.status.profiles.find((p) => p.active) || null;
/** Le compte actif peut installer sans rien redemander. */
const canInstall = () => { const p = activeProfile(); return !!p && (p.connected || p.remembered) && !p.pausedFor; };
const daysLeft = (a, now = Date.now()) => (a.expiresAt == null ? null : (a.expiresAt - now) / DAY);

/** Compare deux numéros de version (1.0.9 < 1.0.10) ; > 0 si a est plus récente. */
function compareVersions(a, b) {
  const pa = String(a).split(/[.\-+ ]/).map((x) => parseInt(x, 10) || 0);
  const pb = String(b).split(/[.\-+ ]/).map((x) => parseInt(x, 10) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const d = (pa[i] || 0) - (pb[i] || 0);
    if (d) return d;
  }
  return 0;
}

async function refresh({ devices = true } = {}) {
  if (!model.available) return;
  const jobs = [
    call("status").then((status) => (model.status = status)),
    call("apps").then((apps) => (model.apps = apps.filter((a) => a.id === APP_ID))),
  ];
  if (devices && !model.scanning) {
    model.scanning = true;
    push(snapshot());
    jobs.push(call("devices")
      .then((list) => { model.devices = list; model.devicesError = null; })
      .catch((e) => { model.devices = []; model.devicesError = e.message; })
      .finally(() => { model.scanning = false; }));
  }
  await Promise.allSettled(jobs);
  push(snapshot());
}

/** Dernière version iOS publiée : la source SideStore du dépôt fait foi. */
async function checkLatest() {
  update({ checking: true });
  try {
    const res = await net.fetch(SOURCE_URL, { cache: "no-store" });
    if (!res.ok) throw new Error(`code ${res.status}`);
    const source = await res.json();
    const entry = source.apps?.find((a) => a.bundleIdentifier === BUNDLE_ID) || source.apps?.[0];
    const v = entry?.versions?.[0] || (entry?.version ? { version: entry.version, downloadURL: entry.downloadURL, size: entry.size } : null);
    model.latest = v?.downloadURL ? { version: v.version, url: v.downloadURL, size: v.size || null, notes: v.localizedDescription || null, date: v.date || null } : null;
    model.lastCheck = Date.now();
    return model.latest;
  } catch {
    return null;
  } finally {
    update({ checking: false });
  }
}

/** Une mise à jour existe pour cette installation. */
const updateFor = (a) => (model.latest && a.version && compareVersions(model.latest.version, a.version) > 0 ? model.latest : null);

// ── Actions ────────────────────────────────────────────────────────────

/** Opération longue (installation) : une seule à la fois, progression suivie. */
async function operation(label, fn) {
  if (model.busy) throw new Error("Une opération iPhone est déjà en cours.");
  update({ busy: label, error: null, progress: null });
  try {
    return await fn();
  } catch (e) {
    update({ error: e.message });
    throw e;
  } finally {
    update({ busy: null, progress: null, twoFactor: null });
    refresh({ devices: false }).catch(() => {});
  }
}

const deviceName = (udid) => model.devices.find((d) => d.udid === udid)?.name || model.apps.find((a) => a.udid === udid)?.deviceName || null;

async function install(udid, source) {
  return operation("Installation de Sona…", () => call("sideload", { app: APP_ID, name: "Sona", udid, deviceName: deviceName(udid), ...source }));
}

const actions = {
  refresh: () => refresh(),
  async check() { await checkLatest(); await refresh(); return snapshot(); },
  async login({ email, password, remember }) {
    return operation("Connexion au compte Apple…", async () => { model.status = await call("login", { email, password, remember: !!remember }); });
  },
  twoFactor: ({ response }) => call("two_factor", { response }),
  async switch({ email }) { model.status = await call("switch", { email }); push(snapshot()); },
  async forget({ email }) { model.status = await call("forget", { email }); push(snapshot()); },
  async resetDevice() { await call("reset_device"); await refresh({ devices: false }); },
  async setWifi({ udid, enabled }) { await call("set_wifi", { udid, enabled: !!enabled }); await refresh(); },
  /** Première installation (ou réinstallation) : la dernière version publiée. */
  async install({ udid }) {
    const latest = model.latest || (await checkLatest());
    if (!latest) throw new Error("Impossible de trouver la dernière version de Sona pour iPhone. Vérifie ta connexion Internet.");
    await install(udid, { ipaUrl: latest.url });
    toast(`Sona ${latest.version} est sur l'iPhone`, "Première fois ? Sur l'iPhone : Réglages › Général › VPN et gestion de l'appareil › fais confiance à ton compte Apple.");
  },
  /** Fichier .ipa choisi à la main. */
  async installFile({ udid, file }) {
    if (!file || !/\.ipa$/i.test(file)) throw new Error("Choisis un fichier .ipa.");
    await install(udid, { ipaPath: file });
  },
  async renew({ udid }) {
    const a = model.apps.find((x) => x.udid === udid);
    if (!a?.ipa) throw new Error("Le fichier de Sona n'a pas été gardé sur ce PC : réinstalle-la.");
    await install(udid, { ipaPath: a.ipa });
    toast("Sona renouvelée", "7 jours de plus sur l'iPhone.");
  },
  async update({ udid }) {
    const latest = model.latest || (await checkLatest());
    if (!latest) throw new Error("Aucune mise à jour trouvée.");
    await install(udid, { ipaUrl: latest.url });
    toast(`Sona ${latest.version} installée`, "L'iPhone est à jour.");
  },
  async forgetApp({ udid }) { await call("app_forget", { app: APP_ID, udid }); await refresh({ devices: false }); },
  setAuto({ auto }) { settings.set("iphoneAuto", !!auto); update({ auto: !!auto }); if (auto) autoPass().catch(() => {}); },
  logs() {
    const file = path.join(app.getPath("userData"), "iphone", "logs", "iphone.log");
    return fs.existsSync(file) ? file : null;
  },
};

function toast(title, body) {
  notify(title, body);
}

// ── Mode automatique ───────────────────────────────────────────────────

let autoBusy = false;
const autoInstalled = new Set();

/**
 * Une passe : pour chaque iPhone suivi, branché (ou en Wi-Fi) et autorisé,
 * installe la nouvelle version si elle existe, sinon renouvelle quand il reste
 * 2 jours ou moins. Rien sans compte Apple prêt, ni pendant une autre opération.
 * Ce qui n'a pas pu être fait : notification la veille de l'expiration.
 */
async function autoPass({ check = true } = {}) {
  if (!model.available || autoBusy) return;
  autoBusy = true;
  try {
    await refresh();
    if (!model.apps.length) return;
    if (check) await checkLatest();
    announceUpdates();
    if (model.auto && !model.busy && canInstall()) {
      const reachable = new Set(model.devices.filter((d) => d.trusted).map((d) => d.udid));
      for (const a of [...model.apps].sort((x, y) => (x.expiresAt || 0) - (y.expiresAt || 0))) {
        if (!reachable.has(a.udid)) continue;
        const upd = updateFor(a);
        const key = upd && `${a.udid}:${upd.version}`;
        const due = (daysLeft(a) ?? 99) <= 2;
        if (upd && !autoInstalled.has(key)) {
          autoInstalled.add(key);
          const ok = await install(a.udid, { ipaUrl: upd.url }).then(() => true, () => false);
          if (ok) toast(`Sona ${upd.version} installée sur l'iPhone`, a.deviceName ? `Sur ${a.deviceName}, automatiquement.` : "Automatiquement.");
          else break;
        } else if (due && a.ipa) {
          const ok = await install(a.udid, { ipaPath: a.ipa }).then(() => true, () => false);
          if (ok) toast("Sona renouvelée sur l'iPhone", "7 jours de plus, automatiquement.");
          else break; // Apple a refusé ou l'iPhone est parti : on réessaiera plus tard.
        }
      }
    }
    remindExpiring();
  } finally {
    autoBusy = false;
  }
}

/** Nouvelle version iOS, une fois par version (si elle n'est pas installée toute seule). */
function announceUpdates() {
  const upd = model.apps.map(updateFor).find(Boolean);
  if (!upd || settings.get("iphoneAnnounced") === upd.version) return;
  settings.set("iphoneAnnounced", upd.version);
  if (!(model.auto && canInstall())) toast(`Sona ${upd.version} pour iPhone est disponible`, "Ouvre l'onglet iPhone de Sona pour l'installer.");
}

/** Expire dans moins de 24 h sans avoir pu être renouvelée : un rappel par échéance. */
function remindExpiring() {
  const now = Date.now();
  const reminded = settings.get("iphoneReminded") || [];
  const reachable = new Set(model.devices.filter((d) => d.trusted).map((d) => d.udid));
  const sent = [];
  for (const a of model.apps) {
    if (a.expiresAt == null || a.expiresAt <= now || a.expiresAt - now > DAY) continue;
    const key = `${a.udid}:${a.expiresAt}`;
    if (reminded.includes(key)) continue;
    const hours = Math.max(1, Math.round((a.expiresAt - now) / 3_600_000));
    const where = a.deviceName || "ton iPhone";
    toast(`Sona expire dans ${hours} h sur ${where}`, reachable.has(a.udid)
      ? "Ouvre l'onglet iPhone de Sona pour la renouveler."
      : `Branche ${where} (ou mets-le sur le même Wi-Fi que ce PC) pour que Sona la renouvelle.`);
    sent.push(key);
  }
  if (sent.length) settings.set("iphoneReminded", [...reminded, ...sent].slice(-30));
}

function init({ onState, onNotify }) {
  push = onState;
  notify = onNotify;
  model.auto = settings.get("iphoneAuto") !== false;
  model.available = !!helperPath();
  if (!model.available) return;
  setTimeout(() => autoPass().catch(() => {}), 60_000);
  setInterval(() => autoPass().catch(() => {}), AUTO_EVERY);
}

async function action(name, args = {}) {
  const fn = actions[name];
  if (!fn) throw new Error("Action inconnue");
  return fn(args);
}

function stop() {
  if (helper) helper.stdin.end();
}

module.exports = { init, action, snapshot, stop, compareVersions, autoPass };
