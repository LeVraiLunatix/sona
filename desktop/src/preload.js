/* Pont entre Sona web et l'app d'ordinateur : `window.sonaDesktop`.
   Seulement pour la page de l'app (app://sona/) — jamais pour une page
   d'Internet qui s'ouvrirait dans la fenêtre. */

const { contextBridge, ipcRenderer } = require("electron");

if (location.protocol === "app:" && location.host === "sona") {
  const info = ipcRenderer.sendSync("desktop:info");
  const on = (channel) => (callback) => {
    const listener = (_e, payload) => callback(payload);
    ipcRenderer.on(channel, listener);
    return () => ipcRenderer.removeListener(channel, listener);
  };

  contextBridge.exposeInMainWorld("sonaDesktop", {
    ...info,
    /** État de lecture (zone de notification, barre des tâches, mini-lecteur, télécommande). */
    report: (state) => ipcRenderer.send("desktop:state", state),
    reply: (id, result, error) => ipcRenderer.send("desktop:reply", { id, result, error }),
    onCommand: on("desktop:command"),
    onAuthDone: on("desktop:auth-done"),
    onRemoteClients: on("desktop:remote-clients"),
    onOpenRemote: on("desktop:open-remote"),
    onWindow: on("desktop:window"),
    onMini: on("desktop:mini"),
    onOverlay: on("desktop:overlay"),
    onTheme: on("desktop:theme"),
    window: {
      minimize: () => ipcRenderer.send("desktop:window", "minimize"),
      maximize: () => ipcRenderer.send("desktop:window", "maximize"),
      close: () => ipcRenderer.send("desktop:window", "close"),
    },
    settings: () => ipcRenderer.invoke("desktop:settings"),
    set: (key, value) => ipcRenderer.invoke("desktop:set", key, value),
    remoteInfo: () => ipcRenderer.invoke("desktop:remote-info"),
    openAuth: (url) => ipcRenderer.send("desktop:auth", url),
    /** Onglet iPhone (installer Sona sur l'iPhone, comme CordLauncher). */
    iphone: (name, args) => ipcRenderer.invoke("desktop:iphone", name, args),
    iphoneState: () => ipcRenderer.invoke("desktop:iphone-state"),
    iphonePick: () => ipcRenderer.invoke("desktop:iphone-pick"),
    iphoneLogs: () => ipcRenderer.invoke("desktop:iphone-logs"),
    onIphone: on("desktop:iphone"),
    /** Mises à jour de l'app Windows. */
    updates: (action, value) => ipcRenderer.invoke("desktop:updates", action, value),
    onUpdates: on("desktop:updates"),
    onOpen: on("desktop:open"),
    openExternal: (url) => ipcRenderer.send("desktop:external", url),
  });
}
