// Test d'interface (navigateur réel, faux serveur) : loupe de la recherche, disques d'un album,
// feat cliquables, barres animées, crédits, paroles, hors ligne, aide clavier.
//   npm i playwright-core && CHROMIUM_PATH=/chemin/vers/chrome node tests/ui/smoke.mjs
// Sort avec un code non nul au moindre échec ou à la moindre erreur JavaScript.
import { chromium } from "playwright-core";
import { createServer } from "node:http";
import { readFileSync, existsSync } from "node:fs";
import { dirname, extname, join } from "node:path";
import { fileURLToPath } from "node:url";

const WEB = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "web");
const types = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".png": "image/png", ".webmanifest": "application/json" };
// WAV de 3 s de silence
function wav(sec = 3) {
  const rate = 8000, n = rate * sec, buf = Buffer.alloc(44 + n * 2);
  buf.write("RIFF", 0); buf.writeUInt32LE(36 + n * 2, 4); buf.write("WAVEfmt ", 8); buf.writeUInt32LE(16, 16);
  buf.writeUInt16LE(1, 20); buf.writeUInt16LE(1, 22); buf.writeUInt32LE(rate, 24); buf.writeUInt32LE(rate * 2, 28);
  buf.writeUInt16LE(2, 32); buf.writeUInt16LE(16, 34); buf.write("data", 36); buf.writeUInt32LE(n * 2, 40);
  return buf;
}
const server = createServer((req, res) => {
  let p = req.url.split("?")[0];
  const isWeb = p.startsWith("/web");
  p = p.replace(/^\/web/, "") || "/";
  const file = join(WEB, p === "/" ? "index.html" : p);
  if (isWeb && existsSync(file)) { res.writeHead(200, { "Content-Type": types[extname(file)] || "text/plain" }); res.end(readFileSync(file)); }
  else { res.writeHead(404); res.end("{}"); }
}).listen(0);
const port = server.address().port;

const artist = { name: "Favé", role: "main", source_id: "10" };
const track = (i, extra = {}) => ({ source: "deezer", source_id: String(i), title: `Titre ${i}`, artist: "Favé", album: "Double", year: "2024", duration_seconds: 3, cover_url: null,
  artist_source_id: "10", album_source_id: "99", artists: [{ name: "Favé", source_id: "10", role: "main" }, { name: "RnBoi", source_id: "11", role: "featured" }], ...extra });
const album = { source: "deezer", source_id: "99", title: "Double", artist: "Favé", artist_source_id: "10", year: "2024", cover_url: null, track_count: 4, duration_seconds: 12,
  tracks: [track(1, { disc_number: 1, track_number: 1 }), track(2, { disc_number: 1, track_number: 2 }), track(3, { disc_number: 2, track_number: 1 }), track(4, { disc_number: 2, track_number: 2 })] };
const jsonRoutes = {
  "/auth/me": { status: "approved", username: "t", display_name: "Test", id: 1 },
  "/settings": { autoplay: false }, "/health": { version: "x", streaming: "ok" },
  "/albums/deezer/99": album, "/albums/deezer/99/versions": [{ ...album, source_id: "98", title: "Double (Deluxe)", tracks: [] }],
  "/artists/deezer/10": { source: "deezer", source_id: "10", name: "Favé", picture_url: null, fans: 5 },
  "/artists/deezer/10/top-tracks": [track(1)], "/artists/deezer/10/related": [],
  "/artists/deezer/10/albums": { albums: [{ ...album, tracks: [] }, { ...album, source_id: "97", title: "Ancien", year: "2019", tracks: [] }, { ...album, source_id: "96", title: "B", year: "2020", tracks: [] }], singles: [{ ...album, source_id: "95", title: "Single", year: "2022", tracks: [] }], other_versions: [{ ...album, source_id: "98", title: "Double (Deluxe)", tracks: [] }] },
  "/artists/deezer/10/bio": { text: "Favé est un rappeur français. ".repeat(12), url: "https://fr.wikipedia.org/wiki/Fave", source: "Wikipédia" },
  "/artists/deezer/10/concerts": [{ id: "1", artist: "Favé", datetime: "2026-12-01T20:00:00", venue: "Zénith", city: "Paris", country: "FR", url: null }],
  "/tracks/deezer/1/credits": { artists: track(1).artists, credits: [{ role: "Producteur", names: ["Beatmaker"] }], album: "Double", label: "Label", release_date: "2024-05-03", genres: ["Rap"], isrc: "FR1", disc_number: 1, track_number: 1, duration_seconds: 3 },
  "/lyrics": { synced: true, instrumental: false, sync: "word", source: "netease", language: "fr", lines: [
    { time: 0, text: "Ligne un", words: [{ time: 0, text: "Ligne ", end: 0.4 }, { time: 0.4, text: "un", end: 0.9 }] },
    { time: 1, text: "" }, { time: 2, text: "Ligne deux" }] },
  "/search": { query_id: "q", provider: "deezer", total: 1, tracks: [track(1)] },
  "/me/playlists/5": { id: 5, name: "Importée", description: null, cover_url: null, covers: [], origin: "soundcloud", origin_url: "https://soundcloud.com/a/sets/b",
    track_count: 2, duration_seconds: 6, import_status: "done", import_total: 3, import_done: 3, import_missing: 1, import_uncertain: 1, import_added: 0,
    import_error: null, synced_at: new Date().toISOString(), updated_at: new Date().toISOString(), visibility: "private", is_owner: true, can_edit: true,
    entries: [{ entry_id: 1, track: track(1) }, { entry_id: 2, track: track(2) }] },
  "/me/shares": { token: "tok123456789abcdefghij", url: "https://sona.exemple.fr/s/tok123456789abcdefghij", kind: "album", source: "deezer", id: "99",
    title: "Double", subtitle: "Favé", cover_url: null, created_at: new Date().toISOString(), expires_at: null, views: 0, active: true },
  "/shares/tok123456789abcdefghij": { kind: "playlist", source: "sona", id: "5", title: "Soirée partagée", subtitle: "Playlist de Léa · 2 titres", cover_url: null, tracks: [track(1), track(2)] },
  "/me/playlists/5/import": { playlist: {}, counts: { found: 1, uncertain: 1, missing: 1 }, items: [
    { id: 1, position: 0, status: "found", reason: null, original: track(1, { source: "soundcloud" }), matched: track(1), entry_id: 1, fixed: false },
    { id: 2, position: 1, status: "uncertain", reason: "Durée différente (6 s d'écart)", original: track(2, { source: "soundcloud", title: "Titre deux" }), matched: track(2), entry_id: 2, fixed: false },
    { id: 3, position: 2, status: "missing", reason: "Introuvable", original: track(3, { source: "soundcloud" }), matched: null, entry_id: null, fixed: false }] },
};
const errors = [];
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined, args: ["--autoplay-policy=no-user-gesture-required", "--no-sandbox"] });
const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
const page = await ctx.newPage();
page.on("pageerror", (e) => errors.push(`pageerror: ${e.message} @ ${(e.stack||"").split("\n").slice(1,3).join(" | ")}`));
page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource|404/.test(m.text())) errors.push(`console: ${m.text()}`); });
await ctx.addInitScript(() => { localStorage.setItem("sona.token", "test"); });
await page.route("**/*", async (route) => {
  const url = new URL(route.request().url());
  if (url.hostname !== "localhost" && url.hostname !== "127.0.0.1") return route.fulfill({ status: 200, body: "" });
  if (url.pathname.startsWith("/web")) return route.continue();
  const cm = url.pathname.match(/^\/tracks\/deezer\/(\d+)\/credits$/);
  const j = cm ? jsonRoutes["/tracks/deezer/1/credits"] : jsonRoutes[url.pathname];
  if (j) return route.fulfill({ json: j });
  if (url.pathname.startsWith("/stream/")) return route.fulfill({ status: 200, contentType: "audio/wav", body: wav() });
  if (/^\/(auth|settings|health|albums|artists|tracks|lyrics|search|me|library|smart|connect|plays|party|friends|stats|home|discover|analysis)/.test(url.pathname)) return route.fulfill({ status: 404, json: { detail: "nope" } });
  return route.continue();
});
const lines = [];
const out = (s) => { lines.push(s); console.log(s); };
await page.goto(`http://localhost:${port}/web/#/search`);
await page.waitForSelector(".search-hero", { timeout: 8000 });
// 1. loupe dans le champ
const geo = await page.evaluate(() => { const i = document.querySelector(".search-hero input").getBoundingClientRect(), c = document.querySelector(".search-hero .icon").getBoundingClientRect(); return { i, c }; });
const inside = geo.c.top >= geo.i.top && geo.c.bottom <= geo.i.bottom && geo.c.left >= geo.i.left;
out(`loupe dans le champ: ${inside}`);
// 2. album avec disques
await page.goto(`http://localhost:${port}/web/#/album/deezer/99`);
await page.waitForSelector(".tracks .tr");
out(`en-têtes de disque: ${await page.$$eval(".disc-head", (e) => e.map((x) => x.textContent.trim()).join(" | "))}`);
out(`numéros: ${await page.$$eval(".tr .n > span", (e) => e.map((x) => x.textContent).join(","))}`);
out(`feat dans la liste: ${await page.$eval(".tr .ar", (e) => e.textContent)}`);
await page.waitForSelector("#album-versions .card, #album-versions .shelf", { timeout: 4000 }).catch(() => out("versions: absentes"));
out(`autres versions: ${await page.$eval("#album-versions", (e) => e.textContent.trim().slice(0, 40))}`);
// 3. lecture, barres, feat+liens dans la barre
await page.click(".tracks .tr[data-i='0']");
await page.waitForSelector(".tr.current .bars", { timeout: 5000 });
out(`barres visibles: ${await page.$eval(".tr.current .bars", (e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(e).display !== "none"; })}`);
out(`barre de lecture: ${await page.$eval(".lcd .meta .a", (e) => e.textContent.trim())}`);
out(`liens: artiste=${await page.$$eval(".lcd [data-goartist]", (e) => e.length)} album=${await page.$$eval(".lcd [data-goalbum]", (e) => e.length)}`);
// 4. clic sur l'invité -> page artiste
await page.click(".lcd [data-goartist='deezer/11']");
await page.waitForFunction(() => location.hash === "#/artist/deezer/11");
out(`clic invité -> ${await page.evaluate(() => location.hash)}`);
await page.click(".lcd [data-goalbum]");
await page.waitForFunction(() => location.hash === "#/album/deezer/99");
out(`clic album -> ${await page.evaluate(() => location.hash)}`);
// 5. artiste : bio, concerts, filtres
await page.goto(`http://localhost:${port}/web/#/artist/deezer/10`);
await page.waitForSelector("#artist-bio .bio-text", { timeout: 5000 });
await page.waitForSelector("#artist-concerts .concert", { timeout: 5000 });
out(`bio+concerts ok, chips: ${await page.$$eval(".disco-controls .chip", (e) => e.length)}`);
await page.click("[data-disco-filter='singles']");
out(`après filtre singles, étagères: ${await page.$$eval("#artist-disco .section-head h2", (e) => e.map((x) => x.textContent).join(",") || "(aucune)")}`);
// 6. drawer crédits + paroles décalage
await page.keyboard.press("l");
await page.waitForSelector(".np.open, #np-right, #drawer-body .lyrics", { timeout: 5000 }).catch(() => {});
out(`outils paroles: ${await page.$$eval(".lyr-tools", (e) => e.length)}`);
await page.click("[data-lyr-off='0.5']").catch((e) => out("décalage: " + e.message.split("\n")[0]));
out(`valeur décalage: ${await page.$eval("#lyr-val", (e) => e.textContent).catch(() => "?")}`);
out(`mots de la 1re ligne: ${await page.$$eval("#lyr [data-l='0'] .w", (e) => e.map((x) => x.textContent.trim()).join("|"))}`);
out(`mots estimés de la 3e ligne: ${await page.$$eval("#lyr [data-l='2'] .w", (e) => e.length)}`);
out(`pause instrumentale: ${await page.$$eval("#lyr p.gap i", (e) => e.length === 3)}`);
out(`source des paroles: ${await page.$eval(".lyr-foot", (e) => e.textContent).catch(() => "absente")}`);
await page.keyboard.press("c");
await page.waitForSelector(".credits .cr", { timeout: 5000 }).catch(() => out("crédits: absents"));
out(`crédits: ${await page.$$eval(".credits .cr .cl", (e) => e.map((x) => x.textContent).join(","))}`);
out(`crédit cliquable: ${await page.$$eval("[data-credit-search]", (e) => e.length)}`);
// 7. fond vivant (WebGL) aux couleurs de la pochette, lecteur plein écran
await page.keyboard.press("Escape");
await page.evaluate(() => {
  playList([{ ...state.queue[state.index], source_id: "8", cover_url: "/web/icons/icon-512.png" }], 0, "");
  openNowPlaying("lyrics");
});
await page.waitForSelector("#np .np-gl.on", { timeout: 5000 }).then(() => out("fond vivant: ok"), () => out("fond vivant: absents"));
if (process.env.SHOT) await page.screenshot({ path: process.env.SHOT });
await page.keyboard.press("Escape");
// 8. rapport d'import d'une playlist (bandeau, filtres, correction)
await page.goto(`http://localhost:${port}/web/#/playlist/5`);
await page.waitForSelector(".import-banner", { timeout: 5000 }).then(() => out("bandeau d'import: ok"), () => out("bandeau d'import: absent"));
out(`synchronisation: ${await page.$eval(".hero", (e) => /Synchronisée avec SoundCloud/.test(e.textContent)).catch(() => false)}`);
await page.click(".import-banner").catch(() => {});
await page.waitForSelector(".imp-row", { timeout: 5000 }).catch(() => {});
out(`à vérifier: ${await page.$$eval(".imp-row", (e) => e.map((x) => x.querySelector("b").textContent).join("|"))}`);
if (process.env.SHOT_IMPORT) { await page.waitForTimeout(400); await page.screenshot({ path: process.env.SHOT_IMPORT }); }
await page.click("[data-imp-filter='missing']").catch(() => {});
out(`introuvables: ${await page.$$eval(".imp-row", (e) => e.length)}`);
await page.click(".imp-row [data-imp-act='fix']").catch(() => {});
await page.waitForSelector(".imp-pick", { timeout: 5000 }).then(() => out("correction (recherche): ok"), () => out("correction (recherche): absente"));
await page.keyboard.press("Escape");
await page.keyboard.press("Escape");
// Fermer le rapport recharge la fiche de la playlist : on attend la fin.
await page.waitForTimeout(800);
// 9. partage : lien d'un album, puis lien reçu ouvert dans Sona
await page.goto(`http://localhost:${port}/web/#/album/deezer/99`);
await page.waitForSelector("[data-share-album]", { timeout: 5000 }).catch(() => {});
await page.click("[data-share-album]").catch((e) => out("partage: " + e.message.split("\n")[0]));
await page.click("[data-share-create]").catch(() => {});
await page.waitForSelector(".share-url", { timeout: 5000 }).catch(() => {});
out(`lien de partage: ${await page.$eval(".share-url", (e) => e.textContent).catch(() => "absent")}`);
await page.keyboard.press("Escape");
await page.goto(`http://localhost:${port}/web/#/s/tok123456789abcdefghij`);
await page.waitForSelector(".hero h1", { timeout: 5000 }).catch(() => {});
out(`lien reçu: ${await page.$eval(".hero h1", (e) => e.textContent).catch(() => "absent")}`);
await page.waitForTimeout(800);
// 10. aide raccourcis
await page.keyboard.press("Escape");
await page.keyboard.press("?");
out(`aide raccourcis: ${await page.$$eval(".shortcuts .sc", (e) => e.length)} lignes`);
// 8. hors ligne : téléchargement puis lecture depuis le stockage
await page.keyboard.press("Escape");
await page.evaluate(async () => { await offlineDownload({ source: "deezer", source_id: "7", title: "Hors", artist: "Favé", duration_seconds: 3 }); });
out(`téléchargé: ${await page.evaluate(() => offlineHas({ source: "deezer", source_id: "7" }))}`);
await page.evaluate(() => { audio.pause(); playList([{ source: "deezer", source_id: "7", title: "Hors", artist: "Favé", duration_seconds: 3 }], 0, ""); });
await page.waitForFunction(() => audio.src.startsWith("blob:"), null, { timeout: 5000 }).then(() => out("lecture depuis blob: ok"), () => out("lecture depuis blob: ÉCHEC src=" + "?"));
await page.goto(`http://localhost:${port}/web/#/library/downloads`);
await page.waitForSelector(".tracks .tr", { timeout: 5000 }).then(() => out("page Téléchargés: ok"), () => out("page Téléchargés: vide"));
out(errors.length ? `ERREURS:\n${errors.join("\n")}` : "aucune erreur JS");
process.exitCode = errors.length || lines.some((l) => /: (false|ÉCHEC|vide|absents?)/.test(l)) ? 1 : 0;
await browser.close(); server.close();
