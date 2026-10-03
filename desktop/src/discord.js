/* Discord Rich Presence : « Écoute Sona » sur le profil Discord, avec le
   titre, l'artiste, la pochette et la progression.

   Parle directement au client Discord du PC, par son canal local (tube
   nommé `discord-ipc-N` sous Windows, socket ailleurs) : pas de dépendance,
   pas de réseau. Discord exige l'identifiant d'une « application » (créée
   en une minute sur discord.com/developers) : son nom est celui affiché
   (« Écoute Sona »). */

const net = require("node:net");
const crypto = require("node:crypto");
const path = require("node:path");

const OP = { HANDSHAKE: 0, FRAME: 1, CLOSE: 2, PING: 3, PONG: 4 };

function pipePath(i) {
  if (process.platform === "win32") return `\\\\?\\pipe\\discord-ipc-${i}`;
  const dir = process.env.XDG_RUNTIME_DIR || process.env.TMPDIR || process.env.TMP || "/tmp";
  return path.join(dir, `discord-ipc-${i}`);
}

function encode(op, data) {
  const json = Buffer.from(JSON.stringify(data));
  const frame = Buffer.alloc(8 + json.length);
  frame.writeInt32LE(op, 0);
  frame.writeInt32LE(json.length, 4);
  json.copy(frame, 8);
  return frame;
}

/** Activité Discord pour un état de lecture (null : rien à montrer). */
function activityFor(state, now = Date.now()) {
  const t = state?.track;
  if (!t) return null;
  const cover = /^https:\/\//.test(t.cover_url || "") ? t.cover_url : null;
  const activity = {
    type: 2, // « Écoute »
    details: String(t.title || "").slice(0, 128) || "Sona",
    state: `${String(t.artist || "").slice(0, 100)}${state.paused ? " · en pause" : ""}`.slice(0, 128) || undefined,
    assets: {
      large_image: cover || "sona",
      large_text: String(t.album || t.title || "Sona").slice(0, 128),
    },
    instance: false,
  };
  const duration = state.duration || t.duration_seconds || 0;
  if (!state.paused && duration) {
    const start = Math.round(now - (state.position || 0) * 1000);
    activity.timestamps = { start, end: start + Math.round(duration * 1000) };
  }
  return activity;
}

class DiscordPresence {
  constructor({ connectTo = pipePath, retry = 15000 } = {}) {
    this.connectTo = connectTo;
    this.retry = retry;
    this.clientId = "";
    this.enabled = false;
    this.socket = null;
    this.ready = false;
    this.error = null;
    this.activity = null;
    this.sentKey = null;
    this.buffer = Buffer.alloc(0);
  }

  /** Activé avec un identifiant d'application : se connecte (et se reconnecte) à Discord. */
  configure(enabled, clientId) {
    const id = String(clientId || "").trim();
    const changed = id !== this.clientId || !!enabled !== this.enabled;
    this.enabled = !!enabled && /^\d{15,25}$/.test(id);
    this.clientId = id;
    this.error = enabled && !this.enabled ? "Identifiant d'application Discord manquant ou invalide." : null;
    if (!changed) return;
    this.close();
    if (this.enabled) this.connect(0);
  }

  status() {
    return { enabled: this.enabled, connected: this.ready, error: this.error };
  }

  connect(i) {
    clearTimeout(this.timer);
    if (!this.enabled) return;
    const socket = net.createConnection(this.connectTo(i));
    this.socket = socket;
    this.buffer = Buffer.alloc(0);
    socket.on("connect", () => socket.write(encode(OP.HANDSHAKE, { v: 1, client_id: this.clientId })));
    socket.on("data", (chunk) => this.onData(chunk));
    socket.on("error", () => {});
    socket.on("close", () => {
      if (this.socket !== socket) return;
      const wasReady = this.ready;
      this.ready = false;
      this.socket = null;
      this.sentKey = null;
      // Discord fermé : on essaie les autres canaux, puis on réessaie plus tard.
      if (!wasReady && i < 9) return this.connect(i + 1);
      if (!this.error) this.error = "Discord n'est pas ouvert sur ce PC.";
      if (this.enabled) this.timer = setTimeout(() => this.connect(0), this.retry);
    });
  }

  onData(chunk) {
    this.buffer = Buffer.concat([this.buffer, chunk]);
    while (this.buffer.length >= 8) {
      const op = this.buffer.readInt32LE(0);
      const len = this.buffer.readInt32LE(4);
      if (this.buffer.length < 8 + len) return;
      let msg = null;
      try { msg = JSON.parse(this.buffer.subarray(8, 8 + len).toString("utf8")); } catch {}
      this.buffer = this.buffer.subarray(8 + len);
      if (op === OP.PING) this.socket?.write(encode(OP.PONG, msg));
      else if (op === OP.CLOSE) {
        this.error = msg?.message ? `Discord refuse : ${msg.message}` : "Discord a fermé la connexion.";
        this.socket?.destroy();
      } else if (msg?.evt === "READY") {
        this.ready = true;
        this.error = null;
        // Rien en lecture : rien à effacer non plus.
        if (this.activity) this.push(true);
      } else if (msg?.evt === "ERROR") {
        this.error = `Discord : ${msg.data?.message || "erreur"}`;
      }
    }
  }

  /** Nouvel état de lecture : envoyé à Discord s'il a vraiment changé. */
  update(state) {
    this.activity = activityFor(state);
    this.push(false);
  }

  push(force) {
    if (!this.ready || !this.socket) return;
    const a = this.activity;
    // Les instants bougent un peu à chaque relevé : on ne renvoie que si
    // le titre change ou que la position saute (plus de 3 s).
    const key = JSON.stringify(a && { ...a, timestamps: !!a.timestamps });
    const start = a?.timestamps?.start ?? null;
    const same = key === this.sentKey && (start === null || Math.abs(start - this.sentStart) < 3000);
    if (!force && same) return;
    this.sentKey = key;
    this.sentStart = start;
    this.socket.write(encode(OP.FRAME, {
      cmd: "SET_ACTIVITY", args: { pid: process.pid, activity: a || undefined }, nonce: crypto.randomUUID(),
    }));
  }

  close() {
    clearTimeout(this.timer);
    this.ready = false;
    this.sentKey = null;
    const socket = this.socket;
    this.socket = null;
    socket?.destroy();
  }
}

module.exports = { DiscordPresence, activityFor, encode, OP };
