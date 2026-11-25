// Faux serveur Sona pour filmer la VRAIE interface (web/app.js + app.css) avec des données fictives.
// Sert web/ sous /web/ et simule l'API. Aucun vrai titre, artiste ni pochette : tout est inventé ici.
const http = require("node:http"), fs = require("node:fs"), path = require("node:path");
const WEB = path.resolve(__dirname, "../../../web");
const PORT = +process.env.PORT || 8765;
const ORIGIN = `http://localhost:${PORT}`;

// ───────── Catalogue fictif ─────────
const ARTISTS = [
  ["a1", "Mira Solen"], ["a2", "Aurel Vance"], ["a3", "Echo Verre"], ["a4", "Lune Basse"], ["a5", "Sable & Co"], ["a6", "Kiro Dune"],
];
const PAL = [["#ff8a5c", "#7a1f5c"], ["#5cc8ff", "#17306e"], ["#b9a4ff", "#2b1b63"], ["#7ee0b0", "#0e4a4a"], ["#ffc46b", "#7a2d12"], ["#ff9bb8", "#4a1240"], ["#9fb8e6", "#1d2a55"], ["#e8957f", "#3d1530"]];
const RAW = [
  ["Le jour se lève", 0, "Sans bruit", 2024, 222], ["Fenêtre sur mer", 1, "Marée basse", 2023, 198], ["Halo", 2, "Verre soufflé", 2025, 205], ["Minuit moins le quart", 3, "Lampadaires", 2024, 187],
  ["Cendres douces", 0, "Sans bruit", 2024, 241], ["Orbite", 1, "Marée basse", 2023, 214], ["Papier glacé", 4, "Dimanche", 2022, 176], ["Dernier métro", 3, "Lampadaires", 2024, 233],
  ["Ciel de plomb", 5, "Dunes", 2025, 201], ["Souffle", 2, "Verre soufflé", 2025, 189], ["Fil rouge", 4, "Dimanche", 2022, 208], ["Là-haut", 5, "Dunes", 2025, 219],
  ["Neige d'août", 0, "Sans bruit", 2024, 196], ["Phare", 1, "Marée basse", 2023, 227], ["Velours", 2, "Verre soufflé", 2025, 182], ["Tout doucement", 3, "Lampadaires", 2024, 205],
];
const albums = {}; RAW.forEach((r, i) => { albums[r[2]] ||= "al" + (Object.keys(albums).length + 1); });
const cover = (i) => `${ORIGIN}/cover/${i}.svg`;
const TRACKS = RAW.map(([title, a, album, year, dur], i) => ({
  source: "deezer", source_id: String(1000 + i), title, artist: ARTISTS[a][1], artist_source_id: ARTISTS[a][0], album, album_source_id: albums[album], year,
  duration_seconds: dur, cover_url: cover(PAL.length ? RAW.findIndex((x) => x[2] === album) : i), artists: [{ name: ARTISTS[a][1], source_id: ARTISTS[a][0], role: "main" }],
}));
const albumCoverIdx = (album) => Object.keys(albums).indexOf(album);
TRACKS.forEach((t) => { t.cover_url = cover(albumCoverIdx(t.album)); });
const tr = (...ix) => ix.map((i) => TRACKS[i]);

// ───────── Pochettes SVG (dégradés + formes) ─────────
function coverSvg(n) {
  const [a, b] = PAL[n % PAL.length], k = n * 37;
  const shapes = n % 3 === 0 ? `<circle cx="${200 + (k % 80)}" cy="${180 + (k % 60)}" r="${120 + (k % 40)}" fill="${a}" opacity=".85"/><circle cx="${330 - (k % 60)}" cy="${300}" r="70" fill="#fff" opacity=".13"/>`
    : n % 3 === 1 ? `<path d="M0 330 Q100 ${250 - (k % 40)} 200 320 T400 ${300 - (k % 50)} V400 H0Z" fill="${a}" opacity=".9"/><path d="M0 370 Q120 ${300} 240 360 T400 340 V400 H0Z" fill="#000" opacity=".28"/><circle cx="${290 - (k % 50)}" cy="120" r="46" fill="#fff" opacity=".9"/>`
    : `<rect x="70" y="70" width="260" height="260" rx="${40 + (k % 40)}" fill="${a}" opacity=".9" transform="rotate(${(k % 40) - 20} 200 200)"/><rect x="120" y="120" width="160" height="160" rx="30" fill="${b}" opacity=".75" transform="rotate(${(k % 30) + 10} 200 200)"/>`;
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${b}"/><stop offset="1" stop-color="#0a0a0f"/></linearGradient></defs><rect width="400" height="400" fill="url(#g)"/>${shapes}</svg>`;
}

// ───────── Paroles mot par mot (texte original, pour la démo) ─────────
const LYR = [
  "Le jour se lève sans bruit", "et chaque mot s'allume", "juste à temps pour toi", "ta musique, en clair",
  "Des notes tenues dans le noir", "qui brillent un peu plus longtemps", "rien ne se perd, rien ne se coupe", "tout ce qui est là est joué",
  "Reste encore un peu", "la nuit n'a pas fini", "on écoute au même moment", "où que tu sois",
];
function lyrics() {
  let t = 5.0; const lines = [];
  LYR.forEach((text, li) => {
    const toks = text.split(" "), start = t, w = [];
    toks.forEach((tok, k) => {
      const last = k === toks.length - 1, d = (last ? 0.85 : 0.2) + tok.length * 0.045;
      w.push({ time: +t.toFixed(2), end: +(t + d).toFixed(2), text: tok + (last ? "" : " ") }); t += d;
    });
    lines.push({ time: +start.toFixed(2), text, words: w }); t += 0.55;
  });
  return { synced: true, sync: "word", source: "Sona", approximate: false, instrumental: false, lines };
}

// ───────── Son d'ambiance (WAV, sans droits) ─────────
function wav() {
  const sr = 22050, secs = 90, n = sr * secs, buf = Buffer.alloc(44 + n * 2);
  buf.write("RIFF", 0); buf.writeUInt32LE(36 + n * 2, 4); buf.write("WAVEfmt ", 8); buf.writeUInt32LE(16, 16); buf.writeUInt16LE(1, 20); buf.writeUInt16LE(1, 22);
  buf.writeUInt32LE(sr, 24); buf.writeUInt32LE(sr * 2, 28); buf.writeUInt16LE(2, 32); buf.writeUInt16LE(16, 34); buf.write("data", 36); buf.writeUInt32LE(n * 2, 40);
  const ch = [220, 277.18, 329.63, 440, 554.37]; // accord ouvert
  for (let i = 0; i < n; i++) {
    const t = i / sr; let v = 0;
    ch.forEach((f, k) => { v += Math.sin(2 * Math.PI * f * t + k) * (0.5 + 0.5 * Math.sin(2 * Math.PI * (0.07 + k * 0.021) * t + k)); });
    buf.writeInt16LE(Math.round((v / ch.length) * 0.35 * 32767), 44 + i * 2);
  }
  return buf;
}
let WAV; const wavBuf = () => (WAV ||= wav());

// ───────── Routes de l'API ─────────
const mixes = [
  { id: "m1", title: "Mix du matin", subtitle: "Mira Solen, Echo Verre et plus", tracks: tr(0, 2, 9, 14, 12, 4), covers: [cover(0), cover(2)] },
  { id: "m2", title: "Mix nuit", subtitle: "Lune Basse, Aurel Vance", tracks: tr(3, 7, 15, 1, 5, 13), covers: [cover(3), cover(1)] },
  { id: "m3", title: "Mix focus", subtitle: "Kiro Dune, Sable & Co", tracks: tr(8, 11, 6, 10), covers: [cover(4), cover(5)] },
  { id: "m4", title: "Mix découverte", subtitle: "Nouveautés pour toi", tracks: tr(2, 8, 11, 14), covers: [cover(6), cover(7)] },
];
const playlists = [
  { id: "p1", name: "Matin calme", track_count: 24, cover_url: cover(0), covers: [cover(0), cover(2), cover(4), cover(1)], import_status: null, visibility: "private" },
  { id: "p2", name: "Route de nuit", track_count: 41, cover_url: cover(3), covers: [cover(3), cover(1), cover(5), cover(6)], import_status: null, visibility: "private" },
  { id: "p3", name: "Fichiers FLAC", track_count: 118, cover_url: cover(2), covers: [cover(2), cover(7), cover(4), cover(0)], import_status: null, visibility: "private" },
  { id: "p4", name: "À deux", track_count: 32, cover_url: cover(5), covers: [cover(5), cover(3), cover(1), cover(6)], import_status: null, visibility: "friends" },
];
const smart = [
  { id: "recent", title: "Ajoutés récemment", count: 37, covers: [cover(0), cover(1), cover(2), cover(3)] },
  { id: "most", title: "Les plus écoutés", count: 50, covers: [cover(4), cover(5), cover(6), cover(7)] },
];

// ───────── Stats, récap, appareils ─────────
const art = (i) => ({ source: "deezer", source_id: ARTISTS[i][0], name: ARTISTS[i][1], plays: [212, 168, 141, 96, 74, 51][i], minutes: [788, 590, 512, 330, 256, 170][i], picture_url: cover([0, 1, 2, 3, 4, 5][i]), cover_url: cover(i) });
const topTracks = [0, 1, 2, 3, 4, 5].map((i) => ({ source: "deezer", source_id: String(1000 + i), name: TRACKS[i].title, subtitle: TRACKS[i].artist, plays: [58, 47, 41, 36, 29, 24][i], minutes: [215, 155, 140, 112, 118, 86][i], cover_url: TRACKS[i].cover_url }));
const days = Array.from({ length: 30 }, (_, i) => ({ label: String(i + 1), minutes: Math.round(40 + 90 * Math.abs(Math.sin(i * 1.3)) * (i % 7 > 4 ? 1.4 : 1)) }));
function stats(period) {
  return { label: "Novembre 2026", plays: 743, previous_plays: 612, minutes: 2646, previous_minutes: 2210, artists: 38, tracks: 211, albums: 64, streak_days: 23,
    timeline: days, top_artists: [0, 1, 2, 3, 4, 5].map(art), top_tracks: topTracks, top_albums: [0, 1, 2, 3].map((i) => ({ source: "deezer", source_id: "al" + (i + 1), name: TRACKS[i].album, subtitle: TRACKS[i].artist, plays: 120 - i * 17, minutes: 410 - i * 60, cover_url: TRACKS[i].cover_url })),
    hours: Array.from({ length: 24 }, (_, h) => Math.round(10 + 60 * Math.exp(-((h - 21) ** 2) / 14) + 24 * Math.exp(-((h - 8) ** 2) / 8))), weekdays: [60, 54, 71, 66, 90, 120, 104], top_hour: 21, top_weekday: "samedi",
    discoveries: [3, 4, 5].map(art), favourite_track: TRACKS[0],
    personality: { emoji: "🌙", title: "Oiseau de nuit", description: "Ta musique prend vie quand la ville s'endort." },
    biggest_day: { label: "samedi 14 novembre", minutes: 214 }, discovered_count: 12, first_track: TRACKS[6], friends_rank: { rank: 1, total: 6 } };
}
const phoneTrack = TRACKS[2];
let CONNECT_ON = true;
const connect = () => CONNECT_ON ? ({
  devices: [
    { id: "iph1", name: "iPhone de Lunatix", kind: "iphone", is_me: false, playing: true, track: phoneTrack, position: 74, volume: 0.7, shuffle: false, repeat: "off", liked: true, queue_length: 12 },
    { id: "pc1", name: "PC · Bureau", kind: "desktop", is_me: false, playing: false, track: null, position: 0, volume: 0.8 },
    { id: "tv1", name: "Télé du salon", kind: "desktop", is_me: false, playing: false, track: null, position: 0, volume: 0.5 },
  ],
  session: { device_id: "iph1", track: phoneTrack, paused: false, position: 74, queue: TRACKS.slice(2, 8), index: 0, updated_at: Date.now() / 1000 },
  active_device_id: "iph1", commands: [], login_requests: [],
}) : { devices: [], session: null, active_device_id: null, commands: [], login_requests: [] };

const unknown = new Set();
function route(method, url, body) {
  const p = url.pathname;
  if (p === "/__mock") { CONNECT_ON = url.searchParams.get("connect") !== "0"; return { connect: CONNECT_ON }; }
  if (p === "/auth/me") return { status: "approved", username: "lunatix", display_name: "Lunatix", avatar_url: null, is_admin: false };
  if (p === "/auth/config") return {};
  if (p === "/settings") return {};
  if (p === "/smart") return smart;
  if (p.startsWith("/smart/")) return { id: p.split("/")[2], title: "Les plus écoutés", tracks: TRACKS.slice(0, 12), covers: [cover(4)] };
  if (p === "/me/playlists") return playlists;
  if (p.startsWith("/me/playlists/")) { const pl = playlists.find((x) => x.id === p.split("/")[3]) || playlists[0]; return { ...pl, tracks: TRACKS.slice(0, 12), owner: "Lunatix", duration_seconds: 3600 }; }
  if (p.startsWith("/library/")) return { items: p.endsWith("/track") ? TRACKS.slice(0, 8) : [] };
  if (p === "/home/mixes") return mixes;
  if (p === "/plays/recent") return TRACKS.slice(0, 14).map((t, i) => ({ ...t, played_at: Date.now() / 1000 - i * 3600 }));
  if (p === "/releases") return [4, 5, 6, 7].map((i) => ({ source: "deezer", source_id: "al" + (i + 1), title: ["Dunes", "Dimanche", "Verre soufflé", "Lampadaires"][i - 4], artist: ARTISTS[i - 2][1], kind: "Album", cover_url: cover(i) }));
  if (p === "/memories" || p === "/party/active" || p === "/browse/radios" || p === "/friends") return [];
  if (p === "/home/daily" || p === "/home/mood") return null;
  if (p === "/exclusives") return { tracks: [] };
  if (p === "/lyrics") return url.searchParams.get("title") === TRACKS[0].title ? lyrics() : null;
  if (p === "/lyrics/prefetch") return {};
  if (p.startsWith("/tracks/") && p.endsWith("/credits")) return null;
  if (p === "/connect/sync") return connect();
  if (p === "/stats") return stats(url.searchParams.get("period"));
  if (p === "/stats/recap") return stats("month");
  if (p === "/stats/live") return null;
  if (p === "/challenges") return null;
  if (p.startsWith("/moments/")) return [];
  if (p === "/plays/now") return {};
  if (p === "/exclusives/status") return {};
  if (p === "/connect/saved") return !CONNECT_ON ? [] : [{ id: "iph1", name: "iPhone de Lunatix", kind: "iphone" }, { id: "pc1", name: "PC · Bureau", kind: "desktop" }, { id: "tv1", name: "Télé du salon", kind: "desktop" }];
  unknown.add(method + " " + p);
  return undefined;
}

http.createServer((req, res) => {
  const url = new URL(req.url, ORIGIN);
  const send = (code, type, data, extra = {}) => { res.writeHead(code, { "Content-Type": type, "Access-Control-Allow-Origin": "*", ...extra }); res.end(data); };
  if (url.pathname.startsWith("/cover/")) return send(200, "image/svg+xml", coverSvg(parseInt(url.pathname.slice(7)) || 0), { "Cache-Control": "max-age=3600" });
  if (url.pathname.startsWith("/stream/")) {
    const b = wavBuf(), r = /bytes=(\d*)-(\d*)/.exec(req.headers.range || "");
    if (r) { const s = +r[1] || 0, e = r[2] ? +r[2] : b.length - 1; return send(206, "audio/wav", b.subarray(s, e + 1), { "Content-Range": `bytes ${s}-${e}/${b.length}`, "Accept-Ranges": "bytes" }); }
    return send(200, "audio/wav", b, { "Accept-Ranges": "bytes" });
  }
  if (url.pathname === "/web" || url.pathname.startsWith("/web/")) {
    let f = path.join(WEB, url.pathname.slice(5) || "index.html"); if (!f.startsWith(WEB)) return send(403, "text/plain", "no");
    if (fs.existsSync(f) && fs.statSync(f).isDirectory()) f = path.join(f, "index.html");
    if (!fs.existsSync(f)) f = path.join(WEB, "index.html");
    const types = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".woff2": "font/woff2", ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".ico": "image/x-icon", ".webmanifest": "application/manifest+json", ".json": "application/json" };
    return send(200, types[path.extname(f)] || "application/octet-stream", fs.readFileSync(f));
  }
  if (req.method === "OPTIONS") return send(204, "text/plain", "", { "Access-Control-Allow-Headers": "*", "Access-Control-Allow-Methods": "*" });
  let body = ""; req.on("data", (c) => (body += c)); req.on("end", () => {
    const out = route(req.method, url, body);
    if (out === undefined) { console.log("[mock] route inconnue:", req.method, url.pathname); return send(404, "application/json", JSON.stringify({ detail: "inconnu" })); }
    send(200, "application/json", JSON.stringify(out));
  });
}).listen(PORT, () => console.log("mock Sona sur", ORIGIN + "/web/"));
