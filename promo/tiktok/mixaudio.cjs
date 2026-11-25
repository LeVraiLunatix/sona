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
const hs = TL.hook_song_start || 0, H = hs ? (TL.hook_beats || 0) * 60 / TL.bpm : 0, S0 = TL.song_start, main = dur - H;
// teaser (le drop) → on « rembobine » (fondu court) → le morceau depuis song_start, fondus, −14 LUFS, whooshes très bas
const head = H ? `[0:a]atrim=start=${hs}:end=${(hs + H).toFixed(3)},asetpts=PTS-STARTPTS,afade=t=out:st=${(H - 0.09).toFixed(3)}:d=0.09[h];` : "";
const body = `[0:a]atrim=start=${S0}:end=${(S0 + main).toFixed(3)},asetpts=PTS-STARTPTS,afade=t=in:d=0.02,afade=t=out:st=${(main - 1.8).toFixed(2)}:d=1.8[m];`;
const join = H ? "[h][m]concat=n=2:v=0:a=1[c0];[c0]" : "[m]";
const V = TL.ly_volume, B = 60 / TL.bpm;   // le volume du morceau suit le curseur de volume montré à l'écran (creux léger → à fond)
const vol = V ? `,volume=eval=frame:volume='1-${1 - V.dip_to}*clip((t-${(V.dip_at * B).toFixed(3)})/0.35,0,1)+${1 - V.dip_to}*pow(clip((t-${(V.up_at * B).toFixed(3)})/${(V.up_beats * B).toFixed(3)},0,1),2)*(3-2*clip((t-${(V.up_at * B).toFixed(3)})/${(V.up_beats * B).toFixed(3)},0,1))'` : "";
const filter = `${head}${body}${join}loudnorm=I=-14:TP=-1.5:LRA=11,aresample=44100${vol}[c];[1:a]aresample=44100,volume=0.5[f];[c][f]amix=inputs=2:duration=longest:normalize=0,atrim=0:${dur.toFixed(2)}[a]`;
execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-i", song, "-i", fx, "-filter_complex", filter, "-map", "[a]", "-ac", "2", "-ar", "44100", "-c:a", "aac", "-b:a", "192k", out], { stdio: "inherit" });
console.log(`bande son : ${H ? `extrait (à ${hs}s) puis ` : ""}morceau à partir de ${TL.song_start}s, ${dur.toFixed(1)} s → ${out}`);
