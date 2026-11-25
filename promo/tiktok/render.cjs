// Rendu : node render.cjs <dossier-frames> [fps] [workers]  — puis encodage avec ffmpeg (voir README).
const { chromium } = require("playwright");
const path = require("node:path"), fs = require("node:fs");
(async () => {
  const dir = path.resolve(process.argv[2]), fps = +process.argv[3] || 60, W = +process.argv[4] || 3;
  fs.mkdirSync(dir, { recursive: true });
  const b = await chromium.launch();
  const probe = await b.newPage({ viewport: { width: 1080, height: 1920 } });
  await probe.goto("file://" + path.resolve("index.html") + "?capture"); await probe.evaluate(() => window.ready);
  const total = Math.round((await probe.evaluate(() => window.DURATION)) * fps) + Math.round(fps * 0.5); // 0,5 s de fin sur le dernier plan
  await probe.close();
  console.log("frames:", total);
  let done = 0; const t0 = Date.now();
  await Promise.all(Array.from({ length: W }, async (_, w) => {
    const p = await b.newPage({ viewport: { width: 1080, height: 1920 }, deviceScaleFactor: 1 });
    await p.goto("file://" + path.resolve("index.html") + "?capture"); await p.evaluate(() => window.ready);
    for (let i = w; i < total; i += W) {
      await p.evaluate((t) => window.seek(Math.min(t, window.DURATION - 0.001)), i / fps);
      await p.screenshot({ path: path.join(dir, `f${String(i).padStart(5, "0")}.png`) });
      if (++done % 120 === 0) console.log(done, "/", total, ((Date.now() - t0) / 1000).toFixed(0) + "s");
    }
  }));
  await b.close(); console.log("ok", ((Date.now() - t0) / 1000).toFixed(0) + "s");
})();
