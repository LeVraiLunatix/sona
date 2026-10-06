/* Sona pour Windows : Sona web (dossier web/ du dépôt, livré avec l'app)
   dans une vraie fenêtre d'ordinateur, avec ce que le navigateur ne sait
   pas faire :

   - Sona Connect en appareil « desktop » : l'iPhone voit le PC et le pilote,
     même fenêtre fermée (l'app reste dans la zone de notification) ;
   - la télécommande du téléphone sur le réseau local, à la Cider Remote
     (remote-server.js, QR code dans Sona) ;
   - mini-lecteur toujours au premier plan, boutons lecture/suivant dans
     l'aperçu de la barre des tâches, menu de la zone de notification ;
   - touches multimédia du clavier et panneau multimédia de Windows (via la
     Media Session de la page, gérée par Chromium).

   La page tourne sous app://sona/ : son stockage (session Sona, réglages)
   est propre à l'app et l'API est appelée à l'adresse du serveur. */

const { app, BrowserWindow, protocol, net, ipcMain, Tray, Menu, nativeImage, nativeTheme, shell, Notification, screen, dialog, powerMonitor, session } = require("electron");
const path = require("node:path");
const os = require("node:os");
const { pathToFileURL } = require("node:url");
const settings = require("./settings");
const { RemoteServer } = require("./remote-server");
const { glyph } = require("./glyphs");
const iphone = require("./iphone");
const updater = require("./updater");
const { DiscordPresence } = require("./discord");
const shortcuts = require("./shortcuts");
const { GameMode } = require("./gamemode");

const isWin = process.platform === "win32";
const WEB_ROOT = app.isPackaged ? path.join(process.resourcesPath, "web") : path.resolve(__dirname, "..", "..", "web");
const REMOTE_ROOT = path.resolve(__dirname, "..", "remote");
const ICONS = path.join(WEB_ROOT, "icons");
const APP_URL = "app://sona/index.html";
// Vrai verre dépoli de Windows (acrylique) : Windows 11 22H2 et plus.
const ACRYLIC = isWin && Number(os.release().split(".")[2] || 0) >= 22621;

protocol.registerSchemesAsPrivileged([{
  scheme: "app",
  privileges: { standard: true, secure: true, supportFetchAPI: true, corsEnabled: true, stream: true, codeCache: true },
}]);

if (!app.requestSingleInstanceLock()) app.quit();
if (isWin) app.setAppUserModelId("app.sona.desktop");

let win = null;
let mini = null;
let overlay = null;        // paroles en surimpression
let shortcutsRefused = [];
const discord = new DiscordPresence();
let pausedByLock = false;
const gameMode = new GameMode({ onChange: (active) => {
  if (overlay && !overlay.isDestroyed()) overlay.webContents.send("overlay:mode", { game: active });
  send("desktop:gamemode", active);
  updateTray(true);
} });
let tray = null;
let quitting = false;
let now = null;          // état de lecture envoyé par la page
let trayKey = "";
let thumbKey = "";
const pending = new Map();
let commandSeq = 0;

const remote = new RemoteServer({
  getState: () => liveState(),
  command: (body) => remoteCommand(body),
  onClients: (clients) => send("desktop:remote-clients", clients),
  remoteRoot: REMOTE_ROOT,
  iconsRoot: ICONS,
});

// ── Démarrage ───────────────────────────────────────────────────────────

app.on("second-instance", () => showWindow());

app.whenReady().then(async () => {
  Menu.setApplicationMenu(null);
  serveWeb();
  createWindow();
  createTray();
  if (settings.get("remoteEnabled")) await startRemote();
  discord.configure(settings.get("discordEnabled"), settings.get("discordClientId"));
  applyShortcuts();
  if (settings.get("lyricsOverlay")) setOverlay(true);
  gameMode.setEnabled(settings.get("gameMode"));
  watchPower();
  // Liste complète des sorties audio (casque débranché → pause), pour la page de l'app seulement.
  session.defaultSession.setPermissionCheckHandler((wc, permission, origin) =>
    permission === "media" ? String(origin || wc?.getURL() || "").startsWith("app://sona") : true);
  iphone.init({ onState: (s) => send("desktop:iphone", s), onNotify: notifyDesktop });
  updater.init({ onState: (s) => send("desktop:updates", s), onNotify: notifyDesktop, onBeforeInstall: () => { quitting = true; } });
  nativeTheme.on("updated", () => {
    send("desktop:theme", nativeTheme.shouldUseDarkColors);
    updateTray(true);
    updateThumbar(true);
  });
});

app.on("before-quit", () => { quitting = true; });
app.on("will-quit", () => { remote.stop(); iphone.stop(); discord.close(); gameMode.stop(); shortcuts.apply({}, () => {}); });

/** PC verrouillé ou en veille : pause ; déverrouillé : la musique repart (si c'est nous qui l'avions coupée). */
function watchPower() {
  const pause = () => {
    if (!settings.get("pauseOnLock") || !now?.track || now.paused || now.remoteDevice) return;
    pausedByLock = true;
    pageCommand({ action: "pause" }).catch(() => {});
  };
  const resume = () => {
    if (!pausedByLock) return;
    pausedByLock = false;
    if (settings.get("resumeOnUnlock")) setTimeout(() => pageCommand({ action: "play" }).catch(() => {}), 800);
  };
  powerMonitor.on("lock-screen", pause);
  powerMonitor.on("suspend", pause);
  powerMonitor.on("unlock-screen", resume);
  powerMonitor.on("resume", resume);
}

/** Télécommande : le port obtenu est noté pour le plugin Stream Deck. */
async function startRemote() {
  const ok = await remote.start(settings.get("remotePort"), settings.get("remoteKey"));
  settings.set("remoteActivePort", ok ? remote.port : null);
  return ok;
}

/** Notification Windows ; un clic ramène Sona. */
function notifyDesktop(title, body) {
  // Mode jeu : pas de notification par-dessus le jeu.
  if (!Notification.isSupported() || gameMode.active) return;
  const n = new Notification({ title, body, icon: appIcon(64) });
  n.on("click", showWindow);
  n.show();
}
app.on("window-all-closed", () => { if (process.platform !== "darwin") app.quit(); });

/** Fichiers de Sona web, sous app://sona/ (et rien d'autre du disque). */
function serveWeb() {
  protocol.handle("app", (request) => {
    const url = new URL(request.url);
    const rel = decodeURIComponent(url.pathname).replace(/^\/+/, "") || "index.html";
    const file = path.normalize(path.join(WEB_ROOT, rel));
    if (url.host !== "sona" || !file.startsWith(WEB_ROOT + path.sep)) return new Response("", { status: 404 });
    return net.fetch(pathToFileURL(file).toString());
  });
}

function serverOrigin() {
  const custom = settings.get("serverUrl");
  if (custom) { try { return new URL(custom).origin; } catch {} }
  try {
    const html = require("node:fs").readFileSync(path.join(WEB_ROOT, "index.html"), "utf8");
    const m = html.match(/name="sona-server"\s+content="([^"]+)"/);
    if (m) return new URL(m[1]).origin;
  } catch {}
  return "";
}

/** Nom du PC dans Sona Connect : « DESKTOP-4F2K9QH » ne dit rien à personne. */
function deviceName() {
  const custom = (settings.get("deviceName") || "").trim();
  if (custom) return custom.slice(0, 60);
  const host = os.hostname() || "";
  if (!host || /^(DESKTOP|LAPTOP|PC|WIN)-[A-Z0-9]{5,}$/i.test(host)) return isWin ? "PC Windows" : "Ordinateur";
  return host.length > 40 ? host.slice(0, 40) : host;
}

function appIcon(size) {
  const image = nativeImage.createFromPath(path.join(ICONS, "icon-192.png"));
  return size ? image.resize({ width: size, height: size, quality: "best" }) : image;
}

// ── Fenêtre principale ─────────────────────────────────────────────────

function createWindow() {
  const saved = settings.get("bounds");
  const bounds = saved && visibleOnSomeScreen(saved) ? saved : { width: 1320, height: 860 };
  win = new BrowserWindow({
    ...bounds,
    minWidth: 940,
    minHeight: 620,
    show: false,
    title: "Sona",
    icon: appIcon(),
    // Fenêtre sans barre de titre : la page dessine la sienne (en verre),
    // Windows garde les coins arrondis, l'ombre et le redimensionnement.
    titleBarStyle: process.platform === "darwin" ? "hiddenInset" : "hidden",
    backgroundColor: "#0b0b10",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      sandbox: true,
      spellcheck: false,
      // La musique, Sona Connect et la télécommande continuent fenêtre cachée.
      backgroundThrottling: false,
      autoplayPolicy: "no-user-gesture-required",
    },
  });
  if (settings.get("maximized")) win.maximize();
  win.loadURL(APP_URL);

  const startHidden = process.argv.includes("--hidden");
  win.once("ready-to-show", () => { if (!startHidden) win.show(); updateThumbar(true); });

  // Liens vers l'extérieur : le navigateur par défaut.
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//.test(url)) shell.openExternal(url);
    return { action: "deny" };
  });
  win.webContents.on("will-navigate", (event, url) => {
    if (!url.startsWith("app://sona/")) { event.preventDefault(); if (/^https?:\/\//.test(url)) shell.openExternal(url); }
  });
  win.webContents.on("before-input-event", (event, input) => {
    if (input.type !== "keyDown") return;
    if (input.control && input.shift && input.key.toLowerCase() === "i") win.webContents.toggleDevTools();
    else if (input.key === "F5" || (input.control && input.key.toLowerCase() === "r")) win.webContents.reload();
    else if (input.key === "F11") win.setFullScreen(!win.isFullScreen());
  });
  // La page se recharge : plus de commande en attente de réponse.
  win.webContents.on("did-start-loading", () => { for (const p of pending.values()) p.reject(new Error("Sona redémarre")); pending.clear(); });

  const sendWindowState = () => send("desktop:window", { maximized: win.isMaximized(), fullscreen: win.isFullScreen(), focused: win.isFocused() });
  for (const ev of ["maximize", "unmaximize", "enter-full-screen", "leave-full-screen", "focus", "blur"]) win.on(ev, sendWindowState);
  win.on("show", () => updateThumbar(true));

  let saveTimer;
  const saveBounds = () => {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      if (!win || win.isDestroyed()) return;
      settings.set("maximized", win.isMaximized());
      if (!win.isMaximized() && !win.isMinimized() && !win.isFullScreen()) settings.set("bounds", win.getBounds());
    }, 400);
  };
  win.on("resize", saveBounds);
  win.on("move", saveBounds);

  win.on("close", (event) => {
    if (quitting || !settings.get("closeToTray")) { quitting = true; return; }
    event.preventDefault();
    win.hide();
    if (!settings.get("trayHintShown") && Notification.isSupported()) {
      settings.set("trayHintShown", true);
      new Notification({
        title: "Sona continue en arrière-plan",
        body: "La musique continue. Sona est dans la zone de notification, à côté de l'horloge.",
        icon: appIcon(64),
      }).show();
    }
  });
  win.on("closed", () => { win = null; if (mini) mini.close(); });
}

function visibleOnSomeScreen(b) {
  return screen.getAllDisplays().some(({ workArea: a }) => b.x < a.x + a.width - 80 && b.x + b.width > a.x + 80 && b.y >= a.y - 10 && b.y < a.y + a.height - 80);
}

function showWindow() {
  if (!win) return createWindow();
  if (win.isMinimized()) win.restore();
  win.show();
  win.focus();
}

function send(channel, payload) {
  if (win && !win.isDestroyed()) win.webContents.send(channel, payload);
}

// ── Commandes vers la page (télécommande, mini-lecteur, barre des tâches) ─

/** Demande une action à la page et attend sa réponse (recherche, etc.). */
function pageCommand(body, timeout = 15000) {
  if (!win || win.isDestroyed()) return Promise.reject(new Error("Sona est fermé sur le PC."));
  const id = ++commandSeq;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { pending.delete(id); reject(new Error("Sona ne répond pas.")); }, timeout);
    pending.set(id, {
      resolve: (v) => { clearTimeout(timer); resolve(v); },
      reject: (e) => { clearTimeout(timer); reject(e); },
    });
    win.webContents.send("desktop:command", { ...body, id });
  });
}

const REMOTE_ACTIONS = new Set(["toggle", "play", "pause", "next", "previous", "seek", "volume", "like", "shuffle", "repeat",
  // Touches Stream Deck : playlists, ajout du titre en cours, radio DJ, paroles en surimpression.
  "playlists", "addToPlaylist", "djradio", "lyricsOverlay",
  "playIndex", "removeIndex", "search", "playTrack", "playNext", "addToQueue", "lyrics", "home"]);

async function remoteCommand(body) {
  if (!REMOTE_ACTIONS.has(body.action)) throw new Error("Action inconnue.");
  // Les paroles en surimpression sont une fenêtre de l'app, pas de la page.
  if (body.action === "lyricsOverlay") {
    setOverlay(typeof body.on === "boolean" ? body.on : !overlay);
    return { on: !!overlay };
  }
  const clean = { action: body.action };
  for (const k of ["position", "volume", "index"]) if (Number.isFinite(body[k])) clean[k] = body[k];
  if (typeof body.query === "string") clean.query = body.query.slice(0, 200);
  if (typeof body.playlist === "string" && /^[\w-]{1,64}$/.test(body.playlist)) clean.playlist = body.playlist;
  // Un autre appareil Sona Connect (l'iPhone…) plutôt que ce PC.
  if (typeof body.target === "string" && /^[\w-]{6,64}$/.test(body.target)) clean.target = body.target;
  if (body.track && typeof body.track === "object") clean.track = body.track;
  return pageCommand(clean);
}

ipcMain.on("desktop:reply", (_e, { id, result, error }) => {
  const p = pending.get(id);
  if (!p) return;
  pending.delete(id);
  error ? p.reject(new Error(error)) : p.resolve(result);
});

// ── État de lecture ────────────────────────────────────────────────────

ipcMain.on("desktop:state", (_e, state) => {
  now = state ? { ...state, at: Date.now() } : null;
  const live = liveState();
  remote.broadcast(live);
  if (mini && !mini.isDestroyed()) mini.webContents.send("mini:state", live);
  if (overlay && !overlay.isDestroyed()) overlay.webContents.send("overlay:state", live);
  discord.update(live);
  updateTray();
  updateThumbar();
  if (win) win.setTitle(now?.track ? `${now.track.title} · ${now.track.artist} — Sona` : "Sona");
});

/** L'état, position remise à l'heure (elle avance toute seule pendant la lecture). */
function liveState() {
  if (!now) return { track: null, device: deviceName(), overlay: !!overlay };
  const { at, ...rest } = now;
  let position = rest.position || 0;
  if (!rest.paused) position += (Date.now() - at) / 1000;
  if (rest.duration) position = Math.min(position, rest.duration);
  return { ...rest, position, device: deviceName(), overlay: !!overlay };
}

// ── Zone de notification ───────────────────────────────────────────────

function createTray() {
  const icon = nativeImage.createEmpty();
  for (const scale of [1, 1.5, 2]) {
    const size = Math.round(16 * scale);
    icon.addRepresentation({ scaleFactor: scale, width: size, height: size, buffer: appIcon(size).toPNG() });
  }
  tray = new Tray(icon);
  tray.setToolTip("Sona");
  tray.on("click", () => (win && win.isVisible() && win.isFocused() ? win.hide() : showWindow()));
  updateTray(true);
}

function updateTray(force) {
  if (!tray) return;
  const t = now?.track;
  const light = !nativeTheme.shouldUseDarkColors;
  const key = JSON.stringify([t?.title, t?.artist, now?.paused, now?.remoteDevice, !!mini, !!overlay, gameMode.active, light]);
  if (!force && key === trayKey) return;
  trayKey = key;
  tray.setToolTip(`${t ? `Sona — ${t.title} · ${t.artist}` : "Sona"}${gameMode.active ? " · mode jeu" : ""}`.slice(0, 127));
  const control = (action) => () => pageCommand({ action }).catch(() => {});
  const items = [];
  if (t) {
    items.push({ label: `${t.title}`.slice(0, 60), enabled: false });
    items.push({ label: `${t.artist}${now.remoteDevice ? ` · sur ${now.remoteDevice}` : ""}`.slice(0, 60), enabled: false });
    items.push({ type: "separator" });
    items.push({ label: now.paused ? "Lecture" : "Pause", icon: glyph(now.paused ? "play" : "pause", 16, 1, light), click: control("toggle") });
    items.push({ label: "Suivant", icon: glyph("next", 16, 1, light), click: control("next") });
    items.push({ label: "Précédent", icon: glyph("previous", 16, 1, light), click: control("previous") });
    items.push({ type: "separator" });
  }
  items.push({ label: "Ouvrir Sona", click: showWindow });
  items.push({ label: mini ? "Fermer le mini-lecteur" : "Mini-lecteur", click: toggleMini });
  items.push({ label: "Paroles en surimpression", type: "checkbox", checked: !!overlay, click: () => setOverlay(!overlay) });
  items.push({ label: "Télécommande du téléphone…", click: () => { showWindow(); send("desktop:open-remote"); } });
  items.push({ label: "Sona sur l'iPhone…", click: () => { showWindow(); send("desktop:open", "#/iphone"); } });
  items.push({ label: "Rechercher les mises à jour", click: () => updater.check({ manual: true }).then((m) => {
    if (m.error) notifyDesktop("Mises à jour", m.error);
    else if (!m.available) notifyDesktop("Sona est à jour", `Version ${m.current}.`);
  }) });
  items.push({ type: "separator" });
  items.push({ label: "Quitter Sona", click: () => { quitting = true; app.quit(); } });
  tray.setContextMenu(Menu.buildFromTemplate(items));
}

/** Boutons précédent / lecture / suivant dans l'aperçu de la barre des tâches. */
function updateThumbar(force) {
  if (!isWin || !win || win.isDestroyed()) return;
  const hasTrack = !!now?.track;
  // L'aperçu de la barre des tâches suit le thème de Windows (clair ou sombre).
  const light = !nativeTheme.shouldUseDarkColors;
  const key = `${hasTrack}:${now?.paused}:${light}`;
  if (!force && key === thumbKey) return;
  thumbKey = key;
  const control = (action) => () => pageCommand({ action }).catch(() => {});
  const flags = hasTrack ? [] : ["disabled"];
  win.setThumbarButtons([
    { tooltip: "Précédent", icon: glyph("previous", 16, 2, light), click: control("previous"), flags },
    { tooltip: now?.paused === false ? "Pause" : "Lecture", icon: glyph(now?.paused === false ? "pause" : "play", 16, 2, light), click: control("toggle"), flags },
    { tooltip: "Suivant", icon: glyph("next", 16, 2, light), click: control("next"), flags },
  ]);
}

// ── Mini-lecteur ───────────────────────────────────────────────────────

function toggleMini() {
  if (mini) { mini.close(); return; }
  const work = screen.getPrimaryDisplay().workArea;
  const saved = settings.get("miniBounds");
  const size = { width: 380, height: 116 };
  const pos = saved && visibleOnSomeScreen({ ...saved, ...size }) ? saved : { x: work.x + work.width - size.width - 24, y: work.y + work.height - size.height - 24 };
  mini = new BrowserWindow({
    ...size, x: pos.x, y: pos.y,
    resizable: false, maximizable: false, minimizable: false, fullscreenable: false,
    alwaysOnTop: true, skipTaskbar: true, show: false, title: "Sona — mini-lecteur",
    titleBarStyle: "hidden",
    frame: isWin,
    backgroundMaterial: ACRYLIC ? "acrylic" : undefined,
    backgroundColor: ACRYLIC ? "#00000000" : "#17171d",
    icon: appIcon(),
    webPreferences: { preload: path.join(__dirname, "mini", "preload.js"), contextIsolation: true, sandbox: true, backgroundThrottling: false },
  });
  mini.setAlwaysOnTop(true, "floating");
  mini.loadFile(path.join(__dirname, "mini", "index.html"), { query: { acrylic: ACRYLIC ? "1" : "0" } });
  mini.once("ready-to-show", () => { mini.showInactive(); mini.webContents.send("mini:state", liveState()); });
  mini.on("moved", () => { if (mini) { const [x, y] = mini.getPosition(); settings.set("miniBounds", { x, y }); } });
  mini.on("closed", () => { mini = null; updateTray(true); send("desktop:mini", false); });
  updateTray(true);
  send("desktop:mini", true);
}

ipcMain.on("mini:command", (_e, action) => {
  if (action === "expand") return showWindow();
  if (action === "close") return mini?.close();
  if (["toggle", "next", "previous", "like"].includes(action)) pageCommand({ action }).catch(() => {});
});
ipcMain.on("mini:seek", (_e, position) => { if (Number.isFinite(position)) pageCommand({ action: "seek", position }).catch(() => {}); });

// ── Paroles en surimpression ────────────────────────────────────────────

/** Une fenêtre transparente, au premier plan, qu'on traverse au clic. */
function setOverlay(on) {
  settings.set("lyricsOverlay", !!on);
  if (!on) { overlay?.close(); return; }
  if (overlay) { placeOverlay(); return; }
  overlay = new BrowserWindow({
    width: 900, height: 130, show: false, frame: false, transparent: true, resizable: false, movable: false,
    focusable: false, skipTaskbar: true, hasShadow: false, alwaysOnTop: true, fullscreenable: false,
    title: "Sona — paroles", backgroundColor: "#00000000",
    webPreferences: { preload: path.join(__dirname, "overlay", "preload.js"), contextIsolation: true, sandbox: true, backgroundThrottling: false },
  });
  overlay.setAlwaysOnTop(true, "screen-saver");
  overlay.setIgnoreMouseEvents(true);
  overlay.setVisibleOnAllWorkspaces?.(true);
  placeOverlay();
  overlay.loadFile(path.join(__dirname, "overlay", "index.html"));
  overlay.once("ready-to-show", () => {
    overlay.showInactive();
    overlay.webContents.send("overlay:state", liveState());
    overlay.webContents.send("overlay:mode", { game: gameMode.active });
  });
  overlay.on("closed", () => { overlay = null; updateTray(true); send("desktop:overlay", false); remote.broadcast(liveState()); });
  updateTray(true);
  send("desktop:overlay", true);
  remote.broadcast(liveState());
}

function placeOverlay() {
  if (!overlay) return;
  const work = screen.getPrimaryDisplay().workArea;
  const width = Math.min(1100, Math.round(work.width * 0.8));
  const height = 130;
  const top = settings.get("overlayPosition") === "top";
  overlay.setBounds({
    x: Math.round(work.x + (work.width - width) / 2),
    y: top ? work.y + 24 : work.y + work.height - height - 36,
    width, height,
  });
}

// ── Raccourcis clavier globaux ─────────────────────────────────────────

function applyShortcuts() {
  shortcutsRefused = shortcuts.apply(settings.get("shortcuts"), (action) => {
    if (action === "show") return showWindow();
    if (action === "lyrics") return setOverlay(!overlay);
    if (action === "volumeUp" || action === "volumeDown") {
      const volume = Math.max(0, Math.min(1, (now?.volume ?? 1) + (action === "volumeUp" ? 0.05 : -0.05)));
      return pageCommand({ action: "volume", volume }).catch(() => {});
    }
    pageCommand({ action }).catch(() => {});
  });
  return shortcutsRefused;
}

// ── Pont avec la page ──────────────────────────────────────────────────

ipcMain.on("desktop:info", (event) => {
  event.returnValue = {
    version: app.getVersion(),
    platform: process.platform,
    acrylic: ACRYLIC,
    server: settings.get("serverUrl") || "",
    deviceName: deviceName(),
    dark: nativeTheme.shouldUseDarkColors,
  };
});

ipcMain.on("desktop:window", (_e, action) => {
  if (!win) return;
  if (action === "minimize") win.minimize();
  else if (action === "maximize") (win.isMaximized() ? win.unmaximize() : win.maximize());
  else if (action === "close") win.close();
});

ipcMain.handle("desktop:settings", () => {
  const s = settings.load();
  return {
    closeToTray: s.closeToTray, launchAtLogin: s.launchAtLogin, remoteEnabled: s.remoteEnabled,
    remotePort: s.remotePort, serverUrl: s.serverUrl, deviceName: s.deviceName, deviceNameShown: deviceName(),
    mini: !!mini, version: app.getVersion(),
    lyricsOverlay: !!overlay, overlayPosition: s.overlayPosition,
    discordEnabled: s.discordEnabled, discordClientId: s.discordClientId, discord: discord.status(),
    shortcuts: s.shortcuts || {}, shortcutActions: shortcuts.ACTIONS, shortcutsRefused,
    pauseOnLock: s.pauseOnLock, resumeOnUnlock: s.resumeOnUnlock, pauseOnHeadphones: s.pauseOnHeadphones,
    gameMode: s.gameMode, gameActive: gameMode.active,
  };
});

ipcMain.handle("desktop:set", async (_e, key, value) => {
  switch (key) {
    case "closeToTray": settings.set(key, !!value); break;
    case "launchAtLogin":
      settings.set(key, !!value);
      // Version portable : l'exécutable lancé est une copie temporaire,
      // c'est l'original qui doit démarrer avec Windows.
      if (isWin || process.platform === "darwin") {
        app.setLoginItemSettings({ openAtLogin: !!value, path: process.env.PORTABLE_EXECUTABLE_FILE || process.execPath, args: ["--hidden"] });
      }
      break;
    case "deviceName": settings.set(key, String(value || "").trim().slice(0, 60)); break;
    case "serverUrl": {
      const url = String(value || "").trim();
      if (url && !/^https?:\/\/[^/\s]+/.test(url)) throw new Error("Adresse invalide (https://…)");
      settings.set(key, url.replace(/\/+$/, ""));
      setImmediate(() => win?.webContents.reload());
      break;
    }
    case "remoteEnabled":
      settings.set(key, !!value);
      if (value) await startRemote();
      else await remote.stop();
      break;
    case "remoteKey":
      settings.set("remoteKey", settings.newKey());
      remote.setKey(settings.get("remoteKey"));
      break;
    case "mini": if (!!value !== !!mini) toggleMini(); break;
    case "lyricsOverlay": setOverlay(!!value); break;
    case "pauseOnLock":
    case "resumeOnUnlock":
    case "pauseOnHeadphones":
      settings.set(key, !!value);
      break;
    case "gameMode":
      settings.set(key, !!value);
      gameMode.setEnabled(!!value);
      break;
    case "overlayPosition":
      settings.set(key, value === "top" ? "top" : "bottom");
      placeOverlay();
      break;
    case "discordEnabled":
    case "discordClientId":
      settings.set(key, key === "discordEnabled" ? !!value : String(value || "").trim().slice(0, 30));
      discord.configure(settings.get("discordEnabled"), settings.get("discordClientId"));
      if (now) discord.update(liveState());
      break;
    case "shortcuts": {
      const map = {};
      for (const [action, accelerator] of Object.entries(value || {})) {
        if (shortcuts.ACTIONS[action] && shortcuts.valid(accelerator)) map[action] = accelerator;
      }
      settings.set(key, map);
      return applyShortcuts();
    }
    default: throw new Error("Réglage inconnu");
  }
  return true;
});

ipcMain.handle("desktop:remote-info", () => remote.info());

/** Page « État » : ce que l'app sait d'elle-même (télécommande, Stream Deck, Discord…). */
ipcMain.handle("desktop:status", () => {
  const clients = [...remote.clients].map((c) => ({ name: c.name, since: c.since }));
  const iph = iphone.snapshot();
  return {
    version: app.getVersion(),
    remote: { enabled: settings.get("remoteEnabled"), running: remote.running, port: remote.port, error: remote.error, clients },
    streamDeck: clients.find((c) => c.name === "Stream Deck") || null,
    discord: { ...discord.status(), configured: !!settings.get("discordClientId"), wanted: !!settings.get("discordEnabled") },
    shortcuts: { count: Object.keys(settings.get("shortcuts") || {}).length, refused: shortcutsRefused },
    overlay: !!overlay,
    gameMode: { enabled: !!settings.get("gameMode"), active: gameMode.active, supported: isWin },
    iphone: { available: iph.available !== false, devices: (iph.devices || []).length, apps: (iph.apps || []).length },
    updates: updater.snapshot(),
  };
});

// ── Onglet iPhone et mises à jour ─────────────────────────────────────

ipcMain.handle("desktop:iphone", (_e, name, args) => iphone.action(String(name), args || {}));
ipcMain.handle("desktop:iphone-state", () => iphone.snapshot());
ipcMain.handle("desktop:iphone-pick", async () => {
  const picked = await dialog.showOpenDialog(win, { title: "Choisir l'app pour l'iPhone", filters: [{ name: "App iPhone", extensions: ["ipa"] }], properties: ["openFile"] });
  return picked.canceled ? null : picked.filePaths[0];
});
ipcMain.handle("desktop:iphone-logs", async () => {
  const file = await iphone.action("logs");
  if (file) shell.showItemInFolder(file);
  return !!file;
});
ipcMain.handle("desktop:updates", async (_e, action, value) => {
  if (action === "check") await updater.check({ manual: true });
  else if (action === "install") await updater.install();
  else if (action === "updatesCheck" || action === "updatesInstall") updater.setOption(action, value);
  return updater.snapshot();
});

ipcMain.on("desktop:external", (_e, url) => { if (/^https?:\/\//.test(String(url))) shell.openExternal(url); });

/** Connexion Last.fm : la page d'autorisation dans une petite fenêtre ; son
    retour vers le serveur Sona (?handoff=1) signale que c'est autorisé. */
ipcMain.on("desktop:auth", (_e, url) => {
  if (!/^https:\/\/(www\.)?last\.fm\//.test(String(url))) return;
  const origin = serverOrigin();
  const auth = new BrowserWindow({
    parent: win || undefined, width: 520, height: 760, title: "Connexion à Last.fm", icon: appIcon(),
    autoHideMenuBar: true, backgroundColor: "#ffffff",
    webPreferences: { contextIsolation: true, sandbox: true, partition: "persist:lastfm" },
  });
  let finished = false;
  const check = (target) => {
    if (finished || !origin || !String(target).startsWith(origin)) return;
    finished = true;
    send("desktop:auth-done", { authorized: true });
    setImmediate(() => auth.close());
  };
  auth.webContents.on("will-redirect", (_ev, u) => check(u));
  auth.webContents.on("will-navigate", (_ev, u) => check(u));
  auth.webContents.on("did-navigate", (_ev, u) => check(u));
  auth.webContents.setWindowOpenHandler(({ url: u }) => { shell.openExternal(u); return { action: "deny" }; });
  auth.on("closed", () => { if (!finished) send("desktop:auth-done", { authorized: false }); });
  auth.loadURL(url);
});
