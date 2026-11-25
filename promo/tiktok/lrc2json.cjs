// Convertit un fichier .lrc (paroles horodatées que TU fournis) en mock/lyrics.local.json.
// usage : node lrc2json.cjs paroles.lrc [décalage_en_secondes]
// Le fichier produit n'est pas versionné (.gitignore) : les paroles d'une chanson sous droits n'ont rien à faire dans le dépôt.
const fs = require("node:fs"), path = require("node:path");
const [, , file, shift = "0"] = process.argv;
if (!file) { console.error("usage : node lrc2json.cjs paroles.lrc [décalage]"); process.exit(1); }
const lines = [];
for (const raw of fs.readFileSync(file, "utf8").split(/\r?\n/)) {
  const m = raw.match(/^((?:\[\d+:\d+(?:\.\d+)?\])+)(.*)$/);
  if (!m) continue;
  for (const t of m[1].matchAll(/\[(\d+):(\d+(?:\.\d+)?)\]/g)) lines.push({ time: +(+t[1] * 60 + +t[2] + +shift).toFixed(2), text: m[2].trim() });
}
lines.sort((a, b) => a.time - b.time);
const out = path.join(__dirname, "mock", "lyrics.local.json");
fs.writeFileSync(out, JSON.stringify({ lines }, null, 1));
console.log(lines.length, "lignes →", out);
