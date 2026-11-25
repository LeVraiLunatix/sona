// Récupère un vrai catalogue (classement Deezer) + les pochettes, pour filmer l'app avec de vrais titres.
// usage : node fetch-catalog.cjs   →   _assets/catalog.json + _assets/*.jpg  (non versionnés)
const { execFileSync } = require("node:child_process");
const fs = require("node:fs"), path = require("node:path");
const OUT = path.join(__dirname, "_assets"); fs.mkdirSync(OUT, { recursive: true });
const get = (url) => JSON.parse(execFileSync("curl", ["-s", "-m", "30", url], { maxBuffer: 1 << 26 }).toString());
const save = (url, file) => { if (!url) return null; const f = path.join(OUT, file); if (!fs.existsSync(f)) execFileSync("curl", ["-s", "-m", "30", "-o", f, url]); return file; };
const artistPic = (a) => a.picture_big || get(`https://api.deezer.com/artist/${a.id}`).picture_big; // les « top titres » ne donnent pas la photo
const slim = (t) => ({ id: String(t.id), title: t.title_short || t.title, artist: t.artist.name, artist_id: String(t.artist.id), album: t.album.title, album_id: String(t.album.id), duration: t.duration,
  cover: save(t.album.cover_big, `al${t.album.id}.jpg`), picture: save(artistPic(t.artist), `ar${t.artist.id}.jpg`) });

// 1) rap français : le titre vedette (Ninho, « Goutte d'eau », 137,8 BPM) puis le titre phare d'artistes très connus
const HERO = get("https://api.deezer.com/track/652380182");
const ARTISTS = ["Jul", "PNL", "SCH", "Booba", "Orelsan", "Nekfeu", "Damso", "Naps", "Gazo", "Tiakola", "Lomepal", "Soolking", "Werenoi", "Hamza", "Josman", "Kaaris", "Freeze Corleone"];
const tracks = [slim(HERO)], seenAlbum = new Set([String(HERO.album.id)]);
for (const name of ARTISTS) {
  if (tracks.length >= 18) break;
  const found = get("https://api.deezer.com/search/artist?q=" + encodeURIComponent(name) + "&limit=1").data[0];
  if (!found) continue;
  const top = get(`https://api.deezer.com/artist/${found.id}/top?limit=10`).data.find((t) => !seenAlbum.has(String(t.album.id)));
  if (String(found.id) === String(HERO.artist.id)) continue;
  if (!top) continue; seenAlbum.add(String(top.album.id));
  tracks.push(slim(top));
}
// 2) un enregistrement réel d'une chanson dont les paroles sont dans le domaine public (« Amazing Grace », 1779),
//    pour la scène des paroles : on ne reproduit pas les paroles d'une chanson sous droits.
const lyr = get("https://api.deezer.com/track/92905736");
const catalog = { bpm: HERO.bpm || 137.8, tracks, lyrics: slim(lyr) };
fs.writeFileSync(path.join(OUT, "catalog.json"), JSON.stringify(catalog, null, 1));
console.log(tracks.length, "titres ;", "paroles :", catalog.lyrics.title, "-", catalog.lyrics.artist);
tracks.forEach((t) => console.log(" ", t.title, "—", t.artist, "·", t.album));
