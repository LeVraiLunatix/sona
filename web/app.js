/* Sona web : même compte, mêmes playlists, mêmes stats que l'app.
   Connexion Last.fm, puis tout passe par l'API du serveur Sona (jeton de
   session gardé dans le navigateur). Servi par le serveur lui-même (/web/)
   ou par Vercel : dans ce cas l'API est appelée à l'adresse de la balise
   <meta name="sona-server">.

   Sur ordinateur : barre latérale et lecteur en haut, façon music.apple.com.
   Sur téléphone : la même allure que l'app iOS (onglets en bas, mini-lecteur,
   lecteur plein écran, grands titres), et installable sur l'écran d'accueil
   comme une vraie appli (manifest.webmanifest + sw.js). */

"use strict";

// ── Utilitaires ────────────────────────────────────────────────────────────

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (s) => { s = Math.max(0, Math.floor(s || 0)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch {} },
};
/** Pochette en grand (Deezer : taille dans l'adresse). */
const big = (url, size = 1000) => (url || "").replace(/\/(\d+)x\1(-\d+-\d+-\d+-\d+)?\.jpg$/, `/${size}x${size}$2.jpg`);
const sameTrack = (a, b) => a && b && a.source === b.source && a.source_id === b.source_id;
const trackKey = (t) => `${t.source}:${t.source_id}`;
/** Fiche de titre au format de l'API (playlists, soirée, TV…). */
const cleanTrack = (t) => ({
  source: t.source, source_id: String(t.source_id), title: t.title || t.name || "", artist: t.artist || t.subtitle || "",
  album: t.album || null, year: t.year || null, duration_seconds: t.duration_seconds || null, cover_url: t.cover_url || null,
  artist_source_id: t.artist_source_id || null, album_source_id: t.album_source_id || null,
});
const isMobile = () => matchMedia("(max-width: 760px)").matches;
const standalone = matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
const isIOS = /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
const haptic = () => { try { navigator.vibrate?.(8); } catch {} };
const plural = (n, word, many = `${word}s`) => `${(n ?? 0).toLocaleString("fr-FR")} ${n > 1 ? many : word}`;
function minutesLabel(m) {
  m = Math.round(m || 0);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  return m % 60 && h < 10 ? `${h} h ${String(m % 60).padStart(2, "0")}` : `${h.toLocaleString("fr-FR")} h`;
}
/** « il y a 5 min » à partir d'une date ISO. */
function since(iso) {
  const t = Date.parse(iso);
  if (!t) return "";
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 60) return "à l'instant";
  if (s < 3600) return `il y a ${Math.round(s / 60)} min`;
  if (s < 86400) return `il y a ${Math.round(s / 3600)} h`;
  if (s < 7 * 86400) return `il y a ${Math.round(s / 86400)} j`;
  return new Date(t).toLocaleDateString("fr-FR", { day: "numeric", month: "short" });
}

// Sona pour Windows (dossier desktop/ du dépôt) : la même page, dans l'app
// d'ordinateur, qui expose `window.sonaDesktop` (télécommande du téléphone,
// mini-lecteur, zone de notification…). Voir « Sona pour Windows » plus bas.
const desktop = window.sonaDesktop || null;
if (desktop) {
  document.documentElement.classList.add("desktop", `desktop-${desktop.platform}`);
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = "desktop.css";
  document.head.append(link);
}

const SERVER = ((desktop && desktop.server) || $('meta[name="sona-server"]')?.content || "").replace(/\/$/, "");
const onServer = !SERVER || location.pathname.startsWith("/web") || (() => { try { return new URL(SERVER).origin === location.origin; } catch { return true; } })();
const BASE = onServer ? "" : SERVER;

let token = store.get("sona.token");
let account = null;
const audio = $("#audio");
const state = {
  queue: [], index: -1, name: "", shuffle: false, repeat: false,
  lyrics: null, lastLyric: -1, listened: 0, lastTick: 0, scrobbled: false, startedAt: null,
  liked: new Set(), likedAlbums: new Set(), likedArtists: new Set(),
  npOpen: false, npTab: "lyrics", smart: [], playlists: [], settings: null,
  // Radio en cours (station Deezer, radio DJ…) : la file se remplit toute seule.
  station: null,
  // `control` : l'appareil choisi dans « Appareils » pour le piloter.
  connect: { devices: [], session: null, active: null, receivedAt: 0, claim: false, open: false, control: store.get("sona.control") || null },
};

async function api(path, options = {}) {
  const res = await fetch(BASE + path, {
    ...options,
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json", ...(options.headers || {}) },
  });
  if (res.status === 401) { signOut(); throw new Error("Session expirée"); }
  if (!res.ok) {
    let msg = `Erreur ${res.status}`;
    try { msg = (await res.json()).detail || msg; } catch {}
    const err = new Error(typeof msg === "string" ? msg : `Erreur ${res.status}`);
    err.status = res.status;
    throw err;
  }
  return res.status === 204 ? null : res.json();
}

function toast(text) {
  let el = $(".toast");
  if (!el) { el = document.createElement("div"); el.className = "toast"; document.body.append(el); }
  el.textContent = text;
  el.classList.add("show");
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove("show"), 2200);
}

// ── Icônes (dans l'esprit des SF Symbols) ─────────────────────────────────

const ic = (d, vb = "0 0 24 24") => `<svg class="icon" viewBox="${vb}" aria-hidden="true"><path d="${d}"/></svg>`;
const icons = {
  play: ic("M7 4.8v14.4c0 .8.9 1.3 1.6.9l11.2-7.2c.6-.4.6-1.4 0-1.8L8.6 3.9C7.9 3.5 7 4 7 4.8z"),
  pause: ic("M7 4h3.2c.4 0 .8.4.8.8v14.4c0 .4-.4.8-.8.8H7c-.4 0-.8-.4-.8-.8V4.8c0-.4.4-.8.8-.8zm6.8 0H17c.4 0 .8.4.8.8v14.4c0 .4-.4.8-.8.8h-3.2c-.4 0-.8-.4-.8-.8V4.8c0-.4.4-.8.8-.8z"),
  next: ic("M3 6.3v11.4c0 .7.8 1.1 1.4.7l8.1-5.7c.5-.4.5-1.1 0-1.4L4.4 5.6C3.8 5.2 3 5.6 3 6.3zm9.5 0v11.4c0 .7.8 1.1 1.4.7l8.1-5.7c.5-.4.5-1.1 0-1.4l-8.1-5.7c-.6-.4-1.4 0-1.4.7z"),
  prev: ic("M21 17.7V6.3c0-.7-.8-1.1-1.4-.7l-8.1 5.7c-.5.4-.5 1.1 0 1.4l8.1 5.7c.6.4 1.4 0 1.4-.7zm-9.5 0V6.3c0-.7-.8-1.1-1.4-.7L2 11.3c-.5.4-.5 1.1 0 1.4l8.1 5.7c.6.4 1.4 0 1.4-.7z"),
  shuffle: ic("M17.3 4.3a1 1 0 0 1 1.4 0l2.5 2.5a1 1 0 0 1 0 1.4l-2.5 2.5a1 1 0 1 1-1.4-1.4l.8-.8h-1.6c-1.2 0-2.3.6-3 1.6l-3.8 5.6A5.6 5.6 0 0 1 5 18.3H3a1 1 0 1 1 0-2h2c1.2 0 2.3-.6 3-1.6l3.8-5.6a5.6 5.6 0 0 1 4.7-2.6h1.6l-.8-.8a1 1 0 0 1 0-1.4zM3 7.5h2c1.9 0 3.6.9 4.7 2.4l-1.2 1.8-.5-.7a3.6 3.6 0 0 0-3-1.5H3a1 1 0 1 1 0-2zm10.3 7.1 1.2-1.8.5.7c.7 1 1.8 1.6 3 1.6h.1l-.8-.8a1 1 0 1 1 1.4-1.4l2.5 2.5a1 1 0 0 1 0 1.4l-2.5 2.5a1 1 0 1 1-1.4-1.4l.8-.8h-.1a5.6 5.6 0 0 1-4.7-2.5z"),
  repeat: ic("M17.3 2.3a1 1 0 0 1 1.4 0l2.5 2.5a1 1 0 0 1 0 1.4l-2.5 2.5a1 1 0 1 1-1.4-1.4l.8-.8H7a3 3 0 0 0-3 3v1a1 1 0 1 1-2 0v-1a5 5 0 0 1 5-5h11.1l-.8-.8a1 1 0 0 1 0-1.4zM21 11.5a1 1 0 0 1 1 1v1a5 5 0 0 1-5 5H5.9l.8.8a1 1 0 1 1-1.4 1.4l-2.5-2.5a1 1 0 0 1 0-1.4l2.5-2.5a1 1 0 1 1 1.4 1.4l-.8.8H17a3 3 0 0 0 3-3v-1a1 1 0 0 1 1-1z"),
  search: ic("M10.5 3a7.5 7.5 0 0 1 6 12l4.3 4.3a1 1 0 0 1-1.4 1.4L15 16.5A7.5 7.5 0 1 1 10.5 3zm0 2a5.5 5.5 0 1 0 0 11 5.5 5.5 0 0 0 0-11z"),
  listen: ic("M12 2a10 10 0 1 1 0 20 10 10 0 0 1 0-20zm-1.8 6.3c-.5-.3-1.2 0-1.2.7v6c0 .7.7 1 1.2.7l5-3c.5-.3.5-1.1 0-1.4z"),
  browse: ic("M4 3h6a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1zm10 0h6a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1h-6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1zM4 13h6a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-6a1 1 0 0 1 1-1zm10 0h6a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1h-6a1 1 0 0 1-1-1v-6a1 1 0 0 1 1-1z"),
  note: ic("M19 3.2v11.3a3.5 3.5 0 1 1-2-3.2V7.4L10 9v7.5a3.5 3.5 0 1 1-2-3.2V6.2c0-.5.3-.9.8-1l9-2c.6-.1 1.2.3 1.2 1z"),
  list: ic("M4 5h12a1 1 0 1 1 0 2H4a1 1 0 0 1 0-2zm0 6h12a1 1 0 1 1 0 2H4a1 1 0 1 1 0-2zm0 6h7a1 1 0 1 1 0 2H4a1 1 0 1 1 0-2zm15-4.5v4.1a2.4 2.4 0 1 1-1.5-2.2V11c0-.4.3-.8.7-.8l2.5-.6a.8.8 0 0 1 .3 1.5z"),
  heart: ic("M12 20.3c-.3 0-.6-.1-.8-.3C5.3 14.9 2.5 12 2.5 8.5A4.8 4.8 0 0 1 7.3 3.6c1.9 0 3.5 1 4.7 2.6 1.2-1.6 2.8-2.6 4.7-2.6a4.8 4.8 0 0 1 4.8 4.9c0 3.5-2.8 6.4-8.7 11.5-.2.2-.5.3-.8.3zM7.3 5.6A2.8 2.8 0 0 0 4.5 8.5c0 2.5 2.3 5 7.5 9.4 5.2-4.4 7.5-6.9 7.5-9.4a2.8 2.8 0 0 0-2.8-2.9c-1.5 0-2.7 1-3.8 2.8a1 1 0 0 1-1.8 0c-1.1-1.8-2.3-2.8-3.8-2.8z"),
  heartFill: ic("M12 20.3c-.3 0-.6-.1-.8-.3C5.3 14.9 2.5 12 2.5 8.5A4.8 4.8 0 0 1 7.3 3.6c1.9 0 3.5 1 4.7 2.6 1.2-1.6 2.8-2.6 4.7-2.6a4.8 4.8 0 0 1 4.8 4.9c0 3.5-2.8 6.4-8.7 11.5-.2.2-.5.3-.8.3z"),
  quote: ic("M5 3h14a3 3 0 0 1 3 3v9a3 3 0 0 1-3 3h-6.6l-4.8 3.6A1 1 0 0 1 6 20.8V18H5a3 3 0 0 1-3-3V6a3 3 0 0 1 3-3zm2.5 5a1 1 0 1 0 0 2h9a1 1 0 1 0 0-2zm0 4a1 1 0 1 0 0 2h6a1 1 0 1 0 0-2z"),
  queue: ic("M3 5h13a1 1 0 1 1 0 2H3a1 1 0 0 1 0-2zm0 6h13a1 1 0 1 1 0 2H3a1 1 0 1 1 0-2zm0 6h9a1 1 0 1 1 0 2H3a1 1 0 1 1 0-2zm15-2.4v-3.2c0-.6.7-1 1.2-.6l2.4 1.6c.5.3.5 1 0 1.3l-2.4 1.6c-.5.3-1.2-.1-1.2-.7z"),
  down: ic("M5.3 8.8a1 1 0 0 1 1.4 0L12 14l5.3-5.2a1 1 0 1 1 1.4 1.4l-6 6a1 1 0 0 1-1.4 0l-6-6a1 1 0 0 1 0-1.4z"),
  left: ic("M15.2 5.3a1 1 0 0 1 0 1.4L10 12l5.2 5.3a1 1 0 1 1-1.4 1.4l-6-6a1 1 0 0 1 0-1.4l6-6a1 1 0 0 1 1.4 0z"),
  right: ic("M8.8 5.3a1 1 0 0 1 1.4 0l6 6a1 1 0 0 1 0 1.4l-6 6a1 1 0 1 1-1.4-1.4L14 12 8.8 6.7a1 1 0 0 1 0-1.4z"),
  speaker: ic("M11 4.5v15c0 .8-.9 1.2-1.5.7L5.3 16.5H3a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1h2.3l4.2-3.7c.6-.5 1.5-.1 1.5.7zm4.6 2.8a1 1 0 0 1 1.4 0 6.6 6.6 0 0 1 0 9.4 1 1 0 1 1-1.4-1.4 4.6 4.6 0 0 0 0-6.6 1 1 0 0 1 0-1.4z"),
  sparkles: ic("M10 2c.4 0 .8.3.9.7l1 3.4a5 5 0 0 0 3.3 3.3l3.4 1a1 1 0 0 1 0 1.9l-3.4 1a5 5 0 0 0-3.3 3.3l-1 3.4a1 1 0 0 1-1.9 0l-1-3.4a5 5 0 0 0-3.3-3.3l-3.4-1a1 1 0 0 1 0-1.9l3.4-1A5 5 0 0 0 8.1 6.1l1-3.4c.1-.4.5-.7.9-.7zm8 12c.3 0 .5.2.6.4l.4 1.3c.2.6.6 1 1.2 1.2l1.3.4a.6.6 0 0 1 0 1.2l-1.3.4c-.6.2-1 .6-1.2 1.2l-.4 1.3a.6.6 0 0 1-1.2 0l-.4-1.3c-.2-.6-.6-1-1.2-1.2l-1.3-.4a.6.6 0 0 1 0-1.2l1.3-.4c.6-.2 1-.6 1.2-1.2l.4-1.3c.1-.2.3-.4.6-.4z"),
  plus: ic("M12 4a1 1 0 0 1 1 1v6h6a1 1 0 1 1 0 2h-6v6a1 1 0 1 1-2 0v-6H5a1 1 0 1 1 0-2h6V5a1 1 0 0 1 1-1z"),
  nextUp: ic("M4 6h11a1 1 0 1 1 0 2H4a1 1 0 0 1 0-2zm0 5h11a1 1 0 1 1 0 2H4a1 1 0 1 1 0-2zm0 5h7a1 1 0 1 1 0 2H4a1 1 0 1 1 0-2zm13.5-1.5V12a1 1 0 1 1 2 0v2.5H22a1 1 0 1 1 0 2h-2.5V19a1 1 0 1 1-2 0v-2.5H15a1 1 0 1 1 0-2z"),
  devices: ic("M4 5a2 2 0 0 1 2-2h11a2 2 0 0 1 2 2v2h-2V5H6v9h7v2H3.5a1 1 0 0 1 0-2H4zm11 4a2 2 0 0 1 2-2h3a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-3a2 2 0 0 1-2-2zm2 0v9h3V9zm1.5 7a.8.8 0 1 1 0 1.6.8.8 0 0 1 0-1.6z"),
  phone: ic("M8 2h8a2 2 0 0 1 2 2v16a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2zm0 2v16h8V4zm4 13a1 1 0 1 1 0 2 1 1 0 0 1 0-2z"),
  laptop: ic("M5 5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v9H5zm2 0v7h10V5zM2 16h20v1a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2z"),
  mic: ic("M12 2a3.5 3.5 0 0 1 3.5 3.5v6a3.5 3.5 0 0 1-7 0v-6A3.5 3.5 0 0 1 12 2zm0 2a1.5 1.5 0 0 0-1.5 1.5v6a1.5 1.5 0 0 0 3 0v-6A1.5 1.5 0 0 0 12 4zM6 10.5a1 1 0 0 1 1 1 5 5 0 0 0 10 0 1 1 0 1 1 2 0 7 7 0 0 1-6 6.9V21a1 1 0 1 1-2 0v-2.6a7 7 0 0 1-6-6.9 1 1 0 0 1 1-1z"),
  pulse: ic("M3 12h3.2l2.3-6.2c.3-.9 1.6-.9 1.9 0l3.6 11.7 2.2-5c.2-.3.5-.5.9-.5H21a1 1 0 1 1 0 2h-3.1l-2.9 6.4c-.4.8-1.6.8-1.9-.1L9.5 8.9 7.9 13.3c-.1.4-.5.7-.9.7H3a1 1 0 1 1 0-2z"),
  more: ic("M5 10.3a1.7 1.7 0 1 1 0 3.4 1.7 1.7 0 0 1 0-3.4zm7 0a1.7 1.7 0 1 1 0 3.4 1.7 1.7 0 0 1 0-3.4zm7 0a1.7 1.7 0 1 1 0 3.4 1.7 1.7 0 0 1 0-3.4z"),
  gear: ic("M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z"),
  friends: ic("M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"),
  stats: ic("M4 13h3a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-6a1 1 0 0 1 1-1zm6.5-9h3a1 1 0 0 1 1 1v15a1 1 0 0 1-1 1h-3a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1zM17 9h3a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1h-3a1 1 0 0 1-1-1V10a1 1 0 0 1 1-1z"),
  library: ic("M6 2h12a1 1 0 0 1 0 2H6a1 1 0 0 1 0-2zM4 5.5h16a1 1 0 0 1 0 2H4a1 1 0 0 1 0-2zM4.5 9h15A2.5 2.5 0 0 1 22 11.5v8a2.5 2.5 0 0 1-2.5 2.5h-15A2.5 2.5 0 0 1 2 19.5v-8A2.5 2.5 0 0 1 4.5 9z"),
  close: ic("M6.7 5.3 12 10.6l5.3-5.3a1 1 0 1 1 1.4 1.4L13.4 12l5.3 5.3a1 1 0 0 1-1.4 1.4L12 13.4l-5.3 5.3a1 1 0 0 1-1.4-1.4l5.3-5.3-5.3-5.3a1 1 0 0 1 1.4-1.4z"),
  share: ic("M12 2.6a1 1 0 0 1 .7.3l3.5 3.5a1 1 0 1 1-1.4 1.4L13 6v8a1 1 0 1 1-2 0V6L9.2 7.8a1 1 0 1 1-1.4-1.4l3.5-3.5a1 1 0 0 1 .7-.3zM6 10h1.5a1 1 0 1 1 0 2H6v8h12v-8h-1.5a1 1 0 1 1 0-2H18a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2z"),
  radio: ic("M12 10a2 2 0 1 1 0 4 2 2 0 0 1 0-4zM7.8 7.8a1 1 0 0 1 0 1.4 4 4 0 0 0 0 5.6 1 1 0 1 1-1.4 1.4 6 6 0 0 1 0-8.4 1 1 0 0 1 1.4 0zm8.4 0a1 1 0 0 1 1.4 0 6 6 0 0 1 0 8.4 1 1 0 1 1-1.4-1.4 4 4 0 0 0 0-5.6 1 1 0 0 1 0-1.4zM5 5a1 1 0 0 1 0 1.4 8 8 0 0 0 0 11.2A1 1 0 1 1 3.6 19a10 10 0 0 1 0-14A1 1 0 0 1 5 5zm14 0a1 1 0 0 1 1.4 0 10 10 0 0 1 0 14 1 1 0 0 1-1.4-1.4 8 8 0 0 0 0-11.2A1 1 0 0 1 19 5z"),
  calendar: ic("M7 2a1 1 0 0 1 1 1v1h8V3a1 1 0 1 1 2 0v1h1a3 3 0 0 1 3 3v12a3 3 0 0 1-3 3H5a3 3 0 0 1-3-3V7a3 3 0 0 1 3-3h1V3a1 1 0 0 1 1-1zM4 10v9a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-9z"),
  trophy: ic("M7 3h10a1 1 0 0 1 1 1v1h2a1 1 0 0 1 1 1v2a4 4 0 0 1-3.8 4 6 6 0 0 1-4.2 3.9V18h3a1 1 0 1 1 0 2H8a1 1 0 1 1 0-2h3v-2.1A6 6 0 0 1 6.8 12 4 4 0 0 1 3 8V6a1 1 0 0 1 1-1h2V4a1 1 0 0 1 1-1zM5 7v1a2 2 0 0 0 1.1 1.8A6 6 0 0 1 6 9V7zm13 0v2c0 .3 0 .5-.1.8A2 2 0 0 0 19 8V7z"),
  headphones: ic("M12 3a9 9 0 0 1 9 9v5.5a3.5 3.5 0 0 1-3.5 3.5H16a1 1 0 0 1-1-1v-6a1 1 0 0 1 1-1h3v-.9a7 7 0 0 0-14 0v.9h3a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1H6.5A3.5 3.5 0 0 1 3 17.5V12a9 9 0 0 1 9-9z"),
  tv: ic("M4 4h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2h-7v1h3a1 1 0 1 1 0 2H8a1 1 0 1 1 0-2h3v-1H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zm0 2v10h16V6z"),
  moon: ic("M12.3 2.1a1 1 0 0 1 .3 1.1 7 7 0 0 0 8.2 9.1 1 1 0 0 1 1.2 1.3A10 10 0 1 1 11.2 2a1 1 0 0 1 1.1.1z"),
  flag: ic("M5 2a1 1 0 0 1 1 1v.3C7.2 2.8 8.5 2.5 10 2.9c1.4.4 2.4 1.1 3.6 1.4 1.3.3 2.8.2 4.9-.8A1 1 0 0 1 20 4.4v9.2a1 1 0 0 1-.6.9c-2.6 1.2-4.6 1.4-6.3 1-1.4-.4-2.4-1.1-3.6-1.4-1-.3-2-.2-3.5.4V21a1 1 0 1 1-2 0V3a1 1 0 0 1 1-1z"),
  check: ic("M20.3 5.8a1 1 0 0 1 0 1.4l-10 10a1 1 0 0 1-1.4 0l-5-5a1 1 0 1 1 1.4-1.4l4.3 4.3 9.3-9.3a1 1 0 0 1 1.4 0z"),
  trash: ic("M9 2h6a1 1 0 0 1 1 1v1h4a1 1 0 1 1 0 2h-1l-.9 13.1A3 3 0 0 1 15.1 22H8.9a3 3 0 0 1-3-2.9L5 6H4a1 1 0 0 1 0-2h4V3a1 1 0 0 1 1-1zm-2 4 .9 13a1 1 0 0 0 1 1h6.2a1 1 0 0 0 1-1L17 6z"),
  pencil: ic("M16.6 2.6a2 2 0 0 1 2.8 0l2 2a2 2 0 0 1 0 2.8L9.2 19.6a1 1 0 0 1-.5.3l-5 1.1a1 1 0 0 1-1.2-1.2l1.1-5a1 1 0 0 1 .3-.5zM15 7l-9.1 9.1-.6 2.6 2.6-.6L17 9z"),
  lock: ic("M12 2a5 5 0 0 1 5 5v3h1a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h1V7a5 5 0 0 1 5-5zm0 2a3 3 0 0 0-3 3v3h6V7a3 3 0 0 0-3-3z"),
  download: ic("M12 3a1 1 0 0 1 1 1v9.6l3.3-3.3a1 1 0 1 1 1.4 1.4l-5 5a1 1 0 0 1-1.4 0l-5-5a1 1 0 1 1 1.4-1.4l3.3 3.3V4a1 1 0 0 1 1-1zM4 18a1 1 0 0 1 1 1v1h14v-1a1 1 0 1 1 2 0v2a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-2a1 1 0 0 1 1-1z"),
  wave: ic("M3 10a1 1 0 0 1 1 1v2a1 1 0 1 1-2 0v-2a1 1 0 0 1 1-1zm4-4a1 1 0 0 1 1 1v10a1 1 0 1 1-2 0V7a1 1 0 0 1 1-1zm4-3a1 1 0 0 1 1 1v16a1 1 0 1 1-2 0V4a1 1 0 0 1 1-1zm4 5a1 1 0 0 1 1 1v6a1 1 0 1 1-2 0V9a1 1 0 0 1 1-1zm4-2a1 1 0 0 1 1 1v10a1 1 0 1 1-2 0V7a1 1 0 0 1 1-1zm4 4a1 1 0 0 1 1 1v2a1 1 0 1 1-2 0v-2a1 1 0 0 1 1-1z"),
  bolt: ic("M13.5 2.2a1 1 0 0 1 .5 1.1L12.8 10H19a1 1 0 0 1 .8 1.6l-8 10a1 1 0 0 1-1.8-.9l1.2-6.7H5a1 1 0 0 1-.8-1.6l8-10a1 1 0 0 1 1.3-.2z"),
  globe: ic("M12 2a10 10 0 1 1 0 20 10 10 0 0 1 0-20zm-2.4 2.3A8 8 0 0 0 4.1 11h3.9c.1-2.5.7-4.8 1.6-6.7zm4.8 0c.9 1.9 1.5 4.2 1.6 6.7h3.9a8 8 0 0 0-5.5-6.7zM12 4.2c-1 1.6-1.9 4-2 6.8h4c-.1-2.8-1-5.2-2-6.8zM4.1 13a8 8 0 0 0 5.5 6.7c-.9-1.9-1.5-4.2-1.6-6.7zm6 0c.1 2.8 1 5.2 2 6.8 1-1.6 1.9-4 2-6.8zm5.9 0c-.1 2.5-.7 4.8-1.6 6.7a8 8 0 0 0 5.5-6.7z"),
  install: ic("M7 3h10a4 4 0 0 1 4 4v10a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4V7a4 4 0 0 1 4-4zm5 4a1 1 0 0 0-1 1v3H8a1 1 0 1 0 0 2h3v3a1 1 0 1 0 2 0v-3h3a1 1 0 1 0 0-2h-3V8a1 1 0 0 0-1-1z"),
  user: ic("M12 2a10 10 0 1 1 0 20 10 10 0 0 1 0-20zm0 4a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7zm0 9c-2.4 0-4.5 1.1-5.7 2.8A8 8 0 0 0 12 20a8 8 0 0 0 5.7-2.2C16.5 16.1 14.4 15 12 15z"),
  miniPlayer: ic("M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zm0 2v12h16V6zm8 6h6a1 1 0 0 1 1 1v3a1 1 0 0 1-1 1h-6a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1z"),
  clock: ic("M12 2a10 10 0 1 1 0 20 10 10 0 0 1 0-20zm0 2a8 8 0 1 0 0 16 8 8 0 0 0 0-16zm0 2a1 1 0 0 1 1 1v4.6l3.2 1.9a1 1 0 1 1-1 1.7l-3.7-2.2A1 1 0 0 1 11 12V7a1 1 0 0 1 1-1z"),
  logo: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5.5 10v4M9.5 6.5v11M13.5 9v6M17.5 11v2" stroke="#fff" stroke-width="2.3" stroke-linecap="round" fill="none"/></svg>`,
};
const bars = () => `<span class="bars ${audio.paused ? "paused" : ""}"><i></i><i></i><i></i></span>`;

// ── Connexion ──────────────────────────────────────────────────────────────

async function boot() {
  registerServiceWorker();
  const params = new URLSearchParams(location.search);
  const lastfmToken = params.get("token");
  const handoff = params.get("handoff");
  if (lastfmToken || params.has("source") || params.has("party")) {
    if (params.get("party")) store.set("sona.joinParty", params.get("party").toUpperCase());
    history.replaceState(null, "", location.pathname + location.hash);
  }
  if (lastfmToken) {
    const pending = store.get("sona.pendingLastfm");
    // Page d'autorisation ouverte depuis l'appli installée, dans un autre
    // navigateur (iPhone) : c'est l'appli qui échangera le jeton.
    if (handoff && pending !== lastfmToken) return renderLoginDone();
    const ok = await exchangeLastfm(lastfmToken);
    if (!ok) return;
  }
  if (!token && store.get("sona.pendingLastfm")) {
    if (await exchangeLastfm(store.get("sona.pendingLastfm"), true)) return startApp();
    return renderLogin(null, true);
  }
  if (!token) return renderLogin();
  startApp();
}

async function startApp() {
  try {
    account = await api("/auth/me");
  } catch (e) { return renderLogin(token ? e.message : null); }
  if (account.status !== "approved") {
    return renderLogin(account.status === "rejected" ? "Accès refusé par un administrateur." : "Ton compte attend la validation d'un administrateur.");
  }
  document.body.style.overflow = "";
  renderShell();
  restoreResume();
  startConnect();
  loadSidebar();
  loadLiked();
  loadSettings();
  route();
  const joinCode = store.get("sona.joinParty");
  if (joinCode) { store.set("sona.joinParty", null); location.hash = `#/party/${joinCode}`; }
  else partyRestore();
}

/** Échange un jeton Last.fm autorisé contre une session Sona. `quiet` :
    jeton pas encore autorisé (on revient dans l'appli trop tôt) — pas d'erreur. */
async function exchangeLastfm(lastfmToken, quiet = false) {
  try {
    const res = await fetch(BASE + "/auth/lastfm", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token: lastfmToken }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      if (!quiet) { store.set("sona.pendingLastfm", null); renderLogin(body.detail || "Connexion refusée."); }
      return false;
    }
    store.set("sona.pendingLastfm", null);
    token = body.session_token;
    store.set("sona.token", token);
    return true;
  } catch {
    if (!quiet) renderLogin("Serveur Sona injoignable.");
    return false;
  }
}

async function renderLogin(error, waiting = false) {
  document.body.style.overflow = "hidden";
  const config = await fetch(BASE + "/auth/config").then((r) => r.json()).catch(() => ({}));
  // App d'ordinateur : la page n'a pas d'adresse web, Last.fm revient sur Sona web du serveur.
  const cb = desktop ? `${SERVER}/web/` : location.origin + location.pathname;
  const url = config.api_key ? `https://www.last.fm/api/auth/?api_key=${encodeURIComponent(config.api_key)}&cb=${encodeURIComponent(cb)}` : null;
  $("#root").innerHTML = `<div class="login"><div class="login-bg"></div><div class="login-card">
    <img class="login-icon" src="icons/icon-192.png" alt="">
    <h1>Sona</h1>
    <p>Ta musique, tes playlists, tes paroles et tes stats.<br>Sur ton ordinateur comme sur ton téléphone.</p>
    ${url ? `<a class="btn" id="login-btn" href="${esc(url)}">Se connecter avec Last.fm</a>` : '<p class="error">Serveur Sona injoignable ou connexion Last.fm non configurée.</p>'}
    ${waiting ? `<p class="fine wait">Autorise Sona sur la page Last.fm, puis reviens ici.<br><button class="link-btn" id="login-check">J'ai autorisé, continuer</button></p>` : ""}
    ${error ? `<p class="error">${esc(error)}</p>` : ""}
    <p class="fine">Le même compte que dans l'app Sona.</p>
    ${desktop ? `<p class="fine">Une fenêtre Last.fm s'ouvre : autorise Sona, elle se ferme toute seule.</p>` : ""}
    ${!standalone && !desktop && isMobile() ? `<p class="fine">${isIOS ? "Astuce : touche Partager puis « Sur l'écran d'accueil » pour installer Sona comme une app." : "Astuce : installe Sona depuis le menu du navigateur (« Installer l'appli »)."}</p>` : ""}
  </div></div>`;
  const btn = $("#login-btn");
  // Appli installée : la page Last.fm s'ouvre dans un navigateur à part, d'où
  // le retour ne revient pas ici — jeton demandé au serveur, échangé au retour.
  if (btn && (standalone || desktop)) {
    btn.onclick = async (e) => {
      e.preventDefault();
      try {
        const res = await fetch(BASE + "/auth/lastfm/token", { method: "POST" });
        if (!res.ok) throw new Error();
        const got = await res.json();
        store.set("sona.pendingLastfm", got.token);
        const authUrl = `${got.auth_url}&cb=${encodeURIComponent(`${cb}?handoff=1`)}`;
        if (desktop) desktop.openAuth(authUrl);
        else if (!window.open(authUrl, "_blank")) location.href = authUrl;
        renderLogin(null, true);
      } catch { if (!desktop) location.href = btn.href; else renderLogin("Serveur Sona injoignable."); }
    };
  }
  const check = $("#login-check");
  if (check) check.onclick = () => retryPendingLogin(false);
}

async function retryPendingLogin(quiet = true) {
  const pending = store.get("sona.pendingLastfm");
  if (token && !account) return startApp();
  if (!pending || account) return;
  if (await exchangeLastfm(pending, true)) return startApp();
  if (!quiet) toast("Pas encore autorisé sur Last.fm");
}

// Retour dans l'appli après l'autorisation Last.fm.
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && !account) {
    token = token || store.get("sona.token");
    retryPendingLogin();
  }
});

function renderLoginDone() {
  document.body.style.overflow = "hidden";
  $("#root").innerHTML = `<div class="login"><div class="login-bg"></div><div class="login-card">
    <img class="login-icon" src="icons/icon-192.png" alt="">
    <h1>C'est autorisé ✓</h1>
    <p>Tu peux fermer cette page et revenir dans l'appli Sona : la connexion se termine toute seule.</p>
  </div></div>`;
}

function signOut() {
  token = null;
  account = null;
  store.set("sona.token", null);
  audio.pause();
  partyLeave(true);
  renderLogin();
}

function registerServiceWorker() {
  if (!("serviceWorker" in navigator) || location.protocol === "file:" || desktop) return;
  navigator.serviceWorker.register("sw.js").catch(() => {});
}

// Installation (Android, Chrome, Edge) : l'invite du navigateur, gardée pour
// le bouton « Installer l'appli » de l'accueil et des réglages.
let installPrompt = null;
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  installPrompt = e;
  const banner = $("#install");
  if (banner) banner.innerHTML = installBanner();
});
window.addEventListener("appinstalled", () => { installPrompt = null; $("#install")?.replaceChildren(); toast("Sona est installé ✓"); });

function installBanner() {
  if (standalone || store.get("sona.installDismissed") || !isMobile() || (!installPrompt && !isIOS)) return "";
  return `<div class="install-card"><img src="icons/icon-192.png" alt="">
    <div><div class="t">Installe Sona</div><div class="s">Sur ton écran d'accueil, comme une vraie app.</div></div>
    <button class="btn small" data-install>Installer</button><button class="x" data-install-close aria-label="Plus tard">${icons.close}</button></div>`;
}

async function installApp() {
  if (installPrompt) {
    installPrompt.prompt();
    const choice = await installPrompt.userChoice.catch(() => null);
    if (choice?.outcome === "accepted") installPrompt = null;
    return;
  }
  openSheet(`<h2 class="sheet-title">Installer Sona</h2>
    <ol class="steps">${isIOS
      ? `<li>Ouvre cette page dans <b>Safari</b>.</li><li>Touche ${icons.share} <b>Partager</b>, en bas de l'écran.</li><li>Choisis <b>Sur l'écran d'accueil</b>, puis <b>Ajouter</b>.</li>`
      : `<li>Ouvre le menu du navigateur (⋮).</li><li>Choisis <b>Installer l'appli</b> (ou « Ajouter à l'écran d'accueil »).</li>`}</ol>
    <p class="muted">Sona s'ouvre alors en plein écran, sans la barre du navigateur, avec son icône.</p>`);
}

// ── Coquille ───────────────────────────────────────────────────────────────

// Les onglets de l'app iOS, dans le même ordre (barre du bas sur téléphone).
const TABS = [
  ["home", "Écouter", icons.listen],
  ["library", "Bibliothèque", icons.library],
  ["friends", "Amis", icons.friends],
  ["stats", "Stats", icons.stats],
  ["search", "Rechercher", icons.search],
];
const SIDE_NAV = [
  ["home", "Écouter", icons.listen],
  ["search", "Rechercher", icons.search],
  ["library", "Bibliothèque", icons.library],
  ["friends", "Amis", icons.friends],
  ["stats", "Stats", icons.stats],
  ["devices", "Appareils", icons.devices],
];
const SIDE_MORE = [
  ["radios", "Radios", icons.radio],
  ["blindtest", "Blind test", icons.wave],
  ["party", "Écoute ensemble", icons.headphones],
  ["concerts", "Concerts", icons.calendar],
  ["sport", "Mode sport", icons.bolt],
];

function renderShell() {
  const name = account.display_name || account.username;
  $("#root").innerHTML = `<div class="app">
    <aside class="sidebar">
      <div class="brand"><img class="brand-icon" src="icons/icon-192.png" alt="">Sona</div>
      <label class="side-search">${icons.search}<input id="side-q" type="search" placeholder="Rechercher" autocomplete="off"></label>
      <div class="side-list scroll">
        ${SIDE_NAV.map(([id, label, icon]) => `<a class="side-link" href="#/${id}" data-nav="${id}">${icon}${label}</a>`).join("")}
        <div class="side-section">Découvrir et jouer</div>
        ${SIDE_MORE.map(([id, label, icon]) => `<a class="side-link" href="#/${id}" data-nav="${id}">${icon}${label}</a>`).join("")}
        ${desktop ? `<div class="side-section">Sur ce PC</div>
        <a class="side-link" href="#/iphone" data-nav="iphone">${icons.phone}Sona sur l'iPhone<span class="side-badge" id="iph-badge"></span></a>` : ""}
        <div class="side-section">Faites pour toi</div>
        <div id="side-smart"></div>
        <div class="side-section">Playlists</div>
        <div id="side-playlists"></div>
        ${account.is_admin ? `<div class="side-section">Administration</div>
        <a class="side-link" href="#/health" data-nav="health">${icons.pulse}Santé de la lecture</a>
        <a class="side-link" href="#/admin" data-nav="admin">${icons.lock}Accès à l'app</a>` : ""}
      </div>
      <a class="side-user" href="#/settings" title="Réglages">
        ${avatar(account.avatar_url, name)}
        <span class="name">${esc(name)}</span>
        <span class="gear">${icons.gear}</span>
      </a>
    </aside>
    <header class="topbar" id="topbar"></header>
    <header class="mhead" id="mhead"></header>
    <main class="content scroll" id="content"></main>
    <div class="mp" id="mp"></div>
    <nav class="tabbar">${TABS.map(([id, label, icon]) => `<button data-tab="${id}">${icon}<span>${label}</span></button>`).join("")}</nav>
  </div>
  <section class="np" id="np" aria-label="Lecture en cours"></section>`;
  $("#side-q").addEventListener("keydown", (e) => {
    if (e.key === "Enter") location.hash = `#/search/${encodeURIComponent(e.target.value.trim())}`;
  });
  $("#side-q").addEventListener("focus", () => { if (!location.hash.startsWith("#/search")) location.hash = "#/search"; });
  $$(".tabbar button").forEach((b) => (b.onclick = () => selectTab(b.dataset.tab)));
  const content = $("#content");
  content.addEventListener("scroll", () => {
    const head = $("#mhead");
    if (!head) return;
    const title = $(".page-title, .hero h1, .profile-head h1", content);
    const limit = title ? title.offsetTop + title.offsetHeight - 50 : 30;
    head.classList.toggle("scrolled", content.scrollTop > Math.max(8, limit));
    head.classList.toggle("edge", content.scrollTop > 4);
  }, { passive: true });
  bindPullToRefresh(content);
  bindNowPlayingGestures();
  renderTopbar();
  renderNowPlaying();
  desktopReport(true);
}

const avatar = (url, name, cls = "avatar") => url
  ? `<img class="${cls}" src="${esc(url)}" alt="" loading="lazy">`
  : `<span class="${cls} avatar-fallback">${esc((name || "?")[0].toUpperCase())}</span>`;

async function loadSidebar() {
  const [smart, playlists] = await Promise.all([
    api(`/smart?tz=${encodeURIComponent(tz())}`).catch(() => []),
    api("/me/playlists").catch(() => []),
  ]);
  state.smart = smart;
  state.playlists = playlists;
  renderSidebarLists();
}

function renderSidebarLists() {
  const smartBox = $("#side-smart");
  if (!smartBox) return;
  smartBox.innerHTML = state.smart.map((s) => `<a class="side-link" href="#/smart/${esc(s.id)}" data-nav="smart/${esc(s.id)}">
    <img class="thumb" src="${esc(s.covers[0] || "")}" alt="">${esc(s.title)}</a>`).join("");
  $("#side-playlists").innerHTML = state.playlists.map((p) => `<a class="side-link" href="#/playlist/${p.id}" data-nav="playlist/${p.id}">
    <img class="thumb" src="${esc(p.cover_url || (p.covers || [])[0] || "")}" alt="">${esc(p.name)}</a>`).join("")
    || '<p class="side-link" style="color:var(--text-3)">Aucune playlist</p>';
  markNav();
}

async function loadLiked() {
  const [tracks, albums, artists] = await Promise.all(["track", "album", "artist"].map((kind) =>
    api(`/library/${kind}?limit=500`).catch(() => ({ items: [] }))));
  state.liked = new Set((tracks.items || []).map(trackKey));
  state.likedAlbums = new Set((albums.items || []).map(trackKey));
  state.likedArtists = new Set((artists.items || []).map(trackKey));
}

async function loadSettings() {
  state.settings = await api("/settings").catch(() => null);
}

const tz = () => Intl.DateTimeFormat().resolvedOptions().timeZone || "Europe/Paris";

function markNav() {
  const current = location.hash.replace(/^#\//, "") || "home";
  $$("[data-nav]").forEach((a) => a.classList.toggle("active", current === a.dataset.nav || current.startsWith(`${a.dataset.nav}/`)));
  $$("[data-tab]").forEach((b) => b.classList.toggle("active", b.dataset.tab === nav.tab));
}

// ── Routes ────────────────────────────────────────────────────────────────
// Comme les onglets de l'app : chaque onglet garde sa pile de pages (album,
// artiste…), un appui sur l'onglet actif revient à sa racine, et le bouton
// retour du haut remonte la pile.

window.addEventListener("hashchange", () => token && account && route());
matchMedia("(max-width: 760px)").addEventListener?.("change", () => { if (account) { renderTopbar(); renderNowPlaying(); route(); } });

const nav = { tab: "home", stacks: {}, titles: {}, scroll: {}, current: null };
let pageCleanup = null;
/** Ce qu'une page doit arrêter en partant (minuteries, son…). */
const onLeave = (fn) => { pageCleanup = fn; };

function selectTab(tab) {
  haptic();
  const stack = nav.stacks[tab] || [`#/${tab}`];
  if (tab === nav.tab) {
    if (stack.length > 1) { nav.stacks[tab] = [stack[0]]; location.hash = stack[0]; }
    else $("#content")?.scrollTo({ top: 0, behavior: "smooth" });
    return;
  }
  nav.tab = tab;
  const target = stack[stack.length - 1];
  if (location.hash === target) route(); else location.hash = target;
}

const go = (hash) => { location.hash = hash; };
function goBack() {
  const stack = nav.stacks[nav.tab] || [];
  go(stack.length > 1 ? stack[stack.length - 2] : `#/${nav.tab}`);
}

async function route() {
  const hash = location.hash || "#/home";
  const parts = (hash.replace(/^#\//, "") || "home").split("/").map(decodeURIComponent);
  const content = $("#content");
  if (!content) return;
  pageCleanup?.();
  pageCleanup = null;
  // Comme dans l'app : ouvrir une fiche ferme le lecteur plein écran.
  if (state.npOpen) closeNowPlaying();
  $$(".sheet-wrap").forEach((w) => w.close?.());
  if (state.connect.open) closeDevices();
  if (nav.current) nav.scroll[nav.current] = content.scrollTop;
  // Pile de l'onglet : racine, page suivante, ou retour en arrière.
  const isRoot = TABS.some(([id]) => id === parts[0]);
  let direction = "none";
  if (isRoot) {
    nav.tab = parts[0];
    nav.stacks[nav.tab] = [hash];
  } else {
    const stack = (nav.stacks[nav.tab] ||= [`#/${nav.tab}`]);
    const i = stack.indexOf(hash);
    if (i >= 0) { direction = i < stack.length - 1 ? "back" : "none"; stack.length = i + 1; }
    else { stack.push(hash); direction = "push"; }
  }
  nav.current = hash;
  markNav();
  renderHeader(parts, isRoot);
  if (direction !== "back") content.scrollTop = 0;
  const views = {
    home: viewHome, search: () => viewSearch(parts.slice(1).join("/") || ""),
    library: () => viewLibrary(parts[1] || "playlists"), playlists: () => viewLibrary("playlists"),
    album: () => viewAlbum(parts[1], parts[2]), artist: () => viewArtist(parts[1], parts[2]),
    playlist: () => viewUserPlaylist(parts[1]), dplaylist: () => viewAlbum(parts[1], parts[2], true),
    smart: () => viewSmart(parts[1]), mix: () => viewMix(parts[1]),
    friends: viewFriends, friend: () => viewFriend(parts[1]), blend: () => viewBlend(parts[1]),
    stats: viewStats, recent: viewRecent, radios: viewRadios, concerts: viewConcerts,
    blindtest: viewBlindTest, live: () => viewLive(parts[1]), party: () => viewParty(parts[1]), sport: viewSport,
    settings: viewSettings, admin: viewAdmin, health: viewHealth, devices: viewDevices, status: viewStatus,
    ...(desktop ? { iphone: viewIphone } : {}),
  };
  const view = views[parts[0]] || viewHome;
  const token_ = (route.seq = (route.seq || 0) + 1);
  try {
    const html = await view();
    if (token_ !== route.seq || html == null) return;
    content.innerHTML = html;
    const pageEl = $(".page", content);
    if (pageEl && direction !== "none" && isMobile()) pageEl.classList.add(direction === "push" ? "push" : "pop");
    bindPage(content);
    if (direction === "back" && nav.scroll[hash]) content.scrollTop = nav.scroll[hash];
  } catch (e) {
    if (token_ !== route.seq) return;
    content.innerHTML = page(`<div class="empty"><div class="big">⚠︎</div><h3>Impossible d'afficher cette page</h3><p>${esc(e.message)}</p></div>`);
  }
  const title = $(".page-title, .hero h1, .profile-head h1", content)?.textContent || "";
  nav.titles[hash] = title;
  $("#mhead .mh-title")?.replaceChildren(document.createTextNode(title));
  content.dispatchEvent(new Event("scroll"));
}

/** Barre du haut sur téléphone : retour, titre (qui apparaît en faisant
    défiler, comme les grands titres d'iOS) et réglages. */
function renderHeader(parts, isRoot) {
  const head = $("#mhead");
  if (!head) return;
  const stack = nav.stacks[nav.tab] || [];
  const prev = stack.length > 1 ? stack[stack.length - 2] : null;
  const tabLabel = TABS.find(([id]) => id === nav.tab)?.[1] || "Retour";
  const backLabel = prev ? (nav.titles[prev] || tabLabel) : tabLabel;
  head.className = "mhead";
  head.innerHTML = `<div class="mh-left">${isRoot ? "" : `<button class="mh-back" data-mh="back">${icons.left}<span>${esc(backLabel.length > 14 ? "Retour" : backLabel)}</span></button>`}</div>
    <div class="mh-title"></div>
    <div class="mh-right">${parts[0] === "devices" ? "" : `<button class="mh-btn ${chosenDevice() ? "on" : ""}" data-mh="devices" aria-label="Appareils">${icons.devices}</button>`}${parts[0] === "settings" ? "" : `<button class="mh-btn" data-mh="settings" aria-label="Réglages">${icons.gear}</button>`}</div>`;
  head.onclick = (e) => {
    const act = e.target.closest("[data-mh]")?.dataset.mh;
    if (act === "back") goBack();
    if (act === "settings") go("#/settings");
    if (act === "devices") go("#/devices");
  };
}

/** Tirer vers le bas en haut d'une page : recharge (comme `.refreshable`). */
function bindPullToRefresh(content) {
  let startY = null, pulled = 0;
  const spinner = document.createElement("div");
  spinner.className = "ptr";
  spinner.innerHTML = `<span></span>`;
  content.before(spinner);
  content.addEventListener("touchstart", (e) => {
    startY = content.scrollTop <= 0 && !e.target.closest(".shelf, .track-grid, input, .np") ? e.touches[0].clientY : null;
    pulled = 0;
  }, { passive: true });
  content.addEventListener("touchmove", (e) => {
    if (startY == null) return;
    pulled = Math.max(0, e.touches[0].clientY - startY);
    spinner.style.setProperty("--pull", Math.min(1, pulled / 90));
    spinner.classList.toggle("ready", pulled > 90);
  }, { passive: true });
  content.addEventListener("touchend", () => {
    if (startY != null && pulled > 90) { haptic(); spinner.classList.add("spin"); route().finally(() => spinner.classList.remove("spin")); }
    startY = null;
    spinner.style.setProperty("--pull", 0);
    spinner.classList.remove("ready");
  });
}

const page = (inner) => `<div class="page">${inner}</div>`;
const skeleton = (title) => page(`<h1 class="page-title">${esc(title)}</h1>
  <div class="section"><div class="shelf">${Array.from({ length: 5 }, () => '<div><div class="skeleton sk-card"></div><div class="skeleton sk-line"></div></div>').join("")}</div></div>`);

// Données des pages, pour les actions (lecture d'une liste, etc.).
const registry = new Map();
let registrySeq = 0;
function register(tracks, name, ctx = null) {
  const id = `l${++registrySeq}`;
  registry.set(id, { tracks: (tracks || []).filter((t) => t && t.source && t.source_id), name, ctx });
  if (registry.size > 60) registry.delete(registry.keys().next().value);
  return id;
}

// ── Composants ─────────────────────────────────────────────────────────────

function shelf(title, items, { kind = "", more = "" } = {}) {
  if (!items.length) return "";
  return `<section class="section">
    <div class="section-head"><h2>${esc(title)}</h2>
      <div class="shelf-nav">${more}<button data-shelf="-1" aria-label="Précédent">${icons.left}</button><button data-shelf="1" aria-label="Suivant">${icons.right}</button></div></div>
    <div class="shelf ${kind}">${items.join("")}</div></section>`;
}

function card({ href, cover, covers, title, subtitle, round, play }) {
  const art = covers && covers.length >= 4
    ? `<div class="mosaic">${covers.slice(0, 4).map((c) => `<img src="${esc(big(c, 300))}" alt="" loading="lazy">`).join("")}</div>`
    : `<img src="${esc(big(cover, 500))}" alt="" loading="lazy">`;
  return `<a class="card ${round ? "round" : ""}" href="${esc(href)}">
    <div class="art-wrap">${art}${play ? `<button class="play-fab" data-play="${play}" aria-label="Lecture">${icons.play}</button>` : ""}</div>
    <div class="t">${esc(title)}</div>${subtitle ? `<div class="s">${esc(subtitle)}</div>` : ""}</a>`;
}

function feature({ href, cover, eyebrow, title, subtitle, play }) {
  return `<a class="feature" href="${esc(href)}">
    <div class="bg"><img src="${esc(big(cover, 800))}" alt="" loading="lazy"></div><div class="shade"></div>
    <div class="label"><div class="eyebrow">${esc(eyebrow)}</div><div class="title">${esc(title)}</div><div class="sub">${esc(subtitle || "")}</div></div>
    ${play ? `<button class="play-fab" data-play="${play}" aria-label="Lecture">${icons.play}</button>` : ""}</a>`;
}

function trackTable(tracks, name, { numbers = true, showAlbum = true, ctx = null } = {}) {
  tracks = (tracks || []).filter((t) => t && t.source && t.source_id);
  const list = register(tracks, name, ctx);
  const current = state.queue[state.index];
  return `<div class="tracks" data-list="${list}">${tracks.map((t, i) => {
    const on = sameTrack(t, current);
    const liked = state.liked.has(`${t.source}:${t.source_id}`);
    return `<div class="tr ${on ? "current" : ""}" data-i="${i}" role="button" tabindex="0">
      <span class="n">${on ? bars() : `<span>${numbers ? i + 1 : ""}</span>`}${icons.play}</span>
      <img src="${esc(big(t.cover_url, 120))}" alt="" loading="lazy">
      <span style="min-width:0"><div class="ti">${esc(t.title)}</div>
        <div class="ar">${t.artist_source_id ? `<span class="link" data-artist="${esc(t.source)}/${esc(t.artist_source_id)}">${esc(t.artist)}</span>` : esc(t.artist)}</div></span>
      <span class="al">${showAlbum && t.album ? (t.album_source_id ? `<span class="link" data-album="${esc(t.source)}/${esc(t.album_source_id)}">${esc(t.album)}</span>` : esc(t.album)) : ""}</span>
      <span class="d">${t.duration_seconds ? fmt(t.duration_seconds) : ""}</span>
      <span class="acts">
        <button data-act="next" title="Lire ensuite">${icons.nextUp}</button>
        <button data-act="like" class="${liked ? "liked" : ""}" title="${liked ? "Dans ta bibliothèque" : "Ajouter à la bibliothèque"}">${liked ? icons.heartFill : icons.heart}</button>
        <button data-act="more" title="Plus d'options">${icons.more}</button>
      </span></div>`;
  }).join("")}</div>`;
}

function trackGrid(tracks, name) {
  tracks = (tracks || []).filter((t) => t && t.source && t.source_id);
  const list = register(tracks, name);
  const current = state.queue[state.index];
  return `<div class="track-grid" data-list="${list}">${tracks.map((t, i) => `
    <button class="mini ${sameTrack(t, current) ? "current" : ""}" data-i="${i}">
      <img src="${esc(big(t.cover_url, 120))}" alt="" loading="lazy">
      <span style="min-width:0"><div class="t">${esc(t.title)}</div><div class="s">${esc(t.artist)}</div></span>
      <span></span></button>`).join("")}</div>`;
}

function hero({ cover, covers, kind, title, by, byHref, info, list, round, extra = "" }) {
  const art = covers && covers.length >= 4 && !cover
    ? `<div class="hero-art mosaic">${covers.slice(0, 4).map((c) => `<img src="${esc(big(c, 300))}" alt="">`).join("")}</div>`
    : `<img class="hero-art ${round ? "round" : ""}" src="${esc(big(cover || covers?.[0], 600))}" alt="">`;
  return `<div class="hero">
    <div class="hero-glow"><img src="${esc(big(cover || covers?.[0], 300))}" alt=""></div>
    ${art}
    <div class="hero-text"><div class="kind">${esc(kind)}</div><h1>${esc(title)}</h1>
      ${by ? (byHref ? `<a class="by link" href="${esc(byHref)}">${esc(by)}</a>` : `<div class="by">${esc(by)}</div>`) : ""}
      ${info ? `<div class="info">${esc(info)}</div>` : ""}
      ${list || extra ? `<div class="actions">${list ? `<button class="btn" data-play="${list}">${icons.play} Lecture</button>
        <button class="btn ghost" data-shuffle="${list}">${icons.shuffle} Aléatoire</button>` : ""}${extra}</div>` : ""}
    </div></div>`;
}

const empty = (icon, title, text) => `<div class="empty"><div class="big">${icon}</div><h3>${esc(title)}</h3><p>${esc(text)}</p></div>`;

function bindPage(root) {
  $$("[data-shelf]", root).forEach((b) => (b.onclick = () => {
    const el = b.closest(".section").querySelector(".shelf, .track-grid");
    el.scrollBy({ left: el.clientWidth * Number(b.dataset.shelf) * 0.9, behavior: "smooth" });
  }));
  $$("[data-play]", root).forEach((b) => (b.onclick = (e) => {
    e.preventDefault(); e.stopPropagation();
    const data = registry.get(b.dataset.play);
    if (data?.tracks.length) playList(data.tracks, 0, data.name);
  }));
  $$("[data-shuffle]", root).forEach((b) => (b.onclick = () => {
    const data = registry.get(b.dataset.shuffle);
    if (data?.tracks.length) { state.shuffle = true; playList(shuffled(data.tracks), 0, data.name); renderTopbar(); }
  }));
  $$("[data-list]", root).forEach((listEl) => {
    const data = registry.get(listEl.dataset.list);
    listEl.addEventListener("click", (e) => {
      const artist = e.target.closest("[data-artist]");
      if (artist) { e.stopPropagation(); location.hash = `#/artist/${artist.dataset.artist}`; return; }
      const album = e.target.closest("[data-album]");
      if (album) { e.stopPropagation(); location.hash = `#/album/${album.dataset.album}`; return; }
      const row = e.target.closest("[data-i]");
      if (!row || !data) return;
      const track = data.tracks[+row.dataset.i];
      const act = e.target.closest("[data-act]");
      if (act?.dataset.act === "like") { e.stopPropagation(); toggleLike(track, act); return; }
      if (act?.dataset.act === "next") { e.stopPropagation(); playNext(track); return; }
      if (act?.dataset.act === "more") { e.stopPropagation(); trackMenu(track, data.ctx, +row.dataset.i); return; }
      haptic();
      playList(data.tracks, +row.dataset.i, data.name);
    });
    // Appui long (téléphone) ou clic droit (ordinateur) : le menu du titre.
    listEl.addEventListener("contextmenu", (e) => {
      const row = e.target.closest("[data-i]");
      if (!row || !data) return;
      e.preventDefault();
      haptic();
      trackMenu(data.tracks[+row.dataset.i], data.ctx, +row.dataset.i);
    });
    listEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && e.target.dataset.i && data) playList(data.tracks, +e.target.dataset.i, data.name);
    });
  });
}

// ── Pages ─────────────────────────────────────────────────────────────────

function greeting() {
  const h = new Date().getHours();
  return h < 5 ? "Bonne nuit" : h < 12 ? "Bonjour" : h < 18 ? "Bon après-midi" : "Bonsoir";
}

const playsToTracks = (plays, limit = 24) => {
  const seen = new Set();
  return plays.filter((p) => p.source && p.source_id && !seen.has(trackKey(p)) && seen.add(trackKey(p))).slice(0, limit);
};

function tile({ href, icon, title, subtitle, tone = "", data = "" }) {
  return `<a class="tile ${tone}" ${href ? `href="${esc(href)}"` : 'role="button" tabindex="0"'} ${data}>
    <span class="tile-icon">${icon}</span><span class="tile-text"><span class="t">${esc(title)}</span><span class="s">${esc(subtitle)}</span></span>${icons.right}</a>`;
}

async function viewHome() {
  $("#content").innerHTML = skeleton("Écouter");
  const [mixes, recent, releases, smart, memories, playlists, radios, liveParties] = await Promise.all([
    api("/home/mixes").catch(() => []),
    api("/plays/recent?limit=80").catch(() => []),
    api("/releases").catch(() => []),
    state.smart.length ? state.smart : api(`/smart?tz=${encodeURIComponent(tz())}`).catch(() => []),
    api(`/memories?tz=${encodeURIComponent(tz())}`).catch(() => []),
    api("/me/playlists").catch(() => state.playlists),
    radioGroups().catch(() => []),
    api("/party/active").catch(() => []),
  ]);
  const recentTracks = playsToTracks(recent);
  const name = (account.display_name || account.username || "").split(" ")[0];
  const heroTrack = recentTracks[0];
  const heroList = heroTrack ? register(recentTracks, "Écoutés récemment") : "";
  const seenArtists = new Set();
  const artists = recentTracks.filter((t) => t.artist_source_id && !seenArtists.has(t.artist_source_id) && seenArtists.add(t.artist_source_id));
  const memory = memories[0];
  const parties = liveParties.filter((p) => !p.joined);
  setTimeout(() => {
    $("[data-install]")?.addEventListener("click", installApp);
    $("[data-install-close]")?.addEventListener("click", () => { store.set("sona.installDismissed", "1"); $("#install").replaceChildren(); });
    $$("[data-radio]").forEach((b) => (b.onclick = (e) => { e.preventDefault(); startRadio(b.dataset.radio, b.dataset.title); }));
    $("[data-memory]")?.addEventListener("click", () => playList(memory.tracks, 0, memory.label));
  });
  return page(`<h1 class="page-title">Écouter</h1><p class="page-sub">${greeting()}${name ? `, ${esc(name)}` : ""}. Voici ta musique du moment.</p>
    <div id="install">${installBanner()}</div>
    <div id="resume">${resumeCard()}</div>
    ${party.state ? `<a class="live-pill" href="#/party">${bars()} Écoute ensemble en cours · ${esc(party.state.code)}</a>` : ""}
    ${parties.map((p) => `<a class="live-pill" href="#/party/${esc(p.code)}">${icons.headphones} ${esc(p.host_name || "Un ami")} écoute en groupe — rejoindre</a>`).join("")}
    ${heroTrack ? `<button class="home-hero" data-play="${heroList}">
      <img src="${esc(big(heroTrack.cover_url, 1000))}" alt=""><span class="shade"></span>
      <span class="label"><span class="eyebrow">Reprendre</span><span class="t">${esc(heroTrack.title)}</span><span class="s">${esc(heroTrack.artist)}</span></span>
      <span class="fab">${icons.play}</span></button>` : ""}
    ${shelf("Faits pour toi", mixes.filter((m) => m.tracks.length).map((m) => feature({
      href: `#/mix/${encodeURIComponent(m.id)}`, cover: m.covers[0], eyebrow: "Mix Sona", title: m.title, subtitle: m.subtitle,
      play: register(m.tracks, m.title),
    })), { kind: "large" })}
    ${shelf("Nouvelles sorties", releases.map((r) => card({
      href: `#/album/${r.source}/${r.source_id}`, cover: r.cover_url, title: r.title, subtitle: `${r.artist} · ${r.kind}`,
    })))}
    ${memory ? `<button class="memory" data-memory>
      <span class="covers">${memory.tracks.slice(0, 3).map((t) => `<img src="${esc(big(t.cover_url, 200))}" alt="">`).join("")}</span>
      <span class="memory-text"><span class="eyebrow">🕰️ ${esc(memory.label)}</span><span class="t">Ce que tu écoutais le ${esc(memory.date_label)}</span>
      <span class="s">${plural(memory.plays, "écoute")} · touche pour réécouter</span></span></button>` : ""}
    <section class="section"><div class="section-head"><h2>Jouer</h2></div>
      <div class="tiles">
        ${tile({ href: "#/blindtest", icon: icons.wave, title: "Blind test", subtitle: "Défi du jour, solo ou en direct", tone: "violet" })}
        ${tile({ href: "#/party", icon: icons.headphones, title: "Écoute ensemble", subtitle: "Le même son, au même moment", tone: "blue" })}
        ${tile({ href: "#/sport", icon: icons.bolt, title: "Mode sport", subtitle: "La musique au tempo de ta course", tone: "green" })}
      </div></section>
    ${shelf("Tes playlists", playlists.filter((p) => p.import_status !== "importing").slice(0, 12).map((p) => card({
      href: `#/playlist/${p.id}`, cover: p.cover_url || (p.covers || [])[0], covers: p.cover_url ? null : p.covers, title: p.name, subtitle: plural(p.track_count, "titre"),
    })))}
    ${recentTracks.length ? `<section class="section"><div class="section-head"><h2>Écouté récemment</h2>
      <div class="shelf-nav"><a class="more" href="#/recent">Tout voir</a><button data-shelf="-1">${icons.left}</button><button data-shelf="1">${icons.right}</button></div></div>
      ${trackGrid(recentTracks, "Écoutés récemment")}</section>` : ""}
    ${shelf("Radios", radios.map((g) => g.radios[0]).filter(Boolean).map(radioCard), { more: `<a class="more" href="#/radios">Tout voir</a>` })}
    <a class="concert-teaser" href="#/concerts"><span class="tile-icon">${icons.calendar}</span><span><span class="t">Concerts près de chez toi</span><span class="s">Les dates à venir de tes artistes préférés</span></span>${icons.right}</a>
    ${shelf("Tes artistes", artists.map((t) => card({ href: `#/artist/${t.source}/${t.artist_source_id}`, cover: t.cover_url, title: t.artist, round: true })), { kind: "round" })}
    ${shelf("Playlists intelligentes", smart.map((s) => card({ href: `#/smart/${s.id}`, covers: s.covers, cover: s.covers[0], title: s.title, subtitle: plural(s.count, "titre") })))}
    ${!mixes.length && !recentTracks.length ? empty("♫", "Rien encore ici", "Lance une radio ou cherche un titre : ton historique et tes mix apparaîtront ici.") : ""}`);
}

const radioCard = (r) => `<a class="card radio-card" href="#" data-radio="${esc(r.id)}" data-title="${esc(r.title)}">
  <div class="art-wrap"><img src="${esc(r.picture_url || "")}" alt="" loading="lazy"><span class="play-fab">${icons.play}</span></div>
  <div class="t">${esc(r.title)}</div><div class="s">Radio</div></a>`;

let radioCache = null;
const radioGroups = async () => (radioCache ||= await api("/browse/radios"));

async function startRadio(id, title) {
  toast(`Radio « ${title} »…`);
  try {
    await playStation(title, () => api(`/radios/${encodeURIComponent(id)}/tracks`));
  } catch (e) { toast(e.message); }
}

async function viewRadios() {
  $("#content").innerHTML = skeleton("Radios");
  const groups = await radioGroups();
  setTimeout(() => $$("[data-radio]").forEach((b) => (b.onclick = (e) => { e.preventDefault(); startRadio(b.dataset.radio, b.dataset.title); })));
  return page(`<h1 class="page-title">Radios</h1><p class="page-sub">Une station par univers : elle ne s'arrête jamais.</p>
    ${groups.map((g) => shelf(g.title, g.radios.map(radioCard))).join("")}`);
}

async function viewSearch(q) {
  const recents = JSON.parse(store.get("sona.searches") || "[]");
  const html = page(`<h1 class="page-title">Rechercher</h1>
    <label class="search-hero">${icons.search}<input id="q" type="search" placeholder="Artistes, titres, albums, liens…" value="${esc(q)}" autocomplete="off" enterkeyhint="search"></label>
    ${recents.length ? `<div class="chips" id="recents">${recents.map((r) => `<button class="chip">${esc(r)}</button>`).join("")}</div>` : ""}
    <div id="results"></div>`);
  setTimeout(() => {
    const input = $("#q");
    if (!input) return;
    if (!isMobile() || q) {
      input.focus();
      input.setSelectionRange(input.value.length, input.value.length);
    }
    let timer;
    input.oninput = () => { clearTimeout(timer); timer = setTimeout(() => runSearch(input.value.trim()), 300); };
    input.onkeydown = (e) => { if (e.key === "Enter") { input.blur(); runSearch(input.value.trim()); } };
    $$("#recents .chip").forEach((c) => (c.onclick = () => { input.value = c.textContent; runSearch(c.textContent); }));
    runSearch(q);
  });
  return html;
}

const looksLikeLink = (q) => /^https?:\/\/|(deezer|spotify|apple|youtube|youtu\.be|music\.)\S*\//i.test(q);

async function runSearch(q) {
  const box = $("#results");
  if (!box) return;
  history.replaceState(null, "", q ? `#/search/${encodeURIComponent(q)}` : "#/search");
  nav.stacks.search = [location.hash];
  nav.current = location.hash;
  const seq = (runSearch.seq = (runSearch.seq || 0) + 1);
  if (!q) {
    // Rien de tapé : les radios, comme l'onglet Rechercher de l'app.
    const groups = await radioGroups().catch(() => []);
    if (seq !== runSearch.seq || !$("#results")) return;
    box.innerHTML = groups.map((g) => shelf(g.title, g.radios.map(radioCard))).join("");
    $$("[data-radio]", box).forEach((b) => (b.onclick = (e) => { e.preventDefault(); startRadio(b.dataset.radio, b.dataset.title); }));
    bindPage(box);
    return;
  }
  if (looksLikeLink(q)) {
    box.innerHTML = `<p class="muted">Ouverture du lien…</p>`;
    try {
      const got = await api("/resolve", { method: "POST", body: JSON.stringify({ text: q }) });
      if (seq !== runSearch.seq) return;
      if (got.kind === "track" && got.track) { playList([got.track], 0, ""); box.innerHTML = trackTable([got.track], "Lien"); bindPage(box); }
      else if (got.kind === "album" && got.album) go(`#/album/${got.album.source}/${got.album.source_id}`);
      else if (got.kind === "playlist" && got.album) go(`#/dplaylist/${got.album.source}/${got.album.source_id}`);
      else if (got.kind === "artist" && got.artist) go(`#/artist/${got.artist.source}/${got.artist.source_id}`);
      return;
    } catch (e) {
      if (seq === runSearch.seq) box.innerHTML = empty("🔗", "Lien non reconnu", e.message);
      return;
    }
  }
  box.innerHTML = `<div class="loading-row"><span class="spinner"></span></div>`;
  const [songs, artists, albums] = await Promise.all([
    api(`/search?q=${encodeURIComponent(q)}&limit=24`).then((r) => r.tracks).catch(() => []),
    api(`/search/artists?q=${encodeURIComponent(q)}&limit=12`).catch(() => []),
    api(`/search/albums?q=${encodeURIComponent(q)}&limit=12`).catch(() => []),
  ]);
  if (seq !== runSearch.seq || !$("#results")) return;
  const recents = [q, ...JSON.parse(store.get("sona.searches") || "[]").filter((r) => r.toLowerCase() !== q.toLowerCase())].slice(0, 8);
  store.set("sona.searches", JSON.stringify(recents));
  if (!songs.length && !artists.length && !albums.length) {
    box.innerHTML = empty("🔍", "Aucun résultat", `Rien trouvé pour « ${q} ».`);
    return;
  }
  const top = artists[0] && songs[0] && artists[0].name.toLowerCase() === songs[0].artist.toLowerCase() ? artists[0] : null;
  const topHtml = top
    ? `<a class="top-card" href="#/artist/${top.source}/${top.source_id}"><img class="round" src="${esc(top.picture_url || "")}" alt=""><div class="t">${esc(top.name)}</div><div class="s">Artiste</div></a>`
    : songs[0] ? `<button class="top-card" data-top><img src="${esc(big(songs[0].cover_url, 300))}" alt=""><div class="t">${esc(songs[0].title)}</div><div class="s">Titre · ${esc(songs[0].artist)}</div></button>` : "";
  box.innerHTML = `<section class="section"><div class="section-head"><h2>Meilleur résultat</h2></div>
      <div class="top-result">${topHtml}<div>${trackTable(songs.slice(0, 5), `Recherche « ${q} »`, { numbers: false, showAlbum: false })}</div></div></section>
    ${shelf("Artistes", artists.map((a) => card({ href: `#/artist/${a.source}/${a.source_id}`, cover: a.picture_url, title: a.name, subtitle: a.fans ? `${a.fans.toLocaleString("fr-FR")} fans` : "Artiste", round: true })), { kind: "round" })}
    ${shelf("Albums", albums.map((a) => card({ href: `#/album/${a.source}/${a.source_id}`, cover: a.cover_url, title: a.title, subtitle: [a.artist, a.year?.slice(0, 4)].filter(Boolean).join(" · ") })))}
    ${songs.length > 5 ? `<section class="section"><div class="section-head"><h2>Titres</h2></div>${trackTable(songs.slice(5), `Recherche « ${q} »`)}</section>` : ""}`;
  const topButton = $("[data-top]", box);
  if (topButton) topButton.onclick = () => playList(songs, 0, `Recherche « ${q} »`);
  bindPage(box);
}

function likeButton(kind, source, id, set) {
  const on = set.has(`${source}:${id}`);
  return `<button class="btn ghost icon-only ${on ? "on" : ""}" data-like-kind="${kind}" data-src="${esc(source)}" data-id="${esc(id)}" title="${on ? "Dans ta bibliothèque" : "Ajouter à la bibliothèque"}">${on ? icons.heartFill : icons.heart}</button>`;
}

function bindLikeButtons(root = document) {
  $$("[data-like-kind]", root).forEach((b) => (b.onclick = async () => {
    const { likeKind: kind, src, id } = b.dataset;
    const set = kind === "album" ? state.likedAlbums : state.likedArtists;
    const key = `${src}:${id}`;
    const on = set.has(key);
    try {
      if (on) await api(`/library/${kind}/${encodeURIComponent(src)}/${encodeURIComponent(id)}`, { method: "DELETE" });
      else await api(`/library/${kind}`, { method: "POST", body: JSON.stringify({ source: src, source_id: id }) });
      on ? set.delete(key) : set.add(key);
      b.classList.toggle("on", !on);
      b.innerHTML = on ? icons.heart : icons.heartFill;
      haptic();
      toast(on ? "Retiré de ta bibliothèque" : "Ajouté à ta bibliothèque");
    } catch (e) { toast(e.message); }
  }));
}

async function viewAlbum(source, id, isPlaylist = false) {
  $("#content").innerHTML = skeleton("");
  const album = await api(`/${isPlaylist ? "playlists" : "albums"}/${encodeURIComponent(source)}/${encodeURIComponent(id)}`);
  const tracks = (album.tracks || []).map((t) => isPlaylist ? t : ({ ...t, cover_url: t.cover_url || album.cover_url, album: t.album || album.title, album_source_id: t.album_source_id || album.source_id }));
  const total = tracks.reduce((s, t) => s + (t.duration_seconds || 0), 0);
  const list = register(tracks, album.title);
  setTimeout(() => {
    bindLikeButtons();
    $("[data-addall]")?.addEventListener("click", () => addToPlaylistSheet(tracks));
  });
  return page(hero({
    cover: album.cover_url, kind: isPlaylist ? "Playlist" : "Album", title: album.title, by: album.artist,
    byHref: album.artist_source_id && !isPlaylist ? `#/artist/${album.source}/${album.artist_source_id}` : "",
    info: [album.year?.slice(0, 4), plural(tracks.length, "titre"), total ? minutesLabel(total / 60) : ""].filter(Boolean).join(" · "), list,
    extra: (isPlaylist ? "" : likeButton("album", album.source, album.source_id, state.likedAlbums))
      + `<button class="btn ghost icon-only" data-addall title="Ajouter à une playlist">${icons.plus}</button>`,
  }) + trackTable(tracks, album.title, { showAlbum: isPlaylist }));
}

async function viewArtist(source, id) {
  $("#content").innerHTML = skeleton("");
  const base = `/artists/${encodeURIComponent(source)}/${encodeURIComponent(id)}`;
  const [artist, top, albums, related] = await Promise.all([
    api(base), api(`${base}/top-tracks`).catch(() => []),
    api(`${base}/albums`).catch(() => ({ albums: [], singles: [] })), api(`${base}/related`).catch(() => []),
  ]);
  const list = register(top, artist.name);
  setTimeout(() => {
    bindLikeButtons();
    $("[data-artist-radio]")?.addEventListener("click", () => playStation(`Radio ${artist.name}`, () => api(`${base}/radio`)).catch((e) => toast(e.message)));
  });
  return page(hero({
    cover: artist.picture_url, kind: "Artiste", title: artist.name, round: true,
    info: artist.fans ? `${artist.fans.toLocaleString("fr-FR")} fans` : "", list: top.length ? list : "",
    extra: `<button class="btn ghost" data-artist-radio>${icons.radio} Radio</button>` + likeButton("artist", artist.source, artist.source_id, state.likedArtists),
  }) + (top.length ? `<section class="section"><div class="section-head"><h2>Titres populaires</h2></div>${trackTable(top.slice(0, 10), artist.name)}</section>` : "")
    + shelf("Albums", (albums.albums || []).map((a) => card({ href: `#/album/${a.source}/${a.source_id}`, cover: a.cover_url, title: a.title, subtitle: a.year?.slice(0, 4) })))
    + shelf("Singles et EP", (albums.singles || []).map((a) => card({ href: `#/album/${a.source}/${a.source_id}`, cover: a.cover_url, title: a.title, subtitle: a.year?.slice(0, 4) })))
    + shelf("Artistes similaires", related.map((a) => card({ href: `#/artist/${a.source}/${a.source_id}`, cover: a.picture_url, title: a.name, round: true })), { kind: "round" }));
}

const VISIBILITY = {
  private: ["Privée", "Toi seul la vois", icons.lock],
  friends: ["Partagée", "Tes amis la voient sur ton profil", icons.friends],
  collaborative: ["Collaborative", "Tes amis peuvent y ajouter des titres", icons.globe],
};

async function viewUserPlaylist(id) {
  $("#content").innerHTML = skeleton("");
  const p = await api(`/me/playlists/${encodeURIComponent(id)}`);
  const entries = p.entries || [];
  const tracks = entries.map((e) => e.track || e);
  const total = tracks.reduce((s, t) => s + (t.duration_seconds || 0), 0);
  const ctx = { playlist: p, entries };
  const importing = p.import_status === "importing";
  if (importing) {
    const timer = setTimeout(() => location.hash === `#/playlist/${id}` && route(), 2500);
    onLeave(() => clearTimeout(timer));
  }
  setTimeout(() => $("[data-pl-menu]")?.addEventListener("click", () => playlistMenu(p)));
  const vis = VISIBILITY[p.visibility] || VISIBILITY.private;
  return page(hero({
    cover: p.cover_url, covers: p.covers, kind: p.is_owner ? `Playlist · ${vis[0]}` : `Playlist de ${p.owner_name || "un ami"}`, title: p.name,
    by: p.description || "",
    info: [plural(tracks.length, "titre"), total ? minutesLabel(total / 60) : "",
      importing ? `Import… ${p.import_done}/${p.import_total ?? "?"}` : p.import_missing ? `${p.import_missing} introuvable(s)` : ""].filter(Boolean).join(" · "),
    list: tracks.length ? register(tracks, p.name, ctx) : "",
    extra: `<button class="btn ghost icon-only" data-pl-menu title="Options">${icons.more}</button>`,
  }) + (p.import_error ? `<p class="error-text">${esc(p.import_error)}</p>` : "")
    + (tracks.length ? trackTable(tracks, p.name, { ctx }) : empty("♫", "Playlist vide", "Ajoute des titres avec le bouton … d'un titre, ou depuis le lecteur.")));
}

function playlistMenu(p) {
  const items = [];
  if (p.can_edit && p.is_owner !== false) {
    items.push({ icon: icons.pencil, label: "Renommer", run: async () => {
      const name = await askText({ title: "Renommer la playlist", value: p.name, confirm: "Renommer" });
      if (!name) return;
      await api(`/me/playlists/${p.id}`, { method: "PATCH", body: JSON.stringify({ name }) });
      loadSidebar(); route();
    } });
  }
  if (p.is_owner) {
    items.push({ icon: VISIBILITY[p.visibility]?.[2] || icons.lock, label: `Visibilité : ${VISIBILITY[p.visibility]?.[0] || "Privée"}`, run: () => actionSheet("Qui peut la voir ?",
      Object.entries(VISIBILITY).map(([key, [label, sub, icon]]) => ({ icon, label, sub, checked: key === p.visibility, run: async () => {
        await api(`/me/playlists/${p.id}`, { method: "PATCH", body: JSON.stringify({ visibility: key }) });
        toast(`Playlist ${label.toLowerCase()}`); route();
      } }))) });
    if (p.origin) items.push({ icon: icons.download, label: "Réimporter depuis la source", run: async () => {
      await api(`/me/playlists/${p.id}/reimport`, { method: "POST" }); toast("Réimport lancé"); route();
    } });
  }
  items.push({ icon: icons.wave, label: "Blind test sur cette playlist", run: () => { bt.pending = { mode: "playlist", ref: String(p.id), label: p.name }; go("#/blindtest"); } });
  if (p.is_owner) {
    items.push({ icon: icons.trash, label: "Supprimer la playlist", danger: true, run: async () => {
      if (!(await confirmSheet(`Supprimer « ${p.name} » ?`, "Supprimer"))) return;
      await api(`/me/playlists/${p.id}`, { method: "DELETE" });
      toast("Playlist supprimée"); loadSidebar(); go("#/library/playlists");
    } });
  }
  actionSheet(p.name, items);
}

async function viewSmart(id) {
  $("#content").innerHTML = skeleton("");
  const [tracks, lists] = await Promise.all([
    api(`/smart/${encodeURIComponent(id)}?tz=${encodeURIComponent(tz())}`),
    state.smart.length ? state.smart : api(`/smart?tz=${encodeURIComponent(tz())}`).catch(() => []),
  ]);
  const meta = lists.find((s) => s.id === id) || { title: "Playlist intelligente", subtitle: "" };
  return page(hero({ cover: tracks[0]?.cover_url, kind: "Playlist intelligente", title: meta.title, info: meta.subtitle, list: register(tracks, meta.title) })
    + (tracks.length ? trackTable(tracks, meta.title) : empty("✦", "Rien pour l'instant", "Cette playlist se remplit toute seule avec tes écoutes.")));
}

async function viewMix(id) {
  $("#content").innerHTML = skeleton("");
  const mix = (await api("/home/mixes")).find((m) => m.id === id);
  if (!mix) return page(empty("♫", "Mix introuvable", "Il a peut-être été renouvelé."));
  return page(hero({ cover: mix.covers[0], kind: "Mix Sona", title: mix.title, info: mix.subtitle, list: register(mix.tracks, mix.title) })
    + trackTable(mix.tracks, mix.title));
}

const LIB_KINDS = [["playlists", "Playlists"], ["tracks", "Titres"], ["albums", "Albums"], ["artists", "Artistes"]];

async function viewLibrary(kind) {
  if (!LIB_KINDS.some(([k]) => k === kind)) kind = "playlists";
  const seg = `<div class="segmented">${LIB_KINDS.map(([k, label]) => `<a href="#/library/${k}" class="${k === kind ? "on" : ""}">${label}</a>`).join("")}</div>`;
  $("#content").innerHTML = page(`<h1 class="page-title">Bibliothèque</h1>${seg}<div class="loading-row"><span class="spinner"></span></div>`);
  let body = "";
  if (kind === "playlists") {
    const [playlists, smart] = await Promise.all([api("/me/playlists").catch(() => []), api(`/smart?tz=${encodeURIComponent(tz())}`).catch(() => [])]);
    state.playlists = playlists;
    state.smart = smart;
    renderSidebarLists();
    if (playlists.some((p) => p.import_status === "importing")) {
      const timer = setTimeout(() => location.hash.startsWith("#/library") && route(), 2500);
      onLeave(() => clearTimeout(timer));
    }
    setTimeout(() => {
      $("[data-new-pl]")?.addEventListener("click", () => newPlaylist());
      $("[data-import-pl]")?.addEventListener("click", importPlaylist);
    });
    body = `<div class="pill-row"><button class="btn" data-new-pl>${icons.plus} Nouvelle</button><button class="btn ghost" data-import-pl>${icons.download} Importer</button></div>
      ${shelf("Faites pour toi", smart.map((s) => card({ href: `#/smart/${s.id}`, covers: s.covers, cover: s.covers[0], title: s.title, subtitle: plural(s.count, "titre") })))}
      <section class="section"><div class="section-head"><h2>Tes playlists</h2></div>
      ${playlists.length ? `<div class="grid">${playlists.map((p) => {
        const importing = p.import_status === "importing";
        return card({
          href: `#/playlist/${p.id}`, cover: p.cover_url || (p.covers || [])[0], covers: p.cover_url ? null : p.covers, title: p.name,
          subtitle: importing ? `Import… ${p.import_done}/${p.import_total ?? "?"}` : p.import_status === "failed" ? "Import impossible" : `${plural(p.track_count, "titre")}${p.is_owner === false ? ` · ${p.owner_name}` : ""}`,
        });
      }).join("")}</div>` : empty("♫", "Aucune playlist", "Crée ta première playlist, ou importe-en une depuis Spotify, Apple Music ou Deezer.")}</section>`;
  } else if (kind === "tracks") {
    const data = await api("/library/track?limit=500").catch(() => ({ items: [] }));
    const tracks = (data.items || []).map((i) => i.track || { source: i.source, source_id: i.source_id, title: i.title, artist: i.subtitle || "", cover_url: i.cover_url }).filter((t) => t.source_id);
    state.liked = new Set(tracks.map(trackKey));
    const list = register(tracks, "Tes titres");
    body = tracks.length ? `<p class="page-sub">${plural(tracks.length, "titre")}</p><div class="pill-row"><button class="btn" data-play="${list}">${icons.play} Lecture</button><button class="btn ghost" data-shuffle="${list}">${icons.shuffle} Aléatoire</button></div>${trackTable(tracks, "Tes titres")}`
      : empty("♡", "Rien ici pour l'instant", "Ajoute des titres avec le cœur, ici ou dans l'app.");
  } else {
    const k = kind === "albums" ? "album" : "artist";
    const data = await api(`/library/${k}?limit=500`).catch(() => ({ items: [] }));
    const items = data.items || [];
    (k === "album" ? state.likedAlbums = new Set(items.map(trackKey)) : state.likedArtists = new Set(items.map(trackKey)));
    body = items.length ? `<div class="grid ${k === "artist" ? "round-grid" : ""}">${items.map((i) => card({
      href: `#/${k}/${i.source}/${i.source_id}`, cover: i.cover_url, title: i.title, subtitle: i.subtitle || "", round: k === "artist",
    })).join("")}</div>` : empty(k === "album" ? "💿" : "🎤", "Rien ici pour l'instant", `Ajoute ${k === "album" ? "un album" : "un artiste"} avec le cœur de sa fiche.`);
  }
  return page(`<h1 class="page-title">Bibliothèque</h1>${seg}${body}`);
}

async function newPlaylist(tracks = []) {
  const name = await askText({ title: "Nouvelle playlist", placeholder: "Nom de la playlist", confirm: "Créer" });
  if (!name) return null;
  try {
    const created = await api("/me/playlists", { method: "POST", body: JSON.stringify({ name, tracks: tracks.map(cleanTrack) }) });
    toast(tracks.length ? `Ajouté à « ${name} »` : "Playlist créée");
    loadSidebar();
    if (!tracks.length) go(`#/playlist/${created.id}`);
    return created;
  } catch (e) { toast(e.message); return null; }
}

async function importPlaylist() {
  const url = await askText({
    title: "Importer une playlist", placeholder: "Lien Spotify, Apple Music, Deezer ou YouTube", confirm: "Importer",
    hint: "Colle le lien de partage de la playlist : Sona retrouve chaque titre.",
  });
  if (!url) return;
  try {
    const created = await api("/me/playlists/import", { method: "POST", body: JSON.stringify({ url }) });
    toast("Import lancé");
    go(`#/playlist/${created.id}`);
  } catch (e) { toast(e.message); }
}

// ── Santé de la lecture (admin) ───────────────────────────────────────────

const STATES = {
  ok: ["Tout fonctionne", "La musique se lance normalement.", "ok"],
  degraded: ["Lecture perturbée", "Certains titres ne se lancent pas.", "warn"],
  down: ["Lecture en panne", "Les titres ne se lancent plus.", "bad"],
};

function ago(seconds) {
  if (seconds == null) return "jamais";
  if (seconds < 90) return "à l'instant";
  if (seconds < 3600) return `il y a ${Math.round(seconds / 60)} min`;
  if (seconds < 86400) return `il y a ${Math.round(seconds / 3600)} h`;
  return `il y a ${Math.round(seconds / 86400)} j`;
}

async function viewHealth() {
  $("#content").innerHTML = skeleton("Santé de la lecture");
  const data = await api("/admin/streaming");
  const h = data.health;
  const [title, sub, tone] = STATES[h.state] || STATES.ok;
  const update = data.ytdlp.last_update;
  const cookies = data.cookies;
  const cookieState = !cookies.present ? ["Aucun fichier", "bad"] : cookies.logged_in === false ? ["Déconnectés (expirés)", "bad"]
    : cookies.logged_in ? ["Connectés", "ok"] : ["Pas encore vérifiés", "warn"];
  setTimeout(bindHealth);
  return page(`<h1 class="page-title">Santé de la lecture</h1>
    <p class="page-sub">Sona surveille la lecture et se répare tout seul quand il peut. Ici, de quoi réparer le reste sans toucher au serveur.</p>
    <div class="health-hero ${tone}"><span class="dot"></span><div><div class="t">${title}</div>
      <div class="s">${esc(h.advice || sub)}</div>
      <div class="meta">${h.recent_ok} titre(s) lancé(s) · ${h.recent_failures} échec(s) sur la dernière demi-heure · dernier titre lancé ${ago(h.last_success_seconds)}</div></div></div>
    <div class="health-grid">
      <section class="health-card">
        <div class="k">Cookies YouTube</div><div class="v"><span class="pill-state ${cookieState[1]}">${cookieState[0]}</span></div>
        <p>${cookies.updated_at ? `Envoyés ${ago(Date.now() / 1000 - cookies.updated_at)}.` : ""} YouTube les demande pour ne pas prendre le serveur pour un robot. Ils expirent de temps en temps.</p>
        <details><summary>Comment les exporter</summary><ol>
          <li>Ouvre une fenêtre de <b>navigation privée</b> et connecte-toi sur youtube.com.</li>
          <li>Avec l'extension « Get cookies.txt LOCALLY », exporte les cookies <b>de ce site uniquement</b>.</li>
          <li><b>Ferme la fenêtre privée</b> tout de suite (sinon Google change les cookies et l'export meurt).</li>
          <li>Envoie le fichier ici.</li></ol></details>
        <label class="btn" style="cursor:pointer">${icons.plus} Envoyer cookies.txt<input type="file" id="cookie-file" accept=".txt,text/plain" hidden></label>
      </section>
      <section class="health-card">
        <div class="k">yt-dlp</div><div class="v">${esc(data.ytdlp.version || "?")}</div>
        <p>${update ? `${esc(update.message)} <span class="muted">(${ago(Date.now() / 1000 - update.checked_at)})</span>` : "Mise à jour automatique chaque nuit à 4 h, avec essai de lecture et retour à l'ancienne version si la nouvelle casse quelque chose."}</p>
        <div style="display:flex;gap:10px;flex-wrap:wrap">
          <button class="btn" id="ytdlp-update">Mettre à jour</button>
          <button class="btn ghost" id="selftest">Essai de lecture</button>
        </div>
      </section>
    </div>
    <p class="health-result" id="health-result"></p>`);
}

function bindHealth() {
  const result = (text, bad) => { const el = $("#health-result"); if (el) { el.textContent = text; el.classList.toggle("bad", !!bad); } };
  $("#cookie-file")?.addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    result("Envoi et vérification auprès de YouTube…");
    try {
      const got = await api("/admin/youtube-cookies", { method: "POST", body: JSON.stringify({ content: await file.text() }) });
      result(got.message, got.logged_in === false);
      setTimeout(route, 1500);
    } catch (err) { result(err.message, true); }
  });
  $("#selftest")?.addEventListener("click", async () => {
    result("Essai de lecture d'une vidéo YouTube…");
    try {
      const got = await api("/admin/streaming/selftest", { method: "POST" });
      result(got.ok ? `✅ YouTube répond (${got.message}).` : `❌ ${got.message}`, !got.ok);
    } catch (err) { result(err.message, true); }
  });
  $("#ytdlp-update")?.addEventListener("click", async () => {
    try { result((await api("/admin/ytdlp/update", { method: "POST" })).message); } catch (err) { result(err.message, true); }
  });
}

// ── Lecture ───────────────────────────────────────────────────────────────

function shuffled(list) {
  const a = [...list];
  for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
  return a;
}

function playList(tracks, index, name, { keepStation = false } = {}) {
  let queue = [...tracks];
  if (!queue.length) return;
  // Invité d'une écoute ensemble : un titre touché se propose à la session
  // (ou on quitte la session pour l'écouter seul).
  if (partyGuest()) {
    const t = queue[index] || queue[0];
    return actionSheet(t.title, [
      { icon: icons.headphones, label: "Proposer à la session", sub: "La plus votée passe après le titre en cours", run: () => partyPropose(t) },
      { icon: icons.play, label: "Quitter la session et l'écouter", run: async () => { await partyLeave(); playList(tracks, index, name, { keepStation }); } },
    ]);
  }
  if (state.shuffle) {
    const first = queue.splice(index, 1)[0];
    queue = [first, ...shuffled(queue)];
    index = 0;
  }
  if (!keepStation) state.station = null;
  state.queue = queue;
  state.name = name || "";
  playAt(index);
}

/** Radio (station Deezer, radio DJ, radio d'artiste…) : la file se recharge
    d'elle-même quand elle se vide. */
async function playStation(name, loader) {
  if (partyGuest()) return toast("Tu es dans une écoute ensemble : c'est l'hôte qui choisit la musique");
  const tracks = await loader();
  if (!tracks?.length) throw new Error("Rien à jouer pour cette radio.");
  state.shuffle = false;
  playList(tracks, 0, name, { keepStation: true });
  state.station = { name, loader };
}

/** Radio DJ à partir d'un titre : des morceaux qui s'enchaînent bien avec lui. */
function djLoader(seed) {
  return () => {
    const exclude = state.queue.slice(-150).map((t) => t.source_id).join(",");
    const q = new URLSearchParams({ title: seed.title, artist: seed.artist, exclude });
    return api(`/djradio/${encodeURIComponent(seed.source)}/${encodeURIComponent(seed.source_id)}?${q}`);
  };
}

async function startDJRadio(seed) {
  if (partyGuest()) return toast("Tu es dans une écoute ensemble : c'est l'hôte qui choisit la musique");
  toast(`Radio DJ à partir de « ${seed.title} »…`);
  try {
    const tracks = await djLoader(seed)();
    state.shuffle = false;
    playList([seed, ...tracks.filter((t) => !sameTrack(t, seed))], 0, `Radio · ${seed.title}`, { keepStation: true });
    state.station = { name: `Radio · ${seed.title}`, loader: () => djLoader(state.queue[state.queue.length - 1])() };
  } catch (e) { toast(e.message); }
}

/** File terminée : la radio continue, ou la lecture automatique (réglage
    de l'app) enchaîne sur des titres similaires. */
async function extendQueue() {
  const last = state.queue[state.queue.length - 1];
  // Invité d'une écoute ensemble : c'est l'hôte qui choisit la suite.
  if (!last || (party.state && !party.state.is_host)) return false;
  let loader = state.station?.loader;
  if (!loader && state.settings?.autoplay !== false) loader = djLoader(last);
  if (!loader) return false;
  try {
    const fresh = (await loader()).filter((t) => !state.queue.some((q) => sameTrack(q, t)));
    if (!fresh.length) return false;
    state.queue.push(...fresh);
    if (!state.station) state.name = state.name || "Lecture automatique";
    if (state.npOpen && state.npTab === "queue") renderQueue();
    return true;
  } catch { return false; }
}

function playNext(track) {
  if (state.index < 0) return playList([track], 0, "");
  state.queue.splice(state.index + 1, 0, track);
  toast(`« ${track.title} » sera lu ensuite`);
  if (state.npOpen && state.npTab === "queue") renderQueue();
}

function addToQueue(track) {
  if (state.index < 0) return playList([track], 0, "");
  state.queue.push(track);
  toast(`« ${track.title} » ajouté à la file`);
  if (state.npOpen && state.npTab === "queue") renderQueue();
}

function playAt(index, { position = 0 } = {}) {
  const t = state.queue[index];
  if (!t) { audio.pause(); return; }
  state.index = index;
  Object.assign(state, { listened: 0, lastTick: 0, scrobbled: false, lyrics: null, lastLyric: -1, startedAt: new Date().toISOString() });
  state.connect.claim = true;
  audio.src = `${BASE}/stream/${encodeURIComponent(t.source)}/${encodeURIComponent(t.source_id)}?token=${encodeURIComponent(token)}`;
  if (position > 1) {
    const seek = () => { audio.currentTime = position; audio.removeEventListener("loadedmetadata", seek); };
    audio.addEventListener("loadedmetadata", seek);
  }
  djAnnounce(t, state.queue[index - 1]);
  remotePlay();
  reportNowPlaying(t, position);
  if ("mediaSession" in navigator) {
    navigator.mediaSession.metadata = new MediaMetadata({
      title: t.title, artist: t.artist, album: t.album || "",
      artwork: t.cover_url ? [{ src: big(t.cover_url, 512), sizes: "512x512", type: "image/jpeg" }] : [],
    });
  }
  document.title = `${t.title} · ${t.artist}`;
  renderTopbar();
  renderNowPlaying();
  refreshCurrentMarks();
  loadLyrics(t);
  loadMoments(t);
  singTrackChanged(t);
  // Dernier titre de la file : la suite est préparée pendant l'écoute.
  if (index >= state.queue.length - 2) extendQueue();
  partyNotify();
}

/** « En train d'écouter » pour les amis et sur Last.fm. */
function reportNowPlaying(t, position = 0) {
  api("/plays/now", {
    method: "POST",
    body: JSON.stringify({
      title: t.title, artist: t.artist, album: t.album, duration_seconds: t.duration_seconds, source: t.source, source_id: t.source_id,
      cover_url: t.cover_url, artist_source_id: t.artist_source_id, album_source_id: t.album_source_id, position_seconds: position || 0,
    }),
  }).catch(() => {});
}

async function next(auto = false) {
  // Invité d'une écoute ensemble : c'est l'hôte qui enchaîne.
  if (partyGuest()) return auto ? undefined : partyIntercept("next");
  if (!auto && remoteDevice()) return sendCommand(remoteDevice().id, "next");
  if (state.repeat && auto) { audio.currentTime = 0; audio.play(); return; }
  if (state.index + 1 >= state.queue.length) await extendQueue();
  if (state.index + 1 < state.queue.length) playAt(state.index + 1);
  else if (auto) { audio.pause(); renderTopbar(); }
}

function prev() {
  if (partyIntercept("prev")) return;
  if (remoteDevice()) return sendCommand(remoteDevice().id, "previous");
  if (audio.currentTime > 3 || state.index <= 0) audio.currentTime = 0;
  else playAt(state.index - 1);
}

function toggle() {
  if (partyIntercept("toggle")) return;
  const remote = remoteDevice();
  // « lecture » ou « pause » explicite (pas « bascule ») : plusieurs appuis
  // rapprochés ne s'annulent pas.
  if (remote) return sendCommand(remote.id, deviceNow(remote).paused ? "play" : "pause");
  if (!audio.src) return state.connect.session ? resumeHere() : null;
  if (audio.paused) { state.connect.claim = true; audio.play(); } else audio.pause();
}

async function toggleLike(t, button) {
  const key = `${t.source}:${t.source_id}`;
  const liked = state.liked.has(key);
  try {
    if (liked) {
      await api(`/library/track/${encodeURIComponent(t.source)}/${encodeURIComponent(t.source_id)}`, { method: "DELETE" });
      state.liked.delete(key);
      toast("Retiré de ta bibliothèque");
    } else {
      await api("/library/track", { method: "POST", body: JSON.stringify({ source: t.source, source_id: t.source_id }) });
      state.liked.add(key);
      toast("Ajouté à ta bibliothèque");
    }
  } catch (e) { toast(e.message); return; }
  if (button) { button.classList.toggle("liked", !liked); button.innerHTML = !liked ? icons.heartFill : icons.heart; }
  if (sameTrack(t, state.queue[state.index])) { renderTopbar(); renderNowPlaying(); startConnect.now?.(); }
}

function refreshCurrentMarks() {
  const current = state.queue[state.index];
  $$("[data-list]").forEach((listEl) => {
    const data = registry.get(listEl.dataset.list);
    if (!data) return;
    $$("[data-i]", listEl).forEach((row) => {
      const on = sameTrack(data.tracks[+row.dataset.i], current);
      row.classList.toggle("current", on);
      const n = $(".n", row);
      if (n) n.innerHTML = on ? bars() + icons.play : `<span>${+row.dataset.i + 1}</span>${icons.play}`;
    });
  });
}

// ── Lecteur du haut ───────────────────────────────────────────────────────

function renderTopbar() {
  const bar = $("#topbar");
  if (!bar) return;
  const remote = remoteDevice();
  const rnow = deviceNow(remote);
  const t = remote ? rnow.track : state.queue[state.index];
  const liked = t && state.liked.has(`${t.source}:${t.source_id}`);
  const playingIcon = remote ? (rnow.paused ? icons.play : icons.pause) : audio.paused ? icons.play : icons.pause;
  const volumeShown = remote ? (state.connect.pendingVolume ?? remote.volume ?? 1) : audio.volume;
  bar.innerHTML = `
    <div class="transport">
      <button class="tbtn small ${state.shuffle ? "on" : ""}" data-act="shuffle" title="Aléatoire">${icons.shuffle}</button>
      <button class="tbtn" data-act="prev" title="Précédent">${icons.prev}</button>
      <button class="tbtn big" data-act="toggle" title="Lecture/Pause (espace)">${playingIcon}</button>
      <button class="tbtn" data-act="next" title="Suivant">${icons.next}</button>
      <button class="tbtn small ${state.repeat ? "on" : ""}" data-act="repeat" title="Répéter le titre">${icons.repeat}</button>
    </div>
    ${grip()}
    ${t ? `<div class="lcd ${remote ? "remote" : ""}"><img class="art" data-act="${remote ? "devices" : "open"}" src="${esc(big(t.cover_url, 120))}" alt="">
      <div class="meta" data-act="${remote ? "devices" : "open"}"><div class="t">${esc(t.title)}</div>
        <div class="a">${remote ? `<span class="on-device">${remote.kind === "iphone" ? icons.phone : icons.laptop} Sur ${esc(remote.name)}</span>` : `${esc(t.artist)}${t.album ? ` — ${esc(t.album)}` : ""}`}</div></div>
      <div class="progress" data-act="seek"><div class="fill" id="lcd-fill"></div></div></div>`
      : `<div class="lcd idle"><span>${icons.note}</span></div>`}
    ${grip()}
    <div class="right-tools">
      ${desktop ? `<button class="tbtn small ${desk.clients.length ? "on" : ""}" data-act="remote" title="Télécommande : pilote ce PC depuis ton téléphone">${icons.phone}</button>
      <button class="tbtn small ${desk.mini ? "on" : ""}" data-act="mini" title="Mini-lecteur">${icons.miniPlayer}</button>` : ""}
      <button class="tbtn small ${remote || otherDevices().length ? "on" : ""}" data-act="devices" title="Sona Connect : tes appareils">${icons.devices}</button>
      ${t ? `<button class="tbtn small ${liked ? "on" : ""}" data-act="like" title="Bibliothèque">${liked ? icons.heartFill : icons.heart}</button>` : ""}
      <button class="tbtn small ${state.npOpen && state.npTab === "lyrics" ? "on" : ""}" data-act="lyrics" title="Paroles">${icons.quote}</button>
      ${soundAvailable && !isMobile() ? `<button class="tbtn small ${viz.el ? "on" : ""}" data-act="viz" title="Visualiseur">${icons.wave}</button>` : ""}
      <button class="tbtn small ${state.npOpen && state.npTab === "queue" ? "on" : ""}" data-act="queue" title="À suivre">${icons.queue}</button>
      <div class="volume" title="${remote ? `Volume de ${esc(remote.name)}` : "Volume"}">${icons.speaker}<input type="range" class="slider" id="vol" min="0" max="1" step="0.01" value="${volumeShown}" style="--p:${volumeShown * 100}%" aria-label="Volume"></div>
    </div>`;
  bar.onclick = (e) => {
    const act = e.target.closest("[data-act]")?.dataset.act;
    if (!act) return;
    if (act === "devices") return toggleDevices();
    if (act === "remote") return openRemotePairing();
    if (act === "mini") return desktop?.set("mini", !desk.mini);
    if (act === "toggle") toggle();
    if (act === "prev") prev();
    if (act === "next") next();
    if (act === "shuffle") { state.shuffle = !state.shuffle; renderTopbar(); startConnect.now?.(); }
    if (act === "repeat") { state.repeat = !state.repeat; renderTopbar(); startConnect.now?.(); }
    if (act === "like" && t) toggleLike(t);
    if (act === "open") openNowPlaying(state.npTab);
    if (act === "lyrics") openNowPlaying("lyrics", true);
    if (act === "viz") viz.el ? closeVisualizer() : openVisualizer();
    if (act === "queue") openNowPlaying("queue", true);
    if (act === "seek" && remote && t?.duration_seconds) {
      const rect = e.target.closest(".progress").getBoundingClientRect();
      sendCommand(remote.id, "seek", { position: ((e.clientX - rect.left) / rect.width) * t.duration_seconds });
    } else if (act === "seek" && audio.duration) {
      const rect = e.target.closest(".progress").getBoundingClientRect();
      audio.currentTime = ((e.clientX - rect.left) / rect.width) * audio.duration;
    }
  };
  const vol = $("#vol");
  if (vol) {
    vol.oninput = () => {
      vol.style.setProperty("--p", `${vol.value * 100}%`);
      if (remoteDevice()) { state.connect.pendingVolume = +vol.value; return; }
      audio.volume = +vol.value;
      store.set("sona.volume", vol.value);
    };
    // Volume de l'appareil distant (iPhone) : envoyé au relâchement.
    vol.onchange = () => {
      const target = remoteDevice();
      if (!target) return;
      sendCommand(target.id, "volume", { volume: +vol.value });
      setTimeout(() => { state.connect.pendingVolume = null; }, 6000);
    };
  }
  renderMini();
  updateProgress();
  desktopReport();
}

/** Mini-lecteur du téléphone, posé au-dessus des onglets (comme dans l'app). */
function renderMini() {
  const mp = $("#mp");
  if (!mp) return;
  const remote = remoteDevice();
  const rnow = deviceNow(remote);
  const t = remote ? rnow.track : state.queue[state.index];
  document.body.classList.toggle("has-mini", !!t);
  if (!t) { mp.innerHTML = ""; return; }
  const paused = remote ? rnow.paused : audio.paused;
  mp.innerHTML = `<div class="mp-inner" data-mp="open">
    <img src="${esc(big(t.cover_url, 120))}" alt="">
    <div class="mp-meta"><div class="t">${esc(t.title)}</div>
      <div class="a">${remote ? `<span class="on-device">${remote.kind === "iphone" ? icons.phone : icons.laptop} Sur ${esc(remote.name)}</span>` : cast.screen ? `${icons.tv} Sur ${esc(cast.screen.name)}` : party.state ? `${icons.headphones} ${party.state.is_host ? "Ta session" : `Avec ${esc(party.state.host_name || "l'hôte")}`} · ${esc(t.artist)}` : esc(t.artist)}</div></div>
    <button class="mp-btn" data-mp="toggle" aria-label="Lecture/Pause">${paused ? icons.play : icons.pause}</button>
    <button class="mp-btn" data-mp="next" aria-label="Suivant">${icons.next}</button>
    <div class="mp-progress"><div class="fill" id="mp-fill"></div></div></div>`;
  mp.onclick = (e) => {
    const act = e.target.closest("[data-mp]")?.dataset.mp;
    if (act === "toggle") { e.stopPropagation(); haptic(); toggle(); }
    else if (act === "next") { e.stopPropagation(); haptic(); next(); }
    else if (act === "open") remote ? (chosenDevice() ? go("#/devices") : toggleDevices()) : openNowPlaying("art");
  };
}

function updateProgress() {
  const remote = remoteDevice();
  updateDevicesProgress();
  if (remote) {
    const rnow = deviceNow(remote);
    const dur = rnow.track?.duration_seconds || 0;
    const pctRemote = dur ? `${Math.min(100, (rnow.position / dur) * 100)}%` : "0%";
    const fill = $("#lcd-fill");
    if (fill) fill.style.width = pctRemote;
    const mini = $("#mp-fill");
    if (mini) mini.style.width = pctRemote;
    return;
  }
  const t = state.queue[state.index];
  const dur = audio.duration && isFinite(audio.duration) ? audio.duration : t?.duration_seconds || 0;
  const pct = dur ? Math.min(100, (audio.currentTime / dur) * 100) : 0;
  const fill = $("#lcd-fill");
  if (fill) fill.style.width = `${pct}%`;
  const mini = $("#mp-fill");
  if (mini) mini.style.width = `${pct}%`;
  const seek = $("#np-seek");
  if (seek && !seek._dragging) { seek.value = pct * 10; seek.style.setProperty("--p", `${pct}%`); }
  const cur = $("#np-cur"), rem = $("#np-rem");
  if (cur) cur.textContent = fmt(audio.currentTime);
  if (rem) rem.textContent = `-${fmt(Math.max(0, dur - audio.currentTime))}`;
}

// ── Lecteur plein écran ───────────────────────────────────────────────────
// Ordinateur : pochette à gauche, paroles ou file à droite. Téléphone : comme
// l'app — la pochette en grand, que les paroles ou la file remplacent, et on
// le ferme en le faisant glisser vers le bas.

function openNowPlaying(tab, toggleIfSame) {
  if (!state.queue[state.index]) return;
  if (tab === "art" && !isMobile()) tab = state.npTab === "art" ? "lyrics" : state.npTab;
  if (toggleIfSame && state.npOpen && state.npTab === tab) return closeNowPlaying();
  state.npTab = tab || state.npTab;
  state.npOpen = true;
  renderNowPlaying();
  $("#np").classList.add("open");
  document.body.classList.add("np-open");
  renderTopbar();
}

function closeNowPlaying() {
  state.npOpen = false;
  const np = $("#np");
  if (np) { np.classList.remove("open"); np.style.transform = ""; }
  document.body.classList.remove("np-open");
  renderTopbar();
}

function renderNowPlaying() {
  const np = $("#np");
  if (!np) return;
  const t = state.queue[state.index];
  if (!t) { np.innerHTML = ""; return; }
  if (isMobile()) return renderNowPlayingMobile(np, t);
  if (state.npTab === "art") state.npTab = "lyrics";
  const liked = state.liked.has(`${t.source}:${t.source_id}`);
  np.classList.toggle("paused", audio.paused);
  np.classList.remove("mobile");
  np.innerHTML = `
    <div class="np-bg"><img src="${esc(big(t.cover_url, 300))}" alt=""></div>
    <div class="np-top">
      <button class="tbtn" data-np="close" title="Fermer (Échap)">${icons.down}</button>${grip()}
      <div class="np-tabs"><button class="${state.npTab === "lyrics" ? "on" : ""}" data-np="lyrics">Paroles</button><button class="${state.npTab === "queue" ? "on" : ""}" data-np="queue">À suivre</button></div>${grip()}
      <div class="np-top-right"><button class="tbtn" data-np="more" title="Plus d'options">${icons.more}</button><button class="tbtn" data-np="devices" title="Sona Connect">${icons.devices}</button></div>
    </div>
    <div class="np-body">
      <div class="np-left">
        <img class="np-art" src="${esc(big(t.cover_url, 1000))}" alt="">
        <div class="np-meta"><div style="min-width:0"><div class="t">${esc(t.title)}</div>
          <div class="a">${t.artist_source_id ? `<span class="link" data-np="artist">${esc(t.artist)}</span>` : esc(t.artist)}</div></div>
          <button class="tbtn ${liked ? "on" : ""}" data-np="like" title="Bibliothèque">${liked ? icons.heartFill : icons.heart}</button></div>
        <div class="np-progress"><div class="np-seek-wrap"><input type="range" class="slider" id="np-seek" min="0" max="1000" value="0" aria-label="Position"><div class="moments" id="np-moments"></div></div>
          <div class="np-times"><span id="np-cur">0:00</span><span id="np-rem">-0:00</span></div></div>
        <div class="np-transport">
          <button class="tbtn small ${state.shuffle ? "on" : ""}" data-np="shuffle">${icons.shuffle}</button>
          <button class="tbtn" data-np="prev">${icons.prev}</button>
          <button class="tbtn big" data-np="toggle" id="np-toggle">${audio.paused ? icons.play : icons.pause}</button>
          <button class="tbtn" data-np="next">${icons.next}</button>
          <button class="tbtn small ${state.repeat ? "on" : ""}" data-np="repeat">${icons.repeat}</button>
        </div>
        <div class="np-sing" id="np-sing"></div>
      </div>
      <div class="np-right" id="np-right"></div>
    </div>`;
  bindNowPlaying(np, t);
  if (state.npTab === "queue") renderQueue(); else renderLyrics();
  renderSing();
  renderMoments();
  updateProgress();
}

function renderNowPlayingMobile(np, t) {
  const liked = state.liked.has(`${t.source}:${t.source_id}`);
  const view = ["lyrics", "queue"].includes(state.npTab) ? state.npTab : "art";
  np.classList.toggle("paused", audio.paused);
  np.classList.add("mobile");
  const singOpen = !!state.npSing;
  np.innerHTML = `
    <div class="np-bg"><img src="${esc(big(t.cover_url, 300))}" alt=""></div>
    <div class="np-m view-${view}">
      <div class="np-grab" data-np="close" aria-label="Fermer"><span></span></div>
      ${view === "art"
        ? `<div class="np-stage" data-np-swipe><img class="np-art" src="${esc(big(t.cover_url, 1000))}" alt=""></div>`
        : `<div class="np-mini-head"><img src="${esc(big(t.cover_url, 200))}" alt="" data-np="art">
            <div class="np-meta-s"><div class="t">${esc(t.title)}</div><div class="a">${esc(t.artist)}</div></div>
            <button class="tbtn ${liked ? "on" : ""}" data-np="like">${liked ? icons.heartFill : icons.heart}</button>
            <button class="tbtn" data-np="more">${icons.more}</button></div>
          <div class="np-stage np-panel" id="np-right"></div>`}
      ${view === "art" ? `<div class="np-meta"><div style="min-width:0"><div class="t">${esc(t.title)}</div>
          <div class="a">${t.artist_source_id ? `<span class="link" data-np="artist">${esc(t.artist)}</span>` : esc(t.artist)}</div></div>
          <button class="tbtn ${liked ? "on" : ""}" data-np="like" aria-label="J'aime">${liked ? icons.heartFill : icons.heart}</button>
          <button class="tbtn" data-np="more" aria-label="Plus d'options">${icons.more}</button></div>` : ""}
      <div class="np-progress"><div class="np-seek-wrap"><input type="range" class="slider" id="np-seek" min="0" max="1000" value="0" aria-label="Position"><div class="moments" id="np-moments"></div></div>
        <div class="np-times"><span id="np-cur">0:00</span><span id="np-rem">-0:00</span></div></div>
      <div class="np-transport">
        <button class="tbtn small ${state.shuffle ? "on" : ""}" data-np="shuffle" aria-label="Aléatoire">${icons.shuffle}</button>
        <button class="tbtn" data-np="prev" aria-label="Précédent">${icons.prev}</button>
        <button class="tbtn big" data-np="toggle" id="np-toggle" aria-label="Lecture/Pause">${audio.paused ? icons.play : icons.pause}</button>
        <button class="tbtn" data-np="next" aria-label="Suivant">${icons.next}</button>
        <button class="tbtn small ${state.repeat ? "on" : ""}" data-np="repeat" aria-label="Répéter">${icons.repeat}</button>
      </div>
      ${isIOS ? "" : `<div class="np-volume">${icons.speaker}<input type="range" class="slider" id="np-vol" min="0" max="1" step="0.01" value="${audio.volume}" style="--p:${audio.volume * 100}%" aria-label="Volume"></div>`}
      <div class="np-sing ${singOpen ? "" : "hidden"}" id="np-sing"></div>
      <div class="np-bottom">
        <button class="tbtn ${view === "lyrics" ? "on" : ""}" data-np="lyrics" aria-label="Paroles">${icons.quote}</button>
        <button class="tbtn ${sing.on || singOpen ? "on" : ""}" data-np="sing-panel" aria-label="Karaoké">${icons.mic}</button>
        <button class="tbtn ${otherDevices().length || cast.screen ? "on" : ""}" data-np="devices" aria-label="Appareils">${icons.devices}</button>
        <button class="tbtn ${view === "queue" ? "on" : ""}" data-np="queue" aria-label="À suivre">${icons.queue}</button>
      </div>
    </div>`;
  bindNowPlaying(np, t);
  const vol = $("#np-vol", np);
  if (vol) vol.oninput = () => { vol.style.setProperty("--p", `${vol.value * 100}%`); audio.volume = +vol.value; store.set("sona.volume", vol.value); };
  if (view === "queue") renderQueue(); else if (view === "lyrics") renderLyrics();
  renderSing();
  renderMoments();
  updateProgress();
}

function bindNowPlaying(np, t) {
  np.onclick = (e) => {
    const act = e.target.closest("[data-np]")?.dataset.np;
    if (!act) return;
    const mobile = isMobile();
    if (act === "close") closeNowPlaying();
    if (act === "devices") { e.stopPropagation(); toggleDevices(); }
    if (act === "lyrics" || act === "queue") {
      state.npTab = mobile && state.npTab === act ? "art" : act;
      renderNowPlaying(); renderTopbar();
    }
    if (act === "art") { state.npTab = "art"; renderNowPlaying(); }
    if (act === "sing-panel") { state.npSing = !state.npSing; $("#np-sing")?.classList.toggle("hidden", !state.npSing); e.target.closest("button").classList.toggle("on", state.npSing || sing.on); }
    if (act === "toggle") { haptic(); toggle(); }
    if (act === "prev") prev();
    if (act === "next") next();
    if (act === "shuffle") { state.shuffle = !state.shuffle; renderNowPlaying(); renderTopbar(); }
    if (act === "repeat") { state.repeat = !state.repeat; renderNowPlaying(); renderTopbar(); }
    if (act === "like") { haptic(); toggleLike(t); }
    if (act === "more") { e.stopPropagation(); trackMenu(t, { nowPlaying: true }); }
    if (act === "artist") { closeNowPlaying(); go(`#/artist/${t.source}/${t.artist_source_id}`); }
  };
  const seek = $("#np-seek", np);
  seek.oninput = () => { seek._dragging = true; seek.style.setProperty("--p", `${seek.value / 10}%`); };
  seek.onchange = () => {
    const dur = audio.duration && isFinite(audio.duration) ? audio.duration : t.duration_seconds || 0;
    if (dur) audio.currentTime = (seek.value / 1000) * dur;
    seek._dragging = false;
  };
}

/** Glisser le lecteur vers le bas le ferme ; sur la pochette, glisser à
    gauche ou à droite change de titre (comme le mini-lecteur de l'app). */
function bindNowPlayingGestures() {
  const np = $("#np");
  if (!np || np._gestures) return;
  np._gestures = true;
  let start = null;
  np.addEventListener("touchstart", (e) => {
    if (!isMobile() || !state.npOpen) return;
    const target = e.target;
    if (target.closest("input, .np-panel, .np-sing, .devices-pop")) { start = null; return; }
    const touch = e.touches[0];
    start = { x: touch.clientX, y: touch.clientY, t: Date.now(), swipe: !!target.closest("[data-np-swipe]"), axis: null };
  }, { passive: true });
  np.addEventListener("touchmove", (e) => {
    if (!start) return;
    const touch = e.touches[0];
    const dx = touch.clientX - start.x, dy = touch.clientY - start.y;
    if (!start.axis && Math.hypot(dx, dy) > 8) start.axis = Math.abs(dy) > Math.abs(dx) ? "y" : "x";
    if (start.axis === "y" && dy > 0) {
      np.style.transition = "none";
      np.style.transform = `translateY(${dy}px)`;
    } else if (start.axis === "x" && start.swipe) {
      const art = $(".np-art", np);
      if (art) art.style.transform = `translateX(${dx * 0.6}px) rotate(${dx / 40}deg)`;
    }
  }, { passive: true });
  np.addEventListener("touchend", (e) => {
    if (!start) return;
    const touch = e.changedTouches[0];
    const dx = touch.clientX - start.x, dy = touch.clientY - start.y;
    const fast = (Date.now() - start.t) < 250;
    np.style.transition = "";
    if (start.axis === "y") {
      if (dy > 140 || (fast && dy > 50)) closeNowPlaying();
      else np.style.transform = "";
    } else if (start.axis === "x" && start.swipe) {
      const art = $(".np-art", np);
      if (art) art.style.transform = "";
      if (Math.abs(dx) > 80) { haptic(); dx < 0 ? next() : prev(); }
    }
    start = null;
  });
}

function renderQueue() {
  const box = $("#np-right");
  if (!box) return;
  const rows = state.queue.map((t, i) => ({ t, i })).slice(Math.max(0, state.index - 3), state.index + 80);
  const label = state.station ? `${state.station.name} · radio` : state.name;
  box.innerHTML = `<div class="queue scroll"><h3>${label ? `À suivre · ${esc(label)}` : "À suivre"}</h3>
    ${rows.map(({ t, i }) => `<div class="qrow ${i === state.index ? "current" : ""} ${i < state.index ? "past" : ""}" data-q="${i}" role="button">
      <img src="${esc(big(t.cover_url, 120))}" alt=""><span style="min-width:0"><div class="t">${esc(t.title)}</div><div class="s">${esc(t.artist)}</div></span>
      <span class="d">${i === state.index ? bars() : i > state.index ? `<button class="q-x" data-qx="${i}" aria-label="Retirer">${icons.close}</button>` : ""}</span></div>`).join("")}
    ${state.index >= state.queue.length - 1 ? `<p class="q-end">${state.station || state.settings?.autoplay !== false ? "La suite arrive toute seule (lecture automatique)." : "Rien après ce morceau."}</p>` : ""}
    ${state.queue.length > state.index + 1 ? `<button class="q-clear" data-qclear>Vider la file</button>` : ""}</div>`;
  box.onclick = (e) => {
    const x = e.target.closest("[data-qx]");
    if (x) { e.stopPropagation(); state.queue.splice(+x.dataset.qx, 1); renderQueue(); return; }
    if (e.target.closest("[data-qclear]")) { state.queue.length = state.index + 1; state.station = null; renderQueue(); return; }
    const row = e.target.closest("[data-q]");
    if (row) playAt(+row.dataset.q);
  };
  $(".qrow.current", box)?.scrollIntoView({ block: "center" });
}

async function loadLyrics(t) {
  const q = new URLSearchParams({ title: t.title, artist: t.artist });
  if (t.album) q.set("album", t.album);
  if (t.duration_seconds) q.set("duration", t.duration_seconds);
  let lyrics = null;
  try { lyrics = await api(`/lyrics?${q}`); } catch {}
  if (!sameTrack(t, state.queue[state.index])) return;
  state.lyrics = { lines: lyrics?.lines || [], synced: !!lyrics?.synced, instrumental: !!lyrics?.instrumental };
  state.lastLyric = -1;
  if (state.npOpen && state.npTab === "lyrics") renderLyrics();
}

function renderLyrics() {
  const box = $("#np-right");
  if (!box) return;
  const ly = state.lyrics;
  if (!ly) { box.innerHTML = `<div class="lyrics"><p class="none">Chargement des paroles…</p></div>`; return; }
  if (!ly.lines.length) {
    box.innerHTML = `<div class="lyrics"><p class="none">${ly.instrumental ? "♪ Instrumental" : "Pas de paroles pour ce titre."}</p></div>`;
    return;
  }
  box.innerHTML = `<div class="lyrics ${ly.synced ? "" : "plain"}" id="lyr">${ly.lines.map((l, i) => `<p data-l="${i}">${esc(l.text || "♪")}</p>`).join("")}</div>`;
  if (ly.synced) {
    $$("[data-l]", box).forEach((p) => (p.onclick = () => {
      const time = ly.lines[+p.dataset.l].time;
      if (time != null) { audio.currentTime = time; if (audio.paused) audio.play(); }
    }));
  }
  state.lastLyric = -1;
  syncLyrics(true);
}

function syncLyrics(force) {
  if (!state.npOpen || state.npTab !== "lyrics" || !state.lyrics?.synced) return;
  const lines = state.lyrics.lines;
  const now = audio.currentTime + 0.25;
  let active = -1;
  for (let i = 0; i < lines.length; i++) { if (lines[i].time != null && lines[i].time <= now) active = i; else if (lines[i].time > now) break; }
  if (active === state.lastLyric && !force) return;
  state.lastLyric = active;
  const box = $("#lyr");
  if (!box) return;
  $$("p", box).forEach((p, i) => {
    p.classList.toggle("on", i === active);
    p.classList.toggle("near", Math.abs(i - active) === 1);
  });
  const el = box.querySelector("p.on") || box.querySelector("p");
  if (el) box.scrollTo({ top: el.offsetTop - box.clientHeight * 0.36, behavior: force ? "auto" : "smooth" });
}

// ── Karaoké (voix / instru séparées par IA sur le serveur) ───────────────
// Même principe que l'app : les deux pistes jouent ensemble, calées, et le
// curseur « Voix » ne règle que le volume de la voix (0 % : instru seule ;
// 100 % : titre normal, le mode se coupe). Elles passent par le Web Audio
// du navigateur, décodées en entier : aucun décalage possible entre elles.
// La balise <audio> continue de jouer le titre, muette, et sert d'horloge :
// progression, paroles, fin du titre, Sona Connect marchent comme avant.
// En attendant que la séparation soit prête, le titre joue normalement.

const sing = {
  on: false,
  level: Math.min(0.95, Math.max(0, +(store.get("sona.vocal") ?? 0) || 0)),
  track: null, gen: 0, status: "", quality: null,
  ctx: null, buffers: null, playing: null, dragging: false,
};

const singShownLevel = () => (sing.on ? sing.level : 1);
// Courbe au carré, comme l'app : 50 % ≈ voix 12 dB plus bas.
const vocalGainOf = (level) => level * level;

function setSing(on, render = true) {
  if (on === sing.on) return;
  sing.on = on;
  if (on) {
    // Créé pendant le clic : le navigateur n'autorise le son qu'après un geste.
    if (!sing.ctx) { try { sing.ctx = new (window.AudioContext || window.webkitAudioContext)(); } catch {} }
    sing.ctx?.resume?.();
    const t = state.queue[state.index];
    if (t) startSing(t);
  } else {
    stopSing();
  }
  if (render) renderSing();
}

/** Curseur « Voix ». `render: false` pendant le glissé (redessiner le
 * curseur sous le doigt casserait le geste). */
function setVocalLevel(value, render = true) {
  const v = Math.min(1, Math.max(0, value));
  if (v >= 0.99) { setSing(false, render); return; }
  sing.level = v;
  store.set("sona.vocal", String(v));
  if (!sing.on) setSing(true, render);
  if (sing.playing) sing.playing.vocals.gain.setTargetAtTime(vocalGainOf(v), sing.ctx.currentTime, 0.03);
  if (render) renderSing();
}

function singTrackChanged(t) {
  if (!sing.on) return;
  startSing(t);
}

function stopSing() {
  // Titres « à venir » demandés au serveur : plus utiles.
  if (sing.on === false && sing.track) api("/karaoke/prepare", { method: "POST", body: JSON.stringify({ tracks: [] }) }).catch(() => {});
  sing.gen++;
  stopStems();
  sing.buffers = null;
  sing.quality = null;
  sing.status = "";
  audio.muted = false;
}

function startSing(t) {
  stopSing();
  sing.track = t;
  const gen = sing.gen;
  followSeparation(t, gen);
  // Titres suivants : séparés d'avance par le serveur.
  const upcoming = state.queue.slice(state.index + 1, state.index + 4).map((x) => ({ source: x.source, source_id: x.source_id }));
  if (upcoming.length) api("/karaoke/prepare", { method: "POST", body: JSON.stringify({ tracks: upcoming }) }).catch(() => {});
}

const karaokePath = (t) => `/karaoke/${encodeURIComponent(t.source)}/${encodeURIComponent(t.source_id)}`;

/** Suit la séparation : pistes rapides dès qu'elles sont prêtes, puis les
 * fines quand la seconde passe est finie. */
async function followSeparation(t, gen) {
  let requested = false;
  let withoutRefine = 0;
  while (sing.gen === gen) {
    let st = null;
    try {
      st = requested ? await api(karaokePath(t)) : await api(karaokePath(t), { method: "POST" });
      requested = true;
    } catch {}
    if (sing.gen !== gen) return;
    if (st?.status === "ready") {
      const quality = st.quality || "hq";
      if (sing.quality === "hq") return;
      if (sing.quality === quality) {
        if (st.refining) {
          withoutRefine = 0;
          sing.status = st.refining.status === "running" ? `Affinage de la séparation… ${Math.round((st.refining.progress || 0) * 100)} %` : "";
        } else if (++withoutRefine >= 3) { sing.status = ""; renderSing(); return; }
      } else {
        if (!sing.quality) { sing.status = "Chargement des pistes…"; renderSing(); }
        const ok = await loadStems(t, quality, gen);
        if (sing.gen !== gen) return;
        if (!ok) { if (!sing.quality) sing.status = "Pistes séparées illisibles"; renderSing(); return; }
        sing.status = "";
        if (quality === "hq") { renderSing(); return; }
      }
    } else if (st?.status === "failed") {
      if (!sing.quality) sing.status = "Séparation impossible pour ce titre";
      renderSing();
      return;
    } else if (st?.status === "running") {
      sing.status = `Séparation en cours… ${Math.round((st.progress || 0) * 100)} %`;
    } else if (st?.status === "queued") {
      sing.status = st.ahead ? `Séparation en attente (${st.ahead} avant)` : "Séparation en cours…";
    } else if (st?.status === "absent") {
      requested = false;
    }
    renderSing();
    await new Promise((r) => setTimeout(r, sing.quality ? 8000 : 4000));
  }
}

async function loadStems(t, quality, gen) {
  if (!sing.ctx) { try { sing.ctx = new (window.AudioContext || window.webkitAudioContext)(); } catch { return false; } }
  try {
    const [vocals, instrumental] = await Promise.all(["vocals", "instrumental"].map(async (stem) => {
      const res = await fetch(`${BASE}/stream/${encodeURIComponent(t.source)}/${encodeURIComponent(t.source_id)}/karaoke/${stem}?quality=${quality}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return sing.ctx.decodeAudioData(await res.arrayBuffer());
    }));
    if (sing.gen !== gen || !sameTrack(t, state.queue[state.index])) return false;
    sing.buffers = { vocals, instrumental };
    sing.quality = quality;
    audio.muted = true;
    startStems(0.08);
    return true;
  } catch {
    return false;
  }
}

/** (Re)lance les deux pistes calées sur la position de la balise <audio>.
 * `fade` : montée du son (s), pour une bascule sans clic. */
function startStems(fade = 0.02) {
  const previous = sing.playing;
  sing.playing = null;
  if (!sing.buffers || !sing.ctx || audio.paused) { stopNodes(previous); return; }
  const ctx = sing.ctx;
  ctx.resume?.();
  const at = ctx.currentTime + 0.05;
  const offset = audio.currentTime + 0.05;
  if (offset >= sing.buffers.instrumental.duration) { stopNodes(previous); return; }
  const master = ctx.createGain();
  master.gain.setValueAtTime(0, at);
  master.gain.linearRampToValueAtTime(audio.volume, at + fade);
  master.connect(ctx.destination);
  const vocalsGain = ctx.createGain();
  vocalsGain.gain.value = vocalGainOf(sing.level);
  vocalsGain.connect(master);
  const sources = ["instrumental", "vocals"].map((stem) => {
    const src = ctx.createBufferSource();
    src.buffer = sing.buffers[stem];
    src.connect(stem === "vocals" ? vocalsGain : master);
    src.start(at, offset);
    return src;
  });
  // L'ancienne lecture s'efface pendant que la nouvelle monte.
  if (previous) {
    previous.master.gain.setValueAtTime(previous.master.gain.value, at);
    previous.master.gain.linearRampToValueAtTime(0, at + fade);
    previous.sources.forEach((src) => { try { src.stop(at + fade + 0.02); } catch {} });
  }
  sing.playing = { sources, master, vocals: vocalsGain, at, offset };
}

function stopNodes(playing) {
  if (!playing) return;
  playing.sources.forEach((src) => { try { src.stop(); } catch {} });
  try { playing.master.disconnect(); } catch {}
}

function stopStems() {
  stopNodes(sing.playing);
  sing.playing = null;
}

/** Les pistes dérivent-elles de la balise <audio> (horloges différentes) ? */
function checkStemsDrift() {
  const p = sing.playing;
  if (!p || audio.paused) return;
  const now = sing.ctx.currentTime;
  if (now < p.at) return;
  const expected = p.offset + (now - p.at);
  if (Math.abs(expected - audio.currentTime) > 0.08) startStems();
}

function renderSing() {
  const box = $("#np-sing");
  if (!box) return;
  if (sing.dragging && $("#np-voice", box)) {
    // Glissé en cours : seulement l'état, pas le curseur.
    const status = $(".np-sing-status", box);
    if (status) status.textContent = sing.status;
    return;
  }
  const level = singShownLevel();
  const pct = Math.round(level * 100);
  const hint = sing.on && !sing.quality && !sing.status ? "Voix normale en attendant la séparation" : "";
  box.innerHTML = `
    <button class="tbtn ${sing.on ? "on" : ""}" data-sing="toggle" title="Chante : voix séparée par IA">${icons.mic}</button>
    <div class="np-sing-body">
      <div class="np-sing-head"><span>Voix</span><span>${pct} %</span></div>
      <input type="range" class="slider" id="np-voice" min="0" max="100" value="${pct}" style="--p:${pct}%" aria-label="Volume de la voix">
      <div class="np-sing-presets">
        ${[["Instru", 0], ["En fond", 0.35], ["Normal", 1]].map(([label, v]) =>
          `<button class="${Math.abs(level - v) < 0.03 ? "on" : ""}" data-preset="${v}">${label}</button>`).join("")}
        ${sing.on ? `<button class="clear" data-sing="clear" title="Vider la file d'attente de séparation du serveur">Vider la file</button>` : ""}
      </div>
      <div class="np-sing-status">${esc(sing.status || hint)}</div>
    </div>`;
  $$("[data-preset]", box).forEach((b) => (b.onclick = () => setVocalLevel(+b.dataset.preset)));
  const clear = $("[data-sing=clear]", box);
  if (clear) clear.onclick = async () => {
    try {
      const res = await api("/karaoke/queue", { method: "DELETE" });
      toast(res.removed ? `File de séparation vidée (${res.removed})` : "La file de séparation était déjà vide");
    } catch (e) { toast(e.message); }
  };
  $("[data-sing=toggle]", box).onclick = () => setSing(!sing.on);
  const slider = $("#np-voice", box);
  slider.oninput = () => {
    slider.style.setProperty("--p", `${slider.value}%`);
    $(".np-sing-head span:last-child", box).textContent = `${slider.value} %`;
    setVocalLevel(+slider.value / 100, false);
    $("[data-sing=toggle]", box).classList.toggle("on", sing.on);
  };
  slider.onpointerdown = () => { sing.dragging = true; };
  slider.onchange = () => { sing.dragging = false; renderSing(); };
}

audio.addEventListener("play", () => { if (sing.buffers) startStems(0.05); });
audio.addEventListener("pause", stopStems);
audio.addEventListener("seeked", () => { if (sing.buffers) startStems(0.03); });
audio.addEventListener("timeupdate", checkStemsDrift);
audio.addEventListener("volumechange", () => {
  if (sing.playing) sing.playing.master.gain.setTargetAtTime(audio.volume, sing.ctx.currentTime, 0.02);
});

// ── Son : égaliseur, volume égalisé, fondu, reprise ─────────────────────
// Sur ordinateur (site, Sona pour Windows). Pas sur iPhone : le traitement
// audio du navigateur y coupe le son écran verrouillé — l'app iPhone a
// tout cela, en natif.

const EQ_BANDS = [60, 250, 1000, 4000, 12000];
const EQ_LABELS = ["60", "250", "1k", "4k", "12k"];
const EQ_PRESETS = [
  ["Normal", [0, 0, 0, 0, 0]], ["Basses", [6, 3, 0, 0, 1]], ["Grosses basses", [9, 5, -1, 0, 2]], ["Voix", [-2, -1, 3, 4, 1]],
  ["Soirée", [5, 2, -1, 2, 4]], ["Voiture", [4, 1, 0, 2, 3]], ["Casque", [3, 1, 0, 1, 2]], ["Aigus", [0, 0, 0, 3, 6]], ["Doux", [2, 1, 0, -2, -3]],
];
const TARGET_LOUDNESS = -10; // LUFS, comme l'app iPhone

const sound = {
  eq: (() => { try { const v = JSON.parse(store.get("sona.eq")); return Array.isArray(v) && v.length === 5 ? v.map(Number) : [0, 0, 0, 0, 0]; } catch { return [0, 0, 0, 0, 0]; } })(),
  normalize: store.get("sona.normalize") === "1",
  fade: Number(store.get("sona.fade")) || 0,
  visual: false, // visualiseur ouvert (il lit le son analysé)
  ctx: null, filters: [], level: null, fader: null, analyser: null,
  loudness: new Map(), fadingOut: false, trackKey: "",
};
const soundAvailable = !isIOS;

function soundWanted() {
  return soundAvailable && (sound.eq.some((g) => Math.abs(g) > 0.05) || sound.normalize || sound.fade > 0 || sound.visual);
}

/** Branche le lecteur sur l'égaliseur (une fois, à la première option activée). */
function ensureSound() {
  if (sound.ctx || !soundWanted()) return sound.ctx;
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    // Le flux doit être lu « en CORS » pour passer par l'égaliseur : le
    // titre en cours est rechargé à la même seconde.
    if (audio.crossOrigin !== "anonymous") {
      audio.crossOrigin = "anonymous";
      if (audio.src && !isSilence()) {
        const position = audio.currentTime, playing = !audio.paused, src = audio.src;
        audio.src = src;
        audio.addEventListener("loadedmetadata", () => { audio.currentTime = position; if (playing) audio.play().catch(() => {}); }, { once: true });
      }
    }
    const input = ctx.createMediaElementSource(audio);
    sound.filters = EQ_BANDS.map((freq, i) => {
      const f = ctx.createBiquadFilter();
      f.type = i === 0 ? "lowshelf" : i === EQ_BANDS.length - 1 ? "highshelf" : "peaking";
      f.frequency.value = freq;
      f.Q.value = 1;
      f.gain.value = sound.eq[i];
      return f;
    });
    sound.level = ctx.createGain();
    sound.fader = ctx.createGain();
    sound.analyser = ctx.createAnalyser();
    sound.analyser.fftSize = 512;
    sound.analyser.smoothingTimeConstant = 0.78;
    [input, ...sound.filters, sound.level, sound.fader, sound.analyser, ctx.destination].reduce((a, b) => (a.connect(b), b));
    sound.ctx = ctx;
    audio.addEventListener("play", () => { if (ctx.state === "suspended") ctx.resume(); });
    if (!audio.paused) ctx.resume();
    soundTrackChanged();
  } catch (e) { console.warn("Égaliseur indisponible", e); }
  return sound.ctx;
}

function setEq(gains) {
  sound.eq = gains.map((g) => Math.max(-12, Math.min(12, Number(g) || 0)));
  store.set("sona.eq", JSON.stringify(sound.eq));
  ensureSound();
  sound.filters.forEach((f, i) => f.gain.setTargetAtTime(sound.eq[i], sound.ctx.currentTime, 0.05));
}

function setNormalize(on) {
  sound.normalize = !!on;
  store.set("sona.normalize", on ? "1" : null);
  ensureSound();
  soundTrackChanged();
}

function setFade(seconds) {
  sound.fade = Math.max(0, Math.min(12, Number(seconds) || 0));
  store.set("sona.fade", sound.fade ? String(sound.fade) : null);
  ensureSound();
}

/** Nouveau titre : sonie (volume égalisé) et fondu d'entrée. */
async function soundTrackChanged() {
  const t = state.queue[state.index];
  if (!sound.ctx || !t || isSilence()) return;
  const key = trackKey(t);
  const now = sound.ctx.currentTime;
  if (key !== sound.trackKey) {
    sound.trackKey = key;
    sound.fadingOut = false;
    sound.fader.gain.cancelScheduledValues(now);
    if (sound.fade > 0 && audio.currentTime < 1) {
      sound.fader.gain.setValueAtTime(0, now);
      sound.fader.gain.linearRampToValueAtTime(1, now + Math.min(sound.fade, 6));
    } else sound.fader.gain.setValueAtTime(1, now);
  }
  let gain = 1;
  if (sound.normalize) {
    if (!sound.loudness.has(key)) {
      sound.loudness.set(key, null);
      const found = await api(`/analysis/${encodeURIComponent(t.source)}/${encodeURIComponent(t.source_id)}`).catch(() => null);
      if (found?.loudness != null) sound.loudness.set(key, found.loudness);
      else sound.loudness.delete(key); // pas encore analysé : on redemandera
    }
    const loudness = sound.loudness.get(key);
    if (loudness != null) gain = Math.min(1, Math.pow(10, (TARGET_LOUDNESS - loudness) / 20));
  }
  if (sound.trackKey === key) sound.level.gain.setTargetAtTime(gain, sound.ctx.currentTime, 0.3);
}

/** Fondu de sortie : les dernières secondes du titre. */
function soundTick() {
  if (!sound.ctx || !(sound.fade > 0) || isSilence()) return;
  const dur = audio.duration && isFinite(audio.duration) ? audio.duration : 0;
  if (!dur) return;
  const remaining = dur - audio.currentTime;
  const now = sound.ctx.currentTime;
  if (!sound.fadingOut && remaining > 0.2 && remaining <= sound.fade && !state.repeat) {
    sound.fadingOut = true;
    sound.fader.gain.cancelScheduledValues(now);
    sound.fader.gain.setValueAtTime(sound.fader.gain.value, now);
    sound.fader.gain.linearRampToValueAtTime(0.0001, now + remaining);
  } else if (sound.fadingOut && remaining > sound.fade + 0.5) {
    // Retour en arrière : le son revient.
    sound.fadingOut = false;
    sound.fader.gain.cancelScheduledValues(now);
    sound.fader.gain.setTargetAtTime(1, now, 0.1);
  }
}

audio.addEventListener("loadedmetadata", () => soundTrackChanged());
audio.addEventListener("timeupdate", soundTick);
// Options activées à une visite précédente : le lecteur passe par
// l'égaliseur dès le premier titre (lecture « en CORS » d'emblée).
if (soundWanted()) audio.crossOrigin = "anonymous";
document.addEventListener("pointerdown", () => ensureSound(), { once: true });

/** Feuille « Son » : égaliseur, volume égalisé, fondu. */
function soundSheet() {
  if (!soundAvailable) return toast("Sur iPhone, ces réglages sont dans l'app Sona");
  const wrap = openSheet(`<h2 class="sheet-title">Son</h2>
    <div class="eq-presets">${EQ_PRESETS.map(([name, gains]) => `<button class="chip" data-eq-preset="${esc(name)}">${esc(name)}</button>`).join("")}</div>
    <div class="eq-bands">${EQ_BANDS.map((_, i) => `<label class="eq-band"><span class="eq-val" id="eq-val-${i}"></span>
      <input type="range" min="-12" max="12" step="1" value="${sound.eq[i]}" data-eq="${i}" aria-label="${EQ_LABELS[i]} Hz"><b>${EQ_LABELS[i]}</b></label>`).join("")}</div>
    <div class="set-group">
      ${toggleRow("snd-normalize", "Volume égalisé", "Tous les titres au même niveau sonore.", sound.normalize)}
      <label class="set-row"><span class="set-text"><b>Fondu entre les titres</b><small>Le titre s'efface en douceur, le suivant arrive en fondu.</small></span>
        <select class="field small" data-fade>${[0, 2, 4, 6, 8, 10, 12].map((v) => `<option value="${v}" ${sound.fade === v ? "selected" : ""}>${v ? `${v} s` : "Aucun"}</option>`).join("")}</select></label>
    </div>`, { cls: "sound-sheet" });
  const paint = () => {
    $$("[data-eq]", wrap).forEach((input) => {
      const i = Number(input.dataset.eq);
      input.value = sound.eq[i];
      $(`#eq-val-${i}`, wrap).textContent = `${sound.eq[i] > 0 ? "+" : ""}${sound.eq[i]}`;
    });
    $$("[data-eq-preset]", wrap).forEach((b) => b.classList.toggle("on", JSON.stringify(EQ_PRESETS.find(([n]) => n === b.dataset.eqPreset)[1]) === JSON.stringify(sound.eq)));
  };
  wrap.addEventListener("input", (e) => {
    if (!e.target.matches("[data-eq]")) return;
    const gains = [...sound.eq];
    gains[Number(e.target.dataset.eq)] = Number(e.target.value);
    setEq(gains);
    paint();
  });
  $$("[data-eq-preset]", wrap).forEach((b) => (b.onclick = () => { setEq(EQ_PRESETS.find(([n]) => n === b.dataset.eqPreset)[1]); paint(); }));
  $('[data-setting="snd-normalize"]', wrap).onchange = (e) => setNormalize(e.target.checked);
  $("[data-fade]", wrap).onchange = (e) => setFade(e.target.value);
  paint();
}

// Reprise : la file, le titre et la seconde, d'une visite à l'autre.
let resumeSavedAt = 0;
function saveResume(force = false) {
  if (!state.queue.length || state.index < 0 || isSilence() || partyGuest()) return;
  if (!force && Date.now() - resumeSavedAt < 5000) return;
  resumeSavedAt = Date.now();
  const start = Math.max(0, state.index - 20);
  store.set("sona.resume", JSON.stringify({
    queue: state.queue.slice(start, start + 150).map(cleanTrack), index: state.index - start,
    position: Math.floor(audio.currentTime || 0), name: state.name || "", at: Date.now(),
  }));
}
audio.addEventListener("timeupdate", () => saveResume());
audio.addEventListener("pause", () => saveResume(true));
window.addEventListener("pagehide", () => saveResume(true));

/** Au démarrage : le dernier titre, en pause, prêt à repartir où on l'avait laissé. */
function restoreResume() {
  if (state.queue.length) return;
  let saved = null;
  try { saved = JSON.parse(store.get("sona.resume")); } catch {}
  if (!saved?.queue?.length || Date.now() - (saved.at || 0) > 14 * 86400e3) return;
  const t = saved.queue[saved.index];
  if (!t) return;
  state.queue = saved.queue;
  state.index = saved.index;
  state.name = saved.name || "";
  audio.preload = "metadata";
  audio.src = `${BASE}/stream/${encodeURIComponent(t.source)}/${encodeURIComponent(t.source_id)}?token=${encodeURIComponent(token)}`;
  if (saved.position > 1) audio.addEventListener("loadedmetadata", () => { audio.currentTime = saved.position; }, { once: true });
  if ("mediaSession" in navigator) {
    navigator.mediaSession.metadata = new MediaMetadata({ title: t.title, artist: t.artist, album: t.album || "",
      artwork: t.cover_url ? [{ src: big(t.cover_url, 512), sizes: "512x512", type: "image/jpeg" }] : [] });
  }
  renderTopbar();
  loadLyrics(t);
}

// ── Casque débranché : pause (Sona pour Windows) ─────────────────────────

/** Une sortie audio disparaît pendant la lecture (casque, enceinte) : pause. */
function watchHeadphones() {
  if (!navigator.mediaDevices?.enumerateDevices) return;
  const outputs = async () => (await navigator.mediaDevices.enumerateDevices())
    .filter((d) => d.kind === "audiooutput" && d.deviceId !== "default" && d.deviceId !== "communications").length;
  let count = null;
  outputs().then((n) => { count = n; }).catch(() => {});
  navigator.mediaDevices.addEventListener("devicechange", async () => {
    const n = await outputs().catch(() => count);
    const lost = count != null && n < count;
    count = n;
    if (!lost || audio.paused || isSilence()) return;
    const s = await desktop.settings().catch(() => null);
    if (s && s.pauseOnHeadphones === false) return;
    audio.pause();
    toast("Sortie audio débranchée : pause");
  });
}

// ── Visualiseur plein écran (ordinateur) ──────────────────────────────────

const viz = { el: null, raf: 0 };

function openVisualizer() {
  if (!soundAvailable) return toast("Le visualiseur est sur ordinateur (et dans le lecteur de l'app iPhone)");
  if (!state.queue[state.index]) return toast("Lance un titre d'abord");
  sound.visual = true;
  if (!ensureSound()) { sound.visual = false; return toast("Visualiseur indisponible sur ce navigateur"); }
  closeVisualizer();
  sound.visual = true;
  const el = document.createElement("div");
  el.className = "viz";
  el.innerHTML = `<div class="viz-bg"><img alt=""></div><canvas></canvas>
    <div class="viz-meta"><img class="viz-art" alt=""><div><b></b><span></span></div></div>
    <div class="viz-tools"><button data-viz="full" title="Plein écran (F)">⛶</button><button data-viz="close" title="Fermer (Échap)">${icons.close}</button></div>`;
  document.body.append(el);
  viz.el = el;
  const canvas = $("canvas", el);
  const g = canvas.getContext("2d");
  const data = new Uint8Array(sound.analyser.frequencyBinCount);
  let shownKey = "";
  const toggleFull = () => (document.fullscreenElement ? document.exitFullscreen() : el.requestFullscreen()).catch(() => {});
  const onKey = (e) => {
    if (e.key === "Escape") closeVisualizer();
    if (e.key === "f" || e.key === "F") toggleFull();
  };
  document.addEventListener("keydown", onKey);
  el._cleanup = () => document.removeEventListener("keydown", onKey);
  el.onclick = (e) => {
    const act = e.target.closest("[data-viz]")?.dataset.viz;
    if (act === "close") closeVisualizer();
    if (act === "full") toggleFull();
  };
  renderTopbar();
  const draw = () => {
    viz.raf = requestAnimationFrame(draw);
    const cur = state.queue[state.index];
    const key = cur ? trackKey(cur) : "";
    if (cur && key !== shownKey) {
      shownKey = key;
      $(".viz-bg img", el).src = big(cur.cover_url, 600);
      $(".viz-art", el).src = big(cur.cover_url, 300);
      $(".viz-meta b", el).textContent = cur.title;
      $(".viz-meta span", el).textContent = cur.artist;
    }
    const w = (canvas.width = el.clientWidth * devicePixelRatio);
    const h = (canvas.height = el.clientHeight * devicePixelRatio);
    sound.analyser.getByteFrequencyData(data);
    g.clearRect(0, 0, w, h);
    // Barres en miroir depuis le centre : les basses au milieu, les aigus aux bords.
    const bars = 64;
    const step = w / (bars * 2);
    const bw = step * 0.62;
    const grad = g.createLinearGradient(0, h * 0.78, 0, h * 0.2);
    grad.addColorStop(0, "rgba(250,45,108,.95)");
    grad.addColorStop(1, "rgba(139,92,246,.85)");
    g.fillStyle = grad;
    for (let i = 0; i < bars; i++) {
      const bin = Math.min(data.length - 1, Math.floor(Math.pow(i / bars, 1.8) * data.length * 0.7));
      const v = data[bin] / 255;
      const bh = Math.max(4 * devicePixelRatio, Math.pow(v, 1.4) * h * 0.55);
      for (const side of [-1, 1]) {
        const x = w / 2 + side * (i * step + step / 2) - bw / 2;
        g.beginPath();
        g.roundRect(x, h * 0.78 - bh, bw, bh, bw / 2);
        g.fill();
      }
    }
  };
  draw();
}

function closeVisualizer() {
  if (!viz.el) return;
  cancelAnimationFrame(viz.raf);
  viz.el._cleanup?.();
  viz.el.remove();
  viz.el = null;
  sound.visual = false;
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  renderTopbar();
}

// ── Sona Connect ─────────────────────────────────────────────────────────
// Un seul lecteur pour tous tes appareils : reprendre ici ce qui jouait sur
// l'iPhone, piloter l'iPhone depuis le PC, envoyer la musique de l'un à
// l'autre (voir app/services/connect.py côté serveur).

const deviceId = store.get("sona.device") || (() => {
  const id = `web-${Math.random().toString(36).slice(2, 12)}`;
  store.set("sona.device", id);
  return id;
})();

function deviceName() {
  if (desktop) return desk.name || desktop.deviceName;
  const ua = navigator.userAgent;
  const browser = /Edg\//.test(ua) ? "Edge" : /OPR\//.test(ua) ? "Opera" : /Firefox\//.test(ua) ? "Firefox" : /Chrome\//.test(ua) ? "Chrome" : /Safari\//.test(ua) ? "Safari" : "Navigateur";
  const os = /Mac OS X/.test(ua) && !/iPhone|iPad/.test(ua) ? "Mac" : /Windows/.test(ua) ? "PC" : /Android/.test(ua) ? "Android" : /iPhone|iPad/.test(ua) ? "iPhone" : /Linux/.test(ua) ? "Linux" : "";
  return os ? `${browser} · ${os}` : browser;
}

const otherDevices = () => state.connect.devices.filter((d) => !d.is_me);

/** L'appareil choisi dans « Appareils » s'il est allumé (pas celui-ci). */
function chosenDevice() {
  const id = state.connect.control;
  return (id && state.connect.devices.find((d) => d.id === id && !d.is_me)) || null;
}

/** L'appareil piloté par le lecteur quand rien ne joue ici : celui choisi
    dans « Appareils », sinon celui de la dernière lecture du compte — qu'il
    joue ou soit en pause : lecture, suivant… le pilotent à distance. */
function remoteDevice() {
  if (audio.src && !audio.paused) return null;
  const chosen = chosenDevice();
  if (chosen) return chosen;
  const { session, devices } = state.connect;
  if (!session || session.device_id === deviceId) return null;
  return devices.find((d) => d.id === session.device_id && !d.is_me) || null;
}

function remotePosition() {
  const session = state.connect.session;
  if (!session) return 0;
  const drift = session.paused ? 0 : (Date.now() - state.connect.receivedAt) / 1000;
  return session.position + drift;
}

/** Ce que joue un autre appareil : titre, pause, position (qui avance). */
function deviceNow(d) {
  if (!d) return { track: null, paused: true, position: 0 };
  const session = state.connect.session;
  if (session && session.device_id === d.id) return { track: session.track, paused: !!session.paused, position: remotePosition() };
  const drift = d.playing ? (Date.now() - state.connect.receivedAt) / 1000 : 0;
  const dur = d.track?.duration_seconds || 0;
  const position = (d.position || 0) + drift;
  return { track: d.track || null, paused: !d.playing, position: dur ? Math.min(position, dur) : position };
}

/** Choisit l'appareil à piloter (null : plus aucun). Gardé d'une visite à l'autre. */
function setControl(id) {
  state.connect.control = id || null;
  store.set("sona.control", id || null);
  renderTopbar();
}

function localState() {
  if (!state.queue.length || state.index < 0) return null;
  const start = Math.max(0, state.index - 20);
  // Début de la fenêtre envoyée : « play_index » s'y rapporte.
  state.connect.windowStart = start;
  const queue = state.queue.slice(start, start + 150).map((t) => ({
    source: t.source, source_id: t.source_id, title: t.title, artist: t.artist, album: t.album || null,
    duration_seconds: t.duration_seconds || null, cover_url: t.cover_url || null,
    artist_source_id: t.artist_source_id || null, album_source_id: t.album_source_id || null,
  }));
  const t = state.queue[state.index];
  return {
    queue, index: state.index - start, position: audio.currentTime || 0, paused: audio.paused, volume: audio.volume, name: state.name || null,
    shuffle: state.shuffle, repeat: state.repeat ? "one" : "off", liked: t ? state.liked.has(trackKey(t)) : null,
  };
}

async function connectSync(wait = 0) {
  const claim = state.connect.claim && !audio.paused;
  if (claim) state.connect.claim = false;
  let data;
  try {
    data = await api("/connect/sync", {
      method: "POST",
      body: JSON.stringify({ device_id: deviceId, name: deviceName(), kind: desktop ? "desktop" : "web", state: localState(), claim, wait }),
    });
  } catch (e) {
    // Pour la page « État ».
    Object.assign(state.connect, { lastError: e.message || "Serveur injoignable", lastErrorAt: Date.now() });
    return false;
  }
  state.connect.lastOk = Date.now();
  const wasRemote = remoteDevice()?.id;
  // Lecture/pause demandée à l'instant : on garde l'état voulu le temps que
  // l'autre appareil le confirme (une réponse partie avant ne l'annule pas).
  const expected = state.connect.expected;
  if (expected) {
    const dev = data.devices.find((d) => d.id === expected.target);
    const confirmed = dev ? dev.playing === !expected.paused : data.session?.paused === expected.paused;
    if (Date.now() > expected.until || confirmed) state.connect.expected = null;
    else {
      if (data.session?.device_id === expected.target) data.session.paused = expected.paused;
      if (dev) dev.playing = !expected.paused;
    }
  }
  Object.assign(state.connect, { devices: data.devices, session: data.session, active: data.active_device_id, receivedAt: Date.now() });
  for (const command of data.commands || []) runCommand(command);
  // Pas de rafraîchissement pendant qu'on fait glisser un curseur de volume.
  const dragging = document.activeElement?.matches?.('#vol, input[data-dc="volume"], input[data-dev-vol]') && state.connect.pointerDown;
  if (!dragging && (wasRemote !== remoteDevice()?.id || remoteDevice())) renderTopbar();
  const resume = $("#resume");
  if (resume) {
    const html = resumeCard();
    if (resume.innerHTML !== html) resume.innerHTML = html;
  }
  if (state.connect.open && !dragging) renderDevices();
  if (!dragging) renderDevicesPage();
  return true;
}

function startConnect() {
  document.addEventListener("pointerdown", () => { state.connect.pointerDown = true; });
  document.addEventListener("pointerup", () => { state.connect.pointerDown = false; });
  // Connexion qui attend les nouvelles : le serveur répond dès qu'une
  // commande arrive ou que la lecture change sur un autre appareil.
  (async function listen() {
    // Même onglet en arrière-plan : une commande de l'iPhone doit arriver
    // tout de suite (une seule requête ouverte, rien de coûteux).
    for (;;) {
      const ok = await connectSync(25);
      if (ok === false) await new Promise((r) => setTimeout(r, 3000));
    }
  })();
  // Changement ici : prévenir tout de suite les autres appareils.
  let pending;
  const report = () => { clearTimeout(pending); pending = setTimeout(() => connectSync(0), 150); };
  document.addEventListener("visibilitychange", () => !document.hidden && report());
  audio.addEventListener("play", report);
  // Lecture lancée ici : on ne pilote plus un autre appareil.
  audio.addEventListener("play", () => { if (state.connect.control) setControl(null); });
  audio.addEventListener("pause", report);
  audio.addEventListener("seeked", report);
  startConnect.now = report;
  setInterval(() => remoteDevice() && updateProgress(), 500);
}

/** Lecture demandée à distance : le navigateur peut la bloquer tant que la
    page n'a pas été touchée — un clic n'importe où la lance alors. */
function remotePlay() {
  audio.play().catch(() => {
    toast(isMobile() ? "Touche l'écran pour lancer la lecture" : "Clique sur la page Sona pour autoriser la lecture à distance");
    document.addEventListener("click", () => audio.play().catch(() => {}), { once: true });
  });
}

function runCommand(c) {
  switch (c.action) {
    case "play": if (audio.src) remotePlay(); break;
    case "pause": if (!audio.paused) { audio.pause(); if (c.from) toast(`Lecture passée sur ${c.from}`); } break;
    case "toggle": if (audio.src) (audio.paused ? remotePlay() : audio.pause()); break;
    case "next": next(); break;
    case "previous": prev(); break;
    case "seek": if (c.position != null) audio.currentTime = c.position; break;
    case "volume": if (c.volume != null) { audio.volume = c.volume; renderTopbar(); } break;
    case "transfer": playFrom(c.queue, c.index, c.position, c.name); if (c.from) toast(`Musique reprise ici depuis ${c.from}`); break;
    // Télécommande complète (« Appareils » sur le téléphone).
    case "shuffle": state.shuffle = !state.shuffle; renderTopbar(); startConnect.now?.(); break;
    case "repeat": state.repeat = !state.repeat; renderTopbar(); startConnect.now?.(); break;
    case "like": if (state.queue[state.index]) toggleLike(state.queue[state.index]).then(() => startConnect.now?.()); break;
    case "play_tracks":
      if (c.queue?.length) { playList(c.queue, c.index || 0, c.name || ""); if (c.from) toast(`Lancé depuis ${c.from}`); }
      break;
    case "play_index": {
      const i = (state.connect.windowStart || 0) + (c.index ?? -1);
      if (c.index != null && state.queue[i]) playAt(i);
      break;
    }
  }
}

/** Reprend une file à une position donnée (transfert, reprise). */
function playFrom(queue, index, position, name) {
  if (!queue?.length) return;
  state.queue = queue;
  state.name = name || "";
  playAt(Math.min(index || 0, queue.length - 1));
  if (position > 1) {
    const seek = () => { audio.currentTime = position; audio.removeEventListener("loadedmetadata", seek); };
    audio.addEventListener("loadedmetadata", seek);
  }
}

function resumeHere() {
  const session = state.connect.session;
  if (!session) return;
  playFrom(session.queue, session.index, remotePosition(), session.name);
}

async function sendCommand(target, action, extra = {}) {
  // Réponse immédiate à l'écran, confirmée par le serveur juste après.
  const session = state.connect.session;
  const dev = state.connect.devices.find((d) => d.id === target);
  if ((action === "toggle" || action === "play" || action === "pause") && (dev || session?.device_id === target)) {
    const now = deviceNow(dev || { id: target });
    const paused = action === "toggle" ? !now.paused : action === "pause";
    if (session?.device_id === target) { session.position = remotePosition(); session.paused = paused; }
    if (dev) { dev.position = now.position; dev.playing = !paused; }
    state.connect.receivedAt = Date.now();
    state.connect.expected = { target, paused, until: Date.now() + 4000 };
    renderTopbar();
    if (state.connect.open) renderDevices();
    renderDevicesPage();
  }
  try {
    await api("/connect/command", { method: "POST", body: JSON.stringify({ device_id: deviceId, target, action, ...extra }) });
    setTimeout(() => startConnect.now?.(), 700);
  } catch (e) { toast(e.message); }
}

/** « Écouter sur… » : la musique part sur cet appareil, à la même seconde. */
async function listenOn(device) {
  if (device.is_me) {
    if (remoteDevice() || (state.connect.session && !audio.src)) resumeHere();
    closeDevices();
    return;
  }
  await connectSync(); // position à jour avant l'envoi
  await sendCommand(device.id, "transfer");
  audio.pause();
  toast(`Musique envoyée sur ${device.name}`);
  closeDevices();
}

function resumeCard() {
  const session = state.connect.session;
  if (!session || session.device_id === deviceId || (audio.src && !audio.paused) || session.age_seconds > 6 * 3600) return "";
  const t = session.track;
  const playing = !session.paused;
  return `<button class="resume" onclick="resumeHere()">
    <img src="${esc(big(t.cover_url, 200))}" alt="">
    <span class="resume-text"><span class="eyebrow">${playing ? `En lecture sur ${esc(session.device_name)}` : `Reprendre depuis ${esc(session.device_name)}`}</span>
      <span class="t">${esc(t.title)}</span><span class="s">${esc(t.artist)} · ${fmt(remotePosition())}</span></span>
    <span class="resume-cta">${icons.play} Écouter ici</span></button>`;
}

function toggleDevices() {
  state.connect.open ? closeDevices() : openDevices();
}

function openDevices() {
  state.connect.open = true;
  renderDevices();
  startConnect.now?.();
  setTimeout(() => document.addEventListener("click", outsideDevices), 0);
}

function closeDevices() {
  state.connect.open = false;
  $(".devices-pop")?.remove();
  document.removeEventListener("click", outsideDevices);
}

function outsideDevices(e) {
  if (!e.target.closest(".devices-pop") && !e.target.closest('[data-act="devices"], [data-np="devices"], [data-mp]')) closeDevices();
}

function renderDevices() {
  let pop = $(".devices-pop");
  if (!pop) { pop = document.createElement("div"); pop.className = "devices-pop"; document.body.append(pop); }
  pop.classList.toggle("as-sheet", isMobile());
  const devices = state.connect.devices.length ? state.connect.devices : [{ id: deviceId, name: deviceName(), kind: desktop ? "desktop" : "web", is_me: true }];
  const remote = remoteDevice();
  const session = state.connect.session;
  const rnow = deviceNow(remote);
  pop.innerHTML = `<div class="dp-head">Sona Connect</div>
    ${remote && rnow.track ? `<div class="dp-remote">
      <img src="${esc(big(rnow.track.cover_url, 120))}" alt="">
      <div style="min-width:0"><div class="t">${esc(rnow.track.title)}</div><div class="s">${esc(rnow.track.artist)}</div></div>
      <div class="dp-ctl"><button data-dc="previous">${icons.prev}</button><button data-dc="toggle">${rnow.paused ? icons.play : icons.pause}</button><button data-dc="next">${icons.next}</button></div>
      <input type="range" class="slider" data-dc="volume" min="0" max="1" step="0.05" value="${remote.volume ?? 1}" style="--p:${(remote.volume ?? 1) * 100}%" aria-label="Volume à distance">
    </div>` : ""}
    ${devices.map((d) => `<button class="dp-device ${d.playing ? "playing" : ""}" data-device="${esc(d.id)}">
      <span class="dp-icon">${d.kind === "iphone" ? icons.phone : icons.laptop}</span>
      <span style="min-width:0"><span class="n">${d.is_me ? (isMobile() ? "Ce téléphone" : "Cet ordinateur") : esc(d.name)}</span>
        <span class="st">${d.playing ? `${bars()} ${esc(d.track?.title || "En lecture")}` : d.is_me ? esc(d.name) : "Connecté"}</span></span>
      <span class="go">${d.is_me ? (remote || (session && !audio.src) ? "Écouter ici" : "") : "Écouter dessus"}</span></button>`).join("")}
    ${devices.length < 2 ? `<p class="dp-hint">Ouvre Sona sur ton iPhone (ou un autre ordinateur) : il apparaîtra ici.</p>` : ""}
    <a class="dp-device" href="#/devices" data-dp-all><span class="dp-icon">${icons.devices}</span><span style="min-width:0"><span class="n">Mes appareils</span>
      <span class="st">Tes PC enregistrés, à piloter d'un appui</span></span><span class="go">${icons.right}</span></a>
    <button class="dp-device" data-cast><span class="dp-icon">${icons.tv}</span><span style="min-width:0"><span class="n">TV ou PS5</span>
      <span class="st">${cast.screen ? `Diffusion sur ${esc(cast.screen.name)}` : "Via l'appli YouTube de l'écran"}</span></span><span class="go">${cast.screen ? "Télécommande" : "Choisir"}</span></button>`;
  $("[data-cast]", pop).onclick = () => { closeDevices(); openCast(); };
  $("[data-dp-all]", pop).onclick = () => closeDevices();
  $$("[data-device]", pop).forEach((b) => (b.onclick = () => listenOn(devices.find((d) => d.id === b.dataset.device))));
  $$("button[data-dc]", pop).forEach((b) => (b.onclick = () => {
    if (!remote) return;
    const action = b.dataset.dc === "toggle" ? (deviceNow(remote).paused ? "play" : "pause") : b.dataset.dc;
    sendCommand(remote.id, action);
  }));
  const vol = $('input[data-dc="volume"]', pop);
  if (vol) vol.onchange = () => { vol.style.setProperty("--p", `${vol.value * 100}%`); sendCommand(remote.id, "volume", { volume: +vol.value }); };
  const anchor = $('.right-tools [data-act="devices"]')?.getBoundingClientRect();
  if (!isMobile() && anchor && anchor.width) { pop.style.top = `${anchor.bottom + 8}px`; pop.style.right = `${Math.max(12, innerWidth - anchor.right - 8)}px`; }
  else { pop.style.top = ""; pop.style.right = ""; }
}

// ── Appareils : tes PC enregistrés, pilotés d'un appui ───────────────────
// Enregistrés sur le compte (pas sur ce téléphone) : ils restent dans la
// liste même éteints ; allumés, un appui suffit pour les piloter, d'ici ou
// de n'importe où (via Sona Connect, sans QR code ni même Wi-Fi commun).

const devs = { saved: [], loaded: false, busy: false, queue: null };

async function viewDevices() {
  devs.saved = await api("/connect/saved").catch(() => devs.saved);
  devs.loaded = true;
  startConnect.now?.();
  setTimeout(() => bindDevicesPage());
  return page(`<h1 class="page-title">Appareils</h1>
    <p class="page-sub">Tes PC restent ici, même éteints. Touche-en un pour le piloter, d'où que tu sois.</p>
    <div id="devices-root">${devicesBody()}</div>`);
}

/** Les appareils enregistrés, avec ce qu'ils jouent s'ils sont allumés. */
function devicesList() {
  const live = state.connect.devices;
  const known = state.connect.receivedAt > 0;
  const saved = devs.saved.map((sv) => {
    const l = live.find((d) => d.id === sv.id && !d.is_me);
    // Le nom enregistré (éventuellement renommé) passe avant celui de l'appareil.
    return l ? { ...sv, ...l, name: sv.name, saved: true, online: true } : { ...sv, saved: true, online: known ? false : sv.online, playing: known ? false : sv.playing };
  });
  const ids = new Set(saved.map((d) => d.id));
  const others = live.filter((d) => !d.is_me && !ids.has(d.id)).map((d) => ({ ...d, online: true }));
  return { saved, others };
}

const deviceIcon = (d) => (d.kind === "iphone" ? icons.phone : icons.laptop);

function deviceStatus(d) {
  if (!d.online) {
    const seen = d.seen_seconds != null ? ` · vu ${since(new Date(Date.now() - d.seen_seconds * 1000).toISOString())}` : "";
    return `Éteint${seen}`;
  }
  const now = deviceNow(d);
  if (now.track && !now.paused) return `<span class="bars"><i></i><i></i><i></i></span> ${esc(now.track.title)}`;
  if (now.track) return `En pause · ${esc(now.track.title)}`;
  return "Allumé · rien en lecture";
}

function deviceRow(d) {
  const chosen = state.connect.control === d.id && d.online;
  return `<div class="dev-row ${d.online ? "" : "off"} ${chosen ? "chosen" : ""}" data-dev-pick="${esc(d.id)}" role="button" tabindex="0">
    <span class="dev-icon">${deviceIcon(d)}</span>
    <span class="dev-text"><b>${esc(d.name)}</b><small>${deviceStatus(d)}</small></span>
    ${d.saved
      ? `${chosen ? `<span class="dev-tag">${icons.check} Piloté</span>` : d.online ? `<span class="dev-go">Piloter</span>` : ""}
         <button class="dev-more" data-dev-menu="${esc(d.id)}" aria-label="Options de ${esc(d.name)}">${icons.more}</button>`
      : `<button class="btn small" data-dev-save="${esc(d.id)}">${icons.plus} Ajouter</button>`}
  </div>`;
}

/** Télécommande de l'appareil choisi : pochette, commandes, volume. */
function deviceRemote(d) {
  const now = deviceNow(d);
  const t = now.track;
  const session = state.connect.session;
  const sendable = session && session.device_id !== d.id && session.track;
  const volume = state.connect.pendingVolume ?? d.volume ?? 1;
  return `<div class="dev-remote">
    <div class="dev-remote-head"><span class="dev-badge">${deviceIcon(d)} ${esc(d.name)}</span>
      <button class="dev-stop" data-dev-stop>Ne plus piloter</button></div>
    ${t ? `<div class="dev-now"><img class="dev-art ${now.paused ? "paused" : ""}" src="${esc(big(t.cover_url, 600))}" alt="">
        <div class="dev-meta"><b>${esc(t.title)}</b><span>${esc(t.artist)}</span></div>
        <div class="dev-progress" data-dev-seek><div class="fill" id="dev-fill"></div></div>
        <div class="dev-times"><span id="dev-cur">${fmt(now.position)}</span><span id="dev-rem">-${fmt(Math.max(0, (t.duration_seconds || 0) - now.position))}</span></div></div>`
      : `<div class="dev-idle">${icons.note}<b>Rien en lecture sur ${esc(d.name)}</b><small>Envoie-lui ta musique, ou lance un titre sur le PC.</small></div>`}
    <div class="dev-ctl">
      <button data-dev-cmd="previous" aria-label="Précédent" ${t ? "" : "disabled"}>${icons.prev}</button>
      <button class="big" data-dev-cmd="toggle" aria-label="Lecture/Pause" ${t ? "" : "disabled"}>${now.paused ? icons.play : icons.pause}</button>
      <button data-dev-cmd="next" aria-label="Suivant" ${t ? "" : "disabled"}>${icons.next}</button>
    </div>
    ${t ? deviceOptions(d) : ""}
    <label class="dev-vol">${icons.speaker}<input type="range" class="slider" data-dev-vol min="0" max="1" step="0.02" value="${volume}" style="--p:${volume * 100}%" aria-label="Volume de ${esc(d.name)}"></label>
    <div class="pill-row center">
      ${t ? `<button class="btn ghost" data-dev-here>${isMobile() ? icons.phone : icons.laptop} Écouter ici</button>` : ""}
      ${sendable ? `<button class="btn" data-dev-send>Envoyer « ${esc(session.track.title)} » sur ${esc(d.name)}</button>` : ""}
    </div>
    ${t ? deviceUpNext(d) : ""}
  </div>`;
}

/** J'aime, aléatoire, répéter — tels que l'appareil les donne (absents s'il ne les donne pas). */
function deviceOptions(d) {
  const opts = [
    d.shuffle != null && `<button class="${d.shuffle ? "on" : ""}" data-dev-opt="shuffle" aria-label="Aléatoire">${icons.shuffle}</button>`,
    d.liked != null && `<button class="${d.liked ? "on" : ""}" data-dev-opt="like" aria-label="J'aime">${d.liked ? icons.heartFill : icons.heart}</button>`,
    d.repeat != null && `<button class="${d.repeat !== "off" ? "on" : ""}" data-dev-opt="repeat" aria-label="Répéter">${icons.repeat}</button>`,
  ].filter(Boolean);
  return opts.length ? `<div class="dev-opts">${opts.join("")}</div>` : "";
}

/** « À suivre » sur l'appareil : sa file, un appui lance le titre dessus. */
function deviceUpNext(d) {
  const q = devs.queue;
  const key = `${d.id}:${trackKey(deviceNow(d).track || {})}`;
  if (!q || q.key !== key) {
    if (!devs.queueLoading || devs.queueLoading !== key) {
      devs.queueLoading = key;
      api(`/connect/devices/${encodeURIComponent(d.id)}/queue`)
        .then((data) => { devs.queue = { key, data }; })
        .catch(() => { devs.queue = { key, data: null }; })
        .finally(() => { devs.queueLoading = null; renderDevicesPage(); });
    }
    return q?.data ? upNextHtml(d, q.data) : "";
  }
  return q.data ? upNextHtml(d, q.data) : "";
}

function upNextHtml(d, data) {
  const next = (data.queue || []).map((t, i) => ({ t, i })).slice(data.index + 1, data.index + 9);
  if (!next.length) return "";
  return `<div class="dev-next"><h4>À suivre sur ${esc(d.name)}${data.name ? ` · ${esc(data.name)}` : ""}</h4>
    ${next.map(({ t, i }) => `<button class="dev-next-row" data-dev-index="${i}">
      <img src="${esc(big(t.cover_url, 120))}" alt="" loading="lazy"><span><b>${esc(t.title)}</b><small>${esc(t.artist)}</small></span></button>`).join("")}</div>`;
}

/** Options d'un appareil enregistré : le renommer, l'oublier. */
function deviceMenu(id) {
  const d = devs.saved.find((x) => x.id === id);
  if (!d) return;
  const wrap = openSheet(`<h2 class="sheet-title">${esc(d.name)}</h2>
    <form class="ask" id="dev-rename">
      <input class="field" name="name" maxlength="40" value="${esc(d.renamed ? d.name : "")}" placeholder="${esc(d.name)}" aria-label="Nom de l'appareil">
      <p class="muted">Laisse vide pour reprendre le nom donné par l'appareil.</p>
      <div class="pill-row"><button type="button" class="btn ghost" data-cancel>Annuler</button><button class="btn" type="submit">Renommer</button></div>
    </form>
    <button class="btn ghost danger wide" data-forget>${icons.trash} Oublier cet appareil</button>`);
  const form = $("#dev-rename", wrap);
  $("[data-cancel]", wrap).onclick = () => wrap.close();
  form.onsubmit = async (e) => {
    e.preventDefault();
    try {
      const item = await api(`/connect/saved/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify({ name: form.name.value.trim() }) });
      devs.saved = devs.saved.map((x) => (x.id === id ? item : x));
      wrap.close();
      renderDevicesPage();
    } catch (err) { toast(err.message); }
  };
  $("[data-forget]", wrap).onclick = async () => {
    wrap.close();
    if (!(await confirmSheet(`Oublier ${d.name} ? Il ne reviendra pas tout seul : tu pourras l'ajouter de nouveau quand il sera allumé.`, "Oublier"))) return;
    await api(`/connect/saved/${encodeURIComponent(id)}`, { method: "DELETE" }).catch((err) => toast(err.message));
    devs.saved = devs.saved.filter((x) => x.id !== id);
    if (state.connect.control === id) setControl(null);
    renderDevicesPage();
  };
}

function devicesBody() {
  const { saved, others } = devicesList();
  const chosen = chosenDevice();
  const hint = `<p class="dev-hint">${icons.laptop}<span>Ouvre <b>Sona pour Windows</b> sur ton PC, connecté avec ce compte : il s'ajoute ici tout seul et y reste, même éteint. Les autres appareils (navigateur, iPhone) s'ajoutent avec <b>Ajouter</b>.</span></p>`;
  return `${chosen ? deviceRemote(chosen) : ""}
    <h3 class="set-head">Mes appareils</h3>
    ${saved.length ? `<div class="dev-list">${saved.map(deviceRow).join("")}</div>` : `<div class="dev-empty">Aucun appareil enregistré pour l'instant.</div>`}
    ${others.length ? `<h3 class="set-head">Allumés en ce moment</h3><div class="dev-list">${others.map(deviceRow).join("")}</div>` : ""}
    ${saved.length && !others.length ? "" : hint}`;
}

function renderDevicesPage() {
  const root = $("#devices-root");
  if (!root) return;
  if (document.activeElement?.matches?.("input[data-dev-vol]") && state.connect.pointerDown) return;
  const html = devicesBody();
  if (root._html === html) return;
  root._html = html;
  root.innerHTML = html;
  updateDevicesProgress();
}

function updateDevicesProgress() {
  const fill = $("#dev-fill");
  if (!fill) return;
  const now = deviceNow(chosenDevice());
  const dur = now.track?.duration_seconds || 0;
  fill.style.width = dur ? `${Math.min(100, (now.position / dur) * 100)}%` : "0%";
  const cur = $("#dev-cur"), rem = $("#dev-rem");
  if (cur) cur.textContent = fmt(now.position);
  if (rem) rem.textContent = `-${fmt(Math.max(0, dur - now.position))}`;
}

/** Choisit un appareil allumé : la télécommande s'affiche en haut. */
function pickDevice(id) {
  const { saved, others } = devicesList();
  const d = [...saved, ...others].find((x) => x.id === id);
  if (!d) return;
  if (!d.online) return toast(`${d.name} est éteint : ouvre Sona dessus pour le piloter.`);
  haptic();
  // Il joue déjà : un seul lecteur à la fois, la musique d'ici s'arrête.
  if (d.playing && audio.src && !audio.paused) audio.pause();
  setControl(d.id);
  renderDevicesPage();
  $("#content")?.scrollTo({ top: 0, behavior: "smooth" });
}

function bindDevicesPage() {
  const root = $("#devices-root");
  if (!root) return;
  updateDevicesProgress();
  const timer = setInterval(updateDevicesProgress, 500);
  onLeave(() => clearInterval(timer));
  root.onclick = async (e) => {
    const el = (sel) => e.target.closest(sel);
    if (el("[data-dev-save]")) {
      e.stopPropagation();
      const b = el("[data-dev-save]");
      b.disabled = true;
      try {
        const item = await api("/connect/saved", { method: "POST", body: JSON.stringify({ device_id: b.dataset.devSave }) });
        devs.saved = [...devs.saved.filter((x) => x.id !== item.id), item];
        toast(`${item.name} ajouté à tes appareils`);
      } catch (err) { toast(err.message); b.disabled = false; }
      return renderDevicesPage();
    }
    if (el("[data-dev-menu]")) {
      e.stopPropagation();
      return deviceMenu(el("[data-dev-menu]").dataset.devMenu);
    }
    if (el("[data-dev-stop]")) { setControl(null); return renderDevicesPage(); }
    const target = chosenDevice();
    if (el("[data-dev-cmd]") && target) {
      haptic();
      const cmd = el("[data-dev-cmd]").dataset.devCmd;
      return sendCommand(target.id, cmd === "toggle" ? (deviceNow(target).paused ? "play" : "pause") : cmd);
    }
    if (el("[data-dev-opt]") && target) {
      haptic();
      const opt = el("[data-dev-opt]").dataset.devOpt;
      // Réponse immédiate à l'écran ; l'appareil confirme à son prochain relevé.
      if (opt === "shuffle") { target.shuffle = !target.shuffle; devs.queue = null; }
      if (opt === "like") target.liked = !target.liked;
      if (opt === "repeat") target.repeat = target.repeat === "off" ? "one" : "off";
      renderDevicesPage();
      return sendCommand(target.id, opt);
    }
    if (el("[data-dev-index]") && target) {
      haptic();
      const index = Number(el("[data-dev-index]").dataset.devIndex);
      devs.queue = null;
      return sendCommand(target.id, "play_index", { index });
    }
    if (el("[data-dev-seek]") && target) {
      const dur = deviceNow(target).track?.duration_seconds;
      if (!dur) return;
      const rect = el("[data-dev-seek]").getBoundingClientRect();
      return sendCommand(target.id, "seek", { position: ((e.clientX - rect.left) / rect.width) * dur });
    }
    if (el("[data-dev-here]") && target) {
      const now = deviceNow(target);
      setControl(null);
      if (state.connect.session?.device_id === target.id) resumeHere();
      else if (now.track) { playFrom([now.track], 0, now.position, ""); sendCommand(target.id, "pause"); }
      return toast(`Musique reprise ici depuis ${target.name}`);
    }
    if (el("[data-dev-send]") && target) {
      await connectSync();
      await sendCommand(target.id, "transfer");
      audio.pause();
      return toast(`Musique envoyée sur ${target.name}`);
    }
    const row = el("[data-dev-pick]");
    if (row) pickDevice(row.dataset.devPick);
  };
  root.onkeydown = (e) => {
    const row = e.target.closest("[data-dev-pick]");
    if (row && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); pickDevice(row.dataset.devPick); }
  };
  root.oninput = (e) => {
    if (!e.target.matches("[data-dev-vol]")) return;
    e.target.style.setProperty("--p", `${e.target.value * 100}%`);
    state.connect.pendingVolume = +e.target.value;
  };
  root.onchange = (e) => {
    const target = chosenDevice();
    if (!e.target.matches("[data-dev-vol]") || !target) return;
    sendCommand(target.id, "volume", { volume: +e.target.value });
    setTimeout(() => { state.connect.pendingVolume = null; }, 6000);
  };
}

// ── État de Sona : ce qui marche, et sinon pourquoi ───────────────────────

async function viewStatus() {
  setTimeout(() => {
    // Un relevé tout de suite (celui en cours peut attendre 25 s une nouveauté).
    startConnect.now?.();
    refreshStatus();
    setTimeout(refreshStatus, 1200);
    const timer = setInterval(refreshStatus, 5000);
    onLeave(() => clearInterval(timer));
  });
  return page(`<h1 class="page-title">État de Sona</h1>
    <p class="page-sub">Chaque élément en vert marche ; sinon, la raison est juste en dessous.</p>
    <div id="status-root"><p class="muted">Vérification…</p></div>`);
}

const statusRow = (level, title, detail = "") => `<div class="set-row st-row"><span class="st-dot ${level}" aria-label="${{ ok: "OK", warn: "Attention", bad: "Problème", off: "Inactif" }[level]}"></span>
  <span class="set-text"><b>${esc(title)}</b>${detail ? `<small>${esc(detail)}</small>` : ""}</span></div>`;

const agoText = (ms) => (ms < 5000 ? "à l'instant" : since(new Date(Date.now() - ms).toISOString()));

async function refreshStatus() {
  if (!$("#status-root")) return;
  const [health, saved, ds] = await Promise.all([
    api("/health").catch((e) => ({ error: e.message || "Injoignable" })),
    api("/connect/saved").catch(() => null),
    desktop?.status ? desktop.status().catch(() => null) : null,
  ]);
  const root = $("#status-root");
  if (!root) return;
  const c = state.connect;
  const groups = [];

  groups.push(["Sona", [
    health.error ? statusRow("bad", "Serveur Sona", `Injoignable : ${health.error}`) : statusRow("ok", "Serveur Sona", `En ligne · version ${health.version || "?"}`),
    !health.error && ({
      ok: statusRow("ok", "Lecture", "Tout fonctionne"),
      degraded: statusRow("warn", "Lecture", "Perturbée : certains titres peuvent mettre du temps à se lancer"),
      down: statusRow("bad", "Lecture", "En panne côté serveur"),
    }[health.streaming] || statusRow("off", "Lecture", "État inconnu")),
    statusRow("ok", "Compte", `Connecté : ${account.display_name || account.username}`),
  ]]);

  const others = otherDevices();
  const chosen = chosenDevice();
  const fresh = c.lastOk && Date.now() - c.lastOk < 45000;
  groups.push(["Sona Connect", [
    fresh ? statusRow("ok", "Synchronisation", `À jour (${agoText(Date.now() - c.lastOk)})`)
      : c.lastError ? statusRow("bad", "Synchronisation", `${c.lastError} (${agoText(Date.now() - c.lastErrorAt)})`)
      : statusRow("warn", "Synchronisation", "En attente du serveur…"),
    others.length ? statusRow("ok", "Appareils allumés", others.map((d) => d.name).join(", ")) : statusRow("off", "Appareils allumés", "Aucun autre appareil Sona ouvert en ce moment"),
    saved ? statusRow(saved.length ? "ok" : "off", "Appareils enregistrés", saved.length
      ? `${plural(saved.length, "appareil")} · ${saved.filter((d) => others.some((o) => o.id === d.id)).length} allumé(s)` : "Aucun pour l'instant") : "",
    c.control ? (chosen ? statusRow("ok", "Appareil piloté", `Tu pilotes ${chosen.name}`)
      : statusRow("warn", "Appareil piloté", `${(saved || []).find((d) => d.id === c.control)?.name || "L'appareil choisi"} est éteint : ouvre Sona dessus`)) : "",
  ]]);

  if (ds) {
    const u = ds.updates || {};
    const r = ds.remote || {};
    const phones = (r.clients || []).filter((x) => x.name !== "Stream Deck");
    const d = ds.discord || {};
    groups.push([`Sona pour ${desktop.platform === "darwin" ? "Mac" : "Windows"}`, [
      u.available && u.latest ? statusRow("warn", "Version", `${ds.version} · la ${u.latest.version} est disponible (Réglages → Mises à jour)`)
        : u.error ? statusRow("warn", "Version", `${ds.version} · vérification impossible : ${u.error}`)
        : statusRow("ok", "Version", `${ds.version} · à jour`),
      !r.enabled ? statusRow("off", "Télécommande du téléphone", "Désactivée")
        : r.running ? statusRow("ok", "Télécommande du téléphone", `Port ${r.port}${phones.length ? ` · ${phones.map((x) => x.name).join(", ")}` : " · aucun téléphone connecté"}`)
        : statusRow("bad", "Télécommande du téléphone", r.error || "Arrêtée"),
      ds.streamDeck ? statusRow("ok", "Stream Deck", `Plugin connecté ${agoText(Date.now() - ds.streamDeck.since)}`)
        : !r.running ? statusRow("bad", "Stream Deck", "La télécommande est arrêtée : le plugin ne peut pas joindre Sona")
        : statusRow("off", "Stream Deck", "Plugin non connecté : installe-le (version Windows, fichier .streamDeckPlugin) et ouvre le logiciel Stream Deck"),
      !d.wanted ? statusRow("off", "Statut Discord", "Désactivé")
        : !d.configured ? statusRow("warn", "Statut Discord", "Identifiant d'application Discord manquant (Réglages)")
        : d.connected ? statusRow("ok", "Statut Discord", "Connecté : « Écoute Sona » sur ton profil")
        : statusRow("warn", "Statut Discord", d.error || "Connexion à Discord…"),
      ds.shortcuts?.refused?.length ? statusRow("warn", "Raccourcis clavier", `${plural(ds.shortcuts.refused.length, "raccourci déjà pris", "raccourcis déjà pris")} par une autre app`)
        : statusRow(ds.shortcuts?.count ? "ok" : "off", "Raccourcis clavier", ds.shortcuts?.count ? plural(ds.shortcuts.count, "raccourci actif", "raccourcis actifs") : "Aucun"),
      statusRow(ds.overlay ? "ok" : "off", "Paroles en surimpression", ds.overlay ? "Affichées" : "Masquées"),
      ds.iphone?.available ? statusRow("ok", "Sona sur l'iPhone", ds.iphone.devices ? plural(ds.iphone.devices, "iPhone vu", "iPhone vus") : "Aucun iPhone branché ou sur le Wi-Fi")
        : statusRow("warn", "Sona sur l'iPhone", "Module iPhone absent de cette version"),
    ]]);
  }
  root.innerHTML = groups.map(([title, rows]) => `<h3 class="set-head">${esc(title)}</h3><div class="set-group">${rows.filter(Boolean).join("")}</div>`).join("");
}

// ── Feuilles et menus (comme les feuilles d'iOS) ─────────────────────────
// Téléphone : la feuille monte du bas et se ferme en glissant ; ordinateur :
// une fenêtre au centre.

function openSheet(html, { cls = "", onClose } = {}) {
  const wrap = document.createElement("div");
  wrap.className = `sheet-wrap ${cls}`;
  wrap.innerHTML = `<div class="sheet-backdrop"></div><div class="sheet" role="dialog" aria-modal="true"><div class="sheet-grab"><span></span></div><div class="sheet-body">${html}</div></div>`;
  document.body.append(wrap);
  requestAnimationFrame(() => wrap.classList.add("open"));
  const sheet = $(".sheet", wrap);
  const close = () => {
    if (wrap._closed) return;
    wrap._closed = true;
    wrap.classList.remove("open");
    document.removeEventListener("keydown", onKey);
    setTimeout(() => wrap.remove(), 320);
    onClose?.();
  };
  const onKey = (e) => { if (e.key === "Escape") { e.stopPropagation(); close(); } };
  document.addEventListener("keydown", onKey);
  $(".sheet-backdrop", wrap).onclick = close;
  // Glisser la feuille vers le bas la ferme.
  let startY = null;
  sheet.addEventListener("touchstart", (e) => {
    const body = $(".sheet-body", sheet);
    startY = (e.target.closest(".sheet-grab") || body.scrollTop <= 0) && !e.target.closest("input, textarea") ? e.touches[0].clientY : null;
  }, { passive: true });
  sheet.addEventListener("touchmove", (e) => {
    if (startY == null) return;
    const dy = e.touches[0].clientY - startY;
    if (dy > 0) { sheet.style.transition = "none"; sheet.style.transform = `translateY(${dy}px)`; }
  }, { passive: true });
  sheet.addEventListener("touchend", (e) => {
    if (startY == null) return;
    const dy = e.changedTouches[0].clientY - startY;
    sheet.style.transition = "";
    sheet.style.transform = "";
    if (dy > 110) close();
    startY = null;
  });
  wrap.close = close;
  return wrap;
}

/** Menu d'actions : [{ icon, label, sub, run, danger, checked }]. */
function actionSheet(title, items, { header = "" } = {}) {
  const wrap = openSheet(`${header || (title ? `<h2 class="sheet-title">${esc(title)}</h2>` : "")}
    <div class="menu">${items.filter(Boolean).map((item, i) => `<button class="menu-item ${item.danger ? "danger" : ""}" data-mi="${i}">
      <span class="mi-icon">${item.icon || ""}</span><span class="mi-text"><span class="mi-label">${esc(item.label)}</span>${item.sub ? `<span class="mi-sub">${esc(item.sub)}</span>` : ""}</span>
      ${item.checked ? `<span class="mi-check">${icons.check}</span>` : ""}</button>`).join("")}</div>`);
  const list = items.filter(Boolean);
  $$("[data-mi]", wrap).forEach((b) => (b.onclick = async () => {
    haptic();
    wrap.close();
    try { await list[+b.dataset.mi].run?.(); } catch (e) { toast(e.message); }
  }));
  return wrap;
}

function askText({ title, placeholder = "", value = "", confirm = "OK", hint = "" }) {
  return new Promise((resolve) => {
    let done = false;
    const finish = (v) => { if (done) return; done = true; resolve(v); wrap.close(); };
    const wrap = openSheet(`<h2 class="sheet-title">${esc(title)}</h2>
      ${hint ? `<p class="muted">${esc(hint)}</p>` : ""}
      <form class="ask"><input class="field" name="v" value="${esc(value)}" placeholder="${esc(placeholder)}" autocomplete="off" required>
      <div class="pill-row"><button type="button" class="btn ghost" data-cancel>Annuler</button><button class="btn" type="submit">${esc(confirm)}</button></div></form>`,
      { onClose: () => { if (!done) { done = true; resolve(null); } } });
    const input = $("input", wrap);
    setTimeout(() => { input.focus(); input.select(); }, 250);
    $("form", wrap).onsubmit = (e) => { e.preventDefault(); finish(input.value.trim() || null); };
    $("[data-cancel]", wrap).onclick = () => finish(null);
  });
}

function confirmSheet(text, confirm = "Confirmer") {
  return new Promise((resolve) => {
    let done = false;
    const wrap = openSheet(`<h2 class="sheet-title">${esc(text)}</h2>
      <div class="pill-row"><button class="btn ghost" data-no>Annuler</button><button class="btn danger" data-yes>${esc(confirm)}</button></div>`,
      { onClose: () => { if (!done) { done = true; resolve(false); } } });
    $("[data-yes]", wrap).onclick = () => { done = true; resolve(true); wrap.close(); };
    $("[data-no]", wrap).onclick = () => { done = true; resolve(false); wrap.close(); };
  });
}

// ── Menu d'un titre ──────────────────────────────────────────────────────

function trackMenu(t, ctx = null, index = -1) {
  if (!t) return;
  const liked = state.liked.has(trackKey(t));
  const playing = sameTrack(t, state.queue[state.index]);
  const entry = ctx?.entries?.[index];
  const header = `<div class="menu-head"><img src="${esc(big(t.cover_url, 200))}" alt=""><div style="min-width:0"><div class="t">${esc(t.title)}</div><div class="s">${esc([t.artist, t.album].filter(Boolean).join(" · "))}</div></div></div>`;
  actionSheet("", [
    !playing && { icon: icons.nextUp, label: "Lire ensuite", run: () => playNext(t) },
    !playing && { icon: icons.queue, label: "Ajouter à la file d'attente", run: () => addToQueue(t) },
    { icon: icons.plus, label: "Ajouter à une playlist…", run: () => addToPlaylistSheet([t]) },
    { icon: liked ? icons.heartFill : icons.heart, label: liked ? "Retirer de la bibliothèque" : "Ajouter à la bibliothèque", run: () => toggleLike(t) },
    { icon: icons.radio, label: "Lancer la radio DJ", sub: "Des titres qui s'enchaînent bien avec celui-ci", run: () => startDJRadio(t) },
    party.state && { icon: icons.headphones, label: party.state.is_host ? "Jouer ensuite dans la session" : "Proposer à la session", run: () => partyPropose(t) },
    t.artist_source_id && { icon: icons.user, label: "Aller à l'artiste", run: () => { closeNowPlaying(); go(`#/artist/${t.source}/${t.artist_source_id}`); } },
    t.album_source_id && { icon: icons.note, label: "Aller à l'album", run: () => { closeNowPlaying(); go(`#/album/${t.source}/${t.album_source_id}`); } },
    playing && { icon: icons.sparkles, label: "Réagir à cet instant", sub: "Tes amis verront ta réaction à ce moment du titre", run: () => addMoment(t) },
    playing && { icon: icons.moon, label: sleep.until ? `Minuteur : ${sleepLabel()}` : "Minuteur de sommeil", run: sleepMenu },
    playing && { icon: icons.tv, label: "Diffuser sur la TV ou la PS5", run: openCast },
    playing && { icon: icons.flag, label: "Mauvaise version ?", sub: "Clip, live, remix… : une autre source est cherchée", run: () => reportWrongVersion(t) },
    entry && ctx.playlist?.can_edit && { icon: icons.trash, label: "Retirer de cette playlist", danger: true, run: async () => {
      await api(`/me/playlists/${ctx.playlist.id}/tracks/${entry.entry_id}`, { method: "DELETE" });
      toast("Retiré de la playlist"); route();
    } },
    ...otherDevices().filter((d) => d.kind !== "iphone" || d.id === state.connect.control).map((d) => ({
      icon: d.kind === "iphone" ? icons.phone : icons.laptop, label: `Écouter sur ${d.name}`,
      sub: "Le titre se lance sur cet appareil", run: () => playOnDevice(d, ctx?.tracks?.length ? ctx.tracks : [t], ctx?.tracks?.length ? Math.max(0, index) : 0, ctx?.name),
    })),
    { icon: icons.share, label: "Partager", run: () => shareTrack(t) },
  ], { header });
}

/** Lance des titres sur un autre appareil (Sona Connect) et le pilote. */
async function playOnDevice(d, tracks, index = 0, name = "") {
  const queue = tracks.slice(0, 150).map(cleanTrack);
  try {
    await api("/connect/command", { method: "POST", body: JSON.stringify({
      device_id: deviceId, target: d.id, action: "play_tracks", queue, index: Math.min(index, queue.length - 1), name: name || null,
    }) });
    if (audio.src && !audio.paused) audio.pause();
    setControl(d.id);
    toast(`Lecture sur ${d.name}`);
    setTimeout(() => startConnect.now?.(), 700);
  } catch (e) { toast(e.message); }
}

async function shareTrack(t) {
  const text = `${t.title} — ${t.artist}`;
  try {
    if (navigator.share) await navigator.share({ title: t.title, text: `🎧 ${text} (via Sona)` });
    else { await navigator.clipboard.writeText(text); toast("Copié"); }
  } catch {}
}

async function addToPlaylistSheet(tracks) {
  tracks = tracks.filter((t) => t?.source && t?.source_id);
  if (!tracks.length) return;
  const playlists = (await api("/me/playlists").catch(() => state.playlists)).filter((p) => p.can_edit !== false && p.import_status !== "importing");
  const wrap = openSheet(`<h2 class="sheet-title">Ajouter à une playlist</h2>
    <p class="muted">${tracks.length > 1 ? plural(tracks.length, "titre") : `« ${esc(tracks[0].title)} »`}</p>
    <div class="menu">
      <button class="menu-item" data-new><span class="mi-icon">${icons.plus}</span><span class="mi-text"><span class="mi-label">Nouvelle playlist</span></span></button>
      ${playlists.map((p) => `<button class="menu-item" data-pl="${p.id}"><img class="mi-thumb" src="${esc(p.cover_url || (p.covers || [])[0] || "icons/icon-192.png")}" alt="">
        <span class="mi-text"><span class="mi-label">${esc(p.name)}</span><span class="mi-sub">${plural(p.track_count, "titre")}${p.is_owner === false ? ` · de ${esc(p.owner_name || "un ami")}` : ""}</span></span></button>`).join("")}
    </div>`);
  $("[data-new]", wrap).onclick = () => { wrap.close(); newPlaylist(tracks); };
  $$("[data-pl]", wrap).forEach((b) => (b.onclick = async () => {
    wrap.close();
    try {
      const got = await api(`/me/playlists/${b.dataset.pl}/tracks`, { method: "POST", body: JSON.stringify({ tracks: tracks.map(cleanTrack) }) });
      haptic();
      toast(`Ajouté à « ${got.name} »`);
      loadSidebar();
    } catch (e) { toast(e.message); }
  }));
}

async function reportWrongVersion(t) {
  try {
    await api(`/stream/${encodeURIComponent(t.source)}/${encodeURIComponent(t.source_id)}/wrong-version`, { method: "POST" });
    toast("Source écartée : on relance avec une autre");
    if (sameTrack(t, state.queue[state.index])) playAt(state.index);
  } catch (e) { toast(e.message); }
}

// ── Moments : réactions posées à un instant du titre ──────────────────────

const moments = { list: [], shown: new Set(), track: null };

async function loadMoments(t) {
  moments.list = [];
  moments.shown = new Set();
  moments.track = t;
  renderMoments();
  const got = await api(`/moments/${encodeURIComponent(t.source)}/${encodeURIComponent(t.source_id)}`).catch(() => []);
  if (!sameTrack(t, state.queue[state.index])) return;
  moments.list = got;
  renderMoments();
}

function renderMoments() {
  const box = $("#np-moments");
  const t = state.queue[state.index];
  if (!box || !t) return;
  const dur = audio.duration && isFinite(audio.duration) ? audio.duration : t.duration_seconds || 0;
  box.innerHTML = dur ? moments.list.map((m) => `<span class="moment" style="left:${Math.min(100, (m.position / dur) * 100)}%" title="${esc(`${m.name} : ${m.text || m.emoji}`)}">${esc(m.emoji)}</span>`).join("") : "";
}

/** Passage sur la réaction d'un ami : elle s'affiche un instant. */
function checkMoments() {
  const now = audio.currentTime;
  for (const m of moments.list) {
    if (m.is_me || moments.shown.has(m.id) || now < m.position || now > m.position + 2) continue;
    moments.shown.add(m.id);
    floatReaction(m.emoji, `${m.name}${m.text ? ` : ${m.text}` : ""}`);
  }
}

function floatReaction(emoji, label = "") {
  const el = document.createElement("div");
  el.className = "float-reaction";
  el.innerHTML = `<span class="e">${esc(emoji)}</span>${label ? `<span class="l">${esc(label)}</span>` : ""}`;
  el.style.left = `${20 + Math.random() * 60}%`;
  document.body.append(el);
  setTimeout(() => el.remove(), 3200);
}

const MOMENT_EMOJIS = ["🔥", "😍", "🥹", "💃", "🤯", "😂", "🎤", "👏"];

function addMoment(t) {
  const position = Math.round(audio.currentTime * 10) / 10;
  const wrap = openSheet(`<h2 class="sheet-title">Réagis à ${fmt(position)}</h2>
    <p class="muted">Tes amis verront ta réaction à cet instant de « ${esc(t.title)} ».</p>
    <div class="emoji-row">${MOMENT_EMOJIS.map((e) => `<button data-emoji="${e}">${e}</button>`).join("")}</div>
    <input class="field" id="moment-text" maxlength="80" placeholder="Un petit mot (facultatif)">
    <div class="pill-row"><button class="btn" data-publish disabled>Publier</button></div>`);
  let emoji = null;
  $$("[data-emoji]", wrap).forEach((b) => (b.onclick = () => {
    emoji = b.dataset.emoji;
    $$("[data-emoji]", wrap).forEach((x) => x.classList.toggle("on", x === b));
    $("[data-publish]", wrap).disabled = false;
  }));
  $("[data-publish]", wrap).onclick = async () => {
    try {
      await api(`/moments/${encodeURIComponent(t.source)}/${encodeURIComponent(t.source_id)}`, {
        method: "POST", body: JSON.stringify({ position, emoji, text: $("#moment-text", wrap).value.trim() || null }),
      });
      wrap.close();
      floatReaction(emoji);
      loadMoments(t);
    } catch (e) { toast(e.message); }
  };
}

// ── Minuteur de sommeil ──────────────────────────────────────────────────

const sleep = { until: null, endOfTrack: false, timer: null };
const sleepLabel = () => sleep.endOfTrack ? "fin du titre" : `${Math.max(1, Math.round((sleep.until - Date.now()) / 60000))} min`;

function setSleep(minutes) {
  clearTimeout(sleep.timer);
  sleep.until = null;
  sleep.endOfTrack = false;
  if (minutes === "track") { sleep.endOfTrack = true; sleep.until = Infinity; toast("Pause à la fin du titre"); return; }
  if (!minutes) { toast("Minuteur arrêté"); return; }
  sleep.until = Date.now() + minutes * 60000;
  sleep.timer = setTimeout(() => { audio.pause(); sleep.until = null; toast("Bonne nuit 🌙"); }, minutes * 60000);
  toast(`Pause dans ${minutes} min`);
}

function sleepMenu() {
  actionSheet("Minuteur de sommeil", [
    ...[15, 30, 45, 60].map((m) => ({ icon: icons.clock, label: `${m} minutes`, run: () => setSleep(m) })),
    { icon: icons.note, label: "Fin du titre", run: () => setSleep("track") },
    sleep.until && { icon: icons.close, label: "Arrêter le minuteur", danger: true, run: () => setSleep(0) },
  ]);
}

// ── DJ vocal : une voix annonce le titre, comme à la radio ───────────────

const dj = { audio: null, seq: 0 };

async function djAnnounce(t, previous) {
  if (store.get("sona.dj") !== "1" || party.state && !party.state.is_host) return;
  const seq = ++dj.seq;
  const q = new URLSearchParams({ title: t.title, artist: t.artist, voice: store.get("sona.djVoice") || "remy", tz: tz() });
  if (previous) { q.set("prev_title", previous.title); q.set("prev_artist", previous.artist); }
  if (t.year) q.set("year", String(t.year).slice(0, 4));
  try {
    const intro = await api(`/dj/intro?${q}`);
    if (seq !== dj.seq || !sameTrack(t, state.queue[state.index])) return;
    const restore = audio.volume;
    const duck = () => { audio.volume = Math.min(restore, 0.25); };
    const unduck = () => { audio.volume = restore; };
    if (intro.audio) {
      dj.audio?.pause();
      dj.audio = new Audio(`data:audio/mpeg;base64,${intro.audio}`);
      dj.audio.onended = unduck;
      dj.audio.onerror = unduck;
      duck();
      dj.audio.play().catch(unduck);
    } else if ("speechSynthesis" in window) {
      const u = new SpeechSynthesisUtterance(intro.text);
      u.lang = "fr-FR";
      u.onend = unduck;
      duck();
      speechSynthesis.speak(u);
    }
  } catch {}
}

// ── Amis ─────────────────────────────────────────────────────────────────

const playTrackFrom = (t) => t && t.source && t.source_id ? playList([t], 0, "") : toast("Titre introuvable");

async function viewFriends() {
  $("#content").innerHTML = skeleton("Amis");
  const [friends, parties, rooms] = await Promise.all([
    api("/friends"), api("/party/active").catch(() => []), api("/blindlive/active").catch(() => []),
  ]);
  // Rafraîchi toutes les 15 s, comme l'onglet de l'app.
  const timer = setInterval(async () => {
    const fresh = await api("/friends").catch(() => null);
    const box = $("#friends-list");
    if (fresh && box) box.innerHTML = friendRows(fresh);
  }, 15000);
  onLeave(() => clearInterval(timer));
  setTimeout(() => {
    $("#friends-list")?.addEventListener("click", (e) => {
      const play = e.target.closest("[data-fplay]");
      if (play) { e.preventDefault(); e.stopPropagation(); const f = friends.find((x) => String(x.account_id) === play.dataset.fplay); playTrackFrom(f?.now_playing?.track || f?.last_play); }
    });
  });
  const live = [
    ...parties.filter((p) => !p.joined).map((p) => `<a class="live-pill" href="#/party/${esc(p.code)}">${icons.headphones} <b>${esc(p.host_name || "Un ami")}</b> écoute en groupe (${p.members}) — rejoindre</a>`),
    ...rooms.filter((r) => !r.joined && r.phase !== "finished").map((r) => `<a class="live-pill violet" href="#/live/${esc(r.code)}">${icons.wave} Blind test de <b>${esc(r.host_name || "un ami")}</b> (${r.players}) — rejoindre</a>`),
  ].join("");
  return page(`<h1 class="page-title">Amis</h1><p class="page-sub">Ce qu'écoutent tes amis en ce moment.</p>
    ${live}
    ${friends.length ? `<div class="friend-list" id="friends-list">${friendRows(friends)}</div>`
      : empty("👋", "Personne pour l'instant", "Les autres comptes Sona qui partagent leur écoute apparaîtront ici.")}`);
}

function friendRows(friends) {
  return friends.map((f) => {
    const name = f.display_name || f.username;
    const t = f.now_playing?.track || f.last_play;
    return `<a class="friend" href="#/friend/${f.account_id}">
      <span class="friend-avatar">${avatar(f.avatar_url, name)}${f.now_playing ? '<i class="live-dot"></i>' : ""}</span>
      <span class="friend-text"><span class="n">${esc(name)}${f.compatibility != null ? ` <span class="compat">${f.compatibility} %</span>` : ""}</span>
        ${t ? `<span class="s">${f.now_playing ? `${bars()} ` : ""}${esc(t.title)} · ${esc(t.artist)}</span>
          <span class="w">${f.now_playing ? "En train d'écouter" : since(f.last_play.played_at)}</span>` : `<span class="s">Pas encore d'écoute</span>`}</span>
      ${t?.cover_url ? `<span class="friend-cover" data-fplay="${f.account_id}"><img src="${esc(big(t.cover_url, 120))}" alt="">${icons.play}</span>` : ""}</a>`;
  }).join("");
}

async function viewFriend(id) {
  $("#content").innerHTML = skeleton("");
  const f = await api(`/friends/${encodeURIComponent(id)}`);
  const name = f.display_name || f.username;
  const recent = f.recent.filter((p) => p.source && p.source_id);
  const tops = f.top_tracks.filter((t) => t.source && t.source_id).map((t) => ({ source: t.source, source_id: t.source_id, title: t.name, artist: t.subtitle || "", cover_url: t.cover_url }));
  setTimeout(() => $("[data-fnow]")?.addEventListener("click", () => playTrackFrom(f.now_playing.track)));
  return page(`<div class="profile-head">
      <div class="hero-glow"><img src="${esc(f.avatar_url || f.now_playing?.track.cover_url || "")}" alt=""></div>
      ${avatar(f.avatar_url, name, "profile-avatar")}
      <h1>${esc(name)}</h1><div class="muted">@${esc(f.username)}</div>
      ${f.compatibility != null ? `<div class="compat-big"><b>${f.compatibility} %</b> d'affinité musicale</div>` : `<div class="muted">Pas encore assez d'écoutes pour comparer.</div>`}
      <div class="pill-row center"><a class="btn" href="#/blend/${f.account_id}">${icons.sparkles} Blend</a></div>
    </div>
    ${f.now_playing ? `<button class="now-card" data-fnow><img src="${esc(big(f.now_playing.track.cover_url, 200))}" alt="">
      <span><span class="eyebrow">${bars()} En train d'écouter</span><span class="t">${esc(f.now_playing.track.title)}</span><span class="s">${esc(f.now_playing.track.artist)}</span></span>${icons.play}</button>` : ""}
    ${f.shared_artists.length ? `<section class="section"><div class="section-head"><h2>Vos goûts en commun</h2></div><div class="chips">${f.shared_artists.map((a) => `<span class="chip">${esc(a)}</span>`).join("")}</div></section>` : ""}
    ${shelf("Ses artistes du mois", f.top_artists.map((a) => card({ href: a.source && a.source_id ? `#/artist/${a.source}/${a.source_id}` : `#/search/${encodeURIComponent(a.name)}`, cover: a.cover_url, title: a.name, subtitle: plural(a.plays, "écoute"), round: true })), { kind: "round" })}
    ${tops.length ? `<section class="section"><div class="section-head"><h2>Ses titres du mois</h2></div>${trackTable(tops, `Titres de ${name}`, { showAlbum: false })}</section>` : ""}
    ${shelf("Ses playlists", f.playlists.map((p) => card({ href: `#/playlist/${p.id}`, cover: p.cover_url || (p.covers || [])[0], covers: p.cover_url ? null : p.covers, title: p.name, subtitle: plural(p.track_count, "titre") })))}
    ${recent.length ? `<section class="section"><div class="section-head"><h2>Écoutes récentes</h2></div>${trackTable(recent, `Écoutes de ${name}`, { numbers: false })}</section>` : ""}`);
}

async function viewBlend(id) {
  $("#content").innerHTML = skeleton("");
  const b = await api(`/friends/${encodeURIComponent(id)}/blend`);
  const list = register(b.tracks, b.title);
  return page(`<div class="blend-head">
      <div class="blend-avatars">${avatar(account.avatar_url, account.display_name || account.username, "profile-avatar")}${avatar(b.friend_avatar_url, b.friend_name, "profile-avatar")}</div>
      <div class="kind">Blend</div><h1 class="page-title">${esc(b.title)}</h1>
      <p class="page-sub">${b.compatibility != null ? `${b.compatibility} % d'affinité · ` : ""}${plural(b.shared_tracks, "titre")} en commun. Une playlist mélangée chaque jour, rien que pour vous deux.</p>
      <div class="pill-row center"><button class="btn" data-play="${list}">${icons.play} Lecture</button><button class="btn ghost" data-shuffle="${list}">${icons.shuffle} Aléatoire</button></div></div>
    ${b.shared_artists.length ? `<div class="chips center">${b.shared_artists.map((a) => `<span class="chip">${esc(a)}</span>`).join("")}</div>` : ""}
    ${b.tracks.length ? trackTable(b.tracks, b.title) : empty("✦", "Pas encore de blend", "Écoutez encore un peu de musique tous les deux.")}`);
}

// ── Stats ────────────────────────────────────────────────────────────────

const PERIODS = [["day", "Jour"], ["week", "Semaine"], ["month", "Mois"], ["year", "Année"], ["all", "Tout"]];
const statsView = { period: store.get("sona.statsPeriod") || "week", offset: 0 };

function barChart(values, labels, { highlight = -1, unit = "" } = {}) {
  const max = Math.max(1, ...values);
  return `<div class="bars-chart">${values.map((v, i) => `<div class="bc-col ${i === highlight ? "hi" : ""}" title="${esc(labels[i])} : ${v}${unit}">
    <div class="bc-bar" style="height:${Math.max(2, (v / max) * 100)}%"></div><span class="bc-l">${esc(labels[i])}</span></div>`).join("")}</div>`;
}

function rankRows(items, kind) {
  return `<div class="rank">${items.map((it, i) => {
    const href = kind === "artist" && it.source && it.source_id ? `#/artist/${it.source}/${it.source_id}`
      : kind === "album" && it.source && it.source_id ? `#/album/${it.source}/${it.source_id}` : "";
    const pic = kind === "artist" ? (it.picture_url || it.cover_url) : it.cover_url;
    const tag = href ? "a" : kind === "track" && it.source_id ? "button" : "div";
    return `<${tag} class="rank-row" ${href ? `href="${href}"` : ""} ${tag === "button" ? `data-rank-play="${i}"` : ""}>
      <span class="rk">${i + 1}</span><img class="${kind === "artist" ? "round" : ""}" src="${esc(big(pic, 120) || "icons/icon-192.png")}" alt="" loading="lazy">
      <span class="rt"><span class="t">${esc(it.name)}</span>${it.subtitle ? `<span class="s">${esc(it.subtitle)}</span>` : ""}</span>
      <span class="rv">${plural(it.plays, "écoute")}<small>${minutesLabel(it.minutes)}</small></span></${tag}>`;
  }).join("")}</div>`;
}

async function viewStats() {
  const { period, offset } = statsView;
  const seg = `<div class="segmented">${PERIODS.map(([k, label]) => `<button data-period="${k}" class="${k === period ? "on" : ""}">${label}</button>`).join("")}</div>`;
  $("#content").innerHTML = page(`<h1 class="page-title">Stats</h1>${seg}<div class="loading-row"><span class="spinner"></span></div>`);
  bindStatsControls();
  const [r, challenges, live] = await Promise.all([
    api(`/stats?period=${period}&offset=${offset}&tz=${encodeURIComponent(tz())}`),
    api(`/challenges?tz=${encodeURIComponent(tz())}`).catch(() => null),
    api(`/stats/live?tz=${encodeURIComponent(tz())}`).catch(() => null),
  ]);
  const delta = r.previous_plays ? Math.round(((r.plays - r.previous_plays) / r.previous_plays) * 100) : null;
  const hourLabels = Array.from({ length: 24 }, (_, h) => (h % 6 === 0 ? `${h}h` : ""));
  const weekLabels = ["L", "M", "M", "J", "V", "S", "D"];
  setTimeout(() => {
    bindStatsControls();
    $$("[data-rank-play]").forEach((b) => (b.onclick = () => {
      const tracks = r.top_tracks.filter((t) => t.source_id).map((t) => ({ source: t.source, source_id: t.source_id, title: t.name, artist: t.subtitle || "", cover_url: t.cover_url }));
      const it = r.top_tracks[+b.dataset.rankPlay];
      playList(tracks, Math.max(0, tracks.findIndex((t) => t.source_id === it.source_id)), `Top titres · ${r.label}`);
    }));
    $$("[data-recap]").forEach((b) => (b.onclick = () => openRecap(b.dataset.recap, -1)));
    $("[data-import-history]")?.addEventListener("click", importLastfmHistory);
  });
  const nowPlaying = live?.now_playing;
  return page(`<h1 class="page-title">Stats</h1>${seg}
    <div class="period-nav">${period === "all" ? "" : `<button data-offset="-1" aria-label="Période précédente">${icons.left}</button>`}
      <span>${esc(r.label)}</span>${period !== "all" && offset < 0 ? `<button data-offset="1" aria-label="Période suivante">${icons.right}</button>` : "<i></i>"}</div>
    ${r.plays ? `
    <div class="stat-hero"><div class="eyebrow">Temps d'écoute</div><div class="big-num">${minutesLabel(r.minutes)}</div>
      <div class="s">${plural(r.plays, "écoute")}${delta != null && period !== "all" ? ` · <span class="${delta >= 0 ? "up" : "down"}">${delta >= 0 ? "+" : ""}${delta} %</span> vs la période précédente` : ""}</div></div>
    <div class="stat-grid">
      <div class="stat"><b>${r.artists}</b><span>artistes</span></div><div class="stat"><b>${r.tracks}</b><span>titres</span></div>
      <div class="stat"><b>${r.albums}</b><span>albums</span></div><div class="stat"><b>${r.streak_days}</b><span>jours d'affilée</span></div>
    </div>
    ${r.timeline.length > 1 ? `<section class="section"><div class="section-head"><h2>Au fil du temps</h2></div>${barChart(r.timeline.map((b) => b.minutes), r.timeline.map((b) => b.label), { unit: " min" })}</section>` : ""}
    ${r.top_artists.length ? `<section class="section"><div class="section-head"><h2>Top artistes</h2></div>${rankRows(r.top_artists.slice(0, 10), "artist")}</section>` : ""}
    ${r.top_tracks.length ? `<section class="section"><div class="section-head"><h2>Top titres</h2></div>${rankRows(r.top_tracks.slice(0, 10), "track")}</section>` : ""}
    ${r.top_albums.length ? `<section class="section"><div class="section-head"><h2>Top albums</h2></div>${rankRows(r.top_albums.slice(0, 6), "album")}</section>` : ""}
    <section class="section"><div class="section-head"><h2>Tes habitudes</h2></div>
      ${r.top_hour != null ? `<p class="muted">Surtout vers ${r.top_hour} h${r.top_weekday ? `, et le ${esc(r.top_weekday)} plus que les autres jours` : ""}.</p>` : ""}
      <div class="habits">${barChart(r.hours, hourLabels, { highlight: r.top_hour ?? -1 })}${barChart(r.weekdays, weekLabels)}</div></section>
    ${r.discoveries.length ? `<section class="section"><div class="section-head"><h2>Découvertes</h2></div><p class="muted">Artistes écoutés pour la première fois sur cette période.</p>
      ${shelfInner(r.discoveries.map((a) => card({ href: a.source && a.source_id ? `#/artist/${a.source}/${a.source_id}` : `#/search/${encodeURIComponent(a.name)}`, cover: a.picture_url || a.cover_url, title: a.name, subtitle: plural(a.plays, "écoute"), round: true })), "round")}</section>` : ""}`
    : empty("📊", "Aucune écoute sur cette période", "Écoute un peu de musique : tes stats se remplissent toutes seules.")}
    <section class="section"><div class="section-head"><h2>Récaps</h2></div>
      <div class="tiles">
        ${tile({ icon: icons.sparkles, title: "Ta semaine", subtitle: "Le récap de la semaine dernière", tone: "violet", data: 'data-recap="week"' })}
        ${tile({ icon: icons.calendar, title: "Ton mois", subtitle: "Le récap du mois dernier", tone: "blue", data: 'data-recap="month"' })}
        ${tile({ icon: icons.trophy, title: "Ton année", subtitle: "Le récap de l'année dernière", tone: "orange", data: 'data-recap="year"' })}
      </div></section>
    ${challenges ? `<section class="section"><div class="section-head"><h2>Défis de la semaine</h2><span class="muted">${challenges.ends_in_days ? `encore ${plural(challenges.ends_in_days, "jour")}` : "dernier jour"}</span></div>
      <div class="challenges">${challenges.challenges.map((c) => `<div class="challenge ${c.done ? "done" : ""}"><div class="ct">${esc(c.title)}${c.done ? ` ${icons.check}` : ""}</div>
        <div class="meter"><i style="width:${Math.round((c.value / c.goal) * 100)}%"></i></div><div class="cv">${c.value}/${c.goal} ${esc(c.unit)}</div></div>`).join("")}</div>
      <div class="badges">${challenges.badges.map((b) => `<div class="badge ${b.earned ? "earned" : ""}" title="${esc(b.description)}"><span>${b.earned ? "🏅" : "🔒"}</span><b>${esc(b.title)}</b><small>${esc(b.description)}</small></div>`).join("")}</div></section>` : ""}
    ${live ? `<section class="section"><div class="section-head"><h2>En direct</h2><a class="more" href="#/recent">Écoutes récentes</a></div>
      <div class="live-card">
        ${nowPlaying ? `<div class="lc-now"><img src="${esc(big(nowPlaying.cover_url, 120))}" alt=""><span><span class="eyebrow">${bars()} En cours</span><b>${esc(nowPlaying.title)}</b> · ${esc(nowPlaying.artist)}</span></div>` : ""}
        <div class="lc-row"><span>Aujourd'hui</span><b>${minutesLabel(live.today_minutes)} · ${plural(live.today_plays, "écoute")}</b></div>
        <div class="lc-row"><span>Last.fm</span><b>${live.lastfm.connected ? (live.lastfm.enabled ? `Scrobbling actif${live.lastfm.scrobbled_at ? ` · dernier ${since(live.lastfm.scrobbled_at)}` : ""}` : "Scrobbling coupé (réglages)") : "Non connecté"}</b></div>
        ${live.lastfm.error ? `<div class="lc-row bad"><span>Erreur Last.fm</span><b>${esc(live.lastfm.error)}</b></div>` : ""}
        <button class="btn ghost" data-import-history>${icons.download} Importer mon historique Last.fm</button>
        <p class="muted" id="import-status"></p>
      </div></section>` : ""}`);
}

const shelfInner = (items, kind = "") => `<div class="shelf ${kind}">${items.join("")}</div>`;

function bindStatsControls() {
  $$("[data-period]").forEach((b) => (b.onclick = () => {
    statsView.period = b.dataset.period; statsView.offset = 0; store.set("sona.statsPeriod", statsView.period); route();
  }));
  $$("[data-offset]").forEach((b) => (b.onclick = () => { statsView.offset = Math.min(0, statsView.offset + Number(b.dataset.offset)); route(); }));
}

async function importLastfmHistory() {
  const line = $("#import-status");
  try {
    let st = await api("/stats/import/lastfm", { method: "POST" });
    while (st.running && $("#import-status")) {
      $("#import-status").textContent = `Import en cours… ${plural(st.imported, "écoute")} ajoutée${st.imported > 1 ? "s" : ""}`;
      await new Promise((r) => setTimeout(r, 2000));
      st = await api("/stats/import/lastfm");
    }
    if ($("#import-status")) $("#import-status").textContent = st.error ? st.error : `Import terminé : ${plural(st.imported, "écoute")} ajoutée${st.imported > 1 ? "s" : ""}.`;
  } catch (e) { if (line) line.textContent = e.message; }
}

async function viewRecent() {
  $("#content").innerHTML = skeleton("Écoutes récentes");
  const plays = await api("/plays/recent?limit=200");
  const groups = [];
  for (const p of plays) {
    const day = new Date(p.played_at).toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" });
    if (groups.at(-1)?.day !== day) groups.push({ day, plays: [] });
    groups.at(-1).plays.push(p);
  }
  return page(`<h1 class="page-title">Écoutes récentes</h1><p class="page-sub">Tout ce que tu as écouté, ici et dans l'app.</p>
    ${groups.map((g) => `<section class="section"><div class="section-head"><h2>${esc(g.day[0].toUpperCase() + g.day.slice(1))}</h2></div>
      ${trackTable(g.plays.filter((p) => p.source && p.source_id), "Écoutes récentes", { numbers: false })}</section>`).join("") || empty("🎧", "Pas encore d'écoute", "Lance un titre : il apparaîtra ici.")}`);
}

// ── Récap en story (façon Wrapped) ───────────────────────────────────────

async function openRecap(period, offset) {
  let r;
  try { r = await api(`/stats/recap?period=${period}&offset=${offset}&tz=${encodeURIComponent(tz())}`); }
  catch (e) { return toast(e.message); }
  if (!r.plays) return toast("Pas d'écoute sur cette période.");
  const what = { week: "ta semaine", month: "ton mois", year: "ton année" }[period];
  const art = r.top_artists[0];
  const slides = [
    `<div class="eyebrow">Récap</div><h2>${esc(r.label)}</h2><p>Voici ${what} en musique.</p>`,
    `<div class="eyebrow">Temps d'écoute</div><div class="huge">${minutesLabel(r.minutes)}</div><p>${plural(r.plays, "écoute")}, ${plural(r.artists, "artiste")}, ${plural(r.tracks, "titre")}.</p>
      ${r.previous_minutes ? `<p class="muted">${r.minutes >= r.previous_minutes ? "Plus" : "Moins"} que la période d'avant (${minutesLabel(r.previous_minutes)}).</p>` : ""}`,
    art && `<div class="eyebrow">Ton artiste n°1</div><img class="rc-art round" src="${esc(art.picture_url || art.cover_url || "")}" alt=""><h2>${esc(art.name)}</h2><p>${plural(art.plays, "écoute")} · ${minutesLabel(art.minutes)}</p>`,
    r.top_artists.length > 1 && `<div class="eyebrow">Tes artistes</div><ol class="rc-list">${r.top_artists.map((a) => `<li><img class="round" src="${esc(a.picture_url || a.cover_url || "")}" alt=""><span>${esc(a.name)}</span></li>`).join("")}</ol>`,
    r.top_tracks.length && `<div class="eyebrow">Tes titres</div><ol class="rc-list">${r.top_tracks.map((t) => `<li><img src="${esc(big(t.cover_url, 120) || "")}" alt=""><span>${esc(t.name)}<small>${esc(t.subtitle || "")}</small></span></li>`).join("")}</ol>
      ${r.favourite_track ? `<button class="btn" data-rc-play>${icons.play} Écouter ton titre préféré</button>` : ""}`,
    r.personality && `<div class="eyebrow">Ta personnalité d'écoute</div><div class="huge">${esc(r.personality.emoji)}</div><h2>${esc(r.personality.title)}</h2><p>${esc(r.personality.description)}</p>`,
    r.biggest_day && `<div class="eyebrow">Ton plus gros jour</div><h2>${esc(r.biggest_day.label)}</h2><p>${minutesLabel(r.biggest_day.minutes)} de musique ce jour-là.</p>`,
    r.discovered_count && `<div class="eyebrow">Découvertes</div><div class="huge">${r.discovered_count}</div><p>nouveaux artistes, dont ${r.discoveries.slice(0, 3).map((d) => esc(d.name)).join(", ")}.</p>`,
    r.friends_rank && `<div class="eyebrow">Parmi tes amis</div><div class="huge">${r.friends_rank.rank === 1 ? "🥇" : `${r.friends_rank.rank}e`}</div><p>sur ${r.friends_rank.total} au temps d'écoute.</p>`,
    `<div class="eyebrow">C'est tout pour ${what}</div><h2>À la prochaine 👋</h2>${r.first_track ? `<p class="muted">Ton premier son : ${esc(r.first_track.title)} — ${esc(r.first_track.artist)}</p>` : ""}`,
  ].filter(Boolean);
  const cover = r.top_artists[0]?.picture_url || r.top_tracks[0]?.cover_url || "";
  const el = document.createElement("div");
  el.className = "recap";
  el.innerHTML = `<div class="recap-bg"><img src="${esc(cover)}" alt=""></div>
    <div class="recap-bars">${slides.map(() => "<i><b></b></i>").join("")}</div>
    <button class="recap-close" aria-label="Fermer">${icons.close}</button>
    <div class="recap-slide"></div><div class="recap-tap left"></div><div class="recap-tap right"></div>`;
  document.body.append(el);
  let i = 0, timer = null;
  const show = (n) => {
    i = n;
    if (i >= slides.length) return close();
    if (i < 0) i = 0;
    const slide = $(".recap-slide", el);
    slide.innerHTML = slides[i];
    slide.classList.remove("in"); void slide.offsetWidth; slide.classList.add("in");
    $$(".recap-bars i", el).forEach((b, k) => b.className = k < i ? "done" : k === i ? "now" : "");
    $("[data-rc-play]", el)?.addEventListener("click", (e) => { e.stopPropagation(); playTrackFrom(r.favourite_track); });
    clearTimeout(timer);
    timer = setTimeout(() => show(i + 1), 6500);
  };
  const close = () => { clearTimeout(timer); el.classList.add("out"); setTimeout(() => el.remove(), 300); document.removeEventListener("keydown", onKey); };
  const onKey = (e) => { if (e.key === "Escape") close(); if (e.key === "ArrowRight") show(i + 1); if (e.key === "ArrowLeft") show(i - 1); };
  document.addEventListener("keydown", onKey);
  $(".recap-close", el).onclick = close;
  $(".recap-tap.left", el).onclick = () => show(i - 1);
  $(".recap-tap.right", el).onclick = () => show(i + 1);
  show(0);
}

// ── Concerts ─────────────────────────────────────────────────────────────

async function viewConcerts() {
  $("#content").innerHTML = skeleton("Concerts");
  const events = await api("/concerts");
  const months = [];
  for (const e of events) {
    const d = new Date(e.datetime);
    const label = d.toLocaleDateString("fr-FR", { month: "long", year: "numeric" });
    if (months.at(-1)?.label !== label) months.push({ label, events: [] });
    months.at(-1).events.push(e);
  }
  return page(`<h1 class="page-title">Concerts</h1><p class="page-sub">Les dates à venir des artistes que tu écoutes le plus.</p>
    ${months.map((m) => `<section class="section"><div class="section-head"><h2>${esc(m.label[0].toUpperCase() + m.label.slice(1))}</h2></div>
      <div class="concerts">${m.events.map((e) => {
        const d = new Date(e.datetime);
        return `<a class="concert" ${e.url ? `href="${esc(e.url)}" target="_blank" rel="noopener"` : ""}>
          <span class="date"><b>${d.getDate()}</b><small>${d.toLocaleDateString("fr-FR", { month: "short" })}</small></span>
          ${e.artist_picture_url ? `<img class="round" src="${esc(e.artist_picture_url)}" alt="">` : ""}
          <span class="ct"><span class="t">${esc(e.artist)}</span><span class="s">${esc([e.venue, e.city, e.country].filter(Boolean).join(" · "))}</span></span>
          ${e.url ? `<span class="go">Billets</span>` : ""}</a>`;
      }).join("")}</div></section>`).join("") || empty("🎟️", "Aucun concert annoncé", "Rien de prévu pour tes artistes préférés pour l'instant.")}`);
}

// ── Blind test ───────────────────────────────────────────────────────────
// Mêmes règles que l'app : 15 s par question, 100 points + 10 par seconde
// restante, +50 à partir de 3 bonnes réponses d'affilée ; mode expert : 5 s
// d'écoute seulement, points ×1,5. « Paroles » : le titre complet joue
// jusqu'à la ligne à compléter.

const BT_SECONDS = 15;
const bt = {
  mode: "solo", ref: null, label: "", guess: store.get("sona.btGuess") || "title", count: 10, expert: false,
  round: null, index: 0, score: 0, correct: 0, streak: 0, picked: null, gain: 0, phase: "menu",
  audio: null, timer: null, cut: null, remaining: BT_SECONDS, resume: false, pending: null, listening: false,
};

const BT_MODES = {
  daily: "Défi du jour", solo: "Tes titres", chart: "Top du moment", radio: "Radio", artist: "Artiste", playlist: "Playlist",
};

async function viewBlindTest() {
  onLeave(btStop);
  if (bt.pending) { const p = bt.pending; bt.pending = null; Object.assign(bt, p); setTimeout(() => btStart(p.mode, p.ref, p.label)); }
  bt.phase = "menu";
  const [board, rooms] = await Promise.all([api("/blindtest/leaderboard?mode=daily").catch(() => []), api("/blindlive/active").catch(() => [])]);
  setTimeout(bindBlindMenu);
  return page(`<h1 class="page-title">Blind test</h1><p class="page-sub">Reconnais les titres le plus vite possible.</p>
    <div id="bt-root">
      <button class="bt-daily" data-bt="daily"><span class="eyebrow">${icons.trophy} Défi du jour</span><span class="t">10 titres, les mêmes pour tout le monde</span><span class="s">Seule ta première partie compte pour le classement.</span></button>
      <section class="section"><div class="section-head"><h2>En direct entre amis</h2></div>
        <div class="pill-row"><button class="btn" data-live-create>${icons.plus} Créer</button><button class="btn ghost" data-live-join>Rejoindre</button></div>
        ${rooms.filter((r) => r.phase !== "finished").map((r) => `<a class="live-pill violet" href="#/live/${esc(r.code)}">${icons.wave} ${r.joined ? "Ta partie" : `Partie de <b>${esc(r.host_name || "un ami")}</b>`} · ${plural(r.players, "joueur")} — ${r.joined ? "reprendre" : "rejoindre"}</a>`).join("")}
      </section>
      <section class="section"><div class="section-head"><h2>Partie solo</h2></div>
        <div class="bt-options">
          <div class="opt-label">Il faut deviner</div>
          <div class="segmented small">${[["title", "Le titre"], ["artist", "L'artiste"], ["lyrics", "Les paroles"]].map(([k, l]) => `<button data-guess="${k}" class="${bt.guess === k ? "on" : ""}">${l}</button>`).join("")}</div>
          <div class="opt-label">Questions</div>
          <div class="segmented small">${[5, 10, 15, 20].map((n) => `<button data-count="${n}" class="${bt.count === n ? "on" : ""}">${n}</button>`).join("")}</div>
          <label class="switch-row"><span><b>Mode expert</b><small>5 s d'écoute seulement · points ×1,5</small></span><input type="checkbox" data-expert ${bt.expert ? "checked" : ""}><i></i></label>
        </div>
        <div class="tiles">
          ${tile({ icon: icons.note, title: "Tes titres", subtitle: "Ce que toi et tes amis écoutez", tone: "violet", data: 'data-bt="solo"' })}
          ${tile({ icon: icons.stats, title: "Top du moment", subtitle: "Les hits Deezer", tone: "orange", data: 'data-bt="chart"' })}
          ${tile({ icon: icons.radio, title: "Une radio", subtitle: "Rap, années 80, électro…", tone: "blue", data: 'data-bt="radio"' })}
          ${tile({ icon: icons.user, title: "Un artiste", subtitle: "Ses titres et ceux d'artistes proches", tone: "green", data: 'data-bt="artist"' })}
          ${tile({ icon: icons.list, title: "Une playlist", subtitle: "Une de tes playlists", tone: "pink", data: 'data-bt="playlist"' })}
        </div>
      </section>
      ${board.length ? `<section class="section"><div class="section-head"><h2>Classement du jour</h2></div>${leaderboard(board)}</section>` : ""}
    </div>`);
}

const leaderboard = (rows) => `<div class="board">${rows.map((r, i) => `<div class="board-row ${r.is_me ? "me" : ""}">
  <span class="rk">${i < 3 ? ["🥇", "🥈", "🥉"][i] : i + 1}</span>${avatar(r.avatar_url, r.name)}<span class="n">${esc(r.name)}</span>
  <span class="sc">${r.score}<small>${r.correct}/${r.total}</small></span></div>`).join("")}</div>`;

function bindBlindMenu() {
  $$("[data-guess]").forEach((b) => (b.onclick = () => { bt.guess = b.dataset.guess; store.set("sona.btGuess", bt.guess); $$("[data-guess]").forEach((x) => x.classList.toggle("on", x === b)); }));
  $$("[data-count]").forEach((b) => (b.onclick = () => { bt.count = +b.dataset.count; $$("[data-count]").forEach((x) => x.classList.toggle("on", x === b)); }));
  $("[data-expert]")?.addEventListener("change", (e) => { bt.expert = e.target.checked; });
  $("[data-live-create]")?.addEventListener("click", async () => {
    try { const room = await api("/blindlive", { method: "POST" }); go(`#/live/${room.code}`); } catch (e) { toast(e.message); }
  });
  $("[data-live-join]")?.addEventListener("click", async () => {
    const code = await askText({ title: "Rejoindre une partie", placeholder: "Code de la partie", confirm: "Rejoindre" });
    if (code) go(`#/live/${code.toUpperCase().replace(/\s/g, "")}`);
  });
  $$("[data-bt]").forEach((b) => (b.onclick = (e) => { e.preventDefault(); pickBlindSource(b.dataset.bt); }));
}

/** Thème d'une partie (radio, artiste, playlist) : `then(ref, label)`. */
async function pickSource(mode, then) {
  if (mode === "radio") {
    const groups = await radioGroups();
    actionSheet("Quelle radio ?", groups.flatMap((g) => g.radios).map((r) => ({ icon: icons.radio, label: r.title, run: () => then(r.id, r.title) })));
  } else if (mode === "artist") {
    const q = await askText({ title: "Quel artiste ?", placeholder: "Nom de l'artiste", confirm: "Chercher" });
    if (!q) return;
    const found = await api(`/search/artists?q=${encodeURIComponent(q)}&limit=8`).catch(() => []);
    if (!found.length) return toast("Aucun artiste trouvé");
    actionSheet("Lequel ?", found.map((a) => ({ icon: `<img class="mi-thumb round" src="${esc(a.picture_url || "")}" alt="">`, label: a.name, run: () => then(a.source_id, a.name) })));
  } else if (mode === "playlist") {
    const lists = await api("/me/playlists").catch(() => []);
    if (!lists.length) return toast("Aucune playlist");
    actionSheet("Quelle playlist ?", lists.map((p) => ({ icon: icons.list, label: p.name, sub: plural(p.track_count, "titre"), run: () => then(String(p.id), p.name) })));
  } else then(null, BT_MODES[mode]);
}

function pickBlindSource(mode) {
  pickSource(mode, (ref, label) => btStart(mode, ref, label));
}

async function btStart(mode, ref, label) {
  const root = $("#bt-root");
  if (!root) return;
  const daily = mode === "daily";
  Object.assign(bt, { mode, ref, label });
  const guess = daily ? "title" : bt.guess;
  root.innerHTML = `<div class="loading-row"><span class="spinner"></span><span class="muted">Préparation de la partie…</span></div>`;
  let round;
  try {
    const q = new URLSearchParams({ mode, count: daily ? 10 : bt.count, guess });
    if (ref) q.set("ref", ref);
    round = await api(`/blindtest/round?${q}`);
  } catch (e) { toast(e.message); return route(); }
  if (!$("#bt-root")) return;
  if ((round.questions || []).length < 3) {
    toast(guess === "lyrics" ? "Pas assez de titres avec paroles synchronisées pour ce thème." : "Pas assez de titres avec extrait pour ce thème.");
    return route();
  }
  if (round.questions[0].kind === "lyrics") {
    for (const q of round.questions) api(`/stream/${encodeURIComponent(q.track.source)}/${encodeURIComponent(q.track.source_id)}/prepare`, { method: "POST" }).catch(() => {});
  }
  Object.assign(bt, { round, index: 0, score: 0, correct: 0, streak: 0, phase: "playing", guessNow: round.guess || guess, expertNow: !daily && bt.expert });
  bt.resume = !audio.paused;
  audio.pause();
  btAsk();
}

function btAsk() {
  const q = bt.round.questions[bt.index];
  if (!q) return btFinish();
  bt.picked = null;
  bt.gain = 0;
  bt.remaining = BT_SECONDS;
  clearInterval(bt.timer); clearTimeout(bt.cut);
  bt.audio?.pause();
  bt.audio = new Audio();
  if (q.kind === "lyrics") {
    bt.listening = true;
    bt.audio.src = `${BASE}/stream/${encodeURIComponent(q.track.source)}/${encodeURIComponent(q.track.source_id)}?token=${encodeURIComponent(token)}`;
    bt.audio.addEventListener("loadedmetadata", () => { bt.audio.currentTime = Math.max(0, q.clip_start || 0); bt.audio.play().catch(() => {}); }, { once: true });
    const started = Date.now();
    const watch = setInterval(() => {
      if (!bt.audio || bt.picked !== null) return clearInterval(watch);
      if (bt.audio.currentTime >= (q.line_time || 0) - 0.05 || Date.now() - started > 25000) {
        clearInterval(watch);
        bt.audio.pause();
        bt.listening = false;
        btStartTimer();
        btRender();
      }
    }, 80);
    bt.cut = watch;
  } else {
    bt.listening = false;
    bt.audio.src = q.preview_url;
    bt.audio.addEventListener("loadedmetadata", () => { try { bt.audio.currentTime = Math.random() * 8; } catch {} }, { once: true });
    bt.audio.play().catch(() => toast("Touche l'écran pour lancer l'extrait"));
    if (bt.expertNow) bt.cut = setTimeout(() => bt.audio?.pause(), 5000);
    btStartTimer();
  }
  btRender();
}

function btStartTimer() {
  clearInterval(bt.timer);
  const start = Date.now();
  bt.timer = setInterval(() => {
    bt.remaining = Math.max(0, BT_SECONDS - (Date.now() - start) / 1000);
    const meter = $("#bt-time");
    if (meter) meter.style.width = `${(bt.remaining / BT_SECONDS) * 100}%`;
    if (bt.remaining <= 0) btAnswer(-1);
  }, 100);
}

function btAnswer(choice) {
  const q = bt.round?.questions[bt.index];
  if (!q || bt.picked !== null || bt.listening) return;
  clearInterval(bt.timer);
  bt.picked = choice;
  if (choice === q.answer) {
    bt.correct++; bt.streak++;
    const base = 100 + Math.floor(bt.remaining * 10) + (bt.streak >= 3 ? 50 : 0);
    bt.gain = bt.expertNow ? Math.floor((base * 3) / 2) : base;
    bt.score += bt.gain;
    haptic();
  } else bt.streak = 0;
  let pause = 1600;
  if (q.kind === "lyrics" && q.line_time != null && bt.audio) {
    clearInterval(bt.cut);
    bt.audio.currentTime = Math.max(0, q.line_time - 0.3);
    bt.audio.play().catch(() => {});
    pause = Math.min(6, Math.max(2.5, (q.reveal_end ?? q.line_time + 3) - q.line_time + 0.6)) * 1000;
  }
  btRender();
  setTimeout(() => { if (bt.phase !== "playing" || !$("#bt-root")) return; bt.index++; bt.index < bt.round.questions.length ? btAsk() : btFinish(); }, pause);
}

function btRender() {
  const root = $("#bt-root");
  if (!root || !bt.round) return;
  const q = bt.round.questions[bt.index];
  const reveal = bt.picked !== null;
  const prompt = q.kind === "lyrics" ? "Complète les paroles" : bt.guessNow === "artist" ? "Quel artiste ?" : "Quel titre ?";
  root.innerHTML = `<div class="bt-game">
    <div class="bt-top"><span>${bt.index + 1} / ${bt.round.questions.length}</span><b>${bt.score} pts</b>${bt.streak >= 3 ? `<span class="streak">🔥 ${bt.streak}</span>` : ""}<button class="tbtn small" data-bt-quit aria-label="Quitter">${icons.close}</button></div>
    <div class="meter big"><i id="bt-time" style="width:${(bt.remaining / BT_SECONDS) * 100}%"></i></div>
    <div class="bt-cover ${reveal ? "reveal" : ""}">${reveal ? `<img src="${esc(big(q.track.cover_url || q.cover_url, 500))}" alt="">` : `<span class="bt-wave ${bt.listening ? "listen" : ""}">${icons.wave}</span>`}</div>
    <h2 class="bt-q">${esc(prompt)}</h2>
    ${q.kind === "lyrics" ? `<div class="bt-lyrics">${(q.before || []).map((l) => `<p class="before">${esc(l)}</p>`).join("")}<p>${esc(q.prompt || "")}</p></div>` : ""}
    ${bt.listening ? `<p class="muted center">Écoute bien…</p>` : ""}
    <div class="bt-choices">${q.choices.map((c, i) => {
      const cls = reveal ? (i === q.answer ? "right" : i === bt.picked ? "wrong" : "dim") : "";
      return `<button class="bt-choice ${cls}" data-choice="${i}" ${reveal || bt.listening ? "disabled" : ""}><b>${esc(c.title || c.artist)}</b>${c.title && c.artist && bt.guessNow !== "artist" && q.kind !== "lyrics" ? `<small>${esc(c.artist)}</small>` : ""}</button>`;
    }).join("")}</div>
    ${reveal ? `<p class="bt-feedback ${bt.picked === q.answer ? "ok" : "ko"}">${bt.picked === q.answer ? `+${bt.gain} points` : bt.picked === -1 ? "Temps écoulé" : "Raté"} · ${esc(q.track.title)} — ${esc(q.track.artist)}</p>` : ""}
  </div>`;
  $$("[data-choice]", root).forEach((b) => (b.onclick = () => btAnswer(+b.dataset.choice)));
  $("[data-bt-quit]", root).onclick = () => { btStop(); route(); };
}

async function btFinish() {
  bt.phase = "finished";
  const total = bt.round.questions.length;
  const tracks = bt.round.questions.map((q) => q.track);
  btStop();
  api("/blindtest/score", { method: "POST", body: JSON.stringify({ mode: bt.mode, score: bt.score, correct: bt.correct, total }) }).catch(() => {});
  const board = await api(`/blindtest/leaderboard?mode=${bt.mode === "daily" ? "daily" : "daily"}`).catch(() => []);
  const root = $("#bt-root");
  if (!root) return;
  root.innerHTML = `<div class="bt-end">
    <div class="eyebrow">${esc(BT_MODES[bt.mode] || "")}${bt.label && bt.label !== BT_MODES[bt.mode] ? ` · ${esc(bt.label)}` : ""}</div>
    <div class="huge">${bt.score} points</div><p>${bt.correct} bonne${bt.correct > 1 ? "s" : ""} réponse${bt.correct > 1 ? "s" : ""} sur ${total}</p>
    <div class="pill-row center"><button class="btn" data-again>Rejouer</button><button class="btn ghost" data-menu>Autre thème</button></div>
    ${board.length ? `<section class="section"><div class="section-head"><h2>Classement du jour</h2></div>${leaderboard(board)}</section>` : ""}
    <section class="section"><div class="section-head"><h2>Les titres de la partie</h2></div>${trackTable(tracks, "Blind test", { numbers: false })}</section></div>`;
  bindPage(root);
  $("[data-again]", root).onclick = () => btStart(bt.mode === "daily" ? "solo" : bt.mode, bt.ref, bt.label);
  $("[data-menu]", root).onclick = () => route();
}

function btStop() {
  clearInterval(bt.timer); clearTimeout(bt.cut); clearInterval(bt.cut);
  bt.audio?.pause();
  bt.audio = null;
  if (bt.phase === "playing") bt.phase = "menu";
  if (bt.resume) { bt.resume = false; audio.play().catch(() => {}); }
}

// ── Blind test en direct ─────────────────────────────────────────────────

const live = { code: null, state: null, offset: 0, timer: null, audio: null, playedIndex: -1 };

async function viewLive(code) {
  code = (code || "").toUpperCase();
  try {
    live.state = await api(`/blindlive/${encodeURIComponent(code)}/join`, { method: "POST" });
  } catch (e) { return page(empty("🎲", "Partie introuvable", e.message)); }
  live.code = code;
  live.playedIndex = -1;
  live.resume = !audio.paused;
  audio.pause();
  live.timer = setInterval(liveTick, 1000);
  onLeave(() => {
    clearInterval(live.timer);
    live.audio?.pause(); live.audio = null;
    if (live.resume) { live.resume = false; audio.play().catch(() => {}); }
    const leaving = live.code;
    live.code = null;
    api(`/blindlive/${encodeURIComponent(leaving)}/leave`, { method: "POST" }).catch(() => {});
  });
  setTimeout(liveRender);
  return page(`<h1 class="page-title">Blind test en direct</h1><div id="live-root"></div>`);
}

async function liveTick() {
  if (!live.code) return;
  try {
    const fresh = await api(`/blindlive/${encodeURIComponent(live.code)}`);
    live.offset = fresh.server_time - Date.now() / 1000;
    const changed = fresh.version !== live.state?.version || fresh.phase !== live.state?.phase;
    live.state = fresh;
    if (changed) liveRender(); else liveClock();
  } catch (e) {
    clearInterval(live.timer);
    const root = $("#live-root");
    if (root) root.innerHTML = empty("👋", "La partie est terminée", e.message);
  }
}

const liveNow = () => Date.now() / 1000 + live.offset;

function liveClock() {
  const s = live.state;
  const el = $("#live-clock");
  if (!el || !s) return;
  if (s.phase === "question") {
    const now = liveNow();
    if (now < s.starts_at) el.textContent = `Ça commence dans ${Math.ceil(s.starts_at - now)} s…`;
    else el.textContent = `${Math.max(0, Math.ceil(s.deadline - now))} s`;
    const meter = $("#live-time");
    if (meter) meter.style.width = `${Math.max(0, Math.min(100, ((s.deadline - now) / (s.deadline - s.starts_at)) * 100))}%`;
  } else if (s.phase === "reveal" && s.next_at) {
    el.textContent = `Question suivante dans ${Math.max(0, Math.ceil(s.next_at - liveNow()))} s`;
  }
}

function livePlay(q) {
  if (live.playedIndex === q.index) return;
  live.playedIndex = q.index;
  live.audio?.pause();
  const a = new Audio();
  live.audio = a;
  const startIn = Math.max(0, (live.state.starts_at - liveNow()) * 1000);
  if (q.kind === "lyrics" && q.stream) {
    a.src = `${BASE}/stream/${encodeURIComponent(q.stream.source)}/${encodeURIComponent(q.stream.source_id)}?token=${encodeURIComponent(token)}`;
    a.addEventListener("loadedmetadata", () => { a.currentTime = q.clip_start || 0; }, { once: true });
    const stopAt = setInterval(() => { if (a !== live.audio) return clearInterval(stopAt); if (a.currentTime >= (q.line_time || 0) - 0.05 && !a.paused && live.state.phase === "question") { a.pause(); clearInterval(stopAt); } }, 80);
  } else {
    a.src = q.preview_url;
  }
  setTimeout(() => { if (a === live.audio) a.play().catch(() => toast("Touche l'écran pour entendre l'extrait")); }, startIn);
}

function liveRender() {
  const root = $("#live-root");
  const s = live.state;
  if (!root || !s) return;
  const players = `<div class="board">${s.players.map((p, i) => `<div class="board-row ${p.is_me ? "me" : ""}">
    <span class="rk">${s.phase === "lobby" ? "" : i + 1}</span>${avatar(p.avatar_url, p.name)}<span class="n">${esc(p.name)}${p.is_host ? " 👑" : ""}</span>
    <span class="sc">${s.phase === "lobby" ? "" : p.score}${p.gained != null ? `<small class="${p.was_right ? "ok" : "ko"}">${p.was_right ? `+${p.gained}` : "✗"}</small>` : p.answered && s.phase === "question" ? "<small>✓</small>" : ""}</span></div>`).join("")}</div>`;
  if (s.phase === "lobby") {
    root.innerHTML = `<div class="live-code"><span class="muted">Code de la partie</span><b>${esc(s.code)}</b>
        <button class="btn ghost small" data-live-share>${icons.share} Inviter</button></div>
      <div class="lobby-config"><div class="muted">Thème</div><b>${esc(s.label || BT_MODES[s.mode] || s.mode)}</b> · ${esc({ title: "le titre", artist: "l'artiste", lyrics: "les paroles" }[s.guess] || "")} · ${s.count} questions</div>
      ${s.is_host ? `<div class="pill-row"><button class="btn ghost" data-live-config>Changer le thème</button><button class="btn" data-live-start ${s.players.length < 1 ? "disabled" : ""}>${icons.play} Lancer la partie</button></div>`
        : `<p class="muted">En attente de ${esc(s.host_name || "l'hôte")}…</p>`}
      <section class="section"><div class="section-head"><h2>Joueurs</h2></div>${players}</section>`;
  } else if (s.phase === "question" || s.phase === "reveal") {
    const q = s.question;
    if (s.phase === "question") livePlay(q);
    const reveal = s.phase === "reveal";
    root.innerHTML = `<div class="bt-game">
      <div class="bt-top"><span>${q.index + 1} / ${s.total}</span><b id="live-clock"></b></div>
      <div class="meter big"><i id="live-time"></i></div>
      <div class="bt-cover ${reveal ? "reveal" : ""}">${reveal && q.cover_url ? `<img src="${esc(big(q.cover_url, 500))}" alt="">` : `<span class="bt-wave listen">${icons.wave}</span>`}</div>
      ${q.kind === "lyrics" ? `<div class="bt-lyrics">${(q.before || []).map((l) => `<p class="before">${esc(l)}</p>`).join("")}<p>${esc(q.prompt || "")}</p></div>` : ""}
      <div class="bt-choices">${q.choices.map((c, i) => {
        const cls = reveal ? (i === q.answer ? "right" : i === q.my_choice ? "wrong" : "dim") : i === q.my_choice ? "picked" : "";
        return `<button class="bt-choice ${cls}" data-live-choice="${i}" ${reveal || q.my_choice != null ? "disabled" : ""}><b>${esc(c.title || c.artist)}</b>${c.title && c.artist && s.guess !== "artist" && q.kind !== "lyrics" ? `<small>${esc(c.artist)}</small>` : ""}</button>`;
      }).join("")}</div>
      ${reveal && q.track ? `<p class="bt-feedback ${q.my_choice === q.answer ? "ok" : "ko"}">${esc(q.track.title)} — ${esc(q.track.artist)}</p>` : ""}
      <section class="section">${players}</section></div>`;
    $$("[data-live-choice]", root).forEach((b) => (b.onclick = async () => {
      haptic();
      try { live.state = await api(`/blindlive/${encodeURIComponent(s.code)}/answer`, { method: "POST", body: JSON.stringify({ index: q.index, choice: +b.dataset.liveChoice }) }); liveRender(); }
      catch (e) { toast(e.message); }
    }));
    liveClock();
  } else {
    live.audio?.pause();
    const winner = s.players[0];
    root.innerHTML = `<div class="bt-end"><div class="huge">🏆</div><h2>${esc(winner?.name || "")} gagne !</h2>
      ${s.is_host ? `<div class="pill-row center"><button class="btn" data-live-start>Revanche</button><button class="btn ghost" data-live-config>Autre thème</button></div>` : `<p class="muted">L'hôte peut lancer une revanche.</p>`}
      <section class="section">${players}</section>
      ${s.tracks.length ? `<section class="section"><div class="section-head"><h2>Les titres de la partie</h2></div>${trackTable(s.tracks, "Blind test en direct", { numbers: false })}</section>` : ""}</div>`;
    bindPage(root);
  }
  $("[data-live-share]", root)?.addEventListener("click", () => {
    const text = `Rejoins mon blind test Sona ! Code : ${s.code}`;
    navigator.share ? navigator.share({ text }).catch(() => {}) : navigator.clipboard?.writeText(s.code).then(() => toast("Code copié"));
  });
  $("[data-live-start]", root)?.addEventListener("click", async (e) => {
    e.target.disabled = true;
    try { live.playedIndex = -1; live.state = await api(`/blindlive/${encodeURIComponent(s.code)}/start`, { method: "POST" }); liveRender(); }
    catch (err) { toast(err.message); e.target.disabled = false; }
  });
  $("[data-live-config]", root)?.addEventListener("click", () => actionSheet("Thème de la partie", Object.entries(BT_MODES).filter(([k]) => k !== "daily").map(([mode, label]) => ({
    icon: icons.wave, label, run: () => pickSource(mode, (ref, refLabel) => actionSheet("Il faut deviner…", [["title", "Le titre"], ["artist", "L'artiste"], ["lyrics", "Les paroles"]].map(([guess, gl]) => ({
      label: gl, run: async () => {
        live.state = await api(`/blindlive/${encodeURIComponent(s.code)}/config`, { method: "POST", body: JSON.stringify({ mode, ref, label: refLabel, count: s.count || 10, guess }) });
        liveRender();
      },
    })))),
  }))));
}

// ── Écoute ensemble ──────────────────────────────────────────────────────
// Comme l'app : l'hôte envoie ce qu'il joue, les invités calent leur lecteur
// dessus (même titre, à ~1,5 s près, même pause) ; les propositions votées
// passent dans la file de l'hôte. Ici en plus : synchro instantanée (le
// serveur répond dès que la session change), discussion, vote pour passer le
// titre, contrôle partagé, titres déjà joués, passage de la main, retour
// automatique dans la session après un rechargement de la page.

const party = {
  state: null, gen: 0, fetchedAt: 0, rtt: 0, sent: null, takenDuring: null, skippedFor: null,
  lastReaction: 0, lastMessage: 0, lastCommand: 0, ownReactions: 0, localPause: false,
  tab: "queue", unread: 0, timer: null, renderedVersion: null,
};
const PARTY_EMOJIS = ["🔥", "❤️", "😂", "🙌", "💃", "🎉"];
const partyGuest = () => !!party.state && !party.state.is_host;
const partyPath = (suffix = "") => `/party/${encodeURIComponent(party.state.code)}${suffix}`;

// Lecture lancée sans geste de l'utilisateur (suivre l'hôte) : sur iPhone,
// le lecteur doit d'abord avoir joué une fois pendant un appui.
const SILENCE = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA=";
let audioUnlocked = false;
audio.addEventListener("play", () => { audioUnlocked = true; });
function unlockAudio() {
  if (audioUnlocked) return;
  if (!audio.src) { audio.src = SILENCE; audio.play().catch(() => {}); return; }
  if (audio.paused) audio.play().then(() => audio.pause()).catch(() => {});
}
const isSilence = () => audio.src.startsWith("data:");

async function partyEnter(fresh) {
  party.gen++;
  Object.assign(party, {
    state: fresh, sent: null, takenDuring: null, skippedFor: null, localPause: false, unread: 0, renderedVersion: null,
    lastReaction: Math.max(0, ...fresh.reactions.map((r) => r.id)),
    lastMessage: Math.max(0, ...(fresh.messages || []).map((m) => m.id)),
    lastCommand: Math.max(0, ...(fresh.commands || []).map((c) => c.id)),
    fetchedAt: Date.now(),
  });
  store.set("sona.party", fresh.code);
  partyLoop(party.gen);
  clearInterval(party.timer);
  // Chaque seconde : l'invité se recale, l'hôte reprend les propositions
  // (la fin d'un titre arrive sans que la session change).
  party.timer = setInterval(partyClock, 1000);
  if (fresh.is_host) partyPublish(true); else partyFollow();
  renderParty();
}

function partyStop(message) {
  if (!party.state) return;
  party.gen++;
  clearInterval(party.timer);
  party.state = null;
  store.set("sona.party", null);
  if (message) toast(message);
  renderParty();
}

async function partyLeave(silent = false) {
  if (!party.state) return;
  const path = partyPath("/leave");
  partyStop();
  if (!silent) api(path, { method: "POST" }).catch(() => {});
}

/** Relit l'état en continu : le serveur ne répond que quand quelque chose
    change (titre, pause, message…), au plus tard après 20 s. */
async function partyLoop(gen) {
  while (party.state && gen === party.gen) {
    const sent = Date.now();
    try {
      const fresh = await api(partyPath(`?since=${party.state.version}&wait=20`));
      if (gen !== party.gen) return;
      partyHandle(fresh, Date.now() - sent);
    } catch (e) {
      if (gen !== party.gen) return;
      if (e.status === 404) return partyStop("La session d'écoute est terminée.");
      if (e.status === 403) return partyStop("Tu ne fais plus partie de la session.");
      await new Promise((r) => setTimeout(r, 2500));
    }
  }
}

/** Nouvel état reçu (lecture, ou réponse à une action). `rtt` : durée de
    l'aller-retour, pour compenser le trajet de la position. */
function partyHandle(fresh, rtt = 0) {
  if (!party.state || fresh.code !== party.state.code) return;
  const wasHost = party.state.is_host;
  party.state = fresh;
  party.fetchedAt = Date.now();
  // Réponse d'une longue attente : seul le trajet retour compte.
  party.rtt = Math.min(rtt, 1500);
  if (fresh.is_host && !wasHost) { toast("Tu es maintenant l'hôte de la session 👑"); party.sent = null; partyPublish(true); }
  if (!fresh.is_host && wasHost) toast(`${fresh.host_name || "Quelqu'un"} est maintenant l'hôte`);
  for (const r of fresh.reactions.filter((x) => x.id > party.lastReaction)) {
    if (party.ownReactions > 0 && r.by === myName()) { party.ownReactions--; continue; }
    if (r.age < 8) floatReaction(r.emoji, r.by);
  }
  party.lastReaction = Math.max(party.lastReaction, ...fresh.reactions.map((r) => r.id));
  const messages = (fresh.messages || []).filter((m) => m.id > party.lastMessage && !m.mine);
  party.lastMessage = Math.max(party.lastMessage, ...(fresh.messages || []).map((m) => m.id));
  if (messages.length) {
    const onChat = location.hash.startsWith("#/party") && party.tab === "chat";
    if (!onChat) { party.unread += messages.length; const m = messages.at(-1); toast(`💬 ${m.by} : ${m.text.slice(0, 80)}`); }
  }
  if (fresh.is_host) partyHostDuties(); else partyFollow();
  renderParty();
}

const myName = () => account?.display_name || account?.username || "";

function partyClock() {
  if (!party.state) return;
  if (party.state.is_host) { partyPublish(false); partyTakeProposals(); }
  else partyFollow();
  partyTick();
}

// ── Hôte ──

let publishTimer = null;
/** L'hôte a changé quelque chose (titre, pause, saut) : prévenir tout de suite. */
function partyNotify() {
  if (!party.state?.is_host) return;
  clearTimeout(publishTimer);
  publishTimer = setTimeout(() => partyPublish(false), 150);
}
["play", "pause", "seeked"].forEach((ev) => audio.addEventListener(ev, partyNotify));

async function partyPublish(force) {
  const s = party.state;
  if (!s?.is_host || isSilence()) return;
  const t = state.queue[state.index] || null;
  const paused = audio.paused;
  const position = audio.currentTime || 0;
  const id = t ? trackKey(t) : null;
  let changed = force || !party.sent || party.sent.id !== id || party.sent.paused !== paused;
  if (!changed && !paused) changed = Math.abs(party.sent.position + (Date.now() - party.sent.at) / 1000 - position) > 1.5;
  if (!changed) return;
  party.sent = { id, paused, position, at: Date.now() };
  try {
    const fresh = await api(partyPath("/state"), { method: "POST", body: JSON.stringify({ track: t ? cleanTrack(t) : null, position, paused }) });
    partyHandle(fresh);
  } catch { party.sent = null; }
}

/** Commandes des invités (contrôle partagé) et vote pour passer le titre. */
function partyHostDuties() {
  const s = party.state;
  for (const c of (s.commands || []).filter((x) => x.id > party.lastCommand)) {
    party.lastCommand = c.id;
    if (c.action === "pause" && !audio.paused) { audio.pause(); toast(`${c.by} a mis en pause`); }
    else if (c.action === "play" && audio.paused && audio.src) { audio.play().catch(() => {}); toast(`${c.by} a relancé la lecture`); }
    else if (c.action === "next") { toast(`${c.by} a passé le titre`); next(); }
    else if (c.action === "previous") { toast(`${c.by} est revenu au titre précédent`); prev(); }
  }
  const key = s.track ? trackKey(s.track) : null;
  if (key && s.skip && s.skip.votes >= s.skip.needed && party.skippedFor !== key && sameTrack(s.track, state.queue[state.index])) {
    party.skippedFor = key;
    toast("Titre passé à la demande des invités ⏭️");
    next();
  }
  partyTakeProposals();
}

/** La proposition la plus votée passe juste après le titre en cours : tout
    de suite si rien d'autre n'est prévu, sinon dans les 25 dernières
    secondes (le temps que les votes s'accumulent). Une seule par titre. */
let takingProposal = false;
async function partyTakeProposals() {
  const s = party.state;
  const top = s?.queue?.[0];
  const playing = state.queue[state.index];
  if (!s?.is_host || !top || !playing || takingProposal) return;
  const dur = audio.duration && isFinite(audio.duration) ? audio.duration : playing.duration_seconds || 0;
  const endingSoon = dur > 0 && dur - audio.currentTime < 25;
  const nothingNext = state.index >= state.queue.length - 1;
  if (!(nothingNext || (endingSoon && party.takenDuring !== trackKey(playing)))) return;
  takingProposal = true;
  party.takenDuring = trackKey(playing);
  state.queue.splice(state.index + 1, 0, top.track);
  if (state.npOpen && state.npTab === "queue") renderQueue();
  try { partyHandle(await api(partyPath("/queue/consume"), { method: "POST", body: JSON.stringify({ ids: [top.id] }) })); }
  catch {} finally { takingProposal = false; }
}

/** Hôte : jouer une proposition tout de suite. */
async function partyPlayNow(item) {
  state.queue.splice(state.index + 1, 0, item.track);
  next();
  try { partyHandle(await api(partyPath("/queue/consume"), { method: "POST", body: JSON.stringify({ ids: [item.id] }) })); } catch {}
}

// ── Invité ──

/** Position de l'hôte maintenant, d'après le dernier état reçu. */
function partyTarget() {
  const s = party.state;
  if (!s) return 0;
  return s.position + (s.paused ? 0 : (Date.now() - party.fetchedAt + party.rtt / 2) / 1000);
}

function partyFollow() {
  const s = party.state;
  if (!s || s.is_host || !s.track) return;
  const target = partyTarget();
  if (!sameTrack(s.track, state.queue[state.index])) {
    // Nouveau titre de l'hôte : même titre, même seconde.
    state.station = null;
    state.queue = [s.track];
    state.name = "Écoute ensemble";
    playAt(0, { position: target });
    if (s.paused || party.localPause) audio.pause();
    return;
  }
  if (audio.readyState < 2) return;  // encore en chargement
  const dur = audio.duration && isFinite(audio.duration) ? audio.duration : 0;
  if (s.paused || party.localPause) {
    if (!audio.paused) audio.pause();
    if (s.paused && Math.abs(audio.currentTime - target) > 1.5) audio.currentTime = target;
    return;
  }
  // Fin du titre chez soi avant l'hôte : on attend le suivant, sans boucler.
  if (audio.ended || (dur && target >= dur - 0.5)) return;
  if (audio.paused) audio.play().catch(() => {});
  if (Math.abs(audio.currentTime - target) > 1.5) audio.currentTime = target;
}

/** Invité : pause/lecture chez soi seulement (la session continue). */
function partyToggleLocal() {
  party.localPause = !party.localPause;
  if (party.localPause) audio.pause();
  else { unlockAudio(); partyFollow(); toast("De retour en synchro ✓"); }
  renderParty();
}

async function partyCommand(action) {
  try { partyHandle(await api(partyPath("/command"), { method: "POST", body: JSON.stringify({ action }) })); haptic(); }
  catch (e) { toast(e.message); }
}

async function partyPropose(t) {
  if (!party.state) return;
  if (party.state.is_host) return playNext(t);
  try {
    partyHandle(await api(partyPath("/queue"), { method: "POST", body: JSON.stringify({ track: cleanTrack(t) }) }));
    toast("Proposé à la session ✓");
  } catch (e) { toast(e.message); }
}

/** Transport de l'invité (mini-lecteur, lecteur, touches) : rien ne doit le
    désynchroniser. Renvoie vrai si l'action a été prise en charge ici. */
function partyIntercept(action) {
  if (!partyGuest()) return false;
  if (action === "toggle") { partyToggleLocal(); return true; }
  if (party.state.open_controls) { partyCommand(action === "prev" ? "previous" : action); return true; }
  toast("C'est l'hôte qui choisit la musique : propose un titre ou vote pour passer");
  return true;
}

// ── Page ──

async function viewParty(code) {
  if (code && party.state?.code !== code.toUpperCase()) {
    try {
      const fresh = await api(`/party/${encodeURIComponent(code.toUpperCase())}/join`, { method: "POST" });
      if (party.state) partyStop();
      await partyEnter(fresh);
    } catch (e) { toast(e.message); }
  }
  const active = party.state ? [] : await api("/party/active").catch(() => []);
  party.renderedVersion = null;
  onLeave(() => { party.renderedVersion = null; });
  setTimeout(renderParty);
  return page(`<h1 class="page-title">Écoute ensemble</h1><p class="page-sub">Le même son, au même moment, chacun sur son téléphone.</p>
    <div id="party-root" data-active='${esc(JSON.stringify(active))}'></div>`);
}

async function partyJoinAsk() {
  unlockAudio();
  const code = await askText({ title: "Rejoindre une session", placeholder: "Code (5 lettres)", confirm: "Rejoindre" });
  if (code) go(`#/party/${code.toUpperCase().replace(/[^A-Z]/g, "")}`);
}

function renderParty() {
  renderMini();
  const root = $("#party-root");
  if (!root) return;
  const s = party.state;
  if (!s) {
    party.renderedVersion = null;
    const active = JSON.parse(root.dataset.active || "[]").filter((p) => !p.joined);
    root.innerHTML = `<div class="pill-row"><button class="btn" data-party-create>${icons.plus} Lancer</button><button class="btn ghost" data-party-join>Rejoindre</button></div>
      ${active.map((p) => `<button class="live-pill" data-party-code="${esc(p.code)}">${icons.headphones} <b>${esc(p.host_name || "Un ami")}</b> · ${plural(p.members, "personne")}${p.track ? ` · ${esc(p.track.title)}` : ""} — rejoindre</button>`).join("")}
      <div class="party-how">
        <p><b>Toi</b>, tu lances la session et tu choisis la musique : tout le monde l'entend en même temps, chacun sur son téléphone.</p>
        <p><b>Tes amis</b> proposent des titres, votent, discutent, réagissent et peuvent voter pour passer un titre.</p>
        <p>Tu peux leur ouvrir les commandes (pause, suivant) ou passer la main à quelqu'un.</p></div>`;
    $("[data-party-create]", root).onclick = async () => {
      unlockAudio();
      try { await partyEnter(await api("/party", { method: "POST" })); } catch (e) { toast(e.message); }
    };
    $("[data-party-join]", root).onclick = partyJoinAsk;
    $$("[data-party-code]", root).forEach((b) => (b.onclick = () => { unlockAudio(); go(`#/party/${b.dataset.partyCode}`); }));
    return;
  }
  // Pas de nouveau rendu sans changement (le champ de discussion garde son texte).
  const key = `${s.version}|${party.tab}|${party.localPause}|${party.unread}`;
  if (party.renderedVersion === key) return;
  party.renderedVersion = key;
  const draft = $("#party-msg", root)?.value || "";
  const hadFocus = document.activeElement?.id === "party-msg";
  const t = s.track;
  const host = s.is_host;
  const canControl = host || s.open_controls;
  const tabs = [["queue", `Propositions${s.queue.length ? ` (${s.queue.length})` : ""}`], ["chat", `Discussion${party.unread ? ` · ${party.unread}` : ""}`], ["history", "Déjà joués"]];
  root.innerHTML = `<div class="live-code"><span class="muted">${host ? "Ta session" : `Session de ${esc(s.host_name || "un ami")}`}</span><b>${esc(s.code)}</b>
      <div class="pill-row center tight"><button class="btn ghost small" data-party-share>${icons.share} Inviter</button><button class="btn ghost small" data-party-copy>Copier le code</button></div></div>
    ${t ? `<div class="party-now">
        <img src="${esc(big(t.cover_url, 300))}" alt="">
        <div class="pn-text"><span class="eyebrow">${s.paused ? "En pause" : `${bars()} En cours`}</span><b>${esc(t.title)}</b><span class="muted">${esc(t.artist)}</span>
          ${host ? "" : `<span class="pn-sync" id="party-sync"></span>`}</div>
        <div class="pn-progress"><i id="party-progress"></i></div>
        <div class="pn-actions">
          ${canControl ? `<button class="btn ghost small" data-pc="${s.paused ? "play" : "pause"}">${s.paused ? icons.play : icons.pause} ${host ? (s.paused ? "Lecture" : "Pause") : (s.paused ? "Lecture pour tous" : "Pause pour tous")}</button><button class="btn ghost small" data-pc="next">${icons.next} ${host ? "Suivant" : "Suivant pour tous"}</button>` : ""}
          ${host ? "" : `<button class="btn ghost small ${party.localPause ? "on" : ""}" data-local>${party.localPause ? `${icons.play} Reprendre chez moi` : `${icons.pause} Pause chez moi`}</button>`}
          ${host ? "" : `<button class="btn ghost small ${s.skip?.voted ? "on" : ""}" data-skip>⏭️ Passer ${s.skip ? `${s.skip.votes}/${s.skip.needed}` : ""}</button>`}
        </div></div>`
      : `<p class="muted party-wait">${host ? "Lance un titre (recherche, playlist, radio…) : il démarre chez tout le monde." : `En attente du premier titre de ${esc(s.host_name || "l'hôte")}…`}</p>`}
    ${host && s.skip?.votes ? `<p class="muted">⏭️ ${s.skip.votes} vote${s.skip.votes > 1 ? "s" : ""} pour passer (${s.skip.needed} nécessaire${s.skip.needed > 1 ? "s" : ""}).</p>` : ""}
    <div class="emoji-row">${PARTY_EMOJIS.map((e) => `<button data-react="${e}">${e}</button>`).join("")}</div>
    ${host ? `<label class="switch-row card-row"><span><b>Les invités contrôlent la lecture</b><small>Pause, reprise et titre suivant pour tout le monde</small></span><input type="checkbox" data-open ${s.open_controls ? "checked" : ""}><i></i></label>` : ""}
    <div class="segmented party-tabs">${tabs.map(([k, l]) => `<button data-ptab="${k}" class="${party.tab === k ? "on" : ""}">${l}</button>`).join("")}</div>
    <div id="party-tab">${partyTabHtml(s)}</div>
    <section class="section"><div class="section-head"><h2>À l'écoute (${s.members.length})</h2></div>
      <div class="members">${s.members.map((m) => `<button class="member" data-member="${m.id ?? ""}">${avatar(m.avatar_url, m.name)}${esc(m.name)}${m.is_host ? " 👑" : ""}${m.is_me ? " (toi)" : ""}</button>`).join("")}</div>
      ${host && s.members.length > 1 ? `<p class="muted small-note">Touche un ami pour lui passer la main ou le retirer.</p>` : ""}</section>
    <button class="btn ghost danger" data-party-leave>${host ? "Terminer la session" : "Quitter la session"}</button>`;
  bindParty(root, s);
  const input = $("#party-msg", root);
  if (input) { input.value = draft; if (hadFocus) input.focus(); }
  const list = $(".chat-list", root);
  if (list) list.scrollTop = list.scrollHeight;
  partyTick();
}

function partyTabHtml(s) {
  if (party.tab === "chat") {
    party.unread = 0;
    return `<div class="chat-list">${(s.messages || []).map((m) => `<div class="msg ${m.mine ? "mine" : ""}">${m.mine ? "" : avatar(m.avatar_url, m.by)}
        <div class="bubble">${m.mine ? "" : `<b>${esc(m.by)}</b>`}${esc(m.text)}</div></div>`).join("") || `<p class="muted">Pas encore de message. Lance la discussion !</p>`}</div>
      <form class="chat-form"><input class="field" id="party-msg" maxlength="300" placeholder="Écris un message…" autocomplete="off" enterkeyhint="send"><button class="btn" type="submit">Envoyer</button></form>`;
  }
  if (party.tab === "history") {
    return s.history?.length ? trackTable(s.history, "Écoute ensemble", { numbers: false }) : `<p class="muted">Les titres joués pendant la session apparaîtront ici.</p>`;
  }
  return `<button class="btn ghost small" data-party-add>${icons.plus} ${s.is_host ? "Ajouter un titre" : "Proposer un titre"}</button>
    ${s.queue.length ? `<div class="party-queue">${s.queue.map((q) => `<div class="pq"><img src="${esc(big(q.track.cover_url, 120))}" alt=""><span class="pt"><b>${esc(q.track.title)}</b><small>${esc(q.track.artist)} · par ${esc(q.by)}</small></span>
      <span class="pq-acts">${s.is_host ? `<button class="vote" data-playnow="${q.id}" title="Jouer maintenant">${icons.play}</button>` : ""}
        <button class="vote ${q.voted ? "on" : ""}" data-vote="${q.id}">▲ ${q.votes}</button>
        ${s.is_host || q.mine ? `<button class="vote" data-unpropose="${q.id}" title="Retirer">${icons.close}</button>` : ""}</span></div>`).join("")}</div>`
      : `<p class="muted">Aucune proposition. ${s.is_host ? "Tes amis peuvent en faire depuis leur téléphone." : "Propose un titre : la plus votée passe après le titre en cours."}</p>`}`;
}

function bindParty(root, s) {
  const post = async (path, body) => {
    try { partyHandle(await api(partyPath(path), { method: "POST", body: body ? JSON.stringify(body) : undefined })); }
    catch (e) { toast(e.message); }
  };
  $$("[data-react]", root).forEach((b) => (b.onclick = () => {
    haptic(); floatReaction(b.dataset.react);
    party.ownReactions++;
    post("/react", { emoji: b.dataset.react });
  }));
  $$("[data-vote]", root).forEach((b) => (b.onclick = () => { haptic(); post(`/queue/${b.dataset.vote}/vote`); }));
  $$("[data-unpropose]", root).forEach((b) => (b.onclick = async () => {
    try { partyHandle(await api(partyPath(`/queue/${b.dataset.unpropose}`), { method: "DELETE" })); } catch (e) { toast(e.message); }
  }));
  $$("[data-playnow]", root).forEach((b) => (b.onclick = () => { const item = s.queue.find((q) => String(q.id) === b.dataset.playnow); if (item) partyPlayNow(item); }));
  $$("[data-pc]", root).forEach((b) => (b.onclick = () => {
    haptic();
    const action = b.dataset.pc;
    if (s.is_host) { if (action === "next") next(); else if (audio.src) action === "play" ? audio.play().catch(() => {}) : audio.pause(); }
    else partyCommand(action);
  }));
  $("[data-local]", root)?.addEventListener("click", partyToggleLocal);
  $("[data-skip]", root)?.addEventListener("click", () => { haptic(); post("/skip"); });
  $("[data-open]", root)?.addEventListener("change", (e) => post("/settings", { open_controls: e.target.checked }));
  $$("[data-ptab]", root).forEach((b) => (b.onclick = () => { party.tab = b.dataset.ptab; party.renderedVersion = null; renderParty(); }));
  $("[data-party-add]", root)?.addEventListener("click", () => quickSearch(s.is_host ? "Ajouter un titre" : "Proposer un titre", partyPropose));
  const form = $(".chat-form", root);
  if (form) form.onsubmit = async (e) => {
    e.preventDefault();
    const input = $("#party-msg", root);
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    await post("/chat", { text });
    $("#party-msg")?.focus();
  };
  $$("[data-member]", root).forEach((b) => (b.onclick = () => {
    const m = s.members.find((x) => String(x.id) === b.dataset.member);
    if (!s.is_host || !m || m.is_me || m.id == null) return;
    actionSheet(m.name, [
      { icon: "👑", label: "Lui passer la main", sub: "Il ou elle choisira la musique", run: () => post("/transfer", { member_id: m.id }) },
      { icon: icons.close, label: "Retirer de la session", danger: true, run: async () => {
        if (await confirmSheet(`Retirer ${m.name} de la session ?`, "Retirer")) post("/kick", { member_id: m.id });
      } },
    ]);
  }));
  $("[data-party-leave]", root).onclick = async () => {
    if (s.is_host && s.members.length > 1 && !(await confirmSheet("Terminer la session pour tout le monde ?", "Terminer"))) return;
    partyLeave();
  };
  const url = `${location.origin}${location.pathname}?party=${s.code}`;
  $("[data-party-share]", root).onclick = () => {
    const text = `Écoute avec moi sur Sona ! Code : ${s.code}`;
    navigator.share ? navigator.share({ text, url }).catch(() => {}) : navigator.clipboard?.writeText(url).then(() => toast("Lien copié"));
  };
  $("[data-party-copy]", root).onclick = () => navigator.clipboard?.writeText(s.code).then(() => toast("Code copié")).catch(() => toast(s.code));
}

/** Barre de progression et état de synchro (chaque seconde, sans tout redessiner). */
function partyTick() {
  const s = party.state;
  if (!s?.track) return;
  const dur = s.track.duration_seconds || (sameTrack(s.track, state.queue[state.index]) && isFinite(audio.duration) ? audio.duration : 0);
  const bar = $("#party-progress");
  if (bar && dur) bar.style.width = `${Math.min(100, (partyTarget() / dur) * 100)}%`;
  const sync = $("#party-sync");
  if (!sync) return;
  const drift = Math.abs(audio.currentTime - partyTarget());
  const ok = sameTrack(s.track, state.queue[state.index]) && (s.paused || party.localPause || (!audio.paused && drift <= 1.5));
  sync.className = `pn-sync ${ok ? "ok" : ""}`;
  sync.textContent = party.localPause ? "En pause chez toi" : ok ? `✓ Synchronisé avec ${s.host_name || "l'hôte"}` : "Synchronisation…";
}

/** Après un rechargement de la page : retour dans la session en cours. */
async function partyRestore() {
  const code = store.get("sona.party");
  if (!code || party.state) return;
  try { await partyEnter(await api(`/party/${encodeURIComponent(code)}/join`, { method: "POST" })); toast("De retour dans l'écoute ensemble 🎧"); }
  catch { store.set("sona.party", null); }
}

/** Petite recherche dans une feuille : `pick(track)` au choix. */
function quickSearch(title, pick) {
  const wrap = openSheet(`<h2 class="sheet-title">${esc(title)}</h2>
    <input class="field" id="qs" type="search" placeholder="Titre, artiste…" autocomplete="off"><div class="menu" id="qs-results"></div>`, { cls: "tall" });
  const input = $("#qs", wrap);
  setTimeout(() => input.focus(), 250);
  let timer, results = [];
  input.oninput = () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const q = input.value.trim();
      results = q ? (await api(`/search?q=${encodeURIComponent(q)}&limit=15`).catch(() => ({ tracks: [] }))).tracks : [];
      $("#qs-results", wrap).innerHTML = results.map((t, i) => `<button class="menu-item" data-qs="${i}"><img class="mi-thumb" src="${esc(big(t.cover_url, 120))}" alt="">
        <span class="mi-text"><span class="mi-label">${esc(t.title)}</span><span class="mi-sub">${esc(t.artist)}</span></span></button>`).join("");
      $$("[data-qs]", wrap).forEach((b) => (b.onclick = () => { wrap.close(); pick(results[+b.dataset.qs]); }));
    }, 300);
  };
}

// ── Mode sport ───────────────────────────────────────────────────────────

async function viewSport() {
  const bpm = +(store.get("sona.sportBpm") || 160);
  setTimeout(() => {
    const slider = $("#sport-bpm");
    const label = $("#sport-val");
    const set = (v) => { slider.value = v; label.textContent = Math.round(v); slider.style.setProperty("--p", `${((v - 100) / 100) * 100}%`); store.set("sona.sportBpm", String(Math.round(v))); };
    slider.oninput = () => set(+slider.value);
    set(bpm);
    let taps = [];
    $("#sport-tap").onclick = () => {
      haptic();
      const now = Date.now();
      taps = [...taps.filter((t) => now - t < 4000), now];
      if (taps.length >= 3) {
        const gaps = taps.slice(1).map((t, i) => t - taps[i]);
        set(Math.max(100, Math.min(200, 60000 / (gaps.reduce((a, b) => a + b, 0) / gaps.length))));
      }
    };
    $("#sport-go").onclick = async () => {
      const tempo = Math.round(+slider.value);
      try {
        await playStation(`Mode sport · ${tempo} BPM`, () => api(`/sport?bpm=${tempo}&exclude=${encodeURIComponent(state.queue.slice(-100).map((t) => t.source_id).join(","))}`));
        openNowPlaying("art");
      } catch (e) { toast(e.message); }
    };
  });
  return page(`<h1 class="page-title">Mode sport</h1><p class="page-sub">La musique au tempo de ta foulée : choisis ta cadence (pas par minute), ou tape-la en rythme.</p>
    <div class="sport">
      <div class="sport-val"><b id="sport-val">${bpm}</b><span>pas / min</span></div>
      <input type="range" class="slider" id="sport-bpm" min="100" max="200" step="1" value="${bpm}" aria-label="Cadence">
      <div class="chips center">${[["Marche", 115], ["Footing", 155], ["Course", 170], ["Sprint", 185]].map(([l, v]) => `<button class="chip" onclick="document.getElementById('sport-bpm').value=${v};document.getElementById('sport-bpm').dispatchEvent(new Event('input'))">${l}</button>`).join("")}</div>
      <button class="tap-btn" id="sport-tap">Tape en rythme</button>
      <button class="btn big" id="sport-go">${icons.play} C'est parti</button>
    </div>`);
}

// ── TV et PS5 (appli YouTube de l'écran) ──────────────────────────────────

const cast = { screen: null, timer: null };

async function openCast() {
  const screens = await api("/tv").catch(() => []);
  const t = state.queue[state.index];
  const wrap = openSheet(`<h2 class="sheet-title">Diffuser sur un écran</h2>
    <p class="muted">L'appli YouTube de ta TV ou de ta PS5 joue la file d'attente. Associe l'écran une fois avec le code affiché dans YouTube → Réglages → Associer à un téléphone.</p>
    <div class="menu">${screens.map((sc) => `<button class="menu-item" data-screen="${esc(sc.screen_id)}"><span class="mi-icon">${icons.tv}</span>
      <span class="mi-text"><span class="mi-label">${esc(sc.name || "Écran")}</span><span class="mi-sub">${cast.screen?.screen_id === sc.screen_id ? "En cours de diffusion" : "Touche pour y envoyer la musique"}</span></span>
      <span class="mi-x" data-unpair="${esc(sc.screen_id)}" title="Oublier">${icons.trash}</span></button>`).join("")}
      <button class="menu-item" data-pair><span class="mi-icon">${icons.plus}</span><span class="mi-text"><span class="mi-label">Associer un écran</span></span></button>
    </div>
    ${cast.screen ? `<div class="cast-remote" id="cast-remote"></div>` : ""}`);
  $$("[data-unpair]", wrap).forEach((b) => (b.onclick = async (e) => {
    e.stopPropagation();
    await api(`/tv/${encodeURIComponent(b.dataset.unpair)}`, { method: "DELETE" }).catch(() => {});
    if (cast.screen?.screen_id === b.dataset.unpair) stopCast();
    wrap.close(); openCast();
  }));
  $$("[data-screen]", wrap).forEach((b) => (b.onclick = async () => {
    if (!t) return toast("Lance d'abord un titre");
    const screen = screens.find((x) => x.screen_id === b.dataset.screen);
    toast(`Envoi sur ${screen.name}…`);
    try {
      await api(`/tv/${encodeURIComponent(screen.screen_id)}/play`, { method: "POST", body: JSON.stringify({ tracks: state.queue.slice(state.index, state.index + 200).map(cleanTrack) }) });
      audio.pause();
      cast.screen = screen;
      renderMini();
      wrap.close();
      openCast();
    } catch (e) { toast(e.message); }
  }));
  $("[data-pair]", wrap).onclick = async () => {
    wrap.close();
    const code = await askText({ title: "Associer un écran", placeholder: "Code affiché sur la TV", confirm: "Associer", hint: "YouTube sur la TV ou la PS5 → Réglages → Associer à un téléphone → Associer avec un code TV." });
    if (!code) return;
    try { const got = await api("/tv/pair", { method: "POST", body: JSON.stringify({ code: code.replace(/\s/g, "") }) }); toast(`${got.name} associé ✓`); openCast(); }
    catch (e) { toast(e.message); }
  };
  if (cast.screen) renderCastRemote(wrap);
}

async function renderCastRemote(wrap) {
  const box = $("#cast-remote", wrap);
  if (!box) return;
  const id = encodeURIComponent(cast.screen.screen_id);
  const control = (action, extra = {}) => api(`/tv/${id}/control`, { method: "POST", body: JSON.stringify({ action, ...extra }) }).catch((e) => toast(e.message));
  const draw = (st) => {
    box.innerHTML = `<div class="cr-head">${icons.tv} <b>${esc(cast.screen.name)}</b><span class="muted">${st ? esc({ playing: "Lecture", paused: "Pause", buffering: "Chargement…", ended: "Terminé", idle: "En attente" }[st.state] || "") : ""}</span></div>
      ${st?.duration ? `<input type="range" class="slider" id="cr-seek" min="0" max="${st.duration}" value="${st.position}" style="--p:${(st.position / st.duration) * 100}%">` : ""}
      <div class="dp-ctl"><button data-cr="previous">${icons.prev}</button><button data-cr="${st?.state === "playing" ? "pause" : "play"}">${st?.state === "playing" ? icons.pause : icons.play}</button><button data-cr="next">${icons.next}</button></div>
      ${st?.volume != null ? `<div class="np-volume">${icons.speaker}<input type="range" class="slider" id="cr-vol" min="0" max="100" value="${st.volume}" style="--p:${st.volume}%"></div>` : ""}
      <button class="btn ghost danger" data-cr="stop">Arrêter la diffusion</button>`;
    $$("[data-cr]", box).forEach((b) => (b.onclick = async () => {
      haptic();
      if (b.dataset.cr === "stop") { await control("stop"); stopCast(); wrap.close(); return; }
      await control(b.dataset.cr); setTimeout(refresh, 600);
    }));
    const seek = $("#cr-seek", box);
    if (seek) seek.onchange = () => control("seek", { seconds: +seek.value });
    const vol = $("#cr-vol", box);
    if (vol) vol.onchange = () => control("volume", { volume: +vol.value });
  };
  const refresh = async () => {
    if (!document.body.contains(box)) return clearInterval(cast.timer);
    const st = await api(`/tv/${id}/state`).catch(() => null);
    if (document.activeElement?.closest?.("#cast-remote")) return;
    draw(st);
  };
  draw(null);
  refresh();
  clearInterval(cast.timer);
  cast.timer = setInterval(refresh, 2500);
}

function stopCast() {
  cast.screen = null;
  clearInterval(cast.timer);
  renderMini();
}

// ── Réglages ─────────────────────────────────────────────────────────────

const toggleRow = (key, title, sub, on) => `<label class="switch-row"><span><b>${esc(title)}</b>${sub ? `<small>${esc(sub)}</small>` : ""}</span>
  <input type="checkbox" data-setting="${key}" ${on ? "checked" : ""}><i></i></label>`;
const linkRow = (attrs, icon, title, sub = "") => `<a class="set-row" ${attrs}><span class="mi-icon">${icon}</span><span class="set-text"><b>${esc(title)}</b>${sub ? `<small>${esc(sub)}</small>` : ""}</span>${icons.right}</a>`;

async function viewSettings() {
  $("#content").innerHTML = skeleton("Réglages");
  const [me, settings, health, loved] = await Promise.all([
    api("/auth/me"), api("/settings").catch(() => state.settings), fetch(`${BASE}/health`).then((r) => r.json()).catch(() => null),
    api("/library/lastfm-loved/import").catch(() => null),
  ]);
  account = me;
  state.settings = settings;
  const name = me.display_name || me.username;
  setTimeout(bindSettings);
  return page(`<h1 class="page-title">Réglages</h1>
    <div class="set-account">${avatar(me.avatar_url, name, "profile-avatar small")}<div><b>${esc(name)}</b><small>Last.fm · ${esc(me.username)}</small></div></div>

    <h3 class="set-head">Lecture</h3><div class="set-group">
      ${settings ? toggleRow("autoplay", "Lecture automatique", "Des morceaux similaires seront lus quand la file se termine.", settings.autoplay) : ""}
      ${toggleRow("dj", "DJ vocal", "Une voix annonce chaque titre, comme à la radio.", store.get("sona.dj") === "1")}
      <a class="set-row" data-dj-voice><span class="set-text"><b>Voix du DJ</b><small>${esc({ remy: "Rémy", vivienne: "Vivienne", henri: "Henri", denise: "Denise" }[store.get("sona.djVoice") || "remy"])}</small></span>${icons.right}</a>
      ${settings ? `<a class="set-row" data-quality><span class="set-text"><b>Qualité audio</b><small>${settings.quality === "standard" ? "Standard (débit réduit)" : "Meilleure disponible"}</small></span>${icons.right}</a>` : ""}
    </div>

    <h3 class="set-head">Compte</h3><div class="set-group">
      ${toggleRow("share_listening", "Partager mon écoute", "Tes amis voient ce que tu écoutes en direct et tes dernières écoutes.", me.share_listening)}
      ${toggleRow("scrobble_to_lastfm", "Scrobbler sur Last.fm", "Chaque morceau écouté au moins à moitié est ajouté à ton profil Last.fm ; un titre aimé devient ♥ sur Last.fm.", me.scrobble_to_lastfm)}
      <a class="set-row" data-loved><span class="mi-icon">${icons.heart}</span><span class="set-text"><b>Importer mes titres aimés Last.fm</b><small id="loved-status">${loved?.running ? `Import en cours… ${loved.done ?? 0} / ${loved.total ?? "?"}` : "Dans ta bibliothèque Sona"}</small></span>${icons.right}</a>
      <a class="set-row" data-history><span class="mi-icon">${icons.download}</span><span class="set-text"><b>Importer mon historique Last.fm</b><small id="history-status">Pour des stats complètes</small></span>${icons.right}</a>
      <a class="set-row" data-clear-history><span class="mi-icon">${icons.clock}</span><span class="set-text"><b>Effacer l'historique de navigation</b><small>Les fiches consultées récemment</small></span>${icons.right}</a>
    </div>

    ${desktop ? `<h3 class="set-head">Sona pour ${desktop.platform === "darwin" ? "Mac" : "Windows"}</h3><div class="set-group" id="desk-settings"><p class="set-row muted">Chargement…</p></div>
    <h3 class="set-head">Mises à jour</h3><div class="set-group" id="desk-updates"><p class="set-row muted">Chargement…</p></div>` : ""}

    <h3 class="set-head">Appli</h3><div class="set-group">
      ${desktop ? "" : standalone ? `<div class="set-row"><span class="mi-icon">${icons.check}</span><span class="set-text"><b>Sona est installé</b><small>Ouvert depuis l'écran d'accueil</small></span></div>`
        : linkRow("data-install-app", icons.install, "Installer Sona sur l'écran d'accueil", isIOS ? "Partager → Sur l'écran d'accueil" : "Comme une vraie app, en plein écran")}
      ${soundAvailable ? linkRow("data-sound", icons.wave, "Son", "Égaliseur, volume égalisé, fondu entre les titres") : ""}
      ${linkRow('href="#/devices"', icons.devices, "Appareils", "Tes PC enregistrés, à piloter d'un appui")}
      ${linkRow('href="#/status"', icons.pulse, "État de Sona", "Serveur, Sona Connect, télécommande, Stream Deck…")}
      ${linkRow('href="#/recent"', icons.clock, "Écoutes récentes")}
      ${linkRow('href="#/concerts"', icons.calendar, "Concerts")}
    </div>

    ${me.is_admin ? `<h3 class="set-head">Administration</h3><div class="set-group">
      ${linkRow('href="#/admin"', icons.lock, "Accès à l'app", "Valider les nouveaux comptes")}
      ${linkRow('href="#/health"', icons.pulse, "Santé de la lecture", "Cookies YouTube, yt-dlp")}
    </div>` : ""}

    <h3 class="set-head">Serveur</h3><div class="set-group">
      <div class="set-row"><span class="set-text"><b>Version du serveur</b><small>${esc(health?.version || "inconnue")}</small></span></div>
      <div class="set-row"><span class="set-text"><b>Lecture</b><small>${esc({ ok: "Tout fonctionne", degraded: "Perturbée", down: "En panne" }[health?.streaming] || "—")}</small></span></div>
    </div>

    <button class="btn ghost danger wide" data-signout>Se déconnecter</button>`);
}

function bindSettings() {
  $$("[data-setting]").forEach((input) => (input.onchange = async () => {
    const key = input.dataset.setting;
    const on = input.checked;
    haptic();
    try {
      if (key === "autoplay") state.settings = await api("/settings", { method: "PUT", body: JSON.stringify({ autoplay: on }) });
      else if (key === "dj") store.set("sona.dj", on ? "1" : null);
      else account = await api("/auth/me", { method: "PUT", body: JSON.stringify({ [key]: on }) });
    } catch (e) { input.checked = !on; toast(e.message); }
  }));
  $("[data-dj-voice]")?.addEventListener("click", () => actionSheet("Voix du DJ", [["remy", "Rémy"], ["vivienne", "Vivienne"], ["henri", "Henri"], ["denise", "Denise"]].map(([id, label]) => ({
    icon: icons.mic, label, checked: (store.get("sona.djVoice") || "remy") === id, run: () => { store.set("sona.djVoice", id); route(); },
  }))));
  $("[data-quality]")?.addEventListener("click", () => actionSheet("Qualité audio", [["best", "Meilleure disponible"], ["standard", "Standard (débit réduit)"]].map(([q, label]) => ({
    label, checked: state.settings?.quality === q, run: async () => { state.settings = await api("/settings", { method: "PUT", body: JSON.stringify({ quality: q }) }); route(); },
  }))));
  $("[data-loved]")?.addEventListener("click", async () => {
    const line = $("#loved-status");
    try {
      let st = await api("/library/lastfm-loved/import", { method: "POST" });
      while (st.running && $("#loved-status")) {
        $("#loved-status").textContent = `Import en cours… ${st.done ?? 0} / ${st.total ?? "?"}`;
        await new Promise((r) => setTimeout(r, 2000));
        st = await api("/library/lastfm-loved/import");
      }
      if ($("#loved-status")) $("#loved-status").textContent = st.error || "Import terminé ✓";
      loadLiked();
    } catch (e) { if (line) line.textContent = e.message; }
  });
  $("[data-history]")?.addEventListener("click", async () => {
    const line = $("#history-status");
    try {
      let st = await api("/stats/import/lastfm", { method: "POST" });
      while (st.running && $("#history-status")) {
        $("#history-status").textContent = `Import en cours… ${plural(st.imported, "écoute")}`;
        await new Promise((r) => setTimeout(r, 2000));
        st = await api("/stats/import/lastfm");
      }
      if ($("#history-status")) $("#history-status").textContent = st.error || `Terminé : ${plural(st.imported, "écoute")} ajoutée${st.imported > 1 ? "s" : ""}`;
    } catch (e) { if (line) line.textContent = e.message; }
  });
  $("[data-clear-history]")?.addEventListener("click", async () => {
    if (!(await confirmSheet("Effacer l'historique de navigation ?", "Effacer"))) return;
    await api("/history", { method: "DELETE" }).then(() => toast("Historique effacé")).catch((e) => toast(e.message));
  });
  $("[data-install-app]")?.addEventListener("click", installApp);
  $("[data-sound]")?.addEventListener("click", soundSheet);
  if (desktop) { renderDesktopSettings(); renderUpdates(); }
  $("[data-signout]")?.addEventListener("click", async () => {
    if (!(await confirmSheet("Se déconnecter de Sona ?", "Se déconnecter"))) return;
    try { await api("/auth/logout", { method: "POST" }); } catch {}
    signOut();
  });
}

async function viewAdmin() {
  $("#content").innerHTML = skeleton("Accès à l'app");
  const accounts = await api("/admin/accounts");
  const groups = [["pending", "En attente"], ["approved", "Acceptés"], ["rejected", "Refusés"]];
  setTimeout(() => $$("[data-decide]").forEach((b) => (b.onclick = async () => {
    try { await api(`/admin/accounts/${b.dataset.id}/${b.dataset.decide}`, { method: "POST" }); toast("C'est fait"); route(); } catch (e) { toast(e.message); }
  })));
  return page(`<h1 class="page-title">Accès à l'app</h1><p class="page-sub">Chaque nouveau compte attend ta validation.</p>
    ${groups.map(([status, label]) => {
      const list = accounts.filter((a) => a.status === status);
      if (!list.length) return "";
      return `<section class="section"><div class="section-head"><h2>${label} (${list.length})</h2></div><div class="set-group">${list.map((a) => `<div class="set-row">
        ${avatar(a.avatar_url, a.display_name || a.username)}<span class="set-text"><b>${esc(a.display_name || a.username)}${a.is_admin ? " · admin" : ""}</b><small>@${esc(a.username)}${a.created_at ? ` · ${since(a.created_at)}` : ""}</small></span>
        ${a.id != null && !a.is_admin ? `<span class="pill-row tight">${status !== "approved" ? `<button class="btn small" data-decide="approve" data-id="${a.id}">Accepter</button>` : ""}${status !== "rejected" ? `<button class="btn small ghost" data-decide="reject" data-id="${a.id}">Refuser</button>` : ""}</span>` : ""}</div>`).join("")}</div></section>`;
    }).join("")}`);
}

// ── Événements audio ─────────────────────────────────────────────────────

audio.volume = +(store.get("sona.volume") ?? 1);
const syncPlayState = () => {
  $$('[data-act="toggle"]').forEach((b) => (b.innerHTML = audio.paused ? icons.play : icons.pause));
  const npToggle = $("#np-toggle");
  if (npToggle) npToggle.innerHTML = audio.paused ? icons.play : icons.pause;
  $("#np")?.classList.toggle("paused", audio.paused);
  $$(".bars").forEach((b) => b.classList.toggle("paused", audio.paused));
  $$('[data-mp="toggle"]').forEach((b) => (b.innerHTML = audio.paused ? icons.play : icons.pause));
  if ("mediaSession" in navigator) navigator.mediaSession.playbackState = audio.paused ? "paused" : "playing";
};
audio.addEventListener("play", syncPlayState);
audio.addEventListener("pause", syncPlayState);
// En pause : plus « en train d'écouter » pour les amis ; reprise : de nouveau.
let presenceTimer = null;
audio.addEventListener("pause", () => {
  clearTimeout(presenceTimer);
  presenceTimer = setTimeout(() => { if (audio.paused && account) api("/plays/now", { method: "DELETE" }).catch(() => {}); }, 3000);
});
audio.addEventListener("play", () => {
  clearTimeout(presenceTimer);
  const t = state.queue[state.index];
  if (t && audio.currentTime > 2) reportNowPlaying(t, audio.currentTime);
});
audio.addEventListener("loadedmetadata", renderMoments);
audio.addEventListener("ended", () => {
  if (isSilence()) return;
  if (sleep.endOfTrack) { setSleep(0); toast("Bonne nuit 🌙"); return; }
  next(true);
});
audio.addEventListener("error", () => {
  if (!audio.src || isSilence()) return;
  if (partyGuest()) return toast("Ce titre ne se lance pas chez toi — l'hôte continue");
  toast("Ce titre ne se lance pas — passage au suivant");
  setTimeout(() => next(true), 1200);
});
audio.addEventListener("timeupdate", () => {
  updateProgress();
  const t = state.queue[state.index];
  const dur = audio.duration && isFinite(audio.duration) ? audio.duration : t?.duration_seconds || 0;
  const delta = audio.currentTime - state.lastTick;
  state.lastTick = audio.currentTime;
  if (!audio.paused && delta > 0 && delta < 1.5) state.listened += delta;
  // Même règle que l'app : écoute comptée à la moitié du titre ou à 4 min.
  if (t && !state.scrobbled && dur > 30 && state.listened >= Math.min(dur / 2, 240)) {
    state.scrobbled = true;
    api("/plays", {
      method: "POST",
      body: JSON.stringify({ plays: [{
        title: t.title, artist: t.artist, album: t.album, source: t.source, source_id: t.source_id,
        artist_source_id: t.artist_source_id, album_source_id: t.album_source_id, cover_url: t.cover_url,
        duration_seconds: Math.round(dur), listened_seconds: Math.round(state.listened), played_at: state.startedAt,
      }] }),
    }).catch(() => {});
  }
  syncLyrics(false);
  checkMoments();
  // Position pour l'écran verrouillé (barre de progression du téléphone).
  if ("mediaSession" in navigator && navigator.mediaSession.setPositionState && dur && isFinite(dur)) {
    try { navigator.mediaSession.setPositionState({ duration: dur, position: Math.min(dur, audio.currentTime), playbackRate: 1 }); } catch {}
  }
});

if ("mediaSession" in navigator) {
  const handlers = {
    play: () => (partyGuest() ? party.localPause && partyToggleLocal() : audio.play()),
    pause: () => (partyGuest() ? !party.localPause && partyToggleLocal() : audio.pause()),
    nexttrack: () => next(), previoustrack: () => prev(),
    seekto: (d) => { audio.currentTime = d.seekTime; },
    seekbackward: (d) => { audio.currentTime = Math.max(0, audio.currentTime - (d.seekOffset || 10)); },
    seekforward: (d) => { audio.currentTime += d.seekOffset || 10; },
  };
  for (const [action, handler] of Object.entries(handlers)) {
    try { navigator.mediaSession.setActionHandler(action, handler); } catch {}
  }
}

document.addEventListener("keydown", (e) => {
  if (e.target.matches("input, textarea")) return;
  if (e.code === "Space") { e.preventDefault(); toggle(); }
  else if (e.key === "Escape" && $(".sheet-wrap")) return;
  else if (e.key === "Escape" && state.npOpen) closeNowPlaying();
  else if (e.key === "ArrowRight" && (e.metaKey || e.ctrlKey)) next();
  else if (e.key === "ArrowLeft" && (e.metaKey || e.ctrlKey)) prev();
  else if (e.key === "ArrowRight" && audio.src) audio.currentTime += 10;
  else if (e.key === "ArrowLeft" && audio.src) audio.currentTime -= 10;
  else if (e.key.toLowerCase() === "l" && audio.src) openNowPlaying("lyrics", true);
});

// ── Sona pour Windows ─────────────────────────────────────────────────────
// La même page dans l'app d'ordinateur (dossier desktop/) : barre de titre
// et fond en verre (desktop.css), état de lecture envoyé à l'app (zone de
// notification, aperçu de la barre des tâches, mini-lecteur, télécommande
// du téléphone) et commandes reçues en retour. Rien de tout ça sur le web.

/** Poignée pour déplacer la fenêtre : un élément vide, à côté des boutons et
    jamais autour. Sous Windows, une zone « drag » avale les clics de tout ce
    qu'elle contient, même marqué « no-drag ». */
function grip() {
  return desktop ? `<div class="grip" aria-hidden="true"></div>` : "";
}

const desk = { clients: [], mini: false, name: "", last: "", pos: 0, at: 0, timer: null, cover: null, slot: 0 };

function desktopInit() {
  if (!desktop) return;
  // Fond vivant (la pochette en cours, floue) et boutons de fenêtre : hors de
  // #root, pour rester en place de l'écran de connexion à l'app.
  const ambient = document.createElement("div");
  ambient.className = "ambient";
  ambient.setAttribute("aria-hidden", "true");
  ambient.innerHTML = `<img alt=""><img alt=""><i class="blob b1"></i><i class="blob b2"></i><i class="blob b3"></i>`;
  const controls = document.createElement("div");
  controls.className = "wctl";
  controls.innerHTML = `<button data-w="minimize" title="Réduire"><svg viewBox="0 0 10 10"><path d="M1 5.5h8"/></svg></button>
    <button data-w="maximize" title="Agrandir"><svg viewBox="0 0 10 10"><rect x="1.5" y="1.5" width="7" height="7" rx="1"/></svg></button>
    <button data-w="close" class="close" title="Fermer"><svg viewBox="0 0 10 10"><path d="M1.5 1.5l7 7M8.5 1.5l-7 7"/></svg></button>`;
  const strip = document.createElement("div");
  strip.className = "drag-top";
  document.body.prepend(ambient);
  document.body.append(strip, controls);
  controls.onclick = (e) => {
    const action = e.target.closest("[data-w]")?.dataset.w;
    if (action) desktop.window[action]();
  };
  desktop.onWindow(({ maximized, focused }) => {
    document.documentElement.classList.toggle("maximized", maximized);
    document.documentElement.classList.toggle("blurred", !focused);
    $('[data-w="maximize"]', controls).innerHTML = maximized
      ? `<svg viewBox="0 0 10 10"><rect x="1.5" y="3" width="5.5" height="5.5" rx="1"/><path d="M3 3V2.4c0-.5.4-.9.9-.9h3.7c.5 0 .9.4.9.9v3.7c0 .5-.4.9-.9.9H7"/></svg>`
      : `<svg viewBox="0 0 10 10"><rect x="1.5" y="1.5" width="7" height="7" rx="1"/></svg>`;
    $('[data-w="maximize"]', controls).title = maximized ? "Restaurer" : "Agrandir";
  });
  desktop.onCommand(async (c) => {
    try { desktop.reply(c.id, await desktopCommand(c)); } catch (e) { desktop.reply(c.id, null, e.message || "Erreur"); }
  });
  desktop.onAuthDone(({ authorized }) => retryPendingLogin(!authorized));
  desktop.onRemoteClients((clients) => {
    const before = desk.clients.length;
    desk.clients = clients || [];
    if (desk.clients.length > before) toast(`${desk.clients[desk.clients.length - 1].name} connecté à la télécommande`);
    if (account) renderTopbar();
    remotePairingRefresh?.();
    if ($("#desk-settings")) renderDesktopSettings();
  });
  desktop.onOpenRemote(() => account && openRemotePairing());
  desktop.onOverlay?.(() => { if ($("#desk-settings")) renderDesktopSettings(); });
  desktop.onGameMode?.((on) => { if (on) closeVisualizer(); });
  watchHeadphones();
  desktop.onMini((on) => { desk.mini = on; if (account) renderTopbar(); if ($("#desk-settings")) renderDesktopSettings(); });
  desktop.settings().then((s) => { desk.mini = s.mini; desk.name = s.deviceNameShown; }).catch(() => {});
  for (const ev of ["play", "pause", "seeked", "volumechange", "loadedmetadata"]) audio.addEventListener(ev, () => desktopReport());
  // Filet de sécurité : file modifiée, paroles chargées, lecture sur un autre appareil…
  setInterval(() => desktopReport(), 1000);
}

/** Ce que joue Sona (ici, ou l'appareil Sona Connect piloté depuis le PC). */
function desktopSnapshot() {
  const remote = remoteDevice();
  const rnow = deviceNow(remote);
  const t = remote ? rnow.track : state.queue[state.index];
  // Les autres appareils Sona Connect : le Stream Deck peut les piloter.
  const devices = otherDevices().map((d) => {
    const n = deviceNow(d);
    return { id: d.id, name: d.name, kind: d.kind, playing: !n.paused, track: n.track ? cleanTrack(n.track) : null,
      position: Math.round(n.position), volume: d.volume ?? null, shuffle: d.shuffle ?? null, repeat: d.repeat ?? null, liked: d.liked ?? null };
  });
  if (!t) return { track: null, volume: audio.volume, shuffle: state.shuffle, repeat: state.repeat, devices };
  const start = Math.max(0, state.index - 15);
  const ly = !remote && sameTrack(t, state.queue[state.index]) ? state.lyrics : null;
  return {
    track: cleanTrack(t),
    paused: remote ? rnow.paused : audio.paused,
    position: remote ? rnow.position : audio.currentTime || 0,
    duration: remote ? t.duration_seconds || 0 : (audio.duration && isFinite(audio.duration) ? audio.duration : t.duration_seconds || 0),
    volume: remote ? remote.volume ?? 1 : audio.volume,
    shuffle: state.shuffle, repeat: state.repeat,
    liked: state.liked.has(trackKey(t)),
    remoteDevice: remote ? remote.name : null,
    devices,
    index: remote ? -1 : state.index,
    queueName: remote ? "" : state.station ? `${state.station.name} · radio` : state.name || "",
    queue: remote ? [] : state.queue.slice(start, state.index + 40).map((q, k) => ({ i: start + k, title: q.title, artist: q.artist, cover_url: q.cover_url || null })),
    lyrics: ly ? { synced: ly.synced, instrumental: ly.instrumental, lines: ly.lines.map((l) => ({ time: l.time ?? null, text: l.text || "" })) } : null,
  };
}

/** Envoie l'état à l'app s'il a changé (ou si la position a sauté). */
function desktopReport(force) {
  if (!desktop || !account) return;
  clearTimeout(desk.timer);
  desk.timer = setTimeout(() => {
    const snap = desktopSnapshot();
    const { position = 0, ...rest } = snap;
    const sig = JSON.stringify(rest);
    const expected = desk.pos + (snap.paused ? 0 : (Date.now() - desk.at) / 1000);
    updateAmbient(snap.track);
    if (!force && sig === desk.last && Math.abs(position - expected) < 1.5) return;
    Object.assign(desk, { last: sig, pos: position, at: Date.now() });
    desktop.report(snap);
  }, force ? 0 : 60);
}

/** Fond de la fenêtre : la pochette en cours, floue, en fondu. */
function updateAmbient(t) {
  const url = t?.cover_url ? big(t.cover_url, 300) : "";
  if (url === desk.cover) return;
  desk.cover = url;
  const imgs = $$(".ambient img");
  if (imgs.length < 2) return;
  document.documentElement.classList.toggle("has-art", !!url);
  if (!url) { imgs.forEach((i) => i.classList.remove("on")); return; }
  const next = imgs[desk.slot = 1 - desk.slot];
  const prev = imgs[1 - desk.slot];
  next.onload = () => { if (desk.cover === url) { next.classList.add("on"); prev.classList.remove("on"); } };
  next.src = url;
}

/** Commande de la télécommande, du mini-lecteur ou de la barre des tâches. */
/** Commande pour un autre appareil Sona Connect (touche Stream Deck réglée sur l'iPhone…). */
async function deviceCommand(c) {
  const d = state.connect.devices.find((x) => x.id === c.target && !x.is_me);
  if (!d) throw new Error("Cet appareil n'est pas allumé.");
  const action = c.action === "toggle" ? (deviceNow(d).paused ? "play" : "pause") : c.action;
  if (!["play", "pause", "next", "previous", "seek", "volume", "shuffle", "repeat", "like"].includes(action)) throw new Error("Action inconnue");
  const extra = {};
  if (Number.isFinite(c.position)) extra.position = c.position;
  if (Number.isFinite(c.volume)) extra.volume = Math.max(0, Math.min(1, c.volume));
  await api("/connect/command", { method: "POST", body: JSON.stringify({ device_id: deviceId, target: d.id, action, ...extra }) });
  setTimeout(() => startConnect.now?.(), 500);
  return true;
}

async function desktopCommand(c) {
  if (c.target) return deviceCommand(c);
  const remote = remoteDevice();
  const t = remote ? deviceNow(remote).track : state.queue[state.index];
  const paused = remote ? deviceNow(remote).paused : audio.paused;
  const track = c.track && c.track.source && c.track.source_id ? cleanTrack(c.track) : null;
  let result = true;
  switch (c.action) {
    case "toggle": toggle(); break;
    case "play": if (paused) toggle(); break;
    case "pause": if (!paused) toggle(); break;
    case "next": await next(); break;
    case "previous": prev(); break;
    case "seek":
      if (!Number.isFinite(c.position)) break;
      if (remote) sendCommand(remote.id, "seek", { position: c.position });
      else if (audio.src) audio.currentTime = c.position;
      break;
    case "volume": {
      if (!Number.isFinite(c.volume)) break;
      const v = Math.max(0, Math.min(1, c.volume));
      if (remote) sendCommand(remote.id, "volume", { volume: v });
      else { audio.volume = v; store.set("sona.volume", String(v)); }
      renderTopbar();
      break;
    }
    case "like": if (t) await toggleLike(t); break;
    case "shuffle": state.shuffle = !state.shuffle; renderTopbar(); break;
    case "repeat": state.repeat = !state.repeat; renderTopbar(); break;
    case "playIndex": if (!remote && state.queue[c.index]) playAt(c.index); break;
    case "removeIndex":
      if (!remote && c.index > state.index && c.index < state.queue.length) {
        state.queue.splice(c.index, 1);
        if (state.npOpen && state.npTab === "queue") renderQueue();
      }
      break;
    case "search": {
      const q = String(c.query || "").trim();
      result = q ? ((await api(`/search?q=${encodeURIComponent(q)}&limit=25`)).tracks || []).map(cleanTrack) : [];
      break;
    }
    case "playTrack": if (track) playList([track], 0, ""); break;
    case "playNext": if (track) playNext(track); break;
    case "addToQueue": if (track) addToQueue(track); break;
    default: throw new Error("Action inconnue");
  }
  desktopReport(true);
  return result;
}

// ── Télécommande : association du téléphone ─────────────────────────────

let remotePairingRefresh = null;

async function openRemotePairing() {
  if (!desktop) return;
  const wrap = openSheet(`<div id="pairing"><h2 class="sheet-title">Télécommande</h2><p class="muted">Chargement…</p></div>`, {
    cls: "pair-sheet", onClose: () => { remotePairingRefresh = null; },
  });
  const paint = async () => {
    const [info, s] = await Promise.all([desktop.remoteInfo(), desktop.settings()]);
    const box = $("#pairing", wrap);
    if (!box) return;
    const others = info.urls.slice(1).filter((u) => u.rank < 9);
    box.innerHTML = `<h2 class="sheet-title">Télécommande</h2>
      <p class="muted">Pilote Sona sur ce PC depuis ton téléphone : pochette, paroles, file d'attente et recherche. Le téléphone doit être sur le même Wi-Fi.</p>
      ${!s.remoteEnabled ? `<div class="pair-off">${icons.phone}<b>Télécommande désactivée</b><small>Active-la pour afficher le QR code.</small></div>`
        : info.qr ? `<div class="pair-qr"><div class="qr-frame"><img src="${info.qr}" alt="QR code d'association"></div>
            <div class="pair-steps"><b>Scanne avec l'appareil photo</b><span>Ouvre le lien : la télécommande s'affiche. Ajoute-la à l'écran d'accueil pour la retrouver.</span>
            <code>${esc(info.urls[0].url)}</code>${others.length ? `<small>Autre réseau : ${others.map((u) => esc(u.url)).join(" · ")}</small>` : ""}</div></div>`
        : `<div class="pair-off">${icons.globe}<b>${esc(info.error || "Aucun réseau trouvé")}</b><small>Connecte le PC au Wi-Fi ou à un câble réseau.</small></div>`}
      ${info.clients.length ? `<div class="pair-clients">${info.clients.map((c) => `<div class="pair-client"><span class="dot"></span>${icons.phone}<b>${esc(c.name)}</b><small>connecté ${esc(since(new Date(c.since).toISOString()))}</small></div>`).join("")}</div>` : ""}
      <div class="set-group">
        ${toggleRow("remote-on", "Télécommande sur le réseau local", "Le PC accepte les téléphones associés (réseau local uniquement).", s.remoteEnabled)}
        ${s.remoteEnabled ? linkRow("data-remote-reset", icons.lock, "Nouveau code d'association", "Les téléphones déjà associés devront rescanner") : ""}
      </div>
      <p class="fine-print">Rien ne passe ? Windows a peut-être demandé d'autoriser Sona dans son pare-feu : accepte pour les <b>réseaux privés</b>.</p>`;
    const toggleInput = $('[data-setting="remote-on"]', box);
    toggleInput.onchange = async () => { await desktop.set("remoteEnabled", toggleInput.checked); paint(); };
    $("[data-remote-reset]", box)?.addEventListener("click", async () => {
      if (!(await confirmSheet("Changer le code d'association ?", "Changer"))) return;
      await desktop.set("remoteKey");
      paint();
      toast("Nouveau code : rescanne-le avec ton téléphone");
    });
  };
  remotePairingRefresh = () => paint().catch(() => {});
  paint().catch((e) => toast(e.message));
  return wrap;
}

async function renderDesktopSettings() {
  const box = $("#desk-settings");
  if (!box) return;
  const s = await desktop.settings().catch(() => null);
  if (!s || !$("#desk-settings")) return;
  desk.name = s.deviceNameShown;
  box.innerHTML = `${linkRow("data-desk-remote", icons.phone, "Télécommande du téléphone",
      !s.remoteEnabled ? "Désactivée" : desk.clients.length ? `${plural(desk.clients.length, "téléphone connecté", "téléphones connectés")}` : "Scanne un QR code avec ton téléphone")}
    ${toggleRow("desk-mini", "Mini-lecteur", "Une petite fenêtre en verre, toujours au premier plan.", s.mini)}
    ${toggleRow("desk-closeToTray", "Continuer en arrière-plan", "Fermer la fenêtre ne coupe pas la musique : Sona reste près de l'horloge, et l'iPhone peut toujours piloter le PC.", s.closeToTray)}
    ${toggleRow("desk-launchAtLogin", "Lancer avec Windows", "Sona démarre discrètement, prêt à recevoir la musique de l'iPhone.", s.launchAtLogin)}
    ${toggleRow("desk-lyricsOverlay", "Paroles en surimpression", "Les paroles synchronisées par-dessus tes autres fenêtres (on clique au travers).", s.lyricsOverlay)}
    ${s.lyricsOverlay ? linkRow("data-desk-overlay-pos", icons.quote, "Position des paroles", s.overlayPosition === "top" ? "En haut de l'écran" : "En bas de l'écran") : ""}
    ${toggleRow("desk-discordEnabled", "Statut Discord", "« Écoute Sona » sur ton profil Discord : titre, pochette et progression — aussi pour ce que tu écoutes sur l'iPhone ou le site, tant que Sona tourne sur ce PC.", s.discordEnabled)}
    ${s.discordEnabled ? linkRow("data-desk-discord", icons.globe, "Application Discord", discordStatusText(s)) : ""}
    ${linkRow("data-desk-shortcuts", icons.bolt, "Raccourcis clavier", shortcutsSummary(s))}
    ${toggleRow("desk-pauseOnLock", "Pause quand le PC se verrouille", "Aussi en veille. La musique repart au déverrouillage.", s.pauseOnLock)}
    ${toggleRow("desk-pauseOnHeadphones", "Pause quand le casque est débranché", "Plus de musique qui part soudain dans les haut-parleurs.", s.pauseOnHeadphones)}
    ${desktop.platform === "win32" ? toggleRow("desk-gameMode", "Mode jeu automatique", "Un jeu en plein écran : plus de notifications, paroles en surimpression discrètes.", s.gameMode) : ""}
    ${linkRow("data-desk-name", icons.laptop, "Nom dans Sona Connect", s.deviceNameShown)}
    ${linkRow("data-desk-server", icons.globe, "Serveur Sona", s.serverUrl || SERVER || "Par défaut")}`;
  $("[data-desk-remote]", box).onclick = () => openRemotePairing();
  for (const key of ["mini", "closeToTray", "launchAtLogin", "lyricsOverlay", "discordEnabled", "pauseOnLock", "pauseOnHeadphones", "gameMode"]) {
    const input = $(`[data-setting="desk-${key}"]`, box);
    if (!input) continue;
    input.onchange = () => {
      haptic();
      desktop.set(key, input.checked)
        .then(() => ["lyricsOverlay", "discordEnabled"].includes(key) && setTimeout(renderDesktopSettings, key === "discordEnabled" ? 900 : 0))
        .catch((e) => { input.checked = !input.checked; toast(e.message); });
    };
  }
  $("[data-desk-overlay-pos]", box)?.addEventListener("click", async () => {
    await desktop.set("overlayPosition", s.overlayPosition === "top" ? "bottom" : "top");
    renderDesktopSettings();
  });
  $("[data-desk-discord]", box)?.addEventListener("click", async () => {
    const id = await askText({ title: "Application Discord", value: s.discordClientId, placeholder: "123456789012345678", confirm: "Enregistrer",
      hint: "Discord demande une « application » à ton nom : sur discord.com/developers/applications, crée-en une nommée « Sona » (New Application), puis copie son Application ID ici. Discord doit être ouvert sur ce PC." });
    if (id == null) return;
    await desktop.set("discordClientId", id).catch((e) => toast(deskErr(e)));
    setTimeout(renderDesktopSettings, 900);
  });
  $("[data-desk-shortcuts]", box).onclick = () => shortcutsSheet();
  $("[data-desk-name]", box).onclick = async () => {
    const name = await askText({ title: "Nom dans Sona Connect", value: s.deviceName || s.deviceNameShown, placeholder: "PC du salon", confirm: "Enregistrer", hint: "C'est le nom que tu verras sur l'iPhone pour envoyer la musique sur ce PC." });
    if (name == null) return;
    await desktop.set("deviceName", name);
    desk.name = (await desktop.settings()).deviceNameShown;
    startConnect.now?.();
    renderDesktopSettings();
  };
  $("[data-desk-server]", box).onclick = async () => {
    const url = await askText({ title: "Serveur Sona", value: s.serverUrl || SERVER, placeholder: "https://…", confirm: "Enregistrer", hint: "Laisse l'adresse par défaut sauf si ton serveur Sona a changé d'adresse. Sona redémarre." });
    if (url == null) return;
    try { await desktop.set("serverUrl", url === SERVER ? "" : url); } catch (e) { toast(e.message); }
  };
}

function discordStatusText(s) {
  if (!s.discordClientId) return "Ajoute l'identifiant de ton application Discord";
  if (s.discord?.connected) return "Connecté à Discord";
  return s.discord?.error || "Connexion à Discord…";
}

// ── Raccourcis clavier globaux (app Windows) ─────────────────────────────

const KEY_NAMES = { ArrowRight: "Right", ArrowLeft: "Left", ArrowUp: "Up", ArrowDown: "Down", " ": "Space", "+": "Plus" };

/** Combinaison appuyée → raccourci au format d'Electron (avec Ctrl, Alt ou Maj). */
function acceleratorFrom(e) {
  if (["Control", "Shift", "Alt", "Meta", "AltGraph"].includes(e.key)) return null;
  const code = /^Key([A-Z])$/.exec(e.code)?.[1] || /^Digit(\d)$/.exec(e.code)?.[1];
  const key = code || KEY_NAMES[e.key] || (e.key.length === 1 ? e.key.toUpperCase() : e.key);
  if (!/^(F\d{1,2}|[A-Z0-9]|Right|Left|Up|Down|Space|Plus|Home|End|PageUp|PageDown|Insert|Delete|[,./;'`=\-])$/.test(key)) return null;
  const mods = [e.ctrlKey && "CommandOrControl", e.altKey && "Alt", e.shiftKey && "Shift", e.metaKey && "Super"].filter(Boolean);
  return mods.length ? [...mods, key].join("+") : null;
}

const prettyAccel = (a) => a.replace("CommandOrControl", "Ctrl").replace("Super", "Win").replace("Shift", "Maj")
  .replace(/\+Right$/, "+→").replace(/\+Left$/, "+←").replace(/\+Up$/, "+↑").replace(/\+Down$/, "+↓").replace(/\+Space$/, "+Espace");

function shortcutsSummary(s) {
  const n = Object.keys(s.shortcuts || {}).length;
  if (s.shortcutsRefused?.length) return `${plural(s.shortcutsRefused.length, "raccourci déjà pris", "raccourcis déjà pris")} par une autre app`;
  return n ? plural(n, "raccourci actif", "raccourcis actifs") : "Contrôler Sona depuis n'importe quelle app";
}

async function shortcutsSheet() {
  const s = await desktop.settings();
  const map = { ...(s.shortcuts || {}) };
  let refused = s.shortcutsRefused || [];
  let capture = null;
  const onKey = (e) => {
    if (!capture) return;
    e.preventDefault();
    e.stopPropagation();
    if (e.key === "Escape") { capture = null; return paint(); }
    const accelerator = acceleratorFrom(e);
    if (!accelerator) return;
    for (const [id, acc] of Object.entries(map)) if (acc === accelerator) delete map[id];
    map[capture] = accelerator;
    capture = null;
    save();
  };
  document.addEventListener("keydown", onKey, true);
  const wrap = openSheet(`<h2 class="sheet-title">Raccourcis clavier</h2>
    <p class="muted">Ils marchent même quand Sona est en arrière-plan. Touche un bouton, puis appuie sur la combinaison (avec Ctrl, Alt ou Maj). Les touches multimédia du clavier marchent déjà sans rien régler.</p>
    <div class="set-group" id="sc-list"></div>`, { onClose: () => { document.removeEventListener("keydown", onKey, true); renderDesktopSettings(); } });
  const list = $("#sc-list", wrap);
  function paint() {
    list.innerHTML = Object.entries(s.shortcutActions || {}).map(([id, label]) => `<div class="set-row sc-row">
      <span class="set-text"><b>${esc(label)}</b>${refused.includes(id) ? `<small class="sc-bad">Déjà pris par une autre app : choisis-en un autre</small>` : ""}</span>
      <button class="btn ghost small ${capture === id ? "capturing" : ""}" data-sc="${id}">${capture === id ? "Appuie sur la combinaison…" : map[id] ? esc(prettyAccel(map[id])) : "Définir"}</button>
      ${map[id] ? `<button class="dev-more" data-sc-clear="${id}" aria-label="Retirer">${icons.close}</button>` : ""}</div>`).join("");
  }
  async function save() {
    try { refused = (await desktop.set("shortcuts", map)) || []; } catch (e) { toast(deskErr(e)); }
    paint();
  }
  list.onclick = (e) => {
    const clear = e.target.closest("[data-sc-clear]")?.dataset.scClear;
    if (clear) { delete map[clear]; capture = null; return save(); }
    const id = e.target.closest("[data-sc]")?.dataset.sc;
    if (id) { capture = capture === id ? null : id; paint(); }
  };
  paint();
}

// ── Sona sur l'iPhone (app Windows) ──────────────────────────────────────
// Comme CordLauncher : Sona s'installe sur l'iPhone depuis le PC, signée
// avec le compte Apple de l'utilisateur, par câble ou en Wi-Fi, puis elle est
// renouvelée avant d'expirer et mise à jour toute seule (mode automatique).
// Le travail est fait par l'app (desktop/src/iphone.js + sona-iphone).

const iph = { state: null, target: null, twoFactorSheet: null, cleanup: null };
const deskErr = (e) => String(e?.message || e || "Erreur").replace(/^Error invoking remote method '[^']+': (Error: )?/, "");
const PHASES = {
  account: "Connexion au compte Apple", downloading: "Téléchargement de Sona", preparing: "Préparation (compte, appareil)",
  signing: "Signature avec ton compte Apple", installing: "Envoi sur l'iPhone", done: "Terminé",
};

function iphoneInit() {
  if (!desktop?.onIphone) return;
  desktop.onIphone((model) => { iph.state = model; iphoneChanged(); });
  desktop.iphoneState().then((model) => { iph.state = model; iphoneChanged(); }).catch(() => {});
  desktop.onOpen((hash) => { if (account) location.hash = hash; });
  desktop.onUpdates((model) => renderUpdates(model));
}

/** Rafraîchit ce qui dépend de l'état iPhone : pastille, page ouverte, fenêtre de code. */
function iphoneChanged() {
  const m = iph.state;
  if (!m) return;
  const badge = $("#iph-badge");
  if (badge) {
    const n = (m.apps || []).filter((a) => iphoneUpdate(a) || iphoneHealth(a) !== "ok").length;
    badge.textContent = n ? String(n) : "";
  }
  if (location.hash.startsWith("#/iphone") && $("#iphone-root")) $("#iphone-root").innerHTML = iphoneBody();
  if ($("#desk-updates")) renderUpdates();
  iphoneTwoFactor();
}

const iphoneUpdate = (a) => {
  const latest = iph.state?.latest;
  if (!latest || !a.version) return null;
  const pa = latest.version.split(".").map(Number), pb = a.version.split(".").map(Number);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) if ((pa[i] || 0) !== (pb[i] || 0)) return (pa[i] || 0) > (pb[i] || 0) ? latest : null;
  return null;
};
const iphoneDays = (a) => (a.expiresAt == null ? null : (a.expiresAt - Date.now()) / 86_400_000);
function iphoneHealth(a) {
  const d = iphoneDays(a);
  if (d == null) return "ok";
  return d <= 0 ? "expired" : d <= 1 ? "urgent" : d <= 2 ? "soon" : "ok";
}
function leftLabel(a) {
  const d = iphoneDays(a);
  if (d == null) return "";
  if (d <= 0) return "Expirée";
  if (d < 1) return `${Math.max(1, Math.round(d * 24))} h`;
  return `${Math.floor(d)} j`;
}

async function viewIphone() {
  if (!iph.state) iph.state = await desktop.iphoneState().catch(() => null);
  setTimeout(() => {
    desktop.iphone("refresh").catch(() => {});
    if (!iph.state?.latest) desktop.iphone("check").catch(() => {});
    bindIphone();
  });
  return page(`<h1 class="page-title">Sona sur l'iPhone</h1>
    <p class="page-sub">Installe Sona sur ton iPhone depuis ce PC, avec ton compte Apple. Elle reste ensuite à jour et se renouvelle toute seule, par câble ou en Wi-Fi.</p>
    <div id="iphone-root">${iphoneBody()}</div>`);
}

function iphoneTargetDevice(m) {
  const reachable = (m.devices || []).filter((d) => d.connection !== "offline");
  if (iph.target && (m.devices || []).some((d) => d.udid === iph.target)) return (m.devices || []).find((d) => d.udid === iph.target);
  const withApp = reachable.find((d) => (m.apps || []).some((a) => a.udid === d.udid));
  return withApp || reachable.find((d) => d.trusted) || reachable[0] || (m.devices || [])[0] || null;
}

function iphoneBody() {
  const m = iph.state;
  if (!m) return `<p class="muted">Chargement…</p>`;
  if (!m.available) {
    return `<div class="iph-card"><div class="pair-off">${icons.phone}<b>Module iPhone absent</b><small>Cette version de Sona a été fabriquée sans lui. Installe la dernière version de Sona pour Windows.</small></div></div>`;
  }
  const device = iphoneTargetDevice(m);
  const installed = device ? (m.apps || []).find((a) => a.udid === device.udid) : (m.apps || [])[0];
  const profile = (m.status?.profiles || []).find((p) => p.active);
  const ready = !!profile && (profile.connected || profile.remembered);
  const reachable = device && device.trusted && device.connection !== "offline";
  const upd = installed && iphoneUpdate(installed);
  const health = installed ? iphoneHealth(installed) : "ok";
  const busy = m.busy;
  const progress = m.progress;
  const pct = progress && progress.progress >= 0 ? Math.round(progress.progress * 100) : null;
  const days = installed ? iphoneDays(installed) : null;
  const total = installed?.expiresAt && installed?.installedAt ? Math.max(1, (installed.expiresAt - installed.installedAt) / 86_400_000) : 7;
  const ring = days == null ? 1 : Math.max(0, Math.min(1, days / total));

  let action = "";
  const disabled = busy || !reachable || !ready ? "disabled" : "";
  if (!installed) action = `<button class="btn" data-iph="install" ${disabled}>${icons.download} Installer Sona${m.latest ? ` ${esc(m.latest.version)}` : ""}</button>`;
  else if (upd) action = `<button class="btn" data-iph="update" ${disabled}>${icons.download} Mettre à jour vers ${esc(upd.version)}</button>`;
  else action = `<button class="btn ${health === "ok" ? "ghost" : ""}" data-iph="renew" ${disabled || (!installed.ipa ? "disabled" : "")}>${icons.repeat} Renouveler</button>`;
  const why = busy ? "" : !ready ? "Connecte d'abord ton compte Apple, juste en dessous."
    : !device ? "Branche ton iPhone à ce PC avec un câble."
    : device.connection === "offline" ? `${esc(device.name || "L'iPhone")} n'est ni branché ni sur le même Wi-Fi que ce PC.`
    : !device.trusted ? "Déverrouille l'iPhone et touche « Se fier à cet ordinateur »." : "";

  const hero = `<div class="iph-hero">
    <div class="iph-ring ${health}" style="--r:${ring}"><img src="icons/icon-192.png" alt=""><span class="iph-left">${installed ? esc(leftLabel(installed)) : ""}</span></div>
    <div class="iph-hero-text">
      <span class="eyebrow">${installed ? (health === "expired" ? "Expirée" : health === "ok" ? "Installée" : "À renouveler bientôt") : "Pas encore installée"}${device?.name ? ` · ${esc(device.name)}` : ""}</span>
      <h2>Sona ${installed?.version ? esc(installed.version) : m.latest ? esc(m.latest.version) : ""}</h2>
      <p>${installed
        ? `${installed.expiresAt ? `Valable jusqu'au ${new Date(installed.expiresAt).toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" })}${health === "ok" ? "" : " — renouvelle-la pour la garder"}.` : "Suivie par Sona."}${upd ? ` La version ${esc(upd.version)} est sortie.` : ""}`
        : "Ta musique, tes playlists et Sona Connect sur l'iPhone. Signée avec ton compte Apple, gratuitement."}</p>
      ${busy ? `<div class="iph-progress"><div class="iph-progress-head"><b>${esc(PHASES[progress?.phase] || busy)}</b><span>${pct != null ? `${pct} %` : ""}</span></div>
        <div class="iph-bar ${pct == null ? "indeterminate" : ""}"><i style="width:${pct ?? 30}%"></i></div></div>`
        : `<div class="iph-actions">${action}${installed ? `<button class="btn ghost" data-iph="menu">${icons.more}</button>` : ""}</div>
        ${why ? `<p class="iph-why">${why}</p>` : ""}`}
      ${m.error && !busy ? `<p class="iph-error">${esc(m.error)}</p>` : ""}
    </div></div>`;

  const devices = (m.devices || []).map((d) => {
    const conn = { usb: "Câble", wifi: "Wi-Fi", offline: "Hors de portée" }[d.connection] || d.connection;
    const app = (m.apps || []).find((a) => a.udid === d.udid);
    return `<div class="iph-device ${device && d.udid === device.udid ? "on" : ""}" data-iph-device="${esc(d.udid)}" role="button">
      <span class="dp-icon">${icons.phone}</span>
      <span class="iph-device-text"><b>${esc(d.name || "iPhone")}</b>
        <small>${d.iosVersion ? `iOS ${esc(d.iosVersion)} · ` : ""}<span class="pill-mini ${d.connection}">${conn}</span>${!d.trusted && d.connection === "usb" ? " · touche « Se fier » sur l'iPhone" : ""}${app?.version ? ` · Sona ${esc(app.version)}` : ""}</small></span>
      ${d.connection === "usb" && d.trusted ? `<label class="iph-wifi" title="Renouveler et mettre à jour sans câble, sur le même Wi-Fi"><span>Wi-Fi</span><input type="checkbox" data-iph-wifi="${esc(d.udid)}" ${d.wifi ? "checked" : ""}><i></i></label>` : ""}
    </div>`;
  }).join("");

  const profiles = (m.status?.profiles || []).map((p) => `<div class="iph-profile ${p.active ? "on" : ""}">
      ${avatar(null, p.email, "avatar")}
      <span class="iph-device-text"><b>${esc(p.email)}</b><small>${p.active ? "Signe Sona · " : ""}${p.pausedFor ? `En pause ${Math.ceil(p.pausedFor / 60)} min (Apple) · ` : ""}${p.connected ? "Connecté" : p.remembered ? "Mot de passe mémorisé" : "À reconnecter"}</small></span>
      <span class="iph-profile-acts">${p.active ? "" : `<button class="btn ghost small" data-iph-switch="${esc(p.email)}">Utiliser</button>`}
        ${!p.connected && !p.remembered ? `<button class="btn ghost small" data-iph-login="${esc(p.email)}">Se connecter</button>` : ""}
        <button class="tbtn small" data-iph-forget="${esc(p.email)}" title="Oublier ce compte">${icons.close}</button></span>
    </div>`).join("");

  return `${hero}
    <div class="iph-grid">
      <section class="iph-card"><div class="iph-card-head"><h3>Ton iPhone</h3><button class="tbtn small ${m.scanning ? "spin" : ""}" data-iph="refresh" title="Actualiser">${icons.repeat}</button></div>
        ${devices || `<div class="iph-empty">${icons.phone}<b>${m.devicesError ? esc(m.devicesError) : "Aucun iPhone branché"}</b>
          <small>${m.devicesError ? "Puis branche l'iPhone avec un câble." : "Branche-le avec un câble, déverrouille-le et touche « Se fier ». Ensuite, active le Wi-Fi ici pour te passer du câble."}</small></div>`}
      </section>
      <section class="iph-card"><div class="iph-card-head"><h3>Compte Apple</h3></div>
        ${profiles || `<p class="muted iph-note">Sona signe l'app avec ton compte Apple (gratuit). Le mot de passe reste sur ce PC, dans le coffre de Windows.</p>`}
        <div class="iph-card-foot"><button class="btn ${profiles ? "ghost" : ""}" data-iph="add-account">${icons.plus} ${profiles ? "Ajouter un compte" : "Connecter mon compte Apple"}</button></div>
      </section>
      <section class="iph-card"><div class="iph-card-head"><h3>Automatique</h3></div>
        <div class="set-group flat">${toggleRow("iph-auto", "Mises à jour et renouvellement automatiques", "Sona installe chaque nouvelle version et renouvelle l'app deux jours avant qu'elle expire, dès que l'iPhone est branché ou sur le même Wi-Fi. Sinon, un rappel la veille.", m.auto)}</div>
        <p class="iph-note muted">${m.latest ? `Dernière version : Sona ${esc(m.latest.version)}` : "Dernière version inconnue"}${m.lastCheck ? ` · vérifié ${esc(since(new Date(m.lastCheck).toISOString()))}` : ""}</p>
        <div class="iph-card-foot"><button class="btn ghost" data-iph="check" ${m.checking ? "disabled" : ""}>${m.checking ? "Recherche…" : "Rechercher une mise à jour"}</button></div>
      </section>
      <section class="iph-card iph-help"><div class="iph-card-head"><h3>Première installation</h3></div>
        <ol class="steps">
          <li>Installe <b>Appareils Apple</b> (Microsoft Store) ou <b>iTunes</b> : Windows en a besoin pour parler à l'iPhone.</li>
          <li>Branche l'iPhone, déverrouille-le et touche <b>Se fier</b>.</li>
          <li>Connecte ton compte Apple ici, puis <b>Installer Sona</b>.</li>
          <li>Sur l'iPhone : <b>Réglages › Général › VPN et gestion de l'appareil</b> › fais confiance à ton compte, puis active le <b>mode développeur</b> si iOS le demande.</li>
        </ol>
        <p class="iph-note muted">Compte Apple gratuit : l'app est valable 7 jours (Sona la renouvelle) et 3 apps au plus par iPhone.</p>
      </section>
    </div>`;
}

function bindIphone() {
  const root = $("#iphone-root");
  if (!root || root._bound) return;
  root._bound = true;
  const run = async (name, args, done) => {
    try { await desktop.iphone(name, args); if (done) toast(done); } catch (e) { toast(deskErr(e)); }
  };
  root.addEventListener("click", async (e) => {
    const target = (sel) => e.target.closest(sel);
    const device = iphoneTargetDevice(iph.state || {});
    const udid = device?.udid;
    if (target("[data-iph-wifi]") || target(".iph-wifi")) return;
    const act = target("[data-iph]")?.dataset.iph;
    if (act === "refresh") return run("refresh");
    if (act === "check") return run("check");
    if (act === "install") return run("install", { udid });
    if (act === "update") return run("update", { udid });
    if (act === "renew") return run("renew", { udid });
    if (act === "add-account") return appleLoginSheet();
    if (act === "menu") {
      return actionSheet("Sona sur l'iPhone", [
        { icon: icons.download, label: "Réinstaller la dernière version", run: () => run("install", { udid }) },
        { icon: icons.install, label: "Installer un fichier .ipa…", sub: "Une version précise de Sona", run: async () => { const file = await desktop.iphonePick(); if (file) run("installFile", { udid, file }); } },
        { icon: icons.lock, label: "Réinitialiser l'appareil Apple", sub: "Si Apple refuse les connexions : il redemandera un code", run: async () => { if (await confirmSheet("Réinitialiser l'appareil présenté à Apple ?", "Réinitialiser")) run("resetDevice", {}, "Appareil Apple réinitialisé"); } },
        { icon: icons.list, label: "Ouvrir le journal", run: () => desktop.iphoneLogs().then((ok) => !ok && toast("Rien dans le journal pour l'instant")) },
        { icon: icons.trash, label: "Ne plus suivre sur cet iPhone", sub: "Sona reste installée, mais ne sera plus renouvelée", danger: true, run: () => run("forgetApp", { udid }) },
      ]);
    }
    const dev = target("[data-iph-device]");
    if (dev) { iph.target = dev.dataset.iphDevice; iphoneChanged(); return; }
    const sw = target("[data-iph-switch]");
    if (sw) return run("switch", { email: sw.dataset.iphSwitch }, "Compte Apple changé");
    const login = target("[data-iph-login]");
    if (login) return appleLoginSheet(login.dataset.iphLogin);
    const forget = target("[data-iph-forget]");
    if (forget && (await confirmSheet(`Oublier ${forget.dataset.iphForget} sur ce PC ?`, "Oublier"))) return run("forget", { email: forget.dataset.iphForget });
  });
  root.addEventListener("change", (e) => {
    const wifi = e.target.closest("[data-iph-wifi]");
    if (wifi) return run("setWifi", { udid: wifi.dataset.iphWifi, enabled: wifi.checked }, wifi.checked ? "Wi-Fi activé : plus besoin du câble sur le même réseau" : "Wi-Fi coupé");
    if (e.target.matches('[data-setting="iph-auto"]')) run("setAuto", { auto: e.target.checked });
  });
}

/** Connexion d'un compte Apple (la 2FA arrive ensuite dans sa propre fenêtre). */
function appleLoginSheet(email = "") {
  const wrap = openSheet(`<h2 class="sheet-title">Compte Apple</h2>
    <p class="muted">Sona signe l'app avec ton identifiant Apple, comme Sideloadly ou AltStore. Le mot de passe ne quitte pas ce PC.</p>
    <form class="ask" id="apple-form">
      <input class="field" name="email" type="email" placeholder="Identifiant Apple" value="${esc(email)}" autocomplete="username" required>
      <input class="field" name="password" type="password" placeholder="Mot de passe" autocomplete="current-password" required>
      <label class="switch-row flat"><span><b>Mémoriser sur ce PC</b><small>Dans le coffre de Windows : Sona renouvelle l'app chaque semaine sans rien te redemander.</small></span><input type="checkbox" name="remember" checked><i></i></label>
      <p class="iph-error" id="apple-error" hidden></p>
      <div class="pill-row"><button type="button" class="btn ghost" data-cancel>Annuler</button><button class="btn" type="submit">Se connecter</button></div>
    </form>`);
  const form = $("#apple-form", wrap);
  setTimeout(() => $(email ? "[name=password]" : "[name=email]", form)?.focus(), 250);
  $("[data-cancel]", wrap).onclick = () => wrap.close();
  form.onsubmit = async (e) => {
    e.preventDefault();
    const button = $("button[type=submit]", form);
    button.disabled = true;
    button.textContent = "Connexion…";
    $("#apple-error", wrap).hidden = true;
    try {
      await desktop.iphone("login", { email: form.email.value.trim(), password: form.password.value, remember: form.remember.checked });
      wrap.close();
      toast("Compte Apple connecté");
    } catch (err) {
      const box = $("#apple-error", wrap);
      if (box) { box.textContent = deskErr(err); box.hidden = false; }
      button.disabled = false;
      button.textContent = "Se connecter";
    }
  };
}

/** Code de vérification Apple : la fenêtre s'ouvre quand le module le demande. */
function iphoneTwoFactor() {
  const tf = iph.state?.twoFactor;
  if (!tf) { iph.twoFactorSheet?.close(); iph.twoFactorSheet = null; return; }
  if (iph.twoFactorSheet) return;
  const numbers = tf.numbers || tf.trustedPhoneNumbers || [];
  const wrap = openSheet(`<h2 class="sheet-title">Code de vérification Apple</h2>
    <p class="muted">Apple vient d'envoyer un code à tes appareils pour ${esc(tf.email || "ton compte")}. Saisis-le ici.</p>
    <form class="ask" id="tf-form">
      <input class="field tf-code" name="code" inputmode="numeric" pattern="[0-9]{6}" maxlength="6" placeholder="000000" autocomplete="one-time-code" required>
      ${tf.lastError ? `<p class="iph-error">${esc(tf.lastError)}</p>` : ""}
      <div class="pill-row"><button type="button" class="btn ghost" data-tf="resend">Renvoyer</button>
        ${numbers.length ? `<button type="button" class="btn ghost" data-tf="sms">Par SMS</button>` : ""}
        <button type="button" class="btn ghost" data-tf="abort">Annuler</button><button class="btn" type="submit">Valider</button></div>
    </form>`, { onClose: () => { if (iph.twoFactorSheet === wrap) { iph.twoFactorSheet = null; if (iph.state?.twoFactor) desktop.iphone("twoFactor", { response: "Abort" }).catch(() => {}); } } });
  iph.twoFactorSheet = wrap;
  const form = $("#tf-form", wrap);
  setTimeout(() => form.code.focus(), 250);
  form.code.oninput = () => { form.code.value = form.code.value.replace(/\D/g, "").slice(0, 6); if (form.code.value.length === 6) form.requestSubmit(); };
  const respond = (response) => desktop.iphone("twoFactor", { response }).catch((e) => toast(deskErr(e)));
  form.onsubmit = (e) => { e.preventDefault(); if (form.code.value.length === 6) { $("button[type=submit]", form).textContent = "Vérification…"; respond({ SubmitCode: form.code.value }); } };
  $('[data-tf="resend"]', wrap).onclick = () => respond("ResendCode");
  $('[data-tf="abort"]', wrap).onclick = () => { iph.twoFactorSheet = null; respond("Abort"); wrap.close(); };
  $('[data-tf="sms"]', wrap)?.addEventListener("click", () => actionSheet("Recevoir le code par SMS", numbers.map((n) => ({
    icon: icons.phone, label: n.numberWithDialCode || `••• ${n.lastTwoDigits}`, run: () => respond({ SendSms: n.id }),
  }))));
}

// ── Mises à jour (app Windows et Sona sur l'iPhone) ──────────────────────

let updatesState = null;

async function renderUpdates(model) {
  const box = $("#desk-updates");
  if (!box || !desktop?.updates) return;
  if (model) updatesState = model;
  if (!updatesState) updatesState = await desktop.updates("state").catch(() => null);
  const u = updatesState;
  if (!u || !$("#desk-updates")) return;
  const m = iph.state;
  const iphoneApp = (m?.apps || [])[0];
  const iphoneUpd = iphoneApp && iphoneUpdate(iphoneApp);
  const winLine = u.downloading != null ? `Téléchargement… ${Math.round(u.downloading * 100)} %`
    : u.available ? `Sona ${esc(u.latest.version)} est disponible (tu as la ${esc(u.current)})`
    : u.checking ? "Recherche…"
    : `Version ${esc(u.current)}${u.lastCheck ? ` · à jour, vérifié ${esc(since(new Date(u.lastCheck).toISOString()))}` : ""}`;
  box.innerHTML = `<div class="set-row"><span class="mi-icon">${icons.laptop}</span><span class="set-text"><b>Sona pour Windows</b><small>${winLine}</small></span>
      ${u.available && u.downloading == null ? `<button class="btn small" data-upd="install">${u.portable ? "Télécharger" : "Mettre à jour"}</button>` : ""}</div>
    <a class="set-row" href="#/iphone"><span class="mi-icon">${icons.phone}</span><span class="set-text"><b>Sona sur l'iPhone</b><small>${
      !m?.available ? "Module iPhone absent de cette version"
      : iphoneApp ? `${esc(iphoneApp.version || "?")} sur ${esc(iphoneApp.deviceName || "l'iPhone")}${iphoneUpd ? ` · ${esc(iphoneUpd.version)} disponible` : " · à jour"}${iphoneApp.expiresAt ? ` · expire ${esc(new Date(iphoneApp.expiresAt).toLocaleDateString("fr-FR", { day: "numeric", month: "short" }))}` : ""}`
      : m?.latest ? `Pas encore installée · dernière version ${esc(m.latest.version)}` : "Pas encore installée"}</small></span>${icons.right}</a>
    ${toggleRow("upd-check", "Rechercher automatiquement", "Au démarrage puis toutes les 6 heures, pour Windows et pour l'iPhone.", u.autoCheck)}
    ${u.portable ? "" : toggleRow("upd-install", "Installer sans demander", "Sona se met à jour tout seul et redémarre (la musique reprend où elle en était sur l'iPhone si tu changes d'appareil).", u.autoInstall)}
    <div class="set-row"><span class="set-text">${u.error ? `<small class="iph-error">${esc(u.error)}</small>` : `<small>Les nouvelles versions arrivent à chaque mise à jour de Sona.</small>`}</span>
      <button class="btn ghost small" data-upd="check" ${u.checking || m?.checking ? "disabled" : ""}>Rechercher</button></div>`;
  $('[data-upd="install"]', box)?.addEventListener("click", () => desktop.updates("install").catch((e) => toast(deskErr(e))));
  $('[data-upd="check"]', box).onclick = async () => {
    const [win] = await Promise.all([desktop.updates("check").catch((e) => ({ error: deskErr(e) })), desktop.iphone("check").catch(() => null)]);
    if (win?.error) toast(win.error);
    else if (!win?.available) toast("Sona est à jour");
  };
  $('[data-setting="upd-check"]', box).onchange = (e) => desktop.updates("updatesCheck", e.target.checked);
  $('[data-setting="upd-install"]', box)?.addEventListener("change", (e) => desktop.updates("updatesInstall", e.target.checked));
}

desktopInit();
iphoneInit();

boot();

window.resumeHere = resumeHere;
