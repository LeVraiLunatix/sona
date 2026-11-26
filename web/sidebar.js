/* Sona : menu latéral « Rail ↔ Panneau » et barre de navigation mobile.
   Styles : sidebar.css. Variante retenue : B « Flottante » (docs/sidebar-variants/).

   - État ouvert / fermé mémorisé PAR APPAREIL (réglage `look.menu`, ouvert par défaut
     seulement sur grand écran) ; Ctrl/Cmd + B pour basculer.
   - Option « survol pour déplier » : fermé, le panneau passe par-dessus le contenu
     (sans le pousser) ; désactivable dans Réglages › Apparence.
   - Bascule animée sans toucher à la largeur : voir sidebar.css. Le contenu change de
     place d'un coup, puis glisse depuis son ancienne position (FLIP, transform seul).
   Utilise les fonctions d'app.js (icons, esc, state, account…) au moment de l'appel. */

"use strict";

const Sidebar = (() => {
  const WIDE = 1200;
  const mac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
  const mod = mac ? "⌘" : "Ctrl";
  const alt = mac ? "⌥" : "Alt";

  /** Entrées principales (7 au plus). `key` : Alt + chiffre. */
  const MAIN = [
    ["Découvrir", [
      { id: "home", label: "Écouter", icon: "listen", key: 1 },
      { id: "search", label: "Rechercher", icon: "search", key: 2 },
      { id: "radios", label: "Radios", icon: "radio", key: 3 },
    ]],
    ["Ma musique", [
      { id: "library", label: "Bibliothèque", icon: "library", key: 4 },
      { id: "stats", label: "Stats", icon: "stats", key: 5 },
    ]],
    ["Social", [
      { id: "friends", label: "Amis", icon: "friends", key: 6, badge: "friendRequests" },
      { id: "party", label: "Sessions", icon: "headphones", key: 7, badge: "invites" },
    ]],
  ];
  const STAFF = { id: "admin", label: "Modération", icon: "lock" };

  const root = () => document.getElementById("sb");
  const h = (s) => esc(s);
  const mq = matchMedia("(min-width: 761px)");

  const s = { hover: false, focus: false, timer: null, counts: { friendRequests: 0, invites: 0, unread: 0 } };

  // ── État ─────────────────────────────────────────────────────────────────

  /** « ouvert » ou « rail » : choix de la personne, sinon selon la largeur de l'écran. */
  const mode = () => (look.menu === "ouvert" || look.menu === "rail" ? look.menu : innerWidth >= WIDE ? "ouvert" : "rail");
  const pinned = () => mode() === "ouvert";
  const hoverEnabled = () => look.hover !== false;

  function applyMode() {
    document.documentElement.dataset.menu = mode();
    paintOpen();
  }

  function paintOpen() {
    const el = root();
    if (!el) return;
    const open = pinned() || s.hover || s.focus;
    el.dataset.open = String(open);
    el.dataset.pinned = pinned() ? "open" : "closed";
    const btn = document.getElementById("sb-toggle");
    if (btn) {
      btn.setAttribute("aria-expanded", String(pinned()));
      btn.setAttribute("aria-label", pinned() ? "Réduire le menu" : "Garder le menu ouvert");
      const label = btn.querySelector(".sb-label");
      if (label) label.textContent = pinned() ? "Réduire le menu" : "Garder ouvert";
    }
    if (open) hideTip();
  }

  /** Bascule épinglé ouvert / fermé, avec glissement du contenu. */
  function toggle() {
    const targets = [document.getElementById("content"), document.getElementById("topbar")].filter(Boolean);
    const before = targets.map((t) => t.getBoundingClientRect().left);
    s.hover = false;
    s.focus = false;
    setLook({ menu: pinned() ? "rail" : "ouvert" });
    applyMode();
    const settle = () => window.dispatchEvent(new Event("resize")); // recale ce qui suit la position du contenu (halo)
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) return settle();
    const anims = targets.map((t, i) => {
      const dx = before[i] - t.getBoundingClientRect().left;
      if (!dx) return null;
      // Le lecteur du haut est centré par une transformation : on la garde pendant le glissement.
      const from = t.id === "topbar" ? `translateX(calc(-50% + ${dx}px))` : `translateX(${dx}px)`;
      const to = t.id === "topbar" ? "translateX(-50%)" : "none";
      return t.animate([{ transform: from }, { transform: to }], { duration: 230, easing: "cubic-bezier(0.32, 0.72, 0, 1)" });
    }).filter(Boolean);
    Promise.all(anims.map((a) => a.finished.catch(() => {}))).then(settle);
    // Bascules enchaînées : une animation annulée ne doit pas laisser le halo mal placé.
    clearTimeout(toggle.settleTimer);
    toggle.settleTimer = setTimeout(settle, 300);
  }

  // ── Survol et clavier ────────────────────────────────────────────────────

  function bindHover(el) {
    el.addEventListener("pointerenter", (e) => {
      if (e.pointerType !== "mouse" || pinned() || !hoverEnabled()) return;
      clearTimeout(s.timer);
      s.timer = setTimeout(() => { s.hover = true; paintOpen(); }, 120);
    });
    el.addEventListener("pointerleave", (e) => {
      if (e.pointerType !== "mouse") return;
      clearTimeout(s.timer);
      s.timer = setTimeout(() => { s.hover = false; paintOpen(); }, 160);
    });
    // Navigation au clavier : le panneau s'ouvre tant que le focus (visible) y est.
    el.addEventListener("focusin", (e) => {
      if (pinned() || !hoverEnabled() || !e.target.matches?.(":focus-visible")) return;
      s.focus = true;
      paintOpen();
    });
    el.addEventListener("focusout", (e) => {
      if (el.contains(e.relatedTarget)) return;
      s.focus = false;
      paintOpen();
    });
    // Un clic sur une page referme le survol (le contenu reprend la main).
    el.addEventListener("click", (e) => {
      if (e.target.closest("a[data-nav]") && s.hover && !pinned()) { s.hover = false; paintOpen(); }
    });
  }

  // ── Info-bulle du rail ───────────────────────────────────────────────────

  let tip = null;
  let tipTimer = null;
  function showTip(link) {
    clearTimeout(tipTimer);
    tipTimer = setTimeout(() => {
      const el = root();
      if (!el || el.dataset.open === "true" || !mq.matches) return;
      tip ||= Object.assign(document.createElement("div"), { className: "sb-tip", role: "tooltip" });
      const key = link.dataset.key ? `<kbd>${alt} ${link.dataset.key}</kbd>` : "";
      tip.innerHTML = `<span>${h(link.dataset.tip || "")}</span>${key}`;
      if (!tip.isConnected) document.body.append(tip);
      const r = link.getBoundingClientRect();
      tip.style.left = `${r.right + 10}px`;
      tip.style.top = `${r.top + r.height / 2 - tip.offsetHeight / 2}px`;
      requestAnimationFrame(() => tip?.classList.add("show"));
    }, 380);
  }
  function hideTip() {
    clearTimeout(tipTimer);
    if (tip) tip.classList.remove("show");
  }

  // ── Rendu ────────────────────────────────────────────────────────────────

  const badgeHtml = (kind) => `<span class="sb-badge" data-badge="${kind}" hidden></span>`;

  function linkHtml(it) {
    const href = it.href || `#/${it.id}`;
    return `<a class="sb-link" href="${href}" data-nav="${it.id}" data-tip="${h(it.label)}" ${it.key ? `data-key="${it.key}"` : ""}>
      <span class="sb-ico">${icons[it.icon]}${it.badge ? badgeHtml(it.badge) : ""}</span><span class="sb-label">${h(it.label)}</span></a>`;
  }

  function groups() {
    return MAIN.map(([title, items], i) => {
      const list = i === MAIN.length - 1 && account?.is_staff ? [...items, STAFF] : items;
      return `<div class="sb-group" role="group" aria-label="${h(title)}"><h2 class="sb-title"><span>${h(title)}</span></h2>${list.map(linkHtml).join("")}</div>`;
    }).join("");
  }

  function playlistsHtml() {
    const list = (state.playlists || []).slice(0, 40);
    return list.length
      ? list.map((p) => `<a class="sb-link" href="#/playlist/${p.id}" data-nav="playlist/${p.id}"><img class="thumb" src="${h(p.cover_url || (p.covers || [])[0] || "")}" alt="" loading="lazy"><span class="sb-label">${h(p.name)}</span></a>`).join("")
      : `<p class="sb-empty">Aucune playlist pour l'instant</p>`;
  }

  function profileHtml() {
    const name = account.display_name || account.username || "Moi";
    const status = account.guest ? "Invité" : account.is_admin ? "Administrateur" : account.is_staff ? "Modérateur" : account.username ? `@${account.username}` : "";
    return `<button class="sb-profile" id="sb-profile" type="button" aria-haspopup="menu" data-tip="${h(name)}">
        <span class="sb-ico">${avatar(account.avatar_url, name)}<span class="sb-badge dot" data-badge="unread" hidden></span></span>
        <span class="sb-name"><b>${h(name)}</b><small>${h(status)}</small></span></button>`;
  }

  /** HTML à insérer dans la grille de l'app (espace réservé + menu fixe). */
  function html() {
    return `<div class="sb-spacer" aria-hidden="true"></div>
    <nav class="sb" id="sb" aria-label="Navigation principale" data-open="false">
      <div class="sb-face" aria-hidden="true"></div>
      <div class="sb-top"><a class="sb-logo" href="#/home" aria-label="Sona, accueil"><span class="sb-brand"><svg viewBox="0 0 64 64" aria-hidden="true"><use href="#sona-mark"/></svg><span class="sb-word" aria-hidden="true">ona</span></span></a></div>
      <button class="sb-link sb-toggle" id="sb-toggle" type="button" aria-expanded="false" aria-controls="sb-scroll" data-tip="Menu" data-key="" style="margin-top:6px">
        <span class="sb-ico"><svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zm0 2v12h3.5V6zm5.500 0v12H19V6z"/></svg></span><span class="sb-label">Réduire le menu</span></button>
      <div class="sb-scroll" id="sb-scroll">
        ${groups()}
        <div class="sb-group sb-pl-wrap" role="group" aria-label="Playlists"><h2 class="sb-title"><span>Playlists</span></h2><div class="sb-pl" id="sb-pl">${playlistsHtml()}</div></div>
      </div>
      <div class="sb-foot">
        <button class="sb-link" id="sb-more" type="button" aria-haspopup="menu" data-tip="Plus"><span class="sb-ico">${icons.more}</span><span class="sb-label">Plus</span></button>
        ${profileHtml()}
      </div>
    </nav>`;
  }

  /** Après insertion : branche les événements. */
  function mount() {
    const el = root();
    if (!el) return;
    applyMode();
    bindHover(el);
    document.getElementById("sb-toggle").addEventListener("click", toggle);
    document.getElementById("sb-more").addEventListener("click", moreMenu);
    document.getElementById("sb-profile").addEventListener("click", profileMenu);
    el.addEventListener("pointerover", (e) => { const l = e.target.closest("[data-tip]"); if (l) showTip(l); });
    el.addEventListener("pointerout", hideTip);
    el.addEventListener("focusin", (e) => { const l = e.target.closest("[data-tip]"); if (l && e.target.matches(":focus-visible")) showTip(l); });
    el.addEventListener("focusout", hideTip);
    el.addEventListener("click", hideTip);
    el.addEventListener("scroll", hideTip, true);
    mark();
    paintBadges();
  }

  /** Page courante : `aria-current`, état actif, liste de playlists à jour. */
  function mark() {
    const current = location.hash.replace(/^#\//, "") || "home";
    document.querySelectorAll("[data-nav]").forEach((a) => {
      const on = current === a.dataset.nav || current.startsWith(`${a.dataset.nav}/`) || (a.dataset.nav === "admin" && current.startsWith("admin"));
      a.classList.toggle("active", on);
      if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    // Barre du bas : « Plus » s'allume quand la page courante n'est pas l'un des 4 onglets.
    const tab = nav?.tab;
    document.querySelectorAll(".tabbar [data-tab]").forEach((b) => { if (b.dataset.tab === tab) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current"); });
    const more = document.querySelector(".tabbar [data-more]");
    if (more) more.classList.toggle("active", !BAR.some(([id]) => id === tab));
  }

  function renderLists() {
    const pl = document.getElementById("sb-pl");
    if (pl) pl.innerHTML = playlistsHtml();
    mark();
  }

  function renderAccount() {
    const p = document.getElementById("sb-profile");
    if (p && account) { p.outerHTML = profileHtml(); document.getElementById("sb-profile")?.addEventListener("click", profileMenu); paintBadges(); }
  }

  // ── Pastilles ────────────────────────────────────────────────────────────

  function paintBadges() {
    document.querySelectorAll("[data-badge]").forEach((b) => {
      const n = s.counts[b.dataset.badge] || 0;
      b.hidden = n <= 0;
      if (!b.classList.contains("dot")) b.textContent = n > 9 ? "9+" : String(n);
      const link = b.closest("a, button");
      if (link && !link.dataset.baseLabel) link.dataset.baseLabel = link.querySelector(".sb-label")?.textContent || "";
      if (link && link.dataset.baseLabel) link.setAttribute("aria-label", n > 0 ? `${link.dataset.baseLabel}, ${n} nouveau${n > 1 ? "x" : ""}` : link.dataset.baseLabel);
    });
    // Barre mobile : pastille sur Amis, point sur Plus.
    const friends = document.querySelector('.tabbar [data-tab="friends"] .tb-dot');
    if (friends) friends.hidden = !(s.counts.friendRequests > 0);
    const more = document.querySelector(".tabbar [data-more] .tb-dot");
    if (more) more.hidden = !(s.counts.invites > 0 || s.counts.unread > 0);
  }

  document.addEventListener("sona:notifications", (e) => {
    Object.assign(s.counts, { friendRequests: e.detail.friendRequests, invites: e.detail.invites, unread: e.detail.unread });
    paintBadges();
  });

  // ── Menus ────────────────────────────────────────────────────────────────

  function moreMenu() {
    const items = [
      { icon: icons.sparkles, label: "Exclus", run: () => go("#/exclusives") },
      { icon: icons.devices, label: "Appareils", sub: "Tes PC enregistrés", run: () => go("#/devices") },
      { icon: icons.clock, label: "Écoutes récentes", run: () => go("#/recent") },
      { icon: icons.sparkles, label: "Apparence", sub: "Couleur, formes, menu", run: () => go("#/appearance") },
      desktop ? { icon: icons.phone, label: "Sona sur l'iPhone", run: () => go("#/iphone") } : { icon: icons.download, label: "Installer Sona pour Windows", run: () => window.open(WINDOWS_PAGE, "_blank", "noopener") },
      account?.is_admin && { icon: icons.pulse, label: "Santé de la lecture", run: () => go("#/health") },
    ];
    actionSheet("Plus", items);
  }

  function profileMenu() {
    const n = s.counts.unread;
    actionSheet(account.display_name || account.username || "Compte", [
      { icon: icons.user, label: "Compte", sub: account.guest ? "Créer ton compte" : "Pseudo, photo, connexion", run: () => go("#/settings/account") },
      !account.guest && { icon: icons.lock, label: "Confidentialité", run: () => go("#/settings/privacy") },
      !account.guest && { icon: icons.friends, label: n ? `Notifications (${n})` : "Notifications", run: () => SonaSettings.notificationsSheet() },
      { icon: icons.gear, label: "Réglages", run: () => go("#/settings") },
      { icon: icons.close, label: "Se déconnecter", danger: true, run: async () => { await Sona.auth.signOut(); signOutLocal(true); } },
    ]);
  }

  // ── Mobile : barre du bas (4 boutons larges + Plus) et tiroir « Plus » ────

  const BAR = [["home", "Écouter", "listen"], ["search", "Rechercher", "search"], ["library", "Bibliothèque", "library"], ["friends", "Amis", "friends"]];

  function tabbarHtml() {
    return `${BAR.map(([id, label, icon]) => `<button type="button" data-tab="${id}" aria-label="${h(label)}">${icons[icon]}<span>${h(label)}</span>${id === "friends" ? '<i class="tb-dot" hidden></i>' : ""}</button>`).join("")}
      <button type="button" data-more aria-haspopup="dialog" aria-label="Plus">${icons.more}<span>Plus</span><i class="tb-dot" hidden></i></button>`;
  }

  function bindTabbar() {
    document.querySelectorAll(".tabbar [data-tab]").forEach((b) => (b.onclick = () => selectTab(b.dataset.tab)));
    document.querySelector(".tabbar [data-more]")?.addEventListener("click", moreSheet);
  }

  /** Tiroir mobile : le même contenu que le panneau (sections, playlists, profil). */
  function moreSheet() {
    const name = account.display_name || account.username || "Moi";
    const wrap = openSheet(`<div class="more-sheet">
      <button class="more-profile sb-link" data-sheet-profile style="height:auto">${avatar(account.avatar_url, name)}<span class="sb-label"><b>${h(name)}</b><br><small style="color:var(--text-3)">${account.guest ? "Invité" : account.username ? `@${h(account.username)}` : ""}</small></span></button>
      ${MAIN.map(([title, items], i) => `<div role="group" aria-label="${h(title)}"><h2 class="sb-title"><span>${h(title)}</span></h2>${(i === MAIN.length - 1 && account?.is_staff ? [...items, STAFF] : items).map(linkHtml).join("")}</div>`).join("")}
      <h2 class="sb-title"><span>Plus</span></h2>
      ${[{ id: "exclusives", label: "Exclus", icon: "sparkles" }, { id: "devices", label: "Appareils", icon: "devices" }, { id: "recent", label: "Écoutes récentes", icon: "clock" }, { id: "settings", label: "Réglages", icon: "gear" }].map(linkHtml).join("")}
      <h2 class="sb-title"><span>Playlists</span></h2><div class="sb-pl">${playlistsHtml()}</div></div>`);
    wrap.querySelectorAll("[data-key]").forEach((a) => a.removeAttribute("data-key"));
    wrap.querySelectorAll("a[data-nav]").forEach((a) => a.addEventListener("click", () => wrap.close()));
    wrap.querySelector("[data-sheet-profile]")?.addEventListener("click", () => { wrap.close(); profileMenu(); });
    document.querySelectorAll(".more-sheet .sb-badge").forEach((b) => { const n = s.counts[b.dataset.badge] || 0; b.hidden = n <= 0; b.textContent = n > 9 ? "9+" : String(n); });
    mark();
  }

  // ── Clavier : Ctrl/Cmd + B, Alt + 1…7 ────────────────────────────────────

  document.addEventListener("keydown", (e) => {
    if (!root() || !mq.matches) return;
    if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.code === "KeyB") { e.preventDefault(); toggle(); return; }
    if (e.altKey && !e.ctrlKey && !e.metaKey && /^Digit[1-7]$/.test(e.code)) {
      const n = Number(e.code.slice(5));
      const item = MAIN.flatMap(([, items]) => items).find((it) => it.key === n);
      if (item) { e.preventDefault(); go(`#/${item.id}`); }
    }
  });

  // Largeur d'écran : sans choix explicite, le menu suit (ouvert ≥ 1200 px, rail en dessous).
  let lastWide = innerWidth >= WIDE;
  addEventListener("resize", () => {
    const wide = innerWidth >= WIDE;
    if (wide !== lastWide) { lastWide = wide; if (root()) applyMode(); }
    hideTip();
  });
  mq.addEventListener?.("change", () => { if (root()) applyMode(); });

  return { html, mount, mark, renderLists, renderAccount, tabbarHtml, bindTabbar, toggle, moreSheet, applyMode, BAR };
})();

// Noms attendus par app.js et par les réglages.
function renderSidebarLists() { Sidebar.renderLists(); }
function renderSidebarAccount() { Sidebar.renderAccount(); }
