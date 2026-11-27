/* Sona : réglages en masonry.
   Chaque section d'une page de réglages (un titre `.set-head` et ce qui le suit) devient une tuile ; les tuiles
   s'emboîtent en colonnes de hauteurs différentes (CSS `columns`, voir pochette.css). Rien n'est recopié : les
   éléments existants sont DÉPLACÉS dans leur tuile, donc leurs écouteurs d'événements restent en place.
   S'applique aux pages #/settings… et #/appearance. */

"use strict";

(() => {
  const applies = () => /^#\/(settings|appearance)(\/|$)/.test(location.hash);

  function tileOf(nodes, cls = "") {
    const tile = document.createElement("section");
    tile.className = `tile ${cls}`.trim();
    nodes.forEach((n) => tile.append(n));
    return tile;
  }

  function masonrify(page) {
    if (page.dataset.mas) return;
    const kids = [...page.children];
    const plans = [];
    for (let i = 0; i < kids.length; i++) {
      const n = kids[i];
      if (n.matches("h3.set-head")) {
        const next = kids[i + 1];
        const group = next && !next.matches("h3, h1, .page-title") ? [n, next] : [n];
        plans.push({ nodes: group, cls: "" });
        i += group.length - 1;
      } else if (n.matches(".set-group")) plans.push({ nodes: [n], cls: "" });
      else if (n.matches(".set-account")) plans.push({ nodes: [n], cls: "hero" });
    }
    if (!plans.length) return;
    page.dataset.mas = "1";
    const mas = document.createElement("div");
    mas.className = "mas";
    page.insertBefore(mas, plans[0].nodes[0]);
    for (const p of plans) {
      const tile = tileOf(p.nodes, p.cls);
      // Sur téléphone, une tuile longue prend toute la largeur ; les courtes se rangent côte à côte.
      const rows = tile.querySelectorAll(".set-row, .switch-row").length;
      if (rows > 3 || tile.textContent.length > 230) tile.classList.add("wide");
      mas.append(tile);
    }
    // Sur téléphone, les tuiles courtes vont par deux ; une tuile courte qui resterait seule dans son rang prend toute la largeur.
    let run = [];
    const flush = () => { if (run.length % 2 === 1) run[run.length - 1].classList.add("wide"); run = []; };
    for (const t of mas.children) { if (t.classList.contains("wide") || t.classList.contains("hero")) flush(); else run.push(t); }
    flush();
  }

  let queued = false;
  function scan() {
    queued = false;
    if (!applies()) return;
    document.querySelectorAll(".page:not([data-mas])").forEach((p) => { if (p.querySelector(".set-head, .set-group, .set-account")) masonrify(p); });
  }
  new MutationObserver(() => { if (!queued) { queued = true; requestAnimationFrame(scan); } }).observe(document.body, { childList: true, subtree: true });
  scan();
})();
