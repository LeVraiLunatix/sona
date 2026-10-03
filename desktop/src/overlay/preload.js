/* Paroles en surimpression : la fenêtre reçoit l'état de lecture (paroles
   synchronisées, position) ; elle ne renvoie rien (on clique au travers). */

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("sonaOverlay", {
  onState: (callback) => ipcRenderer.on("overlay:state", (_e, state) => callback(state)),
  onMode: (callback) => ipcRenderer.on("overlay:mode", (_e, mode) => callback(mode)),
});
