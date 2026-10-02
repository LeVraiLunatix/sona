/* Mini-lecteur : affichage de l'état reçu, boutons renvoyés à Sona. */

"use strict";

const $ = (id) => document.getElementById(id);
const PLAY = '<svg viewBox="0 0 24 24"><path d="M7 4.8v14.4c0 .8.9 1.3 1.6.9l11.2-7.2c.6-.4.6-1.4 0-1.8L8.6 3.9C7.9 3.5 7 4 7 4.8z"/></svg>';
const PAUSE = '<svg viewBox="0 0 24 24"><path d="M7 4h3.2c.4 0 .8.4.8.8v14.4c0 .4-.4.8-.8.8H7c-.4 0-.8-.4-.8-.8V4.8c0-.4.4-.8.8-.8zm6.8 0H17c.4 0 .8.4.8.8v14.4c0 .4-.4.8-.8.8h-3.2c-.4 0-.8-.4-.8-.8V4.8c0-.4.4-.8.8-.8z"/></svg>';
const fmt = (s) => { s = Math.max(0, Math.floor(s || 0)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
const big = (url, size) => (url || "").replace(/\/(\d+)x\1(-\d+-\d+-\d+-\d+)?\.jpg$/, `/${size}x${size}$2.jpg`);

if (new URLSearchParams(location.search).get("acrylic") !== "1") document.body.classList.add("solid");

let state = { track: null, paused: true };
let received = 0;

function position() {
  const p = state.position || 0;
  return state.paused ? p : p + (Date.now() - received) / 1000;
}

function render() {
  const t = state.track;
  document.body.classList.toggle("paused", !t || state.paused);
  $("toggle").innerHTML = !t || state.paused ? PLAY : PAUSE;
  $("title").textContent = t ? t.title : "Rien en lecture";
  $("artist").textContent = t ? (state.remoteDevice ? `${t.artist} · sur ${state.remoteDevice}` : t.artist) : "Lance un titre dans Sona";
  const cover = t?.cover_url ? big(t.cover_url, 300) : "";
  if ($("art").getAttribute("src") !== cover) {
    if (cover) { $("art").src = cover; $("bg").src = big(t.cover_url, 120); }
    else { $("art").removeAttribute("src"); $("bg").removeAttribute("src"); }
  }
  tick();
}

function tick() {
  const dur = state.duration || state.track?.duration_seconds || 0;
  const pos = Math.min(position(), dur || Infinity);
  $("fill").style.width = dur ? `${Math.min(100, (pos / dur) * 100)}%` : "0%";
  $("time").textContent = state.track && dur ? `${fmt(pos)} / ${fmt(dur)}` : "";
}

window.sonaMini.onState((s) => { state = s || { track: null }; received = Date.now(); render(); });
document.addEventListener("click", (e) => {
  const action = e.target.closest("[data-a]")?.dataset.a;
  if (action) window.sonaMini.command(action);
});
$("bar").addEventListener("click", (e) => {
  const dur = state.duration || state.track?.duration_seconds;
  if (!dur) return;
  const rect = $("bar").getBoundingClientRect();
  window.sonaMini.seek(((e.clientX - rect.left) / rect.width) * dur);
});
document.addEventListener("keydown", (e) => {
  if (e.code === "Space") { e.preventDefault(); window.sonaMini.command("toggle"); }
  if (e.key === "Escape") window.sonaMini.command("close");
});
setInterval(tick, 500);
render();
