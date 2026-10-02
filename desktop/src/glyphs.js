/* Petites icônes (lecture, pause, suivant, précédent) pour les
   boutons de l'aperçu dans la barre des tâches et le menu de la zone de
   notification. Dessinées ici, en mémoire, plutôt que livrées en PNG :
   Windows les veut en image bitmap et Electron ne lit pas le SVG. */

const { nativeImage } = require("electron");

// Formes dans un carré de 24 × 24 (comme les icônes de Sona web).
const SHAPES = {
  play: [[[8, 4.5], [19.5, 12], [8, 19.5]]],
  pause: [[[6, 4.5], [10, 4.5], [10, 19.5], [6, 19.5]], [[14, 4.5], [18, 4.5], [18, 19.5], [14, 19.5]]],
  next: [[[3, 6], [11.5, 12], [3, 18]], [[11.5, 6], [20, 12], [11.5, 18]]],
  previous: [[[21, 6], [12.5, 12], [21, 18]], [[12.5, 6], [4, 12], [12.5, 18]]],
};

function inside(poly, x, y) {
  let hit = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i];
    const [xj, yj] = poly[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) hit = !hit;
  }
  return hit;
}

const cache = new Map();

/** Icône `name` en `size` pixels (multiplié par `scale` pour les écrans
    HiDPI), blanche sur thème sombre, noire sur thème clair. */
function glyph(name, size = 16, scale = 2, light = false) {
  const key = `${name}:${size}:${scale}:${light}`;
  if (cache.has(key)) return cache.get(key);
  const px = size * scale;
  const buffer = Buffer.alloc(px * px * 4);
  const polys = SHAPES[name];
  const SS = 4; // suréchantillonnage : bords lissés
  for (let y = 0; y < px; y++) {
    for (let x = 0; x < px; x++) {
      let covered = 0;
      for (let sy = 0; sy < SS; sy++) {
        for (let sx = 0; sx < SS; sx++) {
          const u = ((x + (sx + 0.5) / SS) / px) * 24;
          const v = ((y + (sy + 0.5) / SS) / px) * 24;
          if (polys.some((p) => inside(p, u, v))) covered++;
        }
      }
      // Couleurs prémultipliées (blanc : a,a,a,a ; noir : 0,0,0,a) :
      // identiques quel que soit l'ordre des canaux du système.
      const a = Math.round((covered / (SS * SS)) * 255);
      const i = (y * px + x) * 4;
      buffer.fill(light ? 0 : a, i, i + 3);
      buffer[i + 3] = a;
    }
  }
  const image = nativeImage.createFromBitmap(buffer, { width: px, height: px, scaleFactor: scale });
  cache.set(key, image);
  return image;
}

module.exports = { glyph };
