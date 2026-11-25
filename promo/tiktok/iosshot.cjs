// Aperçu du lecteur iOS : node iosshot.cjs <sortie.png> <temps-du-morceau> [dsf]
const { chromium } = require("playwright"); const fs = require("node:fs"), path = require("node:path");
(async () => {
  const [, , out, t = "38.8", dsf = "1"] = process.argv;
  const cat = JSON.parse(fs.readFileSync(path.join(__dirname, "_assets/catalog.json"), "utf8")), h = cat.tracks[0];
  const url = `http://localhost:8765/promo/ios-player.html?cover=${encodeURIComponent("/asset/" + h.cover)}&title=${encodeURIComponent(h.title)}&artist=${encodeURIComponent(h.artist)}&bpm=138&beat0=0.209&dur=${h.duration}`;
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 430, height: 932 }, deviceScaleFactor: +dsf });
  p.on("pageerror", (e) => console.log("PAGEERROR", e.message)); p.on("console", (m) => m.type() === "error" && console.log("CONSOLE", m.text()));
  await p.goto(url); await p.evaluate(() => window.ready); await p.evaluate((t) => window.setT(+t), t); await p.screenshot({ path: out }); await b.close();
})();
