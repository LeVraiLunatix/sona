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
  // Décalage des paroles réglé pour ce titre dans Sona (positif : plus tôt).
  return (state.position || 0) + (state.lyrics?.offset || 0) + (state.paused ? 0 : (performance.now() - receivedAt) / 1000);
}

/** Ligne en cours mot par mot : un <span> par mot, allumé au fil du chant. */
function renderWords(line) {
  nowEl.textContent = "";
  for (const [, , text] of line.words) {
    const span = document.createElement("span");
    span.className = "w";
    span.textContent = text;
    nowEl.append(span);
  }
}

function fillWords(line, t) {
  if (!line?.words) return;
  const spans = nowEl.children;
  line.words.forEach(([start, end], k) => {
    const p = Math.max(0, Math.min(1, (t - start) / Math.max(0.05, end - start)));
    if (spans[k]) spans[k].style.opacity = (0.45 + 0.55 * p).toFixed(2);
  });
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
  if (active === shown) {
    fillWords(lines[active], t);
    return;
  }
  shown = active;
  document.body.classList.add("swap");
  requestAnimationFrame(() => {
    const line = lines[active];
    if (line?.words?.length) { renderWords(line); fillWords(line, position() + 0.15); }
    else nowEl.textContent = line ? line.text : "♪";
    nextEl.textContent = lines[active + 1]?.text || "";
    requestAnimationFrame(() => document.body.classList.remove("swap"));
  });
}

// Mode jeu : une seule ligne, plus petite et plus transparente.
window.sonaOverlay.onMode?.((mode) => document.body.classList.toggle("game", !!mode?.game));

// 20 fois par seconde : assez pour un remplissage mot par mot fluide
// (fondu CSS entre deux pas), sans tenir le processeur éveillé pour rien.
setInterval(tick, 50);
