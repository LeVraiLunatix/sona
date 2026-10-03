/* Lien avec Sona pour Windows, par sa télécommande du réseau local
   (desktop/src/remote-server.js), en local sur le PC : 127.0.0.1.

   Rien à configurer : la clé d'association et le port sont lus dans les
   réglages de l'app (`%APPDATA%\Sona\settings.json`), sur le même PC et pour
   le même utilisateur. L'état arrive en direct (Server-Sent Events) ; la
   position avance toute seule entre deux nouvelles. */

import { EventEmitter } from "node:events";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export function settingsFile() {
  if (process.platform === "win32") return path.join(process.env.APPDATA || path.join(os.homedir(), "AppData", "Roaming"), "Sona", "settings.json");
  if (process.platform === "darwin") return path.join(os.homedir(), "Library", "Application Support", "Sona", "settings.json");
  return path.join(process.env.XDG_CONFIG_HOME || path.join(os.homedir(), ".config"), "Sona", "settings.json");
}

/** Réglages de la télécommande de Sona, ou null si Sona n'est pas installé. */
export function readSonaSettings(file = settingsFile()) {
  try {
    const s = JSON.parse(fs.readFileSync(file, "utf8"));
    return {
      key: s.remoteKey || "",
      port: Number(s.remotePort) || 7650,
      // Port réellement obtenu par Sona (il en prend un autre si le sien est réservé).
      activePort: Number(s.remoteActivePort) || null,
      enabled: s.remoteEnabled !== false,
    };
  } catch (e) {
    return e.code === "ENOENT" ? null : { key: "", port: 7650, activePort: null, enabled: true, unreadable: e.code || e.message };
  }
}

/**
 * États : `absent` (Sona pas installé), `off` (télécommande coupée dans
 * Sona), `offline` (Sona fermé), `online`.
 */
export class SonaClient extends EventEmitter {
  constructor({ settings = readSonaSettings, host = "127.0.0.1", retry = 3000 } = {}) {
    super();
    this.readSettings = settings;
    this.host = host;
    this.retry = retry;
    this.status = "offline";
    this.state = null;
    this.receivedAt = 0;
    this.base = null;
    this.key = null;
    this.stopped = false;
    this.abort = null;
  }

  start() {
    this.stopped = false;
    this.loop();
    return this;
  }

  stop() {
    this.stopped = true;
    this.abort?.abort();
    clearTimeout(this.timer);
  }

  setStatus(status) {
    if (status === this.status) return;
    this.status = status;
    this.emit("status", status);
  }

  async loop() {
    while (!this.stopped) {
      try {
        await this.connect();
      } catch {
        // Fermé ou injoignable : on réessaie.
      }
      if (this.stopped) return;
      await new Promise((r) => (this.timer = setTimeout(r, this.retry)));
    }
  }

  /** Trouve Sona (port réglé, ou l'un des suivants s'il était pris) puis suit l'état. */
  /** Journal (relayé dans les logs du plugin par Stream Deck), sans doublons. */
  log(message) {
    if (message === this.lastLog) return;
    this.lastLog = message;
    this.emit("log", message);
  }

  /** En-têtes : la clé si on l'a, et l'indication « app de ce PC » (acceptée sans clé en local). */
  headers(extra = {}) {
    return { "X-Sona-Local": "streamdeck", ...(this.key ? { "X-Sona-Key": this.key } : {}), ...extra };
  }

  async connect() {
    // Réglages illisibles ou absents : on essaie quand même, en local, sans clé.
    const s = this.readSettings() || { key: "", port: 7650, activePort: null, enabled: true, missing: true };
    if (s.unreadable) this.log(`Réglages de Sona illisibles (${settingsFile()} : ${s.unreadable}) : connexion locale sans clé.`);
    if (!s.enabled) { this.log("Télécommande coupée dans Sona (Réglages › Télécommande du téléphone)."); return this.setStatus("off"); }
    this.key = s.key;
    const ports = [...new Set([s.activePort, ...Array.from({ length: 20 }, (_, i) => s.port + i)].filter(Boolean))];
    const tried = [];
    for (const port of ports) {
      const base = `http://${this.host}:${port}`;
      const res = await fetch(`${base}/api/state`, { headers: this.headers(), signal: AbortSignal.timeout(1500) }).catch((e) => { tried.push(`${port} : ${e.cause?.code || e.name}`); return null; });
      if (!res) continue;
      tried.push(`${port} : ${res.status}`);
      if (res.status === 401) continue; // une autre app sur ce port, ou une clé périmée
      if (!res.ok) continue;
      this.log(`Sona trouvé sur ${base}`);
      this.base = base;
      this.update(await res.json());
      this.setStatus("online");
      await this.follow();
      this.setStatus("offline");
      return;
    }
    const refused = tried.filter((t) => /ECONNREFUSED/.test(t)).length;
    this.log(`Sona injoignable (${refused === tried.length ? `aucune réponse sur les ports ${ports[0]}–${ports[ports.length - 1]}` : tried.join(", ")}) : l'app est-elle ouverte ?`);
    this.setStatus(s.missing ? "absent" : "offline");
  }

  async follow() {
    this.abort = new AbortController();
    const res = await fetch(`${this.base}/api/events?name=${encodeURIComponent("Stream Deck")}${this.key ? `&k=${encodeURIComponent(this.key)}` : ""}`, { headers: this.headers(), signal: this.abort.signal });
    if (!res.ok || !res.body) return;
    const decoder = new TextDecoder();
    let buffer = "";
    for await (const chunk of res.body) {
      buffer += decoder.decode(chunk, { stream: true });
      let i;
      while ((i = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, i);
        buffer = buffer.slice(i + 2);
        const event = /^event: (.*)$/m.exec(block)?.[1];
        const data = block.split("\n").filter((l) => l.startsWith("data: ")).map((l) => l.slice(6)).join("\n");
        if (event === "state" && data) {
          try { this.update(JSON.parse(data)); } catch {}
        }
      }
    }
  }

  update(state) {
    this.state = state;
    this.receivedAt = Date.now();
    this.emit("state", state);
  }

  /** Position actuelle (elle avance pendant la lecture). */
  position() {
    const st = this.state;
    if (!st?.track) return 0;
    let p = st.position || 0;
    if (!st.paused) p += (Date.now() - this.receivedAt) / 1000;
    const dur = st.duration || st.track.duration_seconds || 0;
    return dur ? Math.min(p, dur) : p;
  }

  async command(action, extra = {}) {
    if (this.status !== "online" || !this.base) throw new Error("Sona n'est pas ouvert");
    const res = await fetch(`${this.base}/api/command`, {
      method: "POST",
      headers: this.headers({ "Content-Type": "application/json" }),
      body: JSON.stringify({ action, ...extra }),
      signal: AbortSignal.timeout(8000),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.error || `Erreur ${res.status}`);
    return body.result;
  }
}
