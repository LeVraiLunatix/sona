// Télécharge les logos des cinq apps de streaming depuis Wikimedia Commons (https://commons.wikimedia.org) → _assets/brands/ (non versionné).
// Ce sont des marques déposées de leurs propriétaires : à utiliser avec prudence (publicité comparative).
// Wikimedia limite le débit (erreur 429) : une requête à la fois, pauses, reprises. User-Agent identifié, comme ils le demandent.
const { execFileSync } = require("node:child_process");
const fs = require("node:fs"), path = require("node:path");
const OUT = path.join(__dirname, "_assets", "brands"); fs.mkdirSync(OUT, { recursive: true });
const UA = "SonaPromoScript/1.0 (video promo; contact via repo LeVraiLunatix/sona)";
const FILES = [   // nom du fichier sur Commons → nom local
  ["Apple_Music_icon.svg", "apple-music.svg"],
  ["Spotify_logo_without_text.svg", "spotify.svg"],
  ["Deezer_New_Icon.svg", "deezer.svg"],
  ["Antu_soundcloud.svg", "soundcloud.svg"],
  ["Youtube_Music_icon.svg", "youtube-music.svg"],
];
const sleep = (s) => execFileSync("sleep", [String(s)]);
for (const [name, local] of FILES) {
  const dest = path.join(OUT, local), tmp = dest + ".tmp";
  if (fs.existsSync(dest) && fs.statSync(dest).size > 500 && !fs.readFileSync(dest).slice(0, 40).toString().includes("too many requests")) { console.log("déjà là :", local); continue; }
  for (let essai = 1; essai <= 10; essai++) {
    const h = require("node:crypto").createHash("md5").update(name).digest("hex");   // chemin direct du fichier sur upload.wikimedia.org
    const url = `https://upload.wikimedia.org/wikipedia/commons/${h[0]}/${h.slice(0, 2)}/${name}`;
    const code = execFileSync("curl", ["-sL", "-m", "40", "-A", UA, "-o", tmp, "-w", "%{http_code}", url]).toString();
    if (code === "200" && fs.statSync(tmp).size > 500) { fs.renameSync(tmp, dest); console.log("ok :", local, fs.statSync(dest).size, "octets"); break; }
    if (fs.existsSync(tmp)) fs.unlinkSync(tmp);   // jamais de page d'erreur gardée comme image
    console.log(`  ${local}: HTTP ${code}, nouvel essai dans ${15 * essai} s`); sleep(15 * essai);
  }
  sleep(6);
}
