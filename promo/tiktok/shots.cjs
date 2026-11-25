// Aperçus : node shots.cjs <page.html> <dossier> <t1> <t2> ...
const { chromium } = require("playwright");
const path = require("node:path");
(async () => {
  const [, , page_, out, ...ts] = process.argv;
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1080, height: 1920 }, deviceScaleFactor: 1 });
  p.on("pageerror", (e) => console.log("PAGEERROR", e.message));
  p.on("requestfailed", (r) => console.log("FAILED", r.url().slice(-60)));
  await p.goto("file://" + path.resolve(page_) + "?capture" + (process.env.GUIDES ? "&guides" : ""));
  await p.evaluate(() => window.ready);
  for (const t of ts) { await p.evaluate((t) => window.seek(+t), t); await p.screenshot({ path: `${out}/m${String(t).replace(".", "_")}.png` }); }
  await b.close();
})();
