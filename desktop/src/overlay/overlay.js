/* Ligne de paroles en cours (et la suivante), d'après la position qui
   avance toute seule entre deux nouvelles de la fenêtre principale. */

const nowEl = document.getElementById("now");
const nextEl = document.getElementById("next");
let state = null;
let receivedAt = 0;
let shown = -2;

window.sonaOverlay.onState((s) => {
  state = s;
  receivedAt = performance.now();
  shown = -2;
  tick();
});

function position() {
  if (!state) return 0;
  return (state.position || 0) + (state.paused ? 0 : (performance.now() - receivedAt) / 1000);
}

function tick() {
  const lines = state?.lyrics?.synced ? state.lyrics.lines.filter((l) => l.time != null && l.text) : [];
  if (!state?.track || !lines.length) {
    if (shown !== -1) { nowEl.textContent = ""; nextEl.textContent = ""; shown = -1; }
    return;
  }
  // Un rien d'avance : la ligne apparaît quand elle commence à être chantée.
  const t = position() + 0.15;
  let active = -1;
  for (let i = 0; i < lines.length; i++) { if (lines[i].time <= t) active = i; else break; }
  if (active === shown) return;
  shown = active;
  document.body.classList.add("swap");
  requestAnimationFrame(() => {
    nowEl.textContent = active >= 0 ? lines[active].text : "♪";
    nextEl.textContent = lines[active + 1]?.text || "";
    requestAnimationFrame(() => document.body.classList.remove("swap"));
  });
}

// Mode jeu : une seule ligne, plus petite et plus transparente.
window.sonaOverlay.onMode?.((mode) => document.body.classList.toggle("game", !!mode?.game));

setInterval(tick, 120);
