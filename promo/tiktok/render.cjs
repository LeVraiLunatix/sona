// Rendu : node render.cjs <page.html> <dossier-frames> [fps] [workers]  — puis encodage avec ffmpeg (voir README).
const { chromium } = require("playwright");
const path = require("node:path"), fs = require("node:fs");
(async () => {
  const page_ = process.argv[2], dir = path.resolve(process.argv[3]), fps = +process.argv[4] || 60, W = +process.argv[5] || 3;
  fs.mkdirSync(dir, { recursive: true });
  const b = await chromium.launch();
  const probe = await b.newPage({ viewport: { width: 1080, height: 1920 } });
  await probe.goto("file://" + path.resolve(page_) + "?capture" + (process.env.EXTRA || "")); await probe.evaluate(() => window.ready);
  const total = Math.round((await probe.evaluate(() => window.DURATION)) * fps) + Math.round(fps * 0.5); // 0,5 s de fin sur le dernier plan
  await probe.close();
  console.log("frames:", total);
  let done = 0; const t0 = Date.now();
  await Promise.all(Array.from({ length: W }, async (_, w) => {
    const p = await b.newPage({ viewport: { width: 1080, height: 1920 }, deviceScaleFactor: 1 });
    await p.goto("file://" + path.resolve(page_) + "?capture" + (process.env.EXTRA || "")); await p.evaluate(() => window.ready);
    const from = +process.env.FROM || 0, to = Math.min(total, +process.env.TO || total); // FROM/TO : ne refaire qu'une plage d'images
    for (let i = from + ((w - from) % W + W) % W; i < to; i += W) {
      await p.evaluate((t) => window.seek(Math.min(t, window.DURATION - 0.001)), i / fps);
      await p.screenshot({ path: path.join(dir, `f${String(i).padStart(5, "0")}.png`) });
      if (++done % 120 === 0) console.log(done, "/", total, ((Date.now() - t0) / 1000).toFixed(0) + "s");
    }
  }));
  await b.close(); console.log("ok", ((Date.now() - t0) / 1000).toFixed(0) + "s");
})();
