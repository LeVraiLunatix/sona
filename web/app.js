/* Sona sur ordinateur : même compte, mêmes playlists, mêmes stats que l'app.
   Connexion Last.fm, puis tout passe par l'API du serveur Sona (jeton de
   session gardé dans le navigateur). Servi par le serveur lui-même (/web/)
   ou par Vercel : dans ce cas l'API est appelée à l'adresse de la balise
   <meta name="sona-server">. */

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

const SERVER = ($('meta[name="sona-server"]')?.content || "").replace(/\/$/, "");
const onServer = !SERVER || location.pathname.startsWith("/web") || (() => { try { return new URL(SERVER).origin === location.origin; } catch { return true; } })();
const BASE = onServer ? "" : SERVER;

let token = store.get("sona.token");
let account = null;
const audio = $("#audio");
const state = {
  queue: [], index: -1, name: "", shuffle: false, repeat: false,
  lyrics: null, lastLyric: -1, listened: 0, lastTick: 0, scrobbled: false, startedAt: null,
  liked: new Set(), npOpen: false, npTab: "lyrics", smart: [], playlists: [],
  connect: { devices: [], session: null, active: null, receivedAt: 0, claim: false, open: false },
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
    throw new Error(typeof msg === "string" ? msg : `Erreur ${res.status}`);
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
  pulse: ic("M3 12h3.2l2.3-6.2c.3-.9 1.6-.9 1.9 0l3.6 11.7 2.2-5c.2-.3.5-.5.9-.5H21a1 1 0 1 1 0 2h-3.1l-2.9 6.4c-.4.8-1.6.8-1.9-.1L9.5 8.9 7.9 13.3c-.1.4-.5.7-.9.7H3a1 1 0 1 1 0-2z"),
  logo: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5.5 10v4M9.5 6.5v11M13.5 9v6M17.5 11v2" stroke="#fff" stroke-width="2.3" stroke-linecap="round" fill="none"/></svg>`,
};
const bars = () => `<span class="bars ${audio.paused ? "paused" : ""}"><i></i><i></i><i></i></span>`;

// ── Connexion ──────────────────────────────────────────────────────────────

async function boot() {
  const params = new URLSearchParams(location.search);
  const lastfmToken = params.get("token");
  if (lastfmToken) {
    history.replaceState(null, "", location.pathname + location.hash);
    try {
      const res = await fetch(BASE + "/auth/lastfm", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token: lastfmToken }),
      });
      const body = await res.json();
      if (!res.ok) return renderLogin(body.detail || "Connexion refusée.");
      token = body.session_token;
      store.set("sona.token", token);
    } catch { return renderLogin("Serveur Sona injoignable."); }
  }
  if (!token) return renderLogin();
  try {
    account = await api("/auth/me");
  } catch (e) { return renderLogin(token ? e.message : null); }
  if (account.status !== "approved") {
    return renderLogin(account.status === "rejected" ? "Accès refusé par un administrateur." : "Ton compte attend la validation d'un administrateur.");
  }
  renderShell();
  startConnect();
  loadSidebar();
  loadLiked();
  route();
}

async function renderLogin(error) {
  document.body.style.overflow = "hidden";
  const config = await fetch(BASE + "/auth/config").then((r) => r.json()).catch(() => ({}));
  const cb = location.origin + location.pathname;
  const url = config.api_key ? `https://www.last.fm/api/auth/?api_key=${encodeURIComponent(config.api_key)}&cb=${encodeURIComponent(cb)}` : null;
  $("#root").innerHTML = `<div class="login"><div class="login-bg"></div><div class="login-card">
    <div class="brand-mark">${icons.logo}</div>
    <h1>Sona</h1>
    <p>Ta musique, tes playlists et tes paroles.<br>Maintenant sur ton ordinateur.</p>
    ${url ? `<a class="btn" href="${esc(url)}">Se connecter avec Last.fm</a>` : '<p class="error">Serveur Sona injoignable ou connexion Last.fm non configurée.</p>'}
    ${error ? `<p class="error">${esc(error)}</p>` : ""}
    <p class="fine">Le même compte que dans l'app Sona.</p>
  </div></div>`;
}

function signOut() {
  token = null;
  store.set("sona.token", null);
  audio.pause();
  renderLogin();
}

// ── Coquille ───────────────────────────────────────────────────────────────

const NAV = [
  ["home", "Écouter", icons.listen],
  ["search", "Rechercher", icons.search],
  ["library", "Titres", icons.note],
  ["playlists", "Playlists", icons.list],
];

function renderShell() {
  const name = account.display_name || account.username;
  $("#root").innerHTML = `<div class="app">
    <aside class="sidebar">
      <div class="brand"><span class="brand-mark">${icons.logo}</span>Sona</div>
      <label class="side-search">${icons.search}<input id="side-q" type="search" placeholder="Rechercher" autocomplete="off"></label>
      <div class="side-list scroll">
        ${NAV.map(([id, label, icon]) => `<a class="side-link" href="#/${id}" data-nav="${id}">${icon}${label}</a>`).join("")}
        <div class="side-section">Faites pour toi</div>
        <div id="side-smart"></div>
        <div class="side-section">Playlists</div>
        <div id="side-playlists"></div>
        ${account.is_admin ? `<div class="side-section">Administration</div>
        <a class="side-link" href="#/health" data-nav="health">${icons.pulse}Santé de la lecture</a>` : ""}
      </div>
      <div class="side-user">
        ${account.avatar_url ? `<img src="${esc(account.avatar_url)}" alt="">` : `<span class="avatar-fallback">${esc(name[0] || "?")}</span>`}
        <span class="name">${esc(name)}</span>
        <button id="signout" title="Se déconnecter">Quitter</button>
      </div>
    </aside>
    <header class="topbar" id="topbar"></header>
    <main class="content scroll" id="content"></main>
    <nav class="tabbar">${NAV.map(([id, label, icon]) => `<button data-tab="${id}">${icon}${label}</button>`).join("")}</nav>
  </div>
  <section class="np" id="np" aria-label="Lecture en cours"></section>`;
  $("#signout").onclick = async () => { try { await api("/auth/logout", { method: "POST" }); } catch {} signOut(); };
  $("#side-q").addEventListener("keydown", (e) => {
    if (e.key === "Enter") location.hash = `#/search/${encodeURIComponent(e.target.value.trim())}`;
  });
  $("#side-q").addEventListener("focus", () => { if (!location.hash.startsWith("#/search")) location.hash = "#/search"; });
  $$(".tabbar button").forEach((b) => (b.onclick = () => (location.hash = `#/${b.dataset.tab}`)));
  renderTopbar();
  renderNowPlaying();
}

async function loadSidebar() {
  const [smart, playlists] = await Promise.all([
    api(`/smart?tz=${encodeURIComponent(tz())}`).catch(() => []),
    api("/me/playlists").catch(() => []),
  ]);
  state.smart = smart;
  state.playlists = playlists;
  $("#side-smart").innerHTML = smart.map((s) => `<a class="side-link" href="#/smart/${esc(s.id)}" data-nav="smart/${esc(s.id)}">
    <img class="thumb" src="${esc(s.covers[0] || "")}" alt="">${esc(s.title)}</a>`).join("");
  $("#side-playlists").innerHTML = playlists.map((p) => `<a class="side-link" href="#/playlist/${p.id}" data-nav="playlist/${p.id}">
    <img class="thumb" src="${esc(p.cover_url || (p.covers || [])[0] || "")}" alt="">${esc(p.name)}</a>`).join("")
    || '<p class="side-link" style="color:var(--text-3)">Aucune playlist</p>';
  markNav();
}

async function loadLiked() {
  const page = await api("/library/track?limit=500").catch(() => ({ items: [] }));
  state.liked = new Set((page.items || []).map((i) => `${i.source}:${i.source_id}`));
}

const tz = () => Intl.DateTimeFormat().resolvedOptions().timeZone || "Europe/Paris";

function markNav() {
  const current = location.hash.replace(/^#\//, "") || "home";
  $$("[data-nav]").forEach((a) => a.classList.toggle("active", current === a.dataset.nav || (a.dataset.nav === "search" && current.startsWith("search"))));
  $$("[data-tab]").forEach((b) => b.classList.toggle("active", current.startsWith(b.dataset.tab)));
}

// ── Routes ────────────────────────────────────────────────────────────────

window.addEventListener("hashchange", () => token && account && route());

async function route() {
  const parts = (location.hash.replace(/^#\//, "") || "home").split("/").map(decodeURIComponent);
  markNav();
  const content = $("#content");
  if (!content) return;
  content.scrollTop = 0;
  const views = {
    home: viewHome, search: () => viewSearch(parts[1] || ""), library: viewLibrary, playlists: viewPlaylists,
    album: () => viewAlbum(parts[1], parts[2]), artist: () => viewArtist(parts[1], parts[2]),
    playlist: () => viewUserPlaylist(parts[1]), smart: () => viewSmart(parts[1]), mix: () => viewMix(parts[1]),
    health: viewHealth,
  };
  const view = views[parts[0]] || viewHome;
  const token_ = (route.seq = (route.seq || 0) + 1);
  try {
    const html = await view();
    if (token_ !== route.seq || html == null) return;
    content.innerHTML = html;
    bindPage(content);
  } catch (e) {
    if (token_ !== route.seq) return;
    content.innerHTML = page(`<div class="empty"><div class="big">⚠︎</div><h3>Impossible d'afficher cette page</h3><p>${esc(e.message)}</p></div>`);
  }
}

const page = (inner) => `<div class="page">${inner}</div>`;
const skeleton = (title) => page(`<h1 class="page-title">${esc(title)}</h1>
  <div class="section"><div class="shelf">${Array.from({ length: 5 }, () => '<div><div class="skeleton sk-card"></div><div class="skeleton sk-line"></div></div>').join("")}</div></div>`);

// Données des pages, pour les actions (lecture d'une liste, etc.).
const registry = new Map();
let registrySeq = 0;
function register(tracks, name) {
  const id = `l${++registrySeq}`;
  registry.set(id, { tracks: (tracks || []).filter((t) => t && t.source && t.source_id), name });
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

function trackTable(tracks, name, { numbers = true, showAlbum = true } = {}) {
  const list = register(tracks, name);
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
      </span></div>`;
  }).join("")}</div>`;
}

function trackGrid(tracks, name) {
  const list = register(tracks, name);
  const current = state.queue[state.index];
  return `<div class="track-grid" data-list="${list}">${tracks.map((t, i) => `
    <button class="mini ${sameTrack(t, current) ? "current" : ""}" data-i="${i}">
      <img src="${esc(big(t.cover_url, 120))}" alt="" loading="lazy">
      <span style="min-width:0"><div class="t">${esc(t.title)}</div><div class="s">${esc(t.artist)}</div></span>
      <span></span></button>`).join("")}</div>`;
}

function hero({ cover, kind, title, by, byHref, info, list, round }) {
  return `<div class="hero">
    <div class="hero-glow"><img src="${esc(big(cover, 300))}" alt=""></div>
    <img class="hero-art ${round ? "round" : ""}" src="${esc(big(cover, 600))}" alt="">
    <div><div class="kind">${esc(kind)}</div><h1>${esc(title)}</h1>
      ${by ? (byHref ? `<a class="by link" href="${esc(byHref)}">${esc(by)}</a>` : `<div class="by">${esc(by)}</div>`) : ""}
      ${info ? `<div class="info">${esc(info)}</div>` : ""}
      ${list ? `<div class="actions"><button class="btn" data-play="${list}">${icons.play} Lecture</button>
        <button class="btn ghost" data-shuffle="${list}">${icons.shuffle} Aléatoire</button></div>` : ""}
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
      playList(data.tracks, +row.dataset.i, data.name);
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

async function viewHome() {
  $("#content").innerHTML = skeleton("Écouter");
  const [mixes, recent, releases, smart] = await Promise.all([
    api("/home/mixes").catch(() => []),
    api("/plays/recent?limit=60").catch(() => []),
    api("/releases").catch(() => []),
    state.smart.length ? state.smart : api(`/smart?tz=${encodeURIComponent(tz())}`).catch(() => []),
  ]);
  const seen = new Set();
  const recentTracks = recent.filter((p) => p.source && p.source_id && !seen.has(p.source + p.source_id) && seen.add(p.source + p.source_id)).slice(0, 24);
  const name = (account.display_name || account.username || "").split(" ")[0];
  return page(`<h1 class="page-title">Écouter</h1><p class="page-sub">${greeting()}${name ? `, ${esc(name)}` : ""}. Voici ta musique du moment.</p>
    <div id="resume">${resumeCard()}</div>
    ${shelf("Faits pour toi", mixes.filter((m) => m.tracks.length).map((m) => feature({
      href: `#/mix/${encodeURIComponent(m.id)}`, cover: m.covers[0], eyebrow: "Mix Sona", title: m.title, subtitle: m.subtitle,
      play: register(m.tracks, m.title),
    })), { kind: "large" })}
    ${recentTracks.length ? `<section class="section"><div class="section-head"><h2>Écouté récemment</h2>
      <div class="shelf-nav"><button data-shelf="-1">${icons.left}</button><button data-shelf="1">${icons.right}</button></div></div>
      ${trackGrid(recentTracks, "Écouté récemment")}</section>` : ""}
    ${shelf("Nouvelles sorties", releases.map((r) => card({
      href: `#/album/${r.source}/${r.source_id}`, cover: r.cover_url, title: r.title, subtitle: `${r.artist} · ${r.kind}`,
    })))}
    ${shelf("Playlists intelligentes", smart.map((s) => card({ href: `#/smart/${s.id}`, covers: s.covers, cover: s.covers[0], title: s.title, subtitle: `${s.count} titres` })))}
    ${!mixes.length && !recentTracks.length ? empty("♫", "Rien encore ici", "Écoute un peu de musique dans l'app ou ici : tes mix apparaîtront.") : ""}`);
}

async function viewSearch(q) {
  const recents = JSON.parse(store.get("sona.searches") || "[]");
  const html = page(`<h1 class="page-title">Rechercher</h1>
    <label class="search-hero">${icons.search}<input id="q" type="search" placeholder="Artistes, titres, albums…" value="${esc(q)}" autocomplete="off"></label>
    ${recents.length ? `<div class="chips" id="recents">${recents.map((r) => `<button class="chip">${esc(r)}</button>`).join("")}</div>` : ""}
    <div id="results"></div>`);
  setTimeout(() => {
    const input = $("#q");
    if (!input) return;
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
    let timer;
    input.oninput = () => { clearTimeout(timer); timer = setTimeout(() => runSearch(input.value.trim()), 280); };
    $$("#recents .chip").forEach((c) => (c.onclick = () => { input.value = c.textContent; runSearch(c.textContent); }));
    if (q) runSearch(q);
  });
  return html;
}

async function runSearch(q) {
  const box = $("#results");
  if (!box) return;
  history.replaceState(null, "", q ? `#/search/${encodeURIComponent(q)}` : "#/search");
  if (!q) { box.innerHTML = ""; return; }
  const seq = (runSearch.seq = (runSearch.seq || 0) + 1);
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
    ${songs.length > 5 ? `<section class="section"><div class="section-head"><h2>Titres</h2></div>${trackTable(songs.slice(5), `Recherche « ${q} »`)}</section>` : ""}
    ${shelf("Artistes", artists.map((a) => card({ href: `#/artist/${a.source}/${a.source_id}`, cover: a.picture_url, title: a.name, subtitle: a.fans ? `${a.fans.toLocaleString("fr-FR")} fans` : "Artiste", round: true })), { kind: "round" })}
    ${shelf("Albums", albums.map((a) => card({ href: `#/album/${a.source}/${a.source_id}`, cover: a.cover_url, title: a.title, subtitle: [a.artist, a.year?.slice(0, 4)].filter(Boolean).join(" · ") })))}`;
  const topButton = $("[data-top]", box);
  if (topButton) topButton.onclick = () => playList(songs, 0, `Recherche « ${q} »`);
  bindPage(box);
}

async function viewAlbum(source, id) {
  $("#content").innerHTML = skeleton("");
  const album = await api(`/albums/${encodeURIComponent(source)}/${encodeURIComponent(id)}`);
  const tracks = (album.tracks || []).map((t) => ({ ...t, cover_url: t.cover_url || album.cover_url, album: t.album || album.title, album_source_id: t.album_source_id || album.source_id }));
  const total = tracks.reduce((s, t) => s + (t.duration_seconds || 0), 0);
  const list = register(tracks, album.title);
  return page(hero({
    cover: album.cover_url, kind: "Album", title: album.title, by: album.artist,
    byHref: album.artist_source_id ? `#/artist/${album.source}/${album.artist_source_id}` : "",
    info: [album.year?.slice(0, 4), `${tracks.length} titres`, total ? `${Math.round(total / 60)} min` : ""].filter(Boolean).join(" · "), list,
  }) + trackTable(tracks, album.title, { showAlbum: false }));
}

async function viewArtist(source, id) {
  $("#content").innerHTML = skeleton("");
  const base = `/artists/${encodeURIComponent(source)}/${encodeURIComponent(id)}`;
  const [artist, top, albums, related] = await Promise.all([
    api(base), api(`${base}/top-tracks`).catch(() => []),
    api(`${base}/albums`).catch(() => ({ albums: [], singles: [] })), api(`${base}/related`).catch(() => []),
  ]);
  const list = register(top, artist.name);
  return page(hero({
    cover: artist.picture_url, kind: "Artiste", title: artist.name, round: true,
    info: artist.fans ? `${artist.fans.toLocaleString("fr-FR")} fans` : "", list: top.length ? list : "",
  }) + (top.length ? `<section class="section"><div class="section-head"><h2>Titres populaires</h2></div>${trackTable(top.slice(0, 10), artist.name)}</section>` : "")
    + shelf("Albums", (albums.albums || []).map((a) => card({ href: `#/album/${a.source}/${a.source_id}`, cover: a.cover_url, title: a.title, subtitle: a.year?.slice(0, 4) })))
    + shelf("Singles et EP", (albums.singles || []).map((a) => card({ href: `#/album/${a.source}/${a.source_id}`, cover: a.cover_url, title: a.title, subtitle: a.year?.slice(0, 4) })))
    + shelf("Artistes similaires", related.map((a) => card({ href: `#/artist/${a.source}/${a.source_id}`, cover: a.picture_url, title: a.name, round: true })), { kind: "round" }));
}

async function viewUserPlaylist(id) {
  $("#content").innerHTML = skeleton("");
  const p = await api(`/me/playlists/${encodeURIComponent(id)}`);
  const tracks = (p.entries || []).map((e) => e.track || e);
  const total = tracks.reduce((s, t) => s + (t.duration_seconds || 0), 0);
  return page(hero({
    cover: p.cover_url || (p.covers || [])[0] || tracks[0]?.cover_url, kind: "Playlist", title: p.name, by: p.owner_name || "",
    info: [`${tracks.length} titres`, total ? `${Math.round(total / 60)} min` : ""].filter(Boolean).join(" · "),
    list: register(tracks, p.name),
  }) + (tracks.length ? trackTable(tracks, p.name) : empty("♫", "Playlist vide", "Ajoute des titres depuis l'app.")));
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

async function viewLibrary() {
  $("#content").innerHTML = skeleton("Titres");
  const pageData = await api("/library/track?limit=500").catch(() => ({ items: [] }));
  const tracks = (pageData.items || []).map((i) => i.track || { source: i.source, source_id: i.source_id, title: i.title, artist: i.subtitle || "", cover_url: i.cover_url }).filter((t) => t.source_id);
  state.liked = new Set(tracks.map((t) => `${t.source}:${t.source_id}`));
  const list = register(tracks, "Tes titres");
  return page(`<h1 class="page-title">Titres</h1><p class="page-sub">${tracks.length} titres dans ta bibliothèque</p>
    ${tracks.length ? `<div class="actions" style="display:flex;gap:12px;margin-bottom:10px"><button class="btn" data-play="${list}">${icons.play} Lecture</button><button class="btn ghost" data-shuffle="${list}">${icons.shuffle} Aléatoire</button></div>${trackTable(tracks, "Tes titres")}`
      : empty("♡", "Ta bibliothèque est vide", "Ajoute des titres avec le cœur, ici ou dans l'app.")}`);
}

async function viewPlaylists() {
  $("#content").innerHTML = skeleton("Playlists");
  const [playlists, smart] = await Promise.all([api("/me/playlists").catch(() => []), api(`/smart?tz=${encodeURIComponent(tz())}`).catch(() => [])]);
  return page(`<h1 class="page-title">Playlists</h1><p class="page-sub">Les tiennes, et celles que Sona fait pour toi.</p>
    ${shelf("Faites pour toi", smart.map((s) => card({ href: `#/smart/${s.id}`, covers: s.covers, cover: s.covers[0], title: s.title, subtitle: `${s.count} titres` })))}
    <section class="section"><div class="section-head"><h2>Tes playlists</h2></div>
      ${playlists.length ? `<div class="grid">${playlists.map((p) => card({
        href: `#/playlist/${p.id}`, cover: p.cover_url || (p.covers || [])[0], covers: p.cover_url ? null : p.covers,
        title: p.name, subtitle: `${p.track_count} titres`,
      })).join("")}</div>` : empty("♫", "Aucune playlist", "Crée ou importe tes playlists dans l'app.")}</section>`);
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

function playList(tracks, index, name) {
  let queue = [...tracks];
  if (state.shuffle) {
    const first = queue.splice(index, 1)[0];
    queue = [first, ...shuffled(queue)];
    index = 0;
  }
  state.queue = queue;
  state.name = name || "";
  playAt(index);
}

function playNext(track) {
  if (state.index < 0) return playList([track], 0, "");
  state.queue.splice(state.index + 1, 0, track);
  toast(`« ${track.title} » sera lu ensuite`);
  if (state.npOpen && state.npTab === "queue") renderQueue();
}

function playAt(index) {
  const t = state.queue[index];
  if (!t) { audio.pause(); return; }
  state.index = index;
  Object.assign(state, { listened: 0, lastTick: 0, scrobbled: false, lyrics: null, lastLyric: -1, startedAt: new Date().toISOString() });
  state.connect.claim = true;
  audio.src = `${BASE}/stream/${encodeURIComponent(t.source)}/${encodeURIComponent(t.source_id)}?token=${encodeURIComponent(token)}`;
  audio.play().catch(() => {});
  api("/plays/now", {
    method: "POST",
    body: JSON.stringify({ title: t.title, artist: t.artist, album: t.album, duration_seconds: t.duration_seconds, source: t.source, source_id: t.source_id, cover_url: t.cover_url }),
  }).catch(() => {});
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
}

function next(auto = false) {
  if (!auto && remoteDevice()) return sendCommand(remoteDevice().id, "next");
  if (state.repeat && auto) { audio.currentTime = 0; audio.play(); return; }
  if (state.index + 1 < state.queue.length) playAt(state.index + 1);
  else if (auto) { audio.pause(); renderTopbar(); }
}

function prev() {
  if (remoteDevice()) return sendCommand(remoteDevice().id, "previous");
  if (audio.currentTime > 3 || state.index <= 0) audio.currentTime = 0;
  else playAt(state.index - 1);
}

function toggle() {
  const remote = remoteDevice();
  if (remote) return sendCommand(remote.id, "toggle");
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
  if (sameTrack(t, state.queue[state.index])) { renderTopbar(); renderNowPlaying(); }
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
  const t = remote ? state.connect.session?.track : state.queue[state.index];
  const liked = t && state.liked.has(`${t.source}:${t.source_id}`);
  const playingIcon = remote ? icons.pause : audio.paused ? icons.play : icons.pause;
  const volumeShown = remote ? (state.connect.pendingVolume ?? remote.volume ?? 1) : audio.volume;
  bar.innerHTML = `
    <div class="transport">
      <button class="tbtn small ${state.shuffle ? "on" : ""}" data-act="shuffle" title="Aléatoire">${icons.shuffle}</button>
      <button class="tbtn" data-act="prev" title="Précédent">${icons.prev}</button>
      <button class="tbtn big" data-act="toggle" title="Lecture/Pause (espace)">${playingIcon}</button>
      <button class="tbtn" data-act="next" title="Suivant">${icons.next}</button>
      <button class="tbtn small ${state.repeat ? "on" : ""}" data-act="repeat" title="Répéter le titre">${icons.repeat}</button>
    </div>
    ${t ? `<div class="lcd ${remote ? "remote" : ""}"><img class="art" data-act="${remote ? "devices" : "open"}" src="${esc(big(t.cover_url, 120))}" alt="">
      <div class="meta" data-act="${remote ? "devices" : "open"}"><div class="t">${esc(t.title)}</div>
        <div class="a">${remote ? `<span class="on-device">${remote.kind === "iphone" ? icons.phone : icons.laptop} Sur ${esc(remote.name)}</span>` : `${esc(t.artist)}${t.album ? ` — ${esc(t.album)}` : ""}`}</div></div>
      <div class="progress" data-act="seek"><div class="fill" id="lcd-fill"></div></div></div>`
      : `<div class="lcd idle"><span>${icons.note}</span></div>`}
    <div class="right-tools">
      <button class="tbtn small ${remote || otherDevices().length ? "on" : ""}" data-act="devices" title="Sona Connect : tes appareils">${icons.devices}</button>
      ${t ? `<button class="tbtn small ${liked ? "on" : ""}" data-act="like" title="Bibliothèque">${liked ? icons.heartFill : icons.heart}</button>` : ""}
      <button class="tbtn small ${state.npOpen && state.npTab === "lyrics" ? "on" : ""}" data-act="lyrics" title="Paroles">${icons.quote}</button>
      <button class="tbtn small ${state.npOpen && state.npTab === "queue" ? "on" : ""}" data-act="queue" title="À suivre">${icons.queue}</button>
      <div class="volume" title="${remote ? `Volume de ${esc(remote.name)}` : "Volume"}">${icons.speaker}<input type="range" class="slider" id="vol" min="0" max="1" step="0.01" value="${volumeShown}" style="--p:${volumeShown * 100}%" aria-label="Volume"></div>
    </div>`;
  bar.onclick = (e) => {
    const act = e.target.closest("[data-act]")?.dataset.act;
    if (!act) return;
    if (act === "devices") return toggleDevices();
    if (act === "toggle") toggle();
    if (act === "prev") prev();
    if (act === "next") next();
    if (act === "shuffle") { state.shuffle = !state.shuffle; renderTopbar(); }
    if (act === "repeat") { state.repeat = !state.repeat; renderTopbar(); }
    if (act === "like" && t) toggleLike(t);
    if (act === "open") openNowPlaying(state.npTab);
    if (act === "lyrics") openNowPlaying("lyrics", true);
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
  updateProgress();
}

function updateProgress() {
  const remote = remoteDevice();
  if (remote) {
    const session = state.connect.session;
    const dur = session?.track?.duration_seconds || 0;
    const fill = $("#lcd-fill");
    if (fill && dur) fill.style.width = `${Math.min(100, (remotePosition() / dur) * 100)}%`;
    return;
  }
  const t = state.queue[state.index];
  const dur = audio.duration && isFinite(audio.duration) ? audio.duration : t?.duration_seconds || 0;
  const pct = dur ? Math.min(100, (audio.currentTime / dur) * 100) : 0;
  const fill = $("#lcd-fill");
  if (fill) fill.style.width = `${pct}%`;
  const seek = $("#np-seek");
  if (seek && !seek._dragging) { seek.value = pct * 10; seek.style.setProperty("--p", `${pct}%`); }
  const cur = $("#np-cur"), rem = $("#np-rem");
  if (cur) cur.textContent = fmt(audio.currentTime);
  if (rem) rem.textContent = `-${fmt(Math.max(0, dur - audio.currentTime))}`;
}

// ── Lecteur plein écran ───────────────────────────────────────────────────

function openNowPlaying(tab, toggleIfSame) {
  if (!state.queue[state.index]) return;
  if (toggleIfSame && state.npOpen && state.npTab === tab) return closeNowPlaying();
  state.npTab = tab || state.npTab;
  state.npOpen = true;
  renderNowPlaying();
  $("#np").classList.add("open");
  renderTopbar();
}

function closeNowPlaying() {
  state.npOpen = false;
  $("#np")?.classList.remove("open");
  renderTopbar();
}

function renderNowPlaying() {
  const np = $("#np");
  if (!np) return;
  const t = state.queue[state.index];
  if (!t) { np.innerHTML = ""; return; }
  const liked = state.liked.has(`${t.source}:${t.source_id}`);
  np.classList.toggle("paused", audio.paused);
  np.innerHTML = `
    <div class="np-bg"><img src="${esc(big(t.cover_url, 300))}" alt=""></div>
    <div class="np-top">
      <button class="tbtn" data-np="close" title="Fermer (Échap)">${icons.down}</button>
      <div class="np-tabs"><button class="${state.npTab === "lyrics" ? "on" : ""}" data-np="lyrics">Paroles</button><button class="${state.npTab === "queue" ? "on" : ""}" data-np="queue">À suivre</button></div>
      <button class="tbtn" data-np="devices" title="Sona Connect">${icons.devices}</button>
    </div>
    <div class="np-body">
      <div class="np-left">
        <img class="np-art" src="${esc(big(t.cover_url, 1000))}" alt="">
        <div class="np-meta"><div style="min-width:0"><div class="t">${esc(t.title)}</div>
          <div class="a">${t.artist_source_id ? `<span class="link" data-np="artist">${esc(t.artist)}</span>` : esc(t.artist)}</div></div>
          <button class="tbtn ${liked ? "on" : ""}" data-np="like" title="Bibliothèque">${liked ? icons.heartFill : icons.heart}</button></div>
        <div class="np-progress"><input type="range" class="slider" id="np-seek" min="0" max="1000" value="0" aria-label="Position">
          <div class="np-times"><span id="np-cur">0:00</span><span id="np-rem">-0:00</span></div></div>
        <div class="np-transport">
          <button class="tbtn small ${state.shuffle ? "on" : ""}" data-np="shuffle">${icons.shuffle}</button>
          <button class="tbtn" data-np="prev">${icons.prev}</button>
          <button class="tbtn big" data-np="toggle" id="np-toggle">${audio.paused ? icons.play : icons.pause}</button>
          <button class="tbtn" data-np="next">${icons.next}</button>
          <button class="tbtn small ${state.repeat ? "on" : ""}" data-np="repeat">${icons.repeat}</button>
        </div>
      </div>
      <div class="np-right" id="np-right"></div>
    </div>`;
  np.onclick = (e) => {
    const act = e.target.closest("[data-np]")?.dataset.np;
    if (!act) return;
    if (act === "close") closeNowPlaying();
    if (act === "devices") { e.stopPropagation(); toggleDevices(); }
    if (act === "lyrics" || act === "queue") { state.npTab = act; renderNowPlaying(); renderTopbar(); }
    if (act === "toggle") toggle();
    if (act === "prev") prev();
    if (act === "next") next();
    if (act === "shuffle") { state.shuffle = !state.shuffle; renderNowPlaying(); renderTopbar(); }
    if (act === "repeat") { state.repeat = !state.repeat; renderNowPlaying(); renderTopbar(); }
    if (act === "like") toggleLike(t);
    if (act === "artist") { closeNowPlaying(); location.hash = `#/artist/${t.source}/${t.artist_source_id}`; }
  };
  const seek = $("#np-seek");
  seek.oninput = () => { seek._dragging = true; seek.style.setProperty("--p", `${seek.value / 10}%`); };
  seek.onchange = () => {
    const dur = audio.duration && isFinite(audio.duration) ? audio.duration : t.duration_seconds || 0;
    if (dur) audio.currentTime = (seek.value / 1000) * dur;
    seek._dragging = false;
  };
  if (state.npTab === "queue") renderQueue(); else renderLyrics();
  updateProgress();
}

function renderQueue() {
  const box = $("#np-right");
  if (!box) return;
  const rows = state.queue.map((t, i) => ({ t, i })).slice(Math.max(0, state.index - 3), state.index + 60);
  box.innerHTML = `<div class="queue scroll"><h3>${state.name ? `À suivre · ${esc(state.name)}` : "À suivre"}</h3>
    ${rows.map(({ t, i }) => `<button class="qrow ${i === state.index ? "current" : ""} ${i < state.index ? "past" : ""}" data-q="${i}">
      <img src="${esc(big(t.cover_url, 120))}" alt=""><span style="min-width:0"><div class="t">${esc(t.title)}</div><div class="s">${esc(t.artist)}</div></span>
      <span class="d">${i === state.index ? bars() : t.duration_seconds ? fmt(t.duration_seconds) : ""}</span></button>`).join("")}</div>`;
  $$("[data-q]", box).forEach((b) => (b.onclick = () => playAt(+b.dataset.q)));
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
  const ua = navigator.userAgent;
  const browser = /Edg\//.test(ua) ? "Edge" : /OPR\//.test(ua) ? "Opera" : /Firefox\//.test(ua) ? "Firefox" : /Chrome\//.test(ua) ? "Chrome" : /Safari\//.test(ua) ? "Safari" : "Navigateur";
  const os = /Mac OS X/.test(ua) && !/iPhone|iPad/.test(ua) ? "Mac" : /Windows/.test(ua) ? "PC" : /Android/.test(ua) ? "Android" : /iPhone|iPad/.test(ua) ? "iPhone" : /Linux/.test(ua) ? "Linux" : "";
  return os ? `${browser} · ${os}` : browser;
}

const otherDevices = () => state.connect.devices.filter((d) => !d.is_me);

/** L'appareil qui joue ailleurs, quand rien ne joue ici : les commandes du
    lecteur (lecture, suivant…) le pilotent à distance. */
function remoteDevice() {
  const { active, devices } = state.connect;
  if (!active || active === deviceId || (audio.src && !audio.paused)) return null;
  return devices.find((d) => d.id === active && d.playing) || null;
}

function remotePosition() {
  const session = state.connect.session;
  if (!session) return 0;
  const drift = session.paused ? 0 : (Date.now() - state.connect.receivedAt) / 1000;
  return session.position + drift;
}

function localState() {
  if (!state.queue.length || state.index < 0) return null;
  const start = Math.max(0, state.index - 20);
  const queue = state.queue.slice(start, start + 150).map((t) => ({
    source: t.source, source_id: t.source_id, title: t.title, artist: t.artist, album: t.album || null,
    duration_seconds: t.duration_seconds || null, cover_url: t.cover_url || null,
    artist_source_id: t.artist_source_id || null, album_source_id: t.album_source_id || null,
  }));
  return { queue, index: state.index - start, position: audio.currentTime || 0, paused: audio.paused, volume: audio.volume, name: state.name || null };
}

async function connectSync() {
  const claim = state.connect.claim && !audio.paused;
  if (claim) state.connect.claim = false;
  let data;
  try {
    data = await api("/connect/sync", {
      method: "POST",
      body: JSON.stringify({ device_id: deviceId, name: deviceName(), kind: "web", state: localState(), claim }),
    });
  } catch { return; }
  const wasRemote = remoteDevice()?.id;
  Object.assign(state.connect, { devices: data.devices, session: data.session, active: data.active_device_id, receivedAt: Date.now() });
  for (const command of data.commands || []) runCommand(command);
  // Pas de rafraîchissement pendant qu'on fait glisser un curseur de volume.
  const dragging = document.activeElement?.matches?.('#vol, input[data-dc="volume"]') && state.connect.pointerDown;
  if (!dragging && (wasRemote !== remoteDevice()?.id || remoteDevice())) renderTopbar();
  const resume = $("#resume");
  if (resume) {
    const html = resumeCard();
    if (resume.innerHTML !== html) resume.innerHTML = html;
  }
  if (state.connect.open && !dragging) renderDevices();
}

function startConnect() {
  let timer;
  document.addEventListener("pointerdown", () => { state.connect.pointerDown = true; });
  document.addEventListener("pointerup", () => { state.connect.pointerDown = false; });
  const loop = async () => {
    clearTimeout(timer);
    await connectSync();
    const busy = !audio.paused || remoteDevice() || state.connect.open;
    timer = setTimeout(loop, document.hidden ? 8000 : busy ? 2000 : 4000);
  };
  loop();
  document.addEventListener("visibilitychange", () => !document.hidden && loop());
  audio.addEventListener("play", () => setTimeout(loop, 300));
  audio.addEventListener("pause", () => setTimeout(loop, 300));
  startConnect.now = loop;
  setInterval(() => remoteDevice() && updateProgress(), 500);
}

function runCommand(c) {
  switch (c.action) {
    case "play": if (audio.src) audio.play(); break;
    case "pause": if (!audio.paused) { audio.pause(); if (c.from) toast(`Lecture passée sur ${c.from}`); } break;
    case "toggle": if (audio.src) (audio.paused ? audio.play() : audio.pause()); break;
    case "next": next(); break;
    case "previous": prev(); break;
    case "seek": if (c.position != null) audio.currentTime = c.position; break;
    case "volume": if (c.volume != null) { audio.volume = c.volume; renderTopbar(); } break;
    case "transfer": playFrom(c.queue, c.index, c.position, c.name); if (c.from) toast(`Musique reprise ici depuis ${c.from}`); break;
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
  if (!e.target.closest(".devices-pop") && !e.target.closest('[data-act="devices"]')) closeDevices();
}

function renderDevices() {
  let pop = $(".devices-pop");
  if (!pop) { pop = document.createElement("div"); pop.className = "devices-pop"; document.body.append(pop); }
  const devices = state.connect.devices.length ? state.connect.devices : [{ id: deviceId, name: deviceName(), kind: "web", is_me: true }];
  const remote = remoteDevice();
  const session = state.connect.session;
  pop.innerHTML = `<div class="dp-head">Sona Connect</div>
    ${remote && session ? `<div class="dp-remote">
      <img src="${esc(big(session.track.cover_url, 120))}" alt="">
      <div style="min-width:0"><div class="t">${esc(session.track.title)}</div><div class="s">${esc(session.track.artist)}</div></div>
      <div class="dp-ctl"><button data-dc="previous">${icons.prev}</button><button data-dc="toggle">${icons.pause}</button><button data-dc="next">${icons.next}</button></div>
      <input type="range" class="slider" data-dc="volume" min="0" max="1" step="0.05" value="${remote.volume ?? 1}" style="--p:${(remote.volume ?? 1) * 100}%" aria-label="Volume à distance">
    </div>` : ""}
    ${devices.map((d) => `<button class="dp-device ${d.playing ? "playing" : ""}" data-device="${esc(d.id)}">
      <span class="dp-icon">${d.kind === "iphone" ? icons.phone : icons.laptop}</span>
      <span style="min-width:0"><span class="n">${d.is_me ? "Cet ordinateur" : esc(d.name)}</span>
        <span class="st">${d.playing ? `${bars()} ${esc(d.track?.title || "En lecture")}` : d.is_me ? esc(d.name) : "Connecté"}</span></span>
      <span class="go">${d.is_me ? (remote || (session && !audio.src) ? "Écouter ici" : "") : "Écouter dessus"}</span></button>`).join("")}
    ${devices.length < 2 ? `<p class="dp-hint">Ouvre Sona sur ton iPhone (ou un autre ordinateur) : il apparaîtra ici.</p>` : ""}`;
  $$("[data-device]", pop).forEach((b) => (b.onclick = () => listenOn(devices.find((d) => d.id === b.dataset.device))));
  $$("button[data-dc]", pop).forEach((b) => (b.onclick = () => remote && sendCommand(remote.id, b.dataset.dc)));
  const vol = $('input[data-dc="volume"]', pop);
  if (vol) vol.onchange = () => { vol.style.setProperty("--p", `${vol.value * 100}%`); sendCommand(remote.id, "volume", { volume: +vol.value }); };
  const anchor = $('.right-tools [data-act="devices"]')?.getBoundingClientRect();
  if (anchor && anchor.width) { pop.style.top = `${anchor.bottom + 8}px`; pop.style.right = `${Math.max(12, innerWidth - anchor.right - 8)}px`; }
}

// ── Événements audio ─────────────────────────────────────────────────────

audio.volume = +(store.get("sona.volume") ?? 1);
const syncPlayState = () => {
  $$('[data-act="toggle"]').forEach((b) => (b.innerHTML = audio.paused ? icons.play : icons.pause));
  const npToggle = $("#np-toggle");
  if (npToggle) npToggle.innerHTML = audio.paused ? icons.play : icons.pause;
  $("#np")?.classList.toggle("paused", audio.paused);
  $$(".bars").forEach((b) => b.classList.toggle("paused", audio.paused));
  if ("mediaSession" in navigator) navigator.mediaSession.playbackState = audio.paused ? "paused" : "playing";
};
audio.addEventListener("play", syncPlayState);
audio.addEventListener("pause", syncPlayState);
audio.addEventListener("ended", () => next(true));
audio.addEventListener("error", () => { if (audio.src) toast("Ce titre ne se lance pas — passage au suivant"); setTimeout(() => next(true), 1200); });
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
});

if ("mediaSession" in navigator) {
  const handlers = {
    play: () => audio.play(), pause: () => audio.pause(), nexttrack: () => next(), previoustrack: () => prev(),
    seekto: (d) => { audio.currentTime = d.seekTime; },
  };
  for (const [action, handler] of Object.entries(handlers)) {
    try { navigator.mediaSession.setActionHandler(action, handler); } catch {}
  }
}

document.addEventListener("keydown", (e) => {
  if (e.target.matches("input, textarea")) return;
  if (e.code === "Space") { e.preventDefault(); toggle(); }
  else if (e.key === "Escape" && state.npOpen) closeNowPlaying();
  else if (e.key === "ArrowRight" && (e.metaKey || e.ctrlKey)) next();
  else if (e.key === "ArrowLeft" && (e.metaKey || e.ctrlKey)) prev();
  else if (e.key === "ArrowRight" && audio.src) audio.currentTime += 10;
  else if (e.key === "ArrowLeft" && audio.src) audio.currentTime -= 10;
  else if (e.key.toLowerCase() === "l" && audio.src) openNowPlaying("lyrics", true);
});

boot();

window.resumeHere = resumeHere;
