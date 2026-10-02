/* Télécommande sur le réseau local, dans l'esprit de Cider Remote : le PC
   sert une petite page web ; le téléphone scanne le QR code affiché par
   Sona et pilote la lecture du PC (pochette, paroles, file, recherche).

   - Les fichiers de la page sont publics (aucune donnée dedans) ; tout ce
     qui lit ou change la lecture demande la clé d'association, qui voyage
     dans le QR code (après le #, donc jamais dans une requête ni un journal).
   - Seules les adresses du réseau local (et Tailscale) sont acceptées :
     même si le pare-feu laisse passer, Internet reste dehors.
   - L'état part en direct (Server-Sent Events) : le téléphone voit tout de
     suite un titre changé sur le PC, sans redemander sans cesse. */

const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");
const crypto = require("node:crypto");
const QRCode = require("qrcode");

const MAX_BODY = 16 * 1024;
const TYPES = {
  ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "application/javascript; charset=utf-8",
  ".png": "image/png", ".webmanifest": "application/manifest+json", ".svg": "image/svg+xml",
};

/** Adresse du réseau local (ou de la machine elle-même). */
function isLocalAddress(raw) {
  const addr = String(raw || "").replace(/^::ffff:/, "");
  if (addr === "::1" || /^127\./.test(addr)) return true;
  if (/^10\./.test(addr) || /^192\.168\./.test(addr) || /^169\.254\./.test(addr)) return true;
  const b = addr.match(/^172\.(\d+)\./);
  if (b && +b[1] >= 16 && +b[1] <= 31) return true;
  // 100.64.0.0/10 : Tailscale et consorts, pratique hors de chez soi.
  const c = addr.match(/^100\.(\d+)\./);
  if (c && +c[1] >= 64 && +c[1] <= 127) return true;
  return /^(fe80|f[cd][0-9a-f]{2}):/i.test(addr);
}

/** Adresses IPv4 du PC, la plus probable d'abord (Wi-Fi/Ethernet de la maison). */
function lanAddresses() {
  const out = [];
  for (const [name, list] of Object.entries(os.networkInterfaces())) {
    for (const a of list || []) {
      if (a.family !== "IPv4" && a.family !== 4) continue;
      if (a.internal || /^169\.254\./.test(a.address)) continue;
      const virtual = /vEthernet|VirtualBox|VMware|WSL|Hyper-V|docker|vbox|Loopback|ZeroTier/i.test(name);
      const rank = virtual ? 9 : /^192\.168\./.test(a.address) ? 0 : /^10\./.test(a.address) ? 1 : /^172\./.test(a.address) ? 2 : /^100\./.test(a.address) ? 3 : 4;
      out.push({ ip: a.address, name, rank });
    }
  }
  return out.sort((x, y) => x.rank - y.rank);
}

function sameKey(given, key) {
  if (!given || !key) return false;
  const a = Buffer.from(String(given));
  const b = Buffer.from(String(key));
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

/** Nom lisible du téléphone, d'après son navigateur. */
function phoneName(ua = "") {
  if (/iPhone/.test(ua)) return "iPhone";
  if (/iPad/.test(ua)) return "iPad";
  if (/Android/.test(ua)) return /Mobile/.test(ua) ? "Téléphone Android" : "Tablette Android";
  if (/Macintosh/.test(ua)) return "Mac";
  if (/Windows/.test(ua)) return "PC";
  return "Appareil";
}

class RemoteServer {
  /**
   * @param {object} o
   * @param {() => object|null} o.getState  état de lecture à envoyer
   * @param {(body: object) => Promise<any>} o.command  commande du téléphone
   * @param {(clients: object[]) => void} o.onClients  téléphones connectés
   * @param {string} o.remoteRoot  dossier de la page de télécommande
   * @param {string} o.iconsRoot  icônes de Sona web
   */
  constructor({ getState, command, onClients, remoteRoot, iconsRoot }) {
    Object.assign(this, { getState, command, onClients, remoteRoot, iconsRoot });
    this.server = null;
    this.port = 0;
    this.key = "";
    this.error = null;
    this.clients = new Set();
  }

  get running() { return !!this.server; }

  async start(port, key) {
    await this.stop();
    this.key = key;
    this.error = null;
    for (let p = port; p < port + 6; p++) {
      try {
        this.server = await this.listen(p);
        this.port = this.server.address().port;
        return true;
      } catch (e) {
        this.server = null;
        if (e.code !== "EADDRINUSE") { this.error = e.message; return false; }
      }
    }
    this.error = `Ports ${port} à ${port + 5} déjà utilisés`;
    return false;
  }

  listen(port) {
    return new Promise((resolve, reject) => {
      const server = http.createServer((req, res) => this.handle(req, res).catch(() => {
        if (!res.headersSent) res.writeHead(500);
        res.end();
      }));
      server.keepAliveTimeout = 30_000;
      server.once("error", reject);
      server.listen(port, "0.0.0.0", () => {
        server.off("error", reject);
        resolve(server);
      });
    });
  }

  async stop() {
    for (const c of this.clients) c.res.end();
    this.clients.clear();
    this.notifyClients();
    if (!this.server) return;
    const server = this.server;
    this.server = null;
    const closed = new Promise((r) => server.close(() => r()));
    server.closeAllConnections();
    await closed;
  }

  /** Nouvelle clé : les téléphones déjà associés doivent rescanner. */
  setKey(key) {
    this.key = key;
    for (const c of this.clients) c.res.end();
    this.clients.clear();
    this.notifyClients();
  }

  notifyClients() {
    this.onClients?.([...this.clients].map((c) => ({ name: c.name, since: c.since, ip: c.ip })));
  }

  /** Envoie l'état à tous les téléphones connectés. */
  broadcast(state) {
    if (!this.clients.size) return;
    const data = `event: state\ndata: ${JSON.stringify(state)}\n\n`;
    for (const c of this.clients) c.res.write(data);
  }

  async info() {
    const addresses = lanAddresses();
    const urls = addresses.map((a) => ({ ...a, url: `http://${a.ip}:${this.port}/` }));
    const pairUrl = urls[0] ? `${urls[0].url}#k=${this.key}` : null;
    let qr = null;
    if (this.running && pairUrl) {
      qr = await QRCode.toDataURL(pairUrl, { margin: 1, width: 360, errorCorrectionLevel: "M", color: { dark: "#000000", light: "#ffffff" } });
    }
    return {
      running: this.running, port: this.port, error: this.error, urls, pairUrl, qr,
      clients: [...this.clients].map((c) => ({ name: c.name, since: c.since, ip: c.ip })),
    };
  }

  async handle(req, res) {
    if (!isLocalAddress(req.socket.remoteAddress)) {
      res.writeHead(403, { "Content-Type": "text/plain; charset=utf-8" });
      return res.end("Réservé au réseau local.");
    }
    const url = new URL(req.url, "http://local");
    const route = url.pathname;
    res.setHeader("X-Content-Type-Options", "nosniff");
    res.setHeader("Referrer-Policy", "no-referrer");

    if (route.startsWith("/api/")) {
      const given = req.headers["x-sona-key"] || url.searchParams.get("k");
      if (!sameKey(given, this.key)) return this.json(res, 401, { error: "Association requise : scanne le QR code affiché par Sona sur le PC." });
      if (route === "/api/state" && req.method === "GET") return this.json(res, 200, this.getState() || {});
      if (route === "/api/events" && req.method === "GET") return this.events(req, res);
      if (route === "/api/command" && req.method === "POST") {
        let body;
        try { body = JSON.parse(await readBody(req)); } catch { return this.json(res, 400, { error: "Requête illisible." }); }
        if (!body || typeof body.action !== "string") return this.json(res, 400, { error: "Action manquante." });
        try {
          const result = await this.command(body);
          return this.json(res, 200, { ok: true, result: result ?? null });
        } catch (e) {
          return this.json(res, 503, { error: e.message || "Sona ne répond pas." });
        }
      }
      return this.json(res, 404, { error: "Inconnu." });
    }
    if (req.method !== "GET" && req.method !== "HEAD") { res.writeHead(405); return res.end(); }
    return this.file(res, route);
  }

  events(req, res) {
    res.writeHead(200, {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    });
    // Téléphone parti sans prévenir (veille, Wi-Fi coupé) : une écriture
    // tardive ne doit jamais faire tomber l'app.
    res.on("error", () => {});
    res.write("retry: 2000\n\n");
    const client = { res, name: phoneName(req.headers["user-agent"]), since: Date.now(), ip: String(req.socket.remoteAddress || "").replace(/^::ffff:/, "") };
    this.clients.add(client);
    this.notifyClients();
    const state = this.getState();
    if (state) res.write(`event: state\ndata: ${JSON.stringify(state)}\n\n`);
    // Battement : garde la connexion ouverte à travers box et téléphones en veille.
    const ping = setInterval(() => res.write(": ping\n\n"), 15_000);
    req.on("close", () => {
      clearInterval(ping);
      this.clients.delete(client);
      this.notifyClients();
    });
  }

  file(res, route) {
    let file;
    if (route === "/" || route === "/index.html") file = path.join(this.remoteRoot, "index.html");
    else if (/^\/(remote\.css|remote\.js|manifest\.webmanifest)$/.test(route)) file = path.join(this.remoteRoot, route.slice(1));
    else if (/^\/icons\/(icon-192|icon-512|apple-touch-icon|favicon-64)\.png$/.test(route)) file = path.join(this.iconsRoot, route.slice("/icons/".length));
    else { res.writeHead(404); return res.end(); }
    fs.readFile(file, (err, data) => {
      if (err) { res.writeHead(404); return res.end(); }
      res.writeHead(200, { "Content-Type": TYPES[path.extname(file)] || "application/octet-stream", "Cache-Control": "no-cache" });
      res.end(data);
    });
  }

  json(res, status, body) {
    res.writeHead(status, { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" });
    res.end(JSON.stringify(body));
  }
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on("data", (chunk) => {
      size += chunk.length;
      if (size > MAX_BODY) { reject(new Error("Trop gros")); req.destroy(); return; }
      chunks.push(chunk);
    });
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

module.exports = { RemoteServer, isLocalAddress, lanAddresses, phoneName };
