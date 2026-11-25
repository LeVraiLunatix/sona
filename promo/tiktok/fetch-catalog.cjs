// Récupère un vrai catalogue (classement Deezer) + les pochettes, pour filmer l'app avec de vrais titres.
// usage : node fetch-catalog.cjs   →   _assets/catalog.json + _assets/*.jpg  (non versionnés)
const { execFileSync } = require("node:child_process");
const fs = require("node:fs"), path = require("node:path");
const OUT = path.join(__dirname, "_assets"); fs.mkdirSync(OUT, { recursive: true });
const get = (url) => JSON.parse(execFileSync("curl", ["-s", "-m", "30", url], { maxBuffer: 1 << 26 }).toString());
const save = (url, file) => { if (!url) return null; const f = path.join(OUT, file); if (!fs.existsSync(f)) execFileSync("curl", ["-s", "-m", "30", "-o", f, url]); return file; };
const slim = (t) => ({ id: String(t.id), title: t.title_short || t.title, artist: t.artist.name, artist_id: String(t.artist.id), album: t.album.title, album_id: String(t.album.id), duration: t.duration,
  cover: save(t.album.cover_big, `al${t.album.id}.jpg`), picture: save(t.artist.picture_big, `ar${t.artist.id}.jpg`) });

// 1) le classement du moment : de vrais titres que tout le monde connaît
const chart = get("https://api.deezer.com/chart/0/tracks?limit=60").data;
const seenAlbum = new Set(), tracks = [];
for (const t of chart) { if (tracks.length >= 18) break; if (seenAlbum.has(t.album.id)) continue; seenAlbum.add(t.album.id); tracks.push(slim(t)); } // un titre par album (pochettes variées)
// 2) un enregistrement réel d'une chanson dont les paroles sont dans le domaine public (« Amazing Grace », 1779),
//    pour la scène des paroles : on ne reproduit pas les paroles d'une chanson sous droits.
const lyr = get("https://api.deezer.com/track/92905736");
const catalog = { tracks, lyrics: slim(lyr) };
fs.writeFileSync(path.join(OUT, "catalog.json"), JSON.stringify(catalog, null, 1));
console.log(tracks.length, "titres ;", "paroles :", catalog.lyrics.title, "-", catalog.lyrics.artist);
tracks.forEach((t) => console.log(" ", t.title, "—", t.artist, "·", t.album));
