/* Le site (web/app.js) n'a pas de build ni de module : on en extrait les deux fonctions pures qui rangent les exclus
   (splitFeat, exclusiveGroups) et on les essaie ici. */

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const src = fs.readFileSync(path.join(__dirname, "../../web/app.js"), "utf8").replace(/\r\n/g, "\n");
const take = (re) => { const m = src.match(re); assert.ok(m, `introuvable dans app.js : ${re}`); return m[0]; };
const { splitFeat, exclusiveGroups } = new Function(`
  ${take(/^const fold = .*$/m)}
  ${take(/^const FEAT_RE = .*$/m)}
  ${take(/^function splitFeat[\s\S]*?\n}\n/m)}
  ${take(/^const ARCHIVE_NAME = .*$/m)}
  ${take(/^function exclusiveGroups[\s\S]*?\n}\n/m)}
  return { splitFeat, exclusiveGroups };
`)();

test("le feat se lit à part du titre", () => {
  assert.deepEqual(splitFeat("GEÔLE (feat. baby hayabusa)"), { title: "GEÔLE", feat: "baby hayabusa" });
  assert.deepEqual(splitFeat("Sparadrap"), { title: "Sparadrap", feat: "" });
});

test("les exclus sont rangés par artiste ; un artiste à identités devient FEMTO (archives)", () => {
  const t = (title, artist, id, extra = {}) => ({ title, artist, artist_source: "deezer", artist_source_id: id, album: "A", track_number: 1, ...extra });
  const groups = exclusiveGroups([
    t("B", "FEMTOGO", "1", { persona: "FEMTOGO" }), t("A", "FEMTOGO", "1", { persona: "FEMTOGO" }), t("C", "baby hayabusa", "1", { persona: "baby hayabusa" }),
    t("Chandail", "Strano", "strano"),
  ]);
  assert.equal(groups.length, 2);
  const femto = groups.find((g) => g.id === "1");
  assert.deepEqual([femto.archive, femto.label, femto.tracks.length], [true, "FEMTO", 3]);
  assert.equal(femto.name, "FEMTOGO"); // le nom le plus fréquent
  assert.deepEqual(femto.tracks.map((x) => x.title), ["C", "A", "B"]); // identité, puis album, numéro, titre
  assert.deepEqual([groups.find((g) => g.id === "strano").archive, groups.find((g) => g.id === "strano").label], [false, "Strano"]);
});
