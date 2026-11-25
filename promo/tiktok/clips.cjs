// Filme les écrans réels de Sona, image par image (60 i/s), pour le montage.
// usage : node clips.cjs <dossier-sortie> <clip|all> [--only=n,n,n]   (--only : quelques images pour tester)
const { open, freeze, step } = require("./appcap.cjs");
const fs = require("node:fs"), path = require("node:path");
const FPS = 60, DT = 1000 / FPS;
const ease = (t) => 1 - Math.pow(1 - t, 3);

const CLIPS = {
  // Lecteur plein écran, paroles mot à mot (téléphone)
  lyrics: { mode: "mobile", secs: 6.0, async setup(p) {
    await p.evaluate(async () => { const t = await api("/__track/lyrics"); playList([t], 0, "Comptines"); }); await p.waitForTimeout(1200);
    await p.evaluate(() => openNowPlaying("lyrics")); await p.mouse.move(2, 2); await p.waitForTimeout(2500); return { audio: 5.0 };
  } },
  // Accueil sur ordinateur, défilement doux
  home: { mode: "desktop", secs: 3.6, async setup(p) { await p.mouse.move(2, 2); await p.waitForTimeout(800); },
    async frame(p, i, n) { const y = 560 * ease(Math.min(1, Math.max(0, (i - 20) / (n - 50)))); await p.evaluate((y) => { document.querySelector("#content").scrollTop = y; }, y); } },
  // Appareils : on pilote l'iPhone depuis l'ordinateur
  devices: { mode: "desktop", connect: true, secs: 3.6, hash: "#/devices", async setup(p) { await p.mouse.move(2, 2); await p.waitForTimeout(800); },
    async frame(p, i) { if (i === 50) await p.evaluate(() => pickDevice("iph1")); } },
  // Récap du mois (stories), téléphone
  recap: { mode: "mobile", secs: 4.2, hash: "#/stats", async setup(p) { await p.mouse.move(2, 2); await p.waitForTimeout(800); await p.evaluate(() => openRecap("month", -1)); await p.waitForTimeout(900); },
    async frame(p, i) { if (i === 55 || i === 120 || i === 185) await p.evaluate(() => document.querySelector(".recap-tap.right")?.click()); } },
};

(async () => {
  const [, , outDir, which = "all", ...flags] = process.argv;
  const only = (flags.find((f) => f.startsWith("--only=")) || "").slice(7).split(",").filter(Boolean).map(Number);
  for (const name of which === "all" ? Object.keys(CLIPS) : which.split(",")) {
    const c = CLIPS[name], dir = path.join(outDir, name); fs.mkdirSync(dir, { recursive: true });
    await fetch("http://localhost:8765/__mock?connect=" + (c.connect ? 1 : 0));
    const { b, page } = await open({ mode: c.mode, hash: c.hash || "#/" });
    const r = (await c.setup(page)) || {};
    await freeze(page, r.audio || 0);
    const n = Math.round(c.secs * FPS), t0 = Date.now();
    for (let i = 0; i < n; i++) {
      if (c.frame) await c.frame(page, i, n);
      await step(page, DT);
      if (!only.length || only.includes(i)) await page.screenshot({ path: path.join(dir, `f${String(i).padStart(4, "0")}.jpg`), type: "jpeg", quality: 90 });
    }
    console.log(name, n, "images", ((Date.now() - t0) / 1000).toFixed(0) + "s");
    await b.close();
  }
})();
