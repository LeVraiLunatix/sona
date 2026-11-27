/* Sona : sessions d'écoute — réglages de l'hôte, modération des participants, signalement.

   Ces écrans s'appuient sur le contrat décrit dans docs/SESSIONS_API.md (règles dans la crate
   Rust `sona_accounts::sessions`). Ils n'apparaissent que si le serveur musique les annonce
   (le snapshot de session contient alors `access` et `role`) : un serveur plus ancien continue de
   fonctionner comme avant. Les vraies vérifications (qui peut expulser, bannir, entrer…) sont
   faites par le serveur à chaque requête, jamais ici. */

"use strict";

const SonaParty = (() => {
  const h = (s) => esc(s);
  const ACCESS = [["friends", "Mes amis", "Seuls tes amis acceptés peuvent rejoindre."], ["invite", "Sur invitation", "Seulement avec un lien privé qui expire."], ["link", "Ouverte à tous avec le code", "Quiconque a le code ou le lien peut rejoindre."]];
  const supported = (s) => s && s.access !== undefined;
  const staff = (s) => s && (s.role === "host" || s.role === "moderator" || s.is_host);

  const call = (path, body, method = "POST") => api(partyPath(path), { method, body: body ? JSON.stringify(body) : undefined });
  const guard = (fn) => async (...a) => { try { return await fn(...a); } catch (e) { toast(e.message); } };

  function settingsSheet(s) {
    const wrap = openSheet(`<h2 class="sheet-title">Réglages de la session</h2>
      <h3 class="set-head">Qui peut rejoindre</h3>
      <div class="reasons" role="radiogroup">${ACCESS.map(([v, l, d]) => `<label class="reason"><input type="radio" name="access" value="${v}" ${s.access === v ? "checked" : ""}><span><b>${h(l)}</b><br><small class="muted">${h(d)}</small></span></label>`).join("")}</div>
      <div class="set-group">
        <label class="switch-row"><span><b>Verrouiller la session</b><small>Plus aucun nouveau participant</small></span><input type="checkbox" data-lock ${s.locked ? "checked" : ""}><i></i></label>
        <label class="switch-row"><span><b>Chat activé</b><small>Couper le chat pour tout le monde</small></span><input type="checkbox" data-chat ${s.chat_enabled !== false ? "checked" : ""}><i></i></label>
        <div class="set-row"><span class="set-text"><b>Nombre maximum de participants</b></span><input class="field small" type="number" min="2" max="50" value="${Number(s.max_participants) || 12}" data-max aria-label="Participants maximum"></div>
      </div>
      <h3 class="set-head">Contrôle de la lecture</h3>
      <div class="set-group">${[["add_tracks", "Ajouter des titres"], ["change_track", "Changer de morceau"], ["pause", "Mettre en pause"]].map(([k, l]) => `<div class="set-row"><span class="set-text"><b>${l}</b></span>
        <select class="field small" data-perm="${k}" aria-label="${l}">${[["host", "Hôte"], ["moderators", "Modérateurs"], ["everyone", "Tout le monde"]].map(([v, t]) => `<option value="${v}" ${(s.permissions?.[k] || (k === "add_tracks" ? "everyone" : "moderators")) === v ? "selected" : ""}>${t}</option>`).join("")}</select></div>`).join("")}</div>
      <h3 class="set-head">Invitation</h3>
      <div class="pill-row"><button class="btn small" data-invite>Créer un lien d'invitation</button><button class="btn small ghost" data-revoke>Révoquer les liens</button></div>
      <p class="muted small-note" id="invite-out">Le lien expire au bout d'une heure et peut être révoqué à tout moment.</p>
      <div class="pill-row"><button class="btn danger" data-close-session>Fermer la session</button></div>`);
    const apply = guard(async (patch) => { partyHandle(await call("/settings", patch)); });
    $$('[name="access"]', wrap).forEach((r) => (r.onchange = () => apply({ access: r.value })));
    $("[data-lock]", wrap).onchange = (e) => apply({ locked: e.target.checked });
    $("[data-chat]", wrap).onchange = (e) => apply({ chat_enabled: e.target.checked });
    $("[data-max]", wrap).onchange = (e) => apply({ max_participants: Math.max(2, Math.min(50, Number(e.target.value) || 12)) });
    $$("[data-perm]", wrap).forEach((sel) => (sel.onchange = () => apply({ permissions: { [sel.dataset.perm]: sel.value } })));
    $("[data-invite]", wrap).onclick = guard(async () => {
      const out = await call("/invite", { ttl_seconds: 3600 });
      const url = `${location.origin}${location.pathname}?party=${encodeURIComponent(s.code)}&invite=${encodeURIComponent(out.token)}`;
      $("#invite-out", wrap).innerHTML = `Lien valable jusqu'à ${new Date(out.expires_at).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })} : <b>${h(url)}</b>`;
      if (navigator.share) navigator.share({ title: "Écoute avec moi sur Sona", url }).catch(() => {});
      else navigator.clipboard?.writeText(url).then(() => toast("Lien copié"));
    });
    $("[data-revoke]", wrap).onclick = guard(async () => { await call("/invite", null, "DELETE"); toast("Liens d'invitation révoqués"); });
    $("[data-close-session]", wrap).onclick = async () => { if (await confirmSheet("Fermer la session pour tout le monde ?", "Fermer")) { wrap.close(); partyLeave(); } };
  }

  /** Participant : modération (hôte, modérateurs) et signalement (tous). */
  function memberSheet(s, m) {
    const me = s.members.find((x) => x.is_me);
    const canMod = staff(s) && !m.is_me && m.role !== "host" && !(me?.role === "moderator" && m.role === "moderator");
    const post = guard(async (path, body) => partyHandle(await call(path, body)));
    actionSheet(m.name, [
      s.is_host && !m.is_me && { icon: icons.crown, label: "Lui passer la main", sub: "Il ou elle choisira la musique", run: () => post("/transfer", { member_id: m.id }) },
      s.is_host && !m.is_me && supported(s) && { icon: icons.sparkles, label: m.role === "moderator" ? "Retirer des modérateurs" : "Nommer modérateur", run: () => post("/moderator", { member_id: m.id, moderator: m.role !== "moderator" }) },
      canMod && { icon: icons.close, label: "Expulser", sub: "Peut revenir", run: async () => { if (await confirmSheet(`Expulser ${m.name} ?`, "Expulser")) post("/kick", { member_id: m.id }); } },
      canMod && supported(s) && { icon: icons.lock, label: "Bannir de la session", sub: "Ne pourra plus revenir", danger: true, run: async () => { if (await confirmSheet(`Bannir ${m.name} de cette session ?`, "Bannir")) post("/ban", { member_id: m.id }); } },
      canMod && supported(s) && { icon: icons.mic, label: m.muted ? "Rendre la parole" : "Couper son chat", run: () => post("/mute", { member_id: m.id, muted: !m.muted }) },
      !m.is_me && { icon: icons.flag, label: "Signaler", danger: true, run: () => SonaSettings.reportSheet({ type: "session", userId: m.uid || null, ref: s.code, title: `Signaler ${m.name}`, snapshot: { name: m.name, session: s.code } }) },
    ]);
  }

  function reportMessage(s, m, index) {
    SonaSettings.reportSheet({ type: "message", userId: m.uid || null, ref: `${s.code}:${m.id ?? index}`, title: "Signaler ce message", snapshot: { text: String(m.text || "").slice(0, 300), by: m.by, session: s.code } });
  }

  /** Suppression d'un message : hôte et modérateurs. */
  async function deleteMessage(s, m, index) {
    if (!(await confirmSheet("Supprimer ce message pour tout le monde ?", "Supprimer"))) return;
    try { partyHandle(await call(`/chat/${encodeURIComponent(m.id ?? index)}`, null, "DELETE")); } catch (e) { toast(e.message); }
  }

  return { supported, staff, settingsSheet, memberSheet, reportMessage, deleteMessage };
})();
