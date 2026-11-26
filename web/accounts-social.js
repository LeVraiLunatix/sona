/* Sona : amis. Personne n'est ami avec personne par défaut. Demandes par pseudo,
   lien personnel ou QR code ; accepter, refuser, ignorer ; retirer ; bloquer ;
   signaler. Toutes les règles (confidentialité, limites, blocages) sont
   appliquées par la base : cette interface ne fait que les présenter. */

"use strict";

const SonaSocial = (() => {
  const { auth, social } = window.Sona;
  const h = (s) => esc(s);
  const guard = (fn) => async (...a) => { try { return await fn(...a); } catch (e) { toast(e.message); } };

  const inviteLink = (code) => `${location.origin}${location.pathname}?ami=${encodeURIComponent(code)}`;

  /** Un ami : ligne de la liste (musique en direct si le serveur la fournit et que l'ami l'autorise). */
  function friendRow(f, music) {
    const name = f.display_name || f.username;
    const t = music?.now_playing?.track || music?.last_play;
    return `<div class="friend-wrap"><a class="friend" href="#/friend/${f.user_id}">
      <span class="friend-avatar">${avatar(f.avatar_url, name)}${music?.now_playing ? '<i class="live-dot"></i>' : ""}</span>
      <span class="friend-text"><span class="n">${h(name)}${music?.compatibility != null ? ` <span class="compat">${music.compatibility} %</span>` : ""}</span>
        ${t ? `<span class="s">${music.now_playing ? `${bars()} ` : ""}${h(t.title)} · ${h(t.artist)}</span>` : `<span class="s">@${h(f.username)}</span>`}</span>
      ${t?.cover_url ? `<span class="friend-cover" data-fplay="${f.user_id}"><img src="${h(big(t.cover_url, 120))}" alt="">${icons.play}</span>` : ""}</a>
      <button class="friend-more" data-fmenu="${f.user_id}" aria-label="Plus d'actions pour ${h(name)}">${icons.more}</button></div>`;
  }

  function requestRows(reqs) {
    const inc = reqs.filter((r) => r.direction === "in");
    const out = reqs.filter((r) => r.direction === "out");
    return `${inc.length ? `<section class="section"><div class="section-head"><h2>Demandes reçues (${inc.length})</h2></div><div class="set-group">${inc.map((r) => `<div class="set-row">${avatar(r.avatar_url, r.username)}
        <span class="set-text"><b>${h(r.display_name || r.username)}</b><small>@${h(r.username)} · ${since(r.created_at)}</small></span>
        <span class="pill-row tight"><button class="btn small" data-accept="${r.id}">Accepter</button><button class="btn small ghost" data-decline="${r.id}">Refuser</button><button class="btn small ghost" data-ignore="${r.id}" title="Ignorer sans répondre">Ignorer</button></span></div>`).join("")}</div></section>` : ""}
      ${out.length ? `<section class="section"><div class="section-head"><h2>Demandes envoyées</h2></div><div class="set-group">${out.map((r) => `<div class="set-row">${avatar(r.avatar_url, r.username)}
        <span class="set-text"><b>${h(r.display_name || r.username)}</b><small>En attente · ${since(r.created_at)}</small></span><button class="btn small ghost" data-cancel="${r.id}">Annuler</button></div>`).join("")}</div></section>` : ""}`;
  }

  async function viewFriends() {
    $("#content").innerHTML = skeleton("Amis");
    if (auth.isGuest()) {
      return cpage(`<h1 class="page-title">Amis</h1><p class="page-sub">Crée un compte pour ajouter des amis et écouter ensemble.</p>
        <div class="pill-row"><button class="btn" data-upgrade>Créer mon compte</button></div>`);
    }
    const [friends, reqs, music, parties] = await Promise.all([
      social.friends(), social.requests(), api("/friends").catch(() => []), api("/party/active").catch(() => []),
    ]);
    // Les infos musicales viennent du serveur musique, qui ne renvoie QUE des amis acceptés.
    const byName = new Map((music || []).map((m) => [String(m.username).toLowerCase(), m]));
    const timer = setInterval(async () => {
      const fresh = await api("/friends").catch(() => null);
      const box = $("#friends-list");
      if (fresh && box) { const m = new Map(fresh.map((x) => [String(x.username).toLowerCase(), x])); box.innerHTML = friends.map((f) => friendRow(f, m.get(f.username.toLowerCase()))).join(""); }
    }, 15000);
    onLeave(() => clearInterval(timer));
    setTimeout(() => bindFriends(friends, music));
    const live = (parties || []).filter((p) => !p.joined).map((p) => `<a class="live-pill" href="#/party/${h(p.code)}">${icons.headphones} <b>${h(p.host_name || "Un ami")}</b> écoute en groupe (${p.members}) — rejoindre</a>`).join("");
    return cpage(`<div class="friends-head"><div><h1 class="page-title">Amis</h1><p class="page-sub">Ce qu'écoutent tes amis, s'ils le partagent.</p></div>
      <div class="pill-row tight"><button class="btn" data-add>${icons.plus} Ajouter</button><button class="btn ghost" data-mycode>Mon code</button></div></div>
      ${live}
      <div id="requests">${requestRows(reqs)}</div>
      ${friends.length ? `<div class="friend-list" id="friends-list">${friends.map((f) => friendRow(f, byName.get(f.username.toLowerCase()))).join("")}</div>`
        : empty("👋", "Personne pour l'instant", "Personne n'est ami avec toi par défaut. Ajoute un ami avec son pseudo, ou partage ton lien ou ton QR code.")}`);
  }

  function bindFriends(friends, music) {
    const reload = () => route();
    $("[data-upgrade]")?.addEventListener("click", SonaUI.upgradeSheet);
    $("[data-add]")?.addEventListener("click", addSheet);
    $("[data-mycode]")?.addEventListener("click", codeSheet);
    $$("[data-accept]").forEach((b) => (b.onclick = guard(async () => { await social.respond(b.dataset.accept, "accept"); toast("Ami ajouté ✓"); reload(); })));
    // Refus : discret, l'expéditeur n'est pas notifié.
    $$("[data-decline]").forEach((b) => (b.onclick = guard(async () => { await social.respond(b.dataset.decline, "decline"); reload(); })));
    $$("[data-ignore]").forEach((b) => (b.onclick = guard(async () => { await social.respond(b.dataset.ignore, "ignore"); reload(); })));
    $$("[data-cancel]").forEach((b) => (b.onclick = guard(async () => { await social.cancel(b.dataset.cancel); reload(); })));
    $("#friends-list")?.addEventListener("click", (e) => {
      const play = e.target.closest("[data-fplay]");
      if (play) {
        e.preventDefault(); e.stopPropagation();
        const f = friends.find((x) => x.user_id === play.dataset.fplay);
        const m = (music || []).find((x) => String(x.username).toLowerCase() === f?.username.toLowerCase());
        playTrackFrom(m?.now_playing?.track || m?.last_play);
        return;
      }
      const more = e.target.closest("[data-fmenu]");
      if (more) { e.preventDefault(); e.stopPropagation(); friendMenu(friends.find((x) => x.user_id === more.dataset.fmenu)); }
    });
  }

  function friendMenu(f) {
    if (!f) return;
    actionSheet(f.display_name || f.username, [
      { icon: icons.user, label: "Voir le profil", run: () => go(`#/friend/${f.user_id}`) },
      { icon: icons.close, label: "Retirer de mes amis", run: async () => { if (await confirmSheet(`Retirer ${f.username} de tes amis ?`, "Retirer")) { await social.remove(f.user_id); route(); } } },
      { icon: icons.lock, label: "Bloquer", sub: "Supprime le lien et interdit toute nouvelle demande", danger: true, run: async () => { if (await confirmSheet(`Bloquer ${f.username} ?`, "Bloquer")) { await social.block(f.user_id); toast("Compte bloqué"); route(); } } },
      { icon: icons.flag, label: "Signaler", danger: true, run: () => SonaSettings.reportSheet({ type: "profile", userId: f.user_id, title: `Signaler ${f.username}`, snapshot: { username: f.username } }) },
    ]);
  }

  /** Ajouter un ami par pseudo. Réponse identique que le pseudo existe ou non : pas d'énumération. */
  function addSheet() {
    const wrap = openSheet(`<h2 class="sheet-title">Ajouter un ami</h2>
      <p class="muted">Entre son pseudo exact. La personne reçoit une demande qu'elle peut accepter, refuser ou ignorer.</p>
      <form class="ask"><input class="field" name="u" placeholder="Pseudo" autocomplete="off" autocapitalize="none" spellcheck="false" maxlength="20" required aria-label="Pseudo de ton ami">
      <p class="muted small-note">Tu peux aussi partager ton lien personnel ou ton QR code (bouton « Mon code »).</p>
      <div class="pill-row"><button type="button" class="btn ghost" data-cancel>Annuler</button><button class="btn" type="submit">Envoyer la demande</button></div></form>`);
    $("[data-cancel]", wrap).onclick = () => wrap.close();
    setTimeout(() => $("input", wrap).focus(), 250);
    $("form", wrap).onsubmit = async (e) => {
      e.preventDefault();
      try {
        await social.sendRequest(new FormData(e.target).get("u"));
        wrap.close();
        toast("Demande envoyée si ce pseudo existe et accepte les demandes");
        route();
      } catch (err) { toast(err.message); }
    };
  }

  /** Mon lien d'invitation et mon QR code. */
  async function codeSheet() {
    const me = await social.me();
    const render = (code) => {
      const link = inviteLink(code);
      const qr = window.qrcode(0, "M");
      qr.addData(link);
      qr.make();
      return { link, svg: qr.createSvgTag({ cellSize: 6, margin: 2, scalable: true }) };
    };
    let { link, svg } = render(me.friend_code);
    const wrap = openSheet(`<h2 class="sheet-title">Mon code ami</h2>
      <p class="muted">Quiconque scanne ce QR code ou ouvre ce lien peut t'envoyer une demande d'ami (que tu acceptes ou non).</p>
      <div class="qr" id="qr" role="img" aria-label="QR code de ton lien d'invitation">${svg}</div>
      <p class="qr-link" id="qr-link">${h(link)}</p>
      <div class="pill-row center"><button class="btn" data-share>${icons.share} Partager</button><button class="btn ghost" data-copy>Copier</button><button class="btn ghost" data-rotate>Nouveau lien</button></div>
      <p class="muted small-note">« Nouveau lien » invalide l'ancien (en cas de partage involontaire).</p>`);
    $("[data-copy]", wrap).onclick = () => navigator.clipboard?.writeText(link).then(() => toast("Lien copié")).catch(() => toast(link));
    $("[data-share]", wrap).onclick = () => (navigator.share ? navigator.share({ title: "Ajoute-moi sur Sona", url: link }).catch(() => {}) : navigator.clipboard?.writeText(link).then(() => toast("Lien copié")));
    $("[data-rotate]", wrap).onclick = guard(async () => {
      if (!(await confirmSheet("Générer un nouveau lien ? L'ancien ne fonctionnera plus.", "Générer"))) return;
      ({ link, svg } = render(await social.rotateCode()));
      $("#qr", wrap).innerHTML = svg;
      $("#qr-link", wrap).textContent = link;
    });
  }

  /** Lien personnel ouvert (?ami=CODE) : on le garde jusqu'à la connexion, puis on envoie la demande. */
  function rememberInvite(params) {
    const code = params.get("ami");
    if (code && /^[a-f0-9]{8,32}$/i.test(code)) store.set("sona.friendCode", code.toLowerCase());
  }
  async function redeemPendingInvite() {
    const code = store.get("sona.friendCode");
    if (!code || auth.isGuest()) return;
    store.set("sona.friendCode", null);
    try { await social.redeemCode(code); toast("Demande d'ami envoyée si le lien est valide"); } catch (e) { toast(e.message); }
  }

  /** Menu ⋯ d'une page de profil d'ami. */
  function profileMenu(userId, username) {
    actionSheet(username, [
      { icon: icons.close, label: "Retirer de mes amis", run: async () => { if (await confirmSheet(`Retirer ${username} de tes amis ?`, "Retirer")) { await social.remove(userId); go("#/friends"); } } },
      { icon: icons.lock, label: "Bloquer", danger: true, run: async () => { if (await confirmSheet(`Bloquer ${username} ?`, "Bloquer")) { await social.block(userId); toast("Compte bloqué"); go("#/friends"); } } },
      { icon: icons.flag, label: "Signaler", danger: true, run: () => SonaSettings.reportSheet({ type: "profile", userId, title: `Signaler ${username}`, snapshot: { username } }) },
    ]);
  }

  /** Profil minimal quand le serveur musique n'a rien à montrer (ou est injoignable). */
  async function viewProfileOnly(userId) {
    const p = await social.profileOf(userId);
    if (!p) return cpage(empty("🔒", "Profil introuvable ou privé", "Ce profil n'existe pas ou n'est pas visible pour toi."));
    setTimeout(() => $("[data-pmenu]")?.addEventListener("click", () => profileMenu(userId, p.username)));
    return cpage(`<div class="profile-head">${avatar(p.avatar_url, p.username, "profile-avatar")}<h1>${h(p.display_name || p.username)}</h1><div class="muted">@${h(p.username)}</div>
      ${p.bio ? `<p class="muted">${h(p.bio)}</p>` : ""}
      <div class="pill-row center"><button class="btn ghost" data-pmenu>${icons.more} Plus</button></div></div>`);
  }

  return { viewFriends, viewProfileOnly, profileMenu, addSheet, codeSheet, rememberInvite, redeemPendingInvite, friendMenu };
})();
