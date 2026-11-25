// Filme la vraie app Sona image par image (horloge simulée → rendu déterministe).
const { chromium } = require("playwright");
const fs = require("node:fs");
const URL = "http://localhost:8765/web/";

async function open({ mode = "mobile", look = {}, hash = "#/", dsf } = {}) {
  const b = await chromium.launch({ args: ["--autoplay-policy=no-user-gesture-required", "--disable-gpu-vsync"] });
  const mobile = mode === "mobile";
  const ctx = await b.newContext({ viewport: mobile ? { width: 430, height: 932 } : { width: 1440, height: 900 }, deviceScaleFactor: dsf || (mobile ? 2 : 1.5),
    serviceWorkers: "block", isMobile: mobile, hasTouch: mobile, locale: "fr-FR", timezoneId: "Europe/Paris", colorScheme: "dark" });
  await ctx.addInitScript((look) => { localStorage.setItem("sona.token", "demo"); localStorage.setItem("sona.look", JSON.stringify(look)); }, { menu: "ouvert", ...look });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => console.log("PAGEERROR", e.message));
  await page.goto(URL + hash);
  await page.waitForTimeout(1800);
  return { b, ctx, page, mobile };
}

/** Virtualise le temps : horloge, rAF, animations CSS et audio.currentTime. */
async function freeze(page, audioStart = 0) {
  await page.evaluate((t0) => {
    const a = document.getElementById("audio");
    window.__vt = t0;
    Object.defineProperty(a, "currentTime", { configurable: true, get: () => window.__vt, set: (v) => { window.__vt = v; } });
    Object.defineProperty(a, "paused", { configurable: true, get: () => false });
    Object.defineProperty(a, "duration", { configurable: true, get: () => 222 });
    Object.defineProperty(a, "readyState", { configurable: true, get: () => 4 });
    Object.defineProperty(a, "seeking", { configurable: true, get: () => false });
    window.__ms = 0; window.__t0 = new WeakMap();
  }, audioStart);
  await page.clock.install();
  await page.clock.pauseAt(Date.now() + 1000); // fige l'horloge ; runFor() l'avance à la main
  await page.evaluate(() => { try { Object.assign(lyricsClockState, { ct: -1, at: 0, est: 0, perf: 0, val: 0 }); syncLyrics(true); } catch {} });
  await step(page, 17);
}
/** Avance d'une image (dt en ms). */
async function step(page, dt) {
  await page.clock.runFor(dt);
  await page.evaluate((dt) => {
    window.__ms += dt; window.__vt += dt / 1000;
    for (const an of document.getAnimations()) {
      if (!window.__t0.has(an)) window.__t0.set(an, window.__ms);
      try { an.pause(); an.currentTime = window.__ms - window.__t0.get(an); } catch {}
    }
  }, dt);
}
module.exports = { open, freeze, step };
