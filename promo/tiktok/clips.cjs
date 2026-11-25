// Filme les écrans réels de Sona, image par image (60 i/s), pour le montage.
// usage : node clips.cjs <dossier-sortie> <clip|all> [--only=n,n,n]   (--only : quelques images pour tester)
const { open, freeze, step } = require("./appcap.cjs");
const fs = require("node:fs"), path = require("node:path");
const FPS = 60, DT = 1000 / FPS;
// Position du morceau au début du clip de la scène « s_ly » : song_start + instant de la scène + 0,3 s (même décalage que motion.html).
const TLSRC = fs.readFileSync(path.join(__dirname, "timeline.js"), "utf8").replace(/\/\/[^\n]*/g, "");
const TL = JSON.parse(TLSRC.slice(TLSRC.indexOf("{"), TLSRC.lastIndexOf("}") + 1));
const LY_AT = TL.song_start + (TL.scenes.find((s) => s.id === "s_ly").b0 - (TL.hook_beats || 0)) * 60 / TL.bpm + 0.3;   // le teaser décale la vidéo, pas le morceau
const HOOK_AT = TL.hook_song_start || 0;
const ease = (t) => 1 - Math.pow(1 - t, 3);

const CLIPS = {
  // Lecteur plein écran, paroles mot à mot (téléphone)
  lyrics: { mode: "mobile", dsf: 3, track: "word", secs: 6.0, async setup(p) {
    await p.evaluate(async () => { const t = await api("/__track/lyrics"); playList([t], 0, "Comptines"); }); await p.waitForTimeout(1200);
    await p.evaluate(() => openNowPlaying("lyrics")); await p.mouse.move(2, 2); await p.waitForTimeout(2500); return { audio: LY_AT };
  } },
  // Lecteur plein écran de l'app iOS (réplique ios-player.html), image par image à la position réelle dans le morceau
  iosplayer: { custom: "ios", view: "player", dsf: 3, secs: 6.0 },
  ioslyrics: { custom: "ios", view: "lyrics", dsf: 3, secs: 6.4, track: true },
  // Lecteur plein écran du titre vedette (quand il n'y a pas de paroles à montrer)
  player: { mode: "mobile", dsf: 3, secs: 6.0, async setup(p) {
    await p.evaluate(async () => { const t = await api("/__track/hero"); playList([t], 0, "Rap français"); }); await p.waitForTimeout(1200);
    await p.evaluate(() => openNowPlaying("art")); await p.mouse.move(2, 2); await p.waitForTimeout(2500); return { audio: LY_AT };
  } },
  // Accueil sur ordinateur, défilement doux
  home: { mode: "desktop", dsf: 2, secs: 4.8, async setup(p) { await p.mouse.move(2, 2); await p.waitForTimeout(800); },
    async frame(p, i, n) { const y = 520 * ease(Math.min(1, Math.max(0, (i - 130) / (n - 150)))); await p.evaluate((y) => { document.querySelector("#content").scrollTop = y; }, y); } },
  // Appareils : on pilote l'iPhone depuis l'ordinateur
  devices: { mode: "desktop", dsf: 2, connect: true, secs: 4.8, hash: "#/devices", async setup(p) { await p.mouse.move(2, 2); await p.waitForTimeout(800); },
    async frame(p, i) { if (i === 60) await p.evaluate(() => pickDevice("iph1")); } },
  // Récap du mois (stories), téléphone
  recap: { mode: "mobile", dsf: 3, secs: 4.8, hash: "#/stats", async setup(p) { await p.mouse.move(2, 2); await p.waitForTimeout(800); await p.evaluate(() => openRecap("month", -1)); await p.waitForTimeout(900); },
    async frame(p, i) { if (i === 80 || i === 170 || i === 250) await p.evaluate(() => document.querySelector(".recap-tap.right")?.click()); } },
};

/** Lecteur iOS : pas de faux temps à gérer, la page est pilotée par setT(temps du morceau). */
async function captureIos(name, c, dir, only) {
  const { chromium } = require("playwright");
  const cat = JSON.parse(fs.readFileSync(path.join(__dirname, "_assets/catalog.json"), "utf8")), h = process.env.LYRICS_TITLE ? cat.lyrics : cat.tracks[0]; // démo : titre aux paroles du domaine public
  const url = `http://localhost:8765/promo/ios-player.html?view=${c.view}&cover=${encodeURIComponent("/asset/" + h.cover)}&title=${encodeURIComponent(h.title)}&artist=${encodeURIComponent(h.artist)}${c.bare ? "&bare=1" : ""}&bpm=${TL.bpm}&beat0=0.209&dur=${h.duration}&shift=${process.env.LYRICS_TITLE ? (LY_AT + 0.8 - 5.0) : 0}&lyrics=${encodeURIComponent("/lyrics?title=" + (process.env.LYRICS_TITLE || h.title) + "&artist=" + h.artist)}`;
  const b = await chromium.launch(), p = await b.newPage({ viewport: { width: 430, height: 932 }, deviceScaleFactor: c.dsf });
  p.on("pageerror", (e) => console.log("PAGEERROR", e.message));
  await p.goto(url); await p.evaluate(() => window.ready);
  const n = Math.round(c.secs * FPS), rects = [], t0 = Date.now();
  for (let i = 0; i < n; i++) {
    await p.evaluate((t) => window.setT(t), (c.start ?? LY_AT) + i / FPS);
    if (c.track) rects.push(await p.evaluate(() => (window.wordRect ? window.wordRect() : null)));
    if (!only.length || only.includes(i)) await p.screenshot({ path: path.join(dir, `f${String(i).padStart(4, "0")}.jpg`), type: "jpeg", quality: 90 });
  }
  if (c.track) fs.writeFileSync(path.join(dir, "track.js"), `window.TRACKS = window.TRACKS || {}; window.TRACKS[${JSON.stringify(name)}] = ${JSON.stringify({ viewport: [430, 932], rects })};`);
  console.log(name, n, "images", ((Date.now() - t0) / 1000).toFixed(0) + "s");
  await b.close();
}

(async () => {
  const [, , outDir, which = "all", ...flags] = process.argv;
  const only = (flags.find((f) => f.startsWith("--only=")) || "").slice(7).split(",").filter(Boolean).map(Number);
  for (const name of which === "all" ? Object.keys(CLIPS) : which.split(",")) {
    const c = CLIPS[name], dir = path.join(outDir, name); fs.mkdirSync(dir, { recursive: true });
    if (c.custom === "ios") { await captureIos(name, c, dir, only); continue; }
    await fetch("http://localhost:8765/__mock?connect=" + (c.connect ? 1 : 0));
    const { b, page } = await open({ mode: c.mode, hash: c.hash || "#/", dsf: c.dsf });
    const track = [];
    const r = (await c.setup(page)) || {};
    await freeze(page, r.audio || 0);
    const n = Math.round(c.secs * FPS), t0 = Date.now();
    for (let i = 0; i < n; i++) {
      if (c.frame) await c.frame(page, i, n);
      await step(page, DT);
      if (c.track) track.push(await page.evaluate((sel) => {
        // « word » : le mot que Sona est en train de remplir (--p entre 0 et 1), sinon le dernier chanté de la ligne active
        let e;
        if (sel === "word") { const ws = [...document.querySelectorAll("#lyr p.on .w")], pv = (w) => parseFloat(w.style.getPropertyValue("--p") || 0); e = ws.find((w) => pv(w) > 0 && pv(w) < 1) || ws.filter((w) => pv(w) >= 1).pop() || ws[0]; }
        else e = document.querySelector(sel);
        if (!e) return null; const r = e.getBoundingClientRect(); return [r.x, r.y, r.width, r.height].map((v) => Math.round(v * 10) / 10);
      }, c.track));
      if (!only.length || only.includes(i)) await page.screenshot({ path: path.join(dir, `f${String(i).padStart(4, "0")}.jpg`), type: "jpeg", quality: 90 });
    }
    if (c.track) fs.writeFileSync(path.join(dir, "track.json"), JSON.stringify({ viewport: [c.mode === "mobile" ? 430 : 1440, c.mode === "mobile" ? 932 : 900], rects: track }));
    if (c.track) fs.writeFileSync(path.join(dir, "track.js"), `window.TRACKS = window.TRACKS || {}; window.TRACKS[${JSON.stringify(name)}] = ${JSON.stringify({ viewport: [430, 932], rects: track })};`);
    console.log(name, n, "images", ((Date.now() - t0) / 1000).toFixed(0) + "s");
    await b.close();
  }
})();
