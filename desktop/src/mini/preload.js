/* Mini-lecteur : il reçoit l'état de lecture et renvoie ses boutons à la
   fenêtre principale (c'est elle qui joue la musique). */

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("sonaMini", {
  onState: (callback) => ipcRenderer.on("mini:state", (_e, state) => callback(state)),
  command: (action) => ipcRenderer.send("mini:command", action),
  seek: (position) => ipcRenderer.send("mini:seek", position),
});
