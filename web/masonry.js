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
    categories(page, mas);
  }


  // ── Téléphone : un bouton, un menu de bulles, une catégorie à la fois ─────────────────────────────────────
  // (même idée que le « Bubble Menu » de reactbits.dev : un bouton qui ouvre des pastilles qui surgissent en cascade).
  const phone = matchMedia("(max-width: 760px)");
  const ICON_GRID = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="7" cy="7" r="1.8"/><circle cx="17" cy="7" r="1.8"/><circle cx="7" cy="17" r="1.8"/><circle cx="17" cy="17" r="1.8"/></svg>';
  const ICON_DOWN = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>';
  const ICON_CLOSE = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>';
  const TILTS = [-2.2, 1.6, -1.2, 2.4, -1.8, 1.2];

  function titleOf(tile, i) {
    return (tile.querySelector(".set-head")?.textContent || "").trim() || (i === 0 ? "Général" : `Section ${i + 1}`);
  }

  function categories(page, mas) {
    const tiles = [...mas.children].filter((t) => !t.classList.contains("hero"));
    if (tiles.length < 2) return;
    const key = `sona.cat:${location.hash.split("?")[0]}`;
    let active = 0;
    try { active = Math.min(tiles.length - 1, Math.max(0, Number(sessionStorage.getItem(key)) || 0)); } catch { /* stockage indisponible : première catégorie */ }

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "cat-btn";
    btn.setAttribute("aria-haspopup", "dialog");
    btn.setAttribute("aria-expanded", "false");
    page.insertBefore(btn, mas);

    const sheet = document.createElement("div");
    sheet.className = "cat-sheet";
    sheet.hidden = true;
    sheet.setAttribute("role", "dialog");
    sheet.setAttribute("aria-modal", "true");
    sheet.setAttribute("aria-label", "Choisir une catégorie");
    sheet._page = page;
    sheet.innerHTML = `<div class="cat-back"></div><nav class="cat-list">${tiles.map((t, i) => `<button type="button" class="cat-bubble" data-i="${i}" style="--i:${i};--r:${TILTS[i % TILTS.length]}deg">${titleOf(t, i).replace(/[<>&]/g, "")}</button>`).join("")}</nav>
      <button type="button" class="cat-x" aria-label="Fermer">${ICON_CLOSE}</button>`;
    document.body.append(sheet);

    const show = (i) => {
      active = i;
      tiles.forEach((t, k) => t.classList.toggle("off", k !== i));
      btn.innerHTML = `<span class="cat-ic">${ICON_GRID}</span><span class="cat-name">${titleOf(tiles[i], i).replace(/[<>&]/g, "")}</span><span class="cat-chev">${ICON_DOWN}</span>`;
      sheet.querySelectorAll(".cat-bubble").forEach((b, k) => b.classList.toggle("on", k === i));
      try { sessionStorage.setItem(key, String(i)); } catch { /* ignoré */ }
    };
    const close = () => {
      if (sheet.hidden) return;
      sheet.classList.remove("open");
      btn.setAttribute("aria-expanded", "false");
      document.removeEventListener("keydown", onKey);
      setTimeout(() => { sheet.hidden = true; }, 380);
      btn.focus({ preventScroll: true });
    };
    const onKey = (e) => { if (e.key === "Escape") { e.stopPropagation(); close(); } };
    const open = () => {
      sheet.hidden = false;
      void sheet.offsetWidth;
      sheet.classList.add("open");
      btn.setAttribute("aria-expanded", "true");
      document.addEventListener("keydown", onKey);
      sheet.querySelector(".cat-bubble.on, .cat-bubble")?.focus({ preventScroll: true });
    };
    btn.onclick = open;
    sheet.querySelector(".cat-back").onclick = close;
    sheet.querySelector(".cat-x").onclick = close;
    sheet.querySelectorAll(".cat-bubble").forEach((b) => (b.onclick = () => {
      show(Number(b.dataset.i));
      close();
      page.closest("#content, .content")?.scrollTo?.({ top: 0 });
    }));
    show(active);
    const sync = () => {
      mas.classList.toggle("cats", phone.matches);
      if (!phone.matches) { close(); sheet.hidden = true; }
    };
    phone.addEventListener("change", sync);
    sync();
  }

  let queued = false;
  function scan() {
    queued = false;
    document.querySelectorAll(".cat-sheet").forEach((n) => { if (!n._page?.isConnected) n.remove(); });
    if (!applies()) return;
    document.querySelectorAll(".page:not([data-mas])").forEach((p) => { if (p.querySelector(".set-head, .set-group, .set-account")) masonrify(p); });
  }
  new MutationObserver(() => { if (!queued) { queued = true; requestAnimationFrame(scan); } }).observe(document.body, { childList: true, subtree: true });
  scan();
})();
