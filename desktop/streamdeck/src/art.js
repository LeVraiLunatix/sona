/* Images des touches : du SVG, dessiné ici (les mêmes formes que les icônes
   de Sona web), en verre sombre avec la touche de rose de Sona. La touche
   « En cours » montre la pochette du titre.

   Stream Deck dessine le SVG avec Qt (SVG Tiny 1.2), bien plus limité qu'un
   navigateur : pas de couleurs `rgba()` (opacité à part, `fill-opacity`),
   pas de filtres, images intégrées en `xlink:href`. Envoyé en base64. */

const ICON = {
  play: "M7 4.8v14.4c0 .8.9 1.3 1.6.9l11.2-7.2c.6-.4.6-1.4 0-1.8L8.6 3.9C7.9 3.5 7 4 7 4.8z",
  pause: "M7 4h3.2c.4 0 .8.4.8.8v14.4c0 .4-.4.8-.8.8H7c-.4 0-.8-.4-.8-.8V4.8c0-.4.4-.8.8-.8zm6.8 0H17c.4 0 .8.4.8.8v14.4c0 .4-.4.8-.8.8h-3.2c-.4 0-.8-.4-.8-.8V4.8c0-.4.4-.8.8-.8z",
  next: "M3 6.3v11.4c0 .7.8 1.1 1.4.7l8.1-5.7c.5-.4.5-1.1 0-1.4L4.4 5.6C3.8 5.2 3 5.6 3 6.3zm9.5 0v11.4c0 .7.8 1.1 1.4.7l8.1-5.7c.5-.4.5-1.1 0-1.4l-8.1-5.7c-.6-.4-1.4 0-1.4.7z",
  previous: "M21 17.7V6.3c0-.7-.8-1.1-1.4-.7l-8.1 5.7c-.5.4-.5 1.1 0 1.4l8.1 5.7c.6.4 1.4 0 1.4-.7zm-9.5 0V6.3c0-.7-.8-1.1-1.4-.7L2 11.3c-.5.4-.5 1.1 0 1.4l8.1 5.7c.6.4 1.4 0 1.4-.7z",
  heart: "M12 20.3c-.3 0-.6-.1-.8-.3C5.3 14.9 2.5 12 2.5 8.5A4.8 4.8 0 0 1 7.3 3.6c1.9 0 3.5 1 4.7 2.6 1.2-1.6 2.8-2.6 4.7-2.6a4.8 4.8 0 0 1 4.8 4.9c0 3.5-2.8 6.4-8.7 11.5-.2.2-.5.3-.8.3zM7.3 5.6A2.8 2.8 0 0 0 4.5 8.5c0 2.5 2.3 5 7.5 9.4 5.2-4.4 7.5-6.9 7.5-9.4a2.8 2.8 0 0 0-2.8-2.9c-1.5 0-2.7 1-3.8 2.8a1 1 0 0 1-1.8 0c-1.1-1.8-2.3-2.8-3.8-2.8z",
  heartFill: "M12 20.3c-.3 0-.6-.1-.8-.3C5.3 14.9 2.5 12 2.5 8.5A4.8 4.8 0 0 1 7.3 3.6c1.9 0 3.5 1 4.7 2.6 1.2-1.6 2.8-2.6 4.7-2.6a4.8 4.8 0 0 1 4.8 4.9c0 3.5-2.8 6.4-8.7 11.5-.2.2-.5.3-.8.3z",
  shuffle: "M17.3 4.3a1 1 0 0 1 1.4 0l2.5 2.5a1 1 0 0 1 0 1.4l-2.5 2.5a1 1 0 1 1-1.4-1.4l.8-.8h-1.6c-1.2 0-2.3.6-3 1.6l-3.8 5.6A5.6 5.6 0 0 1 5 18.3H3a1 1 0 1 1 0-2h2c1.2 0 2.3-.6 3-1.6l3.8-5.6a5.6 5.6 0 0 1 4.7-2.6h1.6l-.8-.8a1 1 0 0 1 0-1.4zM3 7.5h2c1.9 0 3.6.9 4.7 2.4l-1.2 1.8-.5-.7a3.6 3.6 0 0 0-3-1.5H3a1 1 0 1 1 0-2zm10.3 7.1 1.2-1.8.5.7c.7 1 1.8 1.6 3 1.6h.1l-.8-.8a1 1 0 1 1 1.4-1.4l2.5 2.5a1 1 0 0 1 0 1.4l-2.5 2.5a1 1 0 1 1-1.4-1.4l.8-.8h-.1a5.6 5.6 0 0 1-4.7-2.5z",
  repeat: "M17.3 2.3a1 1 0 0 1 1.4 0l2.5 2.5a1 1 0 0 1 0 1.4l-2.5 2.5a1 1 0 1 1-1.4-1.4l.8-.8H7a3 3 0 0 0-3 3v1a1 1 0 1 1-2 0v-1a5 5 0 0 1 5-5h11.1l-.8-.8a1 1 0 0 1 0-1.4zM21 11.5a1 1 0 0 1 1 1v1a5 5 0 0 1-5 5H5.9l.8.8a1 1 0 1 1-1.4 1.4l-2.5-2.5a1 1 0 0 1 0-1.4l2.5-2.5a1 1 0 1 1 1.4 1.4l-.8.8H17a3 3 0 0 0 3-3v-1a1 1 0 0 1 1-1z",
  speaker: "M11 4.5v15c0 .8-.9 1.2-1.5.7L5.3 16.5H3a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1h2.3l4.2-3.7c.6-.5 1.5-.1 1.5.7zm4.6 2.8a1 1 0 0 1 1.4 0 6.6 6.6 0 0 1 0 9.4 1 1 0 1 1-1.4-1.4 4.6 4.6 0 0 0 0-6.6 1 1 0 0 1 0-1.4z",
  volumeUp: "M11 4.5v15c0 .8-.9 1.2-1.5.7L5.3 16.5H3a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1h2.3l4.2-3.7c.6-.5 1.5-.1 1.5.7zM18 8a1 1 0 0 1 1 1v2h2a1 1 0 1 1 0 2h-2v2a1 1 0 1 1-2 0v-2h-2a1 1 0 1 1 0-2h2V9a1 1 0 0 1 1-1z",
  volumeDown: "M11 4.5v15c0 .8-.9 1.2-1.5.7L5.3 16.5H3a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1h2.3l4.2-3.7c.6-.5 1.5-.1 1.5.7zM15 11h6a1 1 0 1 1 0 2h-6a1 1 0 1 1 0-2z",
  note: "M19 3.2v11.3a3.5 3.5 0 1 1-2-3.2V7.4L10 9v7.5a3.5 3.5 0 1 1-2-3.2V6.2c0-.5.3-.9.8-1l9-2c.6-.1 1.2.3 1.2 1z",
  sona: "M5.5 10v4M9.5 6.5v11M13.5 9v6M17.5 11v2",
  playlistAdd: "M3 5h12v2H3zm0 5h12v2H3zm0 5h8v2H3zm15-1v-3h-2v3h-3v2h3v3h2v-3h3v-2z",
  radio: "M12 10a2 2 0 1 1 0 4 2 2 0 0 1 0-4zm-4.2-3.6 1.4 1.4a6 6 0 0 0 0 8.4l-1.4 1.4a8 8 0 0 1 0-11.2zm8.4 0a8 8 0 0 1 0 11.2l-1.4-1.4a6 6 0 0 0 0-8.4zM4.9 3.5l1.4 1.4a10 10 0 0 0 0 14.2l-1.4 1.4a12 12 0 0 1 0-17zm14.2 0a12 12 0 0 1 0 17l-1.4-1.4a10 10 0 0 0 0-14.2z",
  quote: "M5 3h14a3 3 0 0 1 3 3v9a3 3 0 0 1-3 3h-6.6l-4.8 3.6A1 1 0 0 1 6 20.8V18H5a3 3 0 0 1-3-3V6a3 3 0 0 1 3-3zm2.5 5a1 1 0 1 0 0 2h9a1 1 0 1 0 0-2zm0 4a1 1 0 1 0 0 2h6a1 1 0 1 0 0-2z",
};

const ACCENT = "#fa2d6c";

export const dataUrl = (svg) => `data:image/svg+xml;base64,${Buffer.from(svg, "utf8").toString("base64")}`;
const NS = `xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" version="1.2" baseProfile="tiny"`;
const escapeXml = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&apos;" }[c]));

const glyphPath = (name, fill, opacity = 1) => name === "sona"
  ? `<path d="${ICON.sona}" stroke="${fill}" stroke-opacity="${opacity}" stroke-width="2.3" stroke-linecap="round" fill="none"/>`
  : `<path d="${ICON[name]}" fill="${fill}" fill-opacity="${opacity}"${name === "quote" ? ` fill-rule="evenodd"` : ""}/>`;

/**
 * Touche en verre : fond sombre, reflet en haut, icône blanche (rose quand
 * l'option est active). `dim` : Sona fermé ou rien en lecture.
 */
export function keySvg(name, { on = false, dim = false, size = 144 } = {}) {
  const fill = on && !dim ? ACCENT : "#ffffff";
  // Halo rose sous une option active : un dégradé radial (pas de filtre de flou).
  const glow = on && !dim ? `<circle cx="72" cy="72" r="62" fill="url(#o)"/>` : "";
  return `<svg ${NS} width="${size}" height="${size}" viewBox="0 0 144 144">
<defs>
<linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2a2633"/><stop offset="1" stop-color="#121016"/></linearGradient>
<radialGradient id="h" cx="36" cy="0" r="144" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#ffffff" stop-opacity=".22"/><stop offset=".55" stop-color="#ffffff" stop-opacity="0"/></radialGradient>
<radialGradient id="o" cx="72" cy="72" r="62" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="${ACCENT}" stop-opacity=".35"/><stop offset="1" stop-color="${ACCENT}" stop-opacity="0"/></radialGradient>
</defs>
<rect width="144" height="144" fill="url(#g)"/>
<rect width="144" height="144" fill="url(#h)"/>
${glow}
<g transform="translate(36 36) scale(3)">${glyphPath(name, fill, dim ? 0.35 : 1)}</g>
</svg>`;
}

/** Icône de la liste des actions (blanche sur fond transparent). */
export function iconSvg(name, size = 20) {
  return `<svg ${NS} width="${size}" height="${size}" viewBox="0 0 24 24">${glyphPath(name, "#ffffff")}</svg>`;
}

/** Icône du plugin (boutique et catégorie) : le logo de Sona. */
export function pluginSvg(size = 288) {
  return `<svg ${NS} width="${size}" height="${size}" viewBox="0 0 24 24">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#a06bff"/><stop offset="1" stop-color="#ff4f8b"/></linearGradient></defs>
<rect width="24" height="24" rx="5.4" fill="url(#g)"/>${glyphPath("sona", "#ffffff")}</svg>`;
}

/**
 * Touche « En cours » : la pochette, un dégradé pour lire le titre, et une
 * pastille lecture/pause en verre. Sans pochette : une note.
 */
export function coverSvg({ image, paused, title, artist }) {
  const art = image
    ? `<image xlink:href="${image}" x="0" y="0" width="144" height="144" preserveAspectRatio="xMidYMid slice"/>`
    : `<rect width="144" height="144" fill="#1b1820"/><g transform="translate(48 30) scale(2)">${glyphPath("note", "#ffffff", 0.4)}</g>`;
  const label = title
    ? `<rect y="88" width="144" height="56" fill="url(#s)"/>
<text x="10" y="118" font-family="Segoe UI, Arial" font-weight="700" font-size="17" fill="#fff">${escapeXml(truncate(title, 14))}</text>
<text x="10" y="136" font-family="Segoe UI, Arial" font-size="14" fill="#ffffff" fill-opacity=".75">${escapeXml(truncate(artist, 16))}</text>`
    : "";
  return `<svg ${NS} width="144" height="144" viewBox="0 0 144 144">
<defs><linearGradient id="s" x1="0" y1="88" x2="0" y2="144" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#000000" stop-opacity="0"/><stop offset="1" stop-color="#000000" stop-opacity=".78"/></linearGradient></defs>
${art}${label}
<circle cx="120" cy="24" r="17" fill="#14141a" fill-opacity=".55" stroke="#ffffff" stroke-opacity=".35" stroke-width="1"/>
<g transform="translate(110.5 14.5) scale(.8)">${glyphPath(paused ? "play" : "pause", "#ffffff")}</g>
</svg>`;
}

function truncate(text, n) {
  text = String(text || "");
  return text.length > n ? `${text.slice(0, n - 1)}…` : text;
}

export const ICON_NAMES = Object.keys(ICON);
