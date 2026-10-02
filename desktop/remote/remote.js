/* Sona Remote : le téléphone pilote Sona sur le PC, sur le réseau local.
   Associé en scannant le QR code de Sona (la clé arrive après le #, gardée
   ensuite sur le téléphone). L'état arrive en direct (Server-Sent Events) ;
   la position avance toute seule entre deux nouvelles. */

"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (s) => { s = Math.max(0, Math.floor(s || 0)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
const big = (url, size = 600) => (url || "").replace(/\/(\d+)x\1(-\d+-\d+-\d+-\d+)?\.jpg$/, `/${size}x${size}$2.jpg`);
const haptic = () => { try { navigator.vibrate?.(8); } catch {} };
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch {} },
};

const ic = (d) => `<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="${d}"/></svg>`;
const icons = {
  play: ic("M7 4.8v14.4c0 .8.9 1.3 1.6.9l11.2-7.2c.6-.4.6-1.4 0-1.8L8.6 3.9C7.9 3.5 7 4 7 4.8z"),
  pause: ic("M7 4h3.2c.4 0 .8.4.8.8v14.4c0 .4-.4.8-.8.8H7c-.4 0-.8-.4-.8-.8V4.8c0-.4.4-.8.8-.8zm6.8 0H17c.4 0 .8.4.8.8v14.4c0 .4-.4.8-.8.8h-3.2c-.4 0-.8-.4-.8-.8V4.8c0-.4.4-.8.8-.8z"),
  next: ic("M3 6.3v11.4c0 .7.8 1.1 1.4.7l8.1-5.7c.5-.4.5-1.1 0-1.4L4.4 5.6C3.8 5.2 3 5.6 3 6.3zm9.5 0v11.4c0 .7.8 1.1 1.4.7l8.1-5.7c.5-.4.5-1.1 0-1.4l-8.1-5.7c-.6-.4-1.4 0-1.4.7z"),
  prev: ic("M21 17.7V6.3c0-.7-.8-1.1-1.4-.7l-8.1 5.7c-.5.4-.5 1.1 0 1.4l8.1 5.7c.6.4 1.4 0 1.4-.7zm-9.5 0V6.3c0-.7-.8-1.1-1.4-.7L2 11.3c-.5.4-.5 1.1 0 1.4l8.1 5.7c.6.4 1.4 0 1.4-.7z"),
  shuffle: ic("M17.3 4.3a1 1 0 0 1 1.4 0l2.5 2.5a1 1 0 0 1 0 1.4l-2.5 2.5a1 1 0 1 1-1.4-1.4l.8-.8h-1.6c-1.2 0-2.3.6-3 1.6l-3.8 5.6A5.6 5.6 0 0 1 5 18.3H3a1 1 0 1 1 0-2h2c1.2 0 2.3-.6 3-1.6l3.8-5.6a5.6 5.6 0 0 1 4.7-2.6h1.6l-.8-.8a1 1 0 0 1 0-1.4zM3 7.5h2c1.9 0 3.6.9 4.7 2.4l-1.2 1.8-.5-.7a3.6 3.6 0 0 0-3-1.5H3a1 1 0 1 1 0-2zm10.3 7.1 1.2-1.8.5.7c.7 1 1.8 1.6 3 1.6h.1l-.8-.8a1 1 0 1 1 1.4-1.4l2.5 2.5a1 1 0 0 1 0 1.4l-2.5 2.5a1 1 0 1 1-1.4-1.4l.8-.8h-.1a5.6 5.6 0 0 1-4.7-2.5z"),
  repeat: ic("M17.3 2.3a1 1 0 0 1 1.4 0l2.5 2.5a1 1 0 0 1 0 1.4l-2.5 2.5a1 1 0 1 1-1.4-1.4l.8-.8H7a3 3 0 0 0-3 3v1a1 1 0 1 1-2 0v-1a5 5 0 0 1 5-5h11.1l-.8-.8a1 1 0 0 1 0-1.4zM21 11.5a1 1 0 0 1 1 1v1a5 5 0 0 1-5 5H5.9l.8.8a1 1 0 1 1-1.4 1.4l-2.5-2.5a1 1 0 0 1 0-1.4l2.5-2.5a1 1 0 1 1 1.4 1.4l-.8.8H17a3 3 0 0 0 3-3v-1a1 1 0 0 1 1-1z"),
  heart: ic("M12 20.3c-.3 0-.6-.1-.8-.3C5.3 14.9 2.5 12 2.5 8.5A4.8 4.8 0 0 1 7.3 3.6c1.9 0 3.5 1 4.7 2.6 1.2-1.6 2.8-2.6 4.7-2.6a4.8 4.8 0 0 1 4.8 4.9c0 3.5-2.8 6.4-8.7 11.5-.2.2-.5.3-.8.3zM7.3 5.6A2.8 2.8 0 0 0 4.5 8.5c0 2.5 2.3 5 7.5 9.4 5.2-4.4 7.5-6.9 7.5-9.4a2.8 2.8 0 0 0-2.8-2.9c-1.5 0-2.7 1-3.8 2.8a1 1 0 0 1-1.8 0c-1.1-1.8-2.3-2.8-3.8-2.8z"),
  heartFill: ic("M12 20.3c-.3 0-.6-.1-.8-.3C5.3 14.9 2.5 12 2.5 8.5A4.8 4.8 0 0 1 7.3 3.6c1.9 0 3.5 1 4.7 2.6 1.2-1.6 2.8-2.6 4.7-2.6a4.8 4.8 0 0 1 4.8 4.9c0 3.5-2.8 6.4-8.7 11.5-.2.2-.5.3-.8.3z"),
  listen: ic("M12 2a10 10 0 1 1 0 20 10 10 0 0 1 0-20zm-1.8 6.3c-.5-.3-1.2 0-1.2.7v6c0 .7.7 1 1.2.7l5-3c.5-.3.5-1.1 0-1.4z"),
  quote: ic("M5 3h14a3 3 0 0 1 3 3v9a3 3 0 0 1-3 3h-6.6l-4.8 3.6A1 1 0 0 1 6 20.8V18H5a3 3 0 0 1-3-3V6a3 3 0 0 1 3-3zm2.5 5a1 1 0 1 0 0 2h9a1 1 0 1 0 0-2zm0 4a1 1 0 1 0 0 2h6a1 1 0 1 0 0-2z"),
  queue: ic("M3 5h13a1 1 0 1 1 0 2H3a1 1 0 0 1 0-2zm0 6h13a1 1 0 1 1 0 2H3a1 1 0 1 1 0-2zm0 6h9a1 1 0 1 1 0 2H3a1 1 0 1 1 0-2zm15-2.4v-3.2c0-.6.7-1 1.2-.6l2.4 1.6c.5.3.5 1 0 1.3l-2.4 1.6c-.5.3-1.2-.1-1.2-.7z"),
  search: ic("M10.5 3a7.5 7.5 0 0 1 6 12l4.3 4.3a1 1 0 0 1-1.4 1.4L15 16.5A7.5 7.5 0 1 1 10.5 3zm0 2a5.5 5.5 0 1 0 0 11 5.5 5.5 0 0 0 0-11z"),
  plus: ic("M12 4a1 1 0 0 1 1 1v6h6a1 1 0 1 1 0 2h-6v6a1 1 0 1 1-2 0v-6H5a1 1 0 1 1 0-2h6V5a1 1 0 0 1 1-1z"),
  nextUp: ic("M4 6h11a1 1 0 1 1 0 2H4a1 1 0 0 1 0-2zm0 5h11a1 1 0 1 1 0 2H4a1 1 0 1 1 0-2zm0 5h7a1 1 0 1 1 0 2H4a1 1 0 1 1 0-2zm13.5-1.5V12a1 1 0 1 1 2 0v2.5H22a1 1 0 1 1 0 2h-2.5V19a1 1 0 1 1-2 0v-2.5H15a1 1 0 1 1 0-2z"),
  close: ic("M6.7 5.3 12 10.6l5.3-5.3a1 1 0 1 1 1.4 1.4L13.4 12l5.3 5.3a1 1 0 0 1-1.4 1.4L12 13.4l-5.3 5.3a1 1 0 0 1-1.4-1.4l5.3-5.3-5.3-5.3a1 1 0 0 1 1.4-1.4z"),
  speaker: ic("M11 4.5v15c0 .8-.9 1.2-1.5.7L5.3 16.5H3a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1h2.3l4.2-3.7c.6-.5 1.5-.1 1.5.7zm4.6 2.8a1 1 0 0 1 1.4 0 6.6 6.6 0 0 1 0 9.4 1 1 0 1 1-1.4-1.4 4.6 4.6 0 0 0 0-6.6 1 1 0 0 1 0-1.4z"),
  speakerLow: ic("M11 4.5v15c0 .8-.9 1.2-1.5.7L5.3 16.5H3a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1h2.3l4.2-3.7c.6-.5 1.5-.1 1.5.7z"),
  laptop: ic("M5 5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v9H5zm2 0v7h10V5zM2 16h20v1a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2z"),
  phone: ic("M8 2h8a2 2 0 0 1 2 2v16a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2zm0 2v16h8V4zm4 13a1 1 0 1 1 0 2 1 1 0 0 1 0-2z"),
  note: ic("M19 3.2v11.3a3.5 3.5 0 1 1-2-3.2V7.4L10 9v7.5a3.5 3.5 0 1 1-2-3.2V6.2c0-.5.3-.9.8-1l9-2c.6-.1 1.2.3 1.2 1z"),
};

// ── Clé d'association ──────────────────────────────────────────────────

let key = store.get("sonaRemote.key");
{
  const fromHash = new URLSearchParams(location.hash.slice(1)).get("k");
  if (fromHash) {
    key = fromHash;
    store.set("sonaRemote.key", key);
    history.replaceState(null, "", location.pathname);
  }
}

// ── État ───────────────────────────────────────────────────────────────

const S = {
  state: null, received: 0, online: false, view: store.get("sonaRemote.view") || "play",
  dragging: null, lastLyric: -1, lyricsSig: "", queueSig: "", cover: "", ambientSlot: 0,
  results: null, searching: false, query: "",
};
const VIEWS = [["play", "Lecture", icons.listen], ["lyrics", "Paroles", icons.quote], ["queue", "À suivre", icons.queue], ["search", "Rechercher", icons.search]];

function position() {
  const st = S.state;
  if (!st?.track) return 0;
  let p = st.position || 0;
  if (!st.paused) p += (Date.now() - S.received) / 1000;
  const dur = duration();
  return dur ? Math.min(p, dur) : p;
}
const duration = () => S.state?.duration || S.state?.track?.duration_seconds || 0;

// ── Réseau ─────────────────────────────────────────────────────────────

let events = null;
let retryTimer = null;

async function connect() {
  clearTimeout(retryTimer);
  if (!key) return renderPair();
  let res;
  try {
    res = await fetch("api/state", { headers: { "X-Sona-Key": key }, cache: "no-store" });
  } catch {
    setOnline(false);
    if (!S.state) renderOffline();
    retryTimer = setTimeout(connect, 3000);
    return;
  }
  if (res.status === 401) {
    key = null;
    store.set("sonaRemote.key", null);
    return renderPair("Cette association n'est plus valable : scanne à nouveau le QR code.");
  }
  if (!res.ok) { retryTimer = setTimeout(connect, 3000); return; }
  renderApp();
  setState(await res.json());
  openEvents();
}

function openEvents() {
  events?.close();
  events = new EventSource(`api/events?k=${encodeURIComponent(key)}`);
  events.addEventListener("state", (e) => { try { setState(JSON.parse(e.data)); } catch {} });
  events.onopen = () => setOnline(true);
  events.onerror = () => {
    setOnline(false);
    // Fermée pour de bon (clé changée, PC éteint) : on revérifie tout.
    if (events.readyState === EventSource.CLOSED) { events = null; retryTimer = setTimeout(connect, 2500); }
  };
}

// iPhone : la connexion se coupe en arrière-plan ; au retour, on la rouvre.
document.addEventListener("visibilitychange", () => {
  if (document.hidden || !key) return;
  if (!events || events.readyState === EventSource.CLOSED) connect();
});

async function command(action, extra = {}) {
  haptic();
  try {
    const res = await fetch("api/command", {
      method: "POST", headers: { "Content-Type": "application/json", "X-Sona-Key": key },
      body: JSON.stringify({ action, ...extra }),
    });
    const body = await res.json().catch(() => ({}));
    if (res.status === 401) { connect(); return null; }
    if (!res.ok) throw new Error(body.error || "Sona ne répond pas");
    return body.result;
  } catch (e) {
    toast(e.message === "Failed to fetch" || e.message === "Load failed" ? "PC injoignable" : e.message);
    return null;
  }
}

// ── Coquille ───────────────────────────────────────────────────────────

let ticking = null;

function renderApp() {
  if ($(".views")) return;
  Object.assign(S, { cover: null, lyricsSig: "", queueSig: "", lastLyric: -1 });
  $("#app").innerHTML = `
    <div class="top"><div class="status glass" id="status"><span class="dot"></span><span class="icon">${icons.laptop}</span><span class="name">Connexion…</span></div></div>
    <div class="views">
      <section class="view play-view" data-view="play"><div class="play">
        <div class="art-box" id="art-box"></div>
        <div class="meta"><div class="meta-text"><div class="t" id="title"></div><div class="a" id="artist"></div><div id="on-device"></div></div>
          <button class="round glass" id="like" aria-label="Bibliothèque">${icons.heart}</button></div>
        <div><div class="seek" id="seek"><div class="seek-track"><div class="seek-fill" id="seek-fill"></div></div></div>
          <div class="times"><span id="cur">0:00</span><span id="rem">-0:00</span></div></div>
        <div class="transport">
          <button class="tbtn small" data-c="shuffle" id="shuffle" aria-label="Aléatoire">${icons.shuffle}</button>
          <button class="tbtn" data-c="previous" aria-label="Précédent">${icons.prev}</button>
          <button class="tbtn big" data-c="toggle" id="toggle" aria-label="Lecture/Pause">${icons.play}</button>
          <button class="tbtn" data-c="next" aria-label="Suivant">${icons.next}</button>
          <button class="tbtn small" data-c="repeat" id="repeat" aria-label="Répéter">${icons.repeat}</button>
        </div>
        <div class="volume">${icons.speakerLow}<div class="seek" id="vol"><div class="seek-track"><div class="seek-fill" id="vol-fill"></div></div></div>${icons.speaker}</div>
      </div></section>
      <section class="view scroller" data-view="lyrics" id="lyrics-view"></section>
      <section class="view scroller" data-view="queue" id="queue-view"></section>
      <section class="view scroller" data-view="search" id="search-view">
        <label class="search-box glass">${icons.search}<input id="q" type="search" placeholder="Titres, artistes, albums" autocomplete="off" enterkeyhint="search"><button class="clear" id="q-clear" hidden aria-label="Effacer">${icons.close}</button></label>
        <div id="results"></div>
      </section>
    </div>
    <nav class="tabbar glass"><span class="lens" id="lens"></span>${VIEWS.map(([id, label, icon]) => `<button data-tab="${id}">${icon}<span>${label}</span></button>`).join("")}</nav>`;

  $$(".tabbar button").forEach((b) => (b.onclick = () => { haptic(); show(b.dataset.tab); }));
  $$("[data-c]").forEach((b) => (b.onclick = () => {
    const action = b.dataset.c;
    if (!S.state) return;
    if (action === "toggle" && S.state?.track) {
      // Réponse immédiate à l'écran, confirmée par le PC juste après.
      S.state.position = position();
      S.received = Date.now();
      S.state.paused = !S.state.paused;
      paintPlayback();
    }
    if (action === "shuffle" || action === "repeat") { S.state[action] = !S.state[action]; paintPlayback(); }
    command(action);
  }));
  $("#like").onclick = () => {
    if (!S.state?.track) return;
    S.state.liked = !S.state.liked;
    paintPlayback();
    command("like");
  };
  bindSlider($("#seek"), {
    value: () => (duration() ? position() / duration() : 0),
    preview: (r) => { $("#seek-fill").style.width = `${r * 100}%`; $("#cur").textContent = fmt(r * duration()); $("#rem").textContent = `-${fmt((1 - r) * duration())}`; },
    commit: (r) => {
      if (!duration()) return;
      S.state.position = r * duration();
      S.received = Date.now();
      command("seek", { position: S.state.position });
    },
  });
  bindSlider($("#vol"), {
    value: () => S.state?.volume ?? 1,
    preview: (r, live) => { $("#vol-fill").style.width = `${r * 100}%`; if (live) throttledVolume(r); },
    commit: (r) => { if (S.state) S.state.volume = r; command("volume", { volume: r }); },
  });
  const input = $("#q");
  let timer;
  input.addEventListener("input", () => {
    $("#q-clear").hidden = !input.value;
    clearTimeout(timer);
    timer = setTimeout(() => search(input.value), 380);
  });
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") { clearTimeout(timer); search(input.value); input.blur(); } });
  $("#q-clear").onclick = (e) => { e.preventDefault(); input.value = ""; $("#q-clear").hidden = true; S.results = null; paintResults(); input.focus(); };
  paintResults();
  show(S.view, true);
  ticking ??= setInterval(tick, 250);
}

let volumeTimer = 0;
function throttledVolume(r) {
  if (Date.now() - volumeTimer < 150) return;
  volumeTimer = Date.now();
  fetch("api/command", { method: "POST", headers: { "Content-Type": "application/json", "X-Sona-Key": key }, body: JSON.stringify({ action: "volume", volume: r }) }).catch(() => {});
}

function show(view, instant) {
  if (!VIEWS.some(([id]) => id === view)) view = "play";
  S.view = view;
  store.set("sonaRemote.view", view);
  const i = VIEWS.findIndex(([id]) => id === view);
  const lens = $("#lens");
  if (lens) { if (instant) lens.style.transition = "none"; lens.style.transform = `translateX(${i * 100}%)`; if (instant) requestAnimationFrame(() => (lens.style.transition = "")); }
  $$(".tabbar button").forEach((b) => b.classList.toggle("on", b.dataset.tab === view));
  $$(".view").forEach((v) => v.classList.toggle("on", v.dataset.view === view));
  document.body.className = document.body.className.replace(/\bview-\w+/, "") + ` view-${view}`;
  if (view === "lyrics") { S.lastLyric = -1; syncLyrics(true); }
  if (view === "queue") $(".row.current", $("#queue-view"))?.scrollIntoView({ block: "center" });
}

/** Curseur tactile (progression, volume) : le doigt le tient, relâché il envoie. */
function bindSlider(el, { value, preview, commit }) {
  const ratio = (e) => {
    const rect = el.getBoundingClientRect();
    return Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
  };
  el.addEventListener("pointerdown", (e) => {
    if (!S.state?.track && el.id === "seek") return;
    el.setPointerCapture(e.pointerId);
    el.classList.add("drag");
    S.dragging = el.id;
    preview(ratio(e), true);
  });
  el.addEventListener("pointermove", (e) => { if (S.dragging === el.id) preview(ratio(e), true); });
  const end = (e) => {
    if (S.dragging !== el.id) return;
    S.dragging = null;
    el.classList.remove("drag");
    commit(ratio(e));
  };
  el.addEventListener("pointerup", end);
  el.addEventListener("pointercancel", () => { S.dragging = null; el.classList.remove("drag"); preview(value()); });
}

// ── Affichage ──────────────────────────────────────────────────────────

function setOnline(online) {
  S.online = online;
  const st = $("#status");
  if (!st) return;
  st.classList.toggle("off", !online);
  $(".name", st).textContent = online ? (S.state?.device ? `Sona · ${S.state.device}` : "Sona sur le PC") : "Reconnexion…";
}

function setState(st) {
  S.state = st || { track: null };
  S.received = Date.now();
  setOnline(true);
  paintPlayback();
  paintLyrics();
  paintQueue();
}

function paintPlayback() {
  const st = S.state;
  const t = st?.track;
  document.body.classList.toggle("paused", !t || st.paused);
  document.body.classList.toggle("has-art", !!t?.cover_url);
  const cover = t?.cover_url ? big(t.cover_url, 800) : "";
  if (cover !== S.cover) {
    S.cover = cover;
    $("#art-box").innerHTML = cover ? `<img class="art" src="${esc(cover)}" alt="">` : `<div class="art empty">${icons.note}</div>`;
    setAmbient(t?.cover_url ? big(t.cover_url, 300) : "");
  }
  $("#title").textContent = t ? t.title : "Rien en lecture";
  $("#artist").textContent = t ? t.artist : "Cherche un titre pour le lancer sur le PC";
  $("#on-device").innerHTML = st?.remoteDevice ? `<div class="on-device">${icons.phone} Sur ${esc(st.remoteDevice)}, piloté par le PC</div>` : "";
  $("#toggle").innerHTML = !t || st.paused ? icons.play : icons.pause;
  $("#like").innerHTML = st?.liked ? icons.heartFill : icons.heart;
  $("#like").classList.toggle("liked", !!st?.liked);
  $("#like").style.visibility = t ? "" : "hidden";
  $("#shuffle").classList.toggle("on", !!st?.shuffle);
  $("#repeat").classList.toggle("on", !!st?.repeat);
  if (S.dragging !== "vol") $("#vol-fill").style.width = `${(st?.volume ?? 1) * 100}%`;
  setOnline(S.online);
  tick();
}

function setAmbient(url) {
  const imgs = $$(".amb");
  const next = imgs[S.ambientSlot = 1 - S.ambientSlot];
  const prev = imgs[1 - S.ambientSlot];
  if (!url) { imgs.forEach((i) => i.classList.remove("on")); return; }
  next.onload = () => { next.classList.add("on"); prev.classList.remove("on"); };
  next.src = url;
}

function tick() {
  if (!$("#seek-fill")) return;
  if (S.dragging !== "seek") {
    const dur = duration();
    const pos = position();
    $("#seek-fill").style.width = dur ? `${Math.min(100, (pos / dur) * 100)}%` : "0%";
    $("#cur").textContent = fmt(pos);
    $("#rem").textContent = `-${fmt(Math.max(0, dur - pos))}`;
  }
  syncLyrics(false);
}

function paintLyrics() {
  const box = $("#lyrics-view");
  const st = S.state;
  const ly = st?.lyrics;
  const sig = `${st?.track?.source}:${st?.track?.source_id}:${ly ? ly.lines.length : "none"}:${ly?.synced}`;
  if (sig === S.lyricsSig) return;
  S.lyricsSig = sig;
  S.lastLyric = -1;
  if (!st?.track) { box.innerHTML = empty(icons.quote, "Paroles", "Lance un titre pour voir ses paroles."); return; }
  if (!ly) { box.innerHTML = empty(icons.quote, "Chargement des paroles…", ""); return; }
  if (!ly.lines.length) { box.innerHTML = empty(icons.note, ly.instrumental ? "♪ Instrumental" : "Pas de paroles", ly.instrumental ? "" : "Aucune parole trouvée pour ce titre."); return; }
  box.innerHTML = `<div class="lyrics ${ly.synced ? "" : "plain"}" id="lyr">${ly.lines.map((l, i) => `<p data-l="${i}">${esc(l.text || "♪")}</p>`).join("")}</div>`;
  if (ly.synced) {
    $$("[data-l]", box).forEach((p) => (p.onclick = () => {
      const time = ly.lines[+p.dataset.l].time;
      if (time == null) return;
      S.state.position = time;
      S.received = Date.now();
      command("seek", { position: time });
      syncLyrics(true);
    }));
  }
  syncLyrics(true);
}

function syncLyrics(force) {
  if (S.view !== "lyrics") return;
  const ly = S.state?.lyrics;
  if (!ly?.synced || !ly.lines?.length) return;
  const now = position() + 0.25;
  let active = -1;
  for (let i = 0; i < ly.lines.length; i++) {
    const time = ly.lines[i].time;
    if (time != null && time <= now) active = i; else if (time > now) break;
  }
  if (active === S.lastLyric && !force) return;
  S.lastLyric = active;
  const lines = $$("#lyr p");
  lines.forEach((p, i) => { p.classList.toggle("on", i === active); p.classList.toggle("near", Math.abs(i - active) === 1); });
  const el = lines[Math.max(0, active)];
  const box = $("#lyrics-view");
  if (el) box.scrollTo({ top: el.offsetTop - box.clientHeight * 0.34, behavior: force ? "auto" : "smooth" });
}

function paintQueue() {
  const box = $("#queue-view");
  const st = S.state;
  const queue = st?.queue || [];
  const sig = JSON.stringify([st?.index, queue.map((q) => q.i + q.title), st?.queueName]);
  if (sig === S.queueSig) return;
  S.queueSig = sig;
  if (!queue.length) { box.innerHTML = empty(icons.queue, "La file est vide", "Ce que tu lances depuis la recherche s'ajoute ici."); return; }
  box.innerHTML = `<div class="list-head">${st.queueName ? `À suivre · ${esc(st.queueName)}` : "À suivre"}</div><div class="rows">${queue.map((q) => `
    <div class="row ${q.i === st.index ? "current" : ""} ${q.i < st.index ? "past" : ""}" data-qi="${q.i}" role="button">
      ${q.cover_url ? `<img src="${esc(big(q.cover_url, 120))}" alt="" loading="lazy">` : `<span class="ph"></span>`}
      <span style="min-width:0"><div class="t">${esc(q.title)}</div><div class="s">${esc(q.artist)}</div></span>
      <span class="acts">${q.i === st.index ? `<span class="bars"><i></i><i></i><i></i></span>` : q.i > st.index ? `<button data-qx="${q.i}" aria-label="Retirer">${icons.close}</button>` : ""}</span>
    </div>`).join("")}</div>`;
  box.onclick = (e) => {
    const x = e.target.closest("[data-qx]");
    if (x) { e.stopPropagation(); command("removeIndex", { index: +x.dataset.qx }); return; }
    const row = e.target.closest("[data-qi]");
    if (row && +row.dataset.qi !== st.index) command("playIndex", { index: +row.dataset.qi });
  };
  if (S.view === "queue") $(".row.current", box)?.scrollIntoView({ block: "center" });
}

async function search(q) {
  q = q.trim();
  S.query = q;
  if (!q) { S.results = null; paintResults(); return; }
  S.searching = true;
  paintResults();
  const result = await command("search", { query: q });
  if (S.query !== q) return;
  S.searching = false;
  S.results = Array.isArray(result) ? result : [];
  paintResults();
}

function paintResults() {
  const box = $("#results");
  if (!box) return;
  if (S.searching && !S.results) { box.innerHTML = `<p class="hint">Recherche…</p>`; return; }
  if (!S.results) { box.innerHTML = `<p class="hint">Cherche un titre : il se lance sur le PC.</p>`; return; }
  if (!S.results.length) { box.innerHTML = `<p class="hint">Aucun résultat.</p>`; return; }
  box.innerHTML = `<div class="rows">${S.results.map((t, i) => `
    <div class="row" data-ri="${i}" role="button">
      ${t.cover_url ? `<img src="${esc(big(t.cover_url, 120))}" alt="" loading="lazy">` : `<span class="ph"></span>`}
      <span style="min-width:0"><div class="t">${esc(t.title)}</div><div class="s">${esc(t.artist)}${t.album ? ` · ${esc(t.album)}` : ""}</div></span>
      <span class="acts"><button data-rn="${i}" aria-label="Lire ensuite">${icons.nextUp}</button><button data-ra="${i}" aria-label="Ajouter à la file">${icons.plus}</button></span>
    </div>`).join("")}</div>`;
  box.onclick = async (e) => {
    const next = e.target.closest("[data-rn]");
    const add = e.target.closest("[data-ra]");
    if (next) { e.stopPropagation(); if (await command("playNext", { track: S.results[+next.dataset.rn] }) !== null) toast("Lu ensuite"); return; }
    if (add) { e.stopPropagation(); if (await command("addToQueue", { track: S.results[+add.dataset.ra] }) !== null) toast("Ajouté à la file"); return; }
    const row = e.target.closest("[data-ri]");
    if (row) { await command("playTrack", { track: S.results[+row.dataset.ri] }); show("play"); }
  };
}

const empty = (icon, title, sub) => `<div class="empty"><div class="big">${icon}</div><h2>${esc(title)}</h2>${sub ? `<p>${esc(sub)}</p>` : ""}</div>`;

function renderPair(message) {
  events?.close();
  events = null;
  $("#app").innerHTML = `<div class="pair"><div class="pair-card glass">
    <img src="icons/icon-192.png" alt="">
    <h1>Sona Remote</h1>
    <p>${esc(message || "Pilote Sona sur ton PC depuis ce téléphone.")}</p>
    <ol><li>Sur le PC, ouvre <b>Sona</b>.</li><li>Clique sur l'icône <b>téléphone</b> en haut (ou Réglages → <b>Télécommande</b>).</li><li><b>Scanne le QR code</b> avec l'appareil photo.</li></ol>
    <p class="fine">Le téléphone et le PC doivent être sur le même Wi-Fi.</p>
  </div></div>`;
}

function renderOffline() {
  $("#app").innerHTML = `<div class="pair"><div class="pair-card glass">
    <img src="icons/icon-192.png" alt="">
    <h1>PC injoignable</h1>
    <p>Sona est fermé sur le PC, ou ce téléphone n'est plus sur le même Wi-Fi.</p>
    <button class="pill" id="retry">Réessayer</button>
    <p class="fine">Nouvel essai automatique toutes les quelques secondes.</p>
  </div></div>`;
  $("#retry").onclick = () => { haptic(); connect(); };
}

function toast(text) {
  let el = $(".toast");
  if (!el) { el = document.createElement("div"); el.className = "toast glass"; document.body.append(el); }
  el.textContent = text;
  el.classList.add("show");
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove("show"), 2000);
}

connect();
