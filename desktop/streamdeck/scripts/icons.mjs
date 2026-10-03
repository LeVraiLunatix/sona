// Images fixes du plugin (liste des actions, touches par défaut, icône du
// plugin), tirées des mêmes dessins que les touches vivantes.
import fs from "node:fs";
import path from "node:path";
import { iconSvg, keySvg, coverSvg } from "../src/art.js";

const root = path.join(path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1")), "..", "app.sona.remote.sdPlugin", "imgs");
const write = (rel, svg) => {
  const file = path.join(root, `${rel}.svg`);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, svg);
};

const actions = {
  playpause: "play", nowplaying: "note", next: "next", previous: "previous", like: "heart",
  shuffle: "shuffle", repeat: "repeat", volumeup: "volumeUp", volumedown: "volumeDown", dial: "speaker", seekdial: "next",
};
for (const [id, glyph] of Object.entries(actions)) {
  write(`actions/${id}/icon`, iconSvg(glyph));
  write(`actions/${id}/key`, id === "nowplaying" ? coverSvg({ image: null, paused: true }) : keySvg(glyph));
}
// Icône du plugin : Stream Deck la veut en PNG (celle de l'app Sona).
fs.mkdirSync(path.join(root, "plugin"), { recursive: true });
for (const name of ["marketplace.png", "marketplace@2x.png"]) {
  fs.copyFileSync(path.join(root, "..", "..", "assets", name), path.join(root, "plugin", name));
}
write("plugin/category-icon", iconSvg("sona", 28));
console.log("images écrites dans", root);
