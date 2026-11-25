// Bande son finale : extrait du VRAI morceau (celui que tu fournis) calé sur timeline.js + whooshes très bas.
// usage : node mixaudio.cjs <morceau.m4a|mp3|wav> <fx.wav> <sortie.m4a>      (fx.wav : python3 beat.py fx.wav --fx-only)
// Le morceau n'est jamais copié dans le dépôt (_assets/ est ignoré par git).
const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const [, , song, fx, out] = process.argv;
if (!song || !fx || !out) { console.error("usage : node mixaudio.cjs morceau fx.wav sortie.m4a"); process.exit(1); }
const src = fs.readFileSync(__dirname + "/timeline.js", "utf8").replace(/\/\/[^\n]*/g, "");
const TL = JSON.parse(src.slice(src.indexOf("{"), src.lastIndexOf("}") + 1));
const beats = Math.max(...TL.scenes.map((s) => s.b0 + s.beats)), dur = beats * 60 / TL.bpm + 0.6;
const filter = `[0:a]afade=t=in:d=0.04,afade=t=out:st=${(dur - 1.8).toFixed(2)}:d=1.8,loudnorm=I=-14:TP=-1.5:LRA=11,aresample=44100[m];[1:a]aresample=44100,volume=0.5[f];[m][f]amix=inputs=2:duration=longest:normalize=0,atrim=0:${dur.toFixed(2)}[a]`;
execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-ss", String(TL.song_start), "-t", dur.toFixed(2), "-i", song, "-i", fx, "-filter_complex", filter, "-map", "[a]", "-ac", "2", "-ar", "44100", "-c:a", "aac", "-b:a", "192k", out], { stdio: "inherit" });
console.log(`bande son : morceau à partir de ${TL.song_start}s, ${dur.toFixed(1)} s → ${out}`);
