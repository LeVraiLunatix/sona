/* Sona : panneau d'administration et de modération (#/admin), utilisable au téléphone.

   Ce panneau ne protège rien par lui-même : chaque lecture passe par des fonctions
   SQL qui exigent un compte de l'équipe, chaque action par le service sona-accounts
   (rôle relu en base) qui la fait revérifier par la base. Cacher un bouton aux
   modérateurs n'est qu'une commodité. */

"use strict";

const SonaAdmin = (() => {
  const { social, svc } = window.Sona;
  const h = (s) => esc(s);
  const guard = (fn) => async (...a) => { try { return await fn(...a); } catch (e) { toast(e.message); } };
  const date = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—");
  const TABS = [["dashboard", "Tableau de bord"], ["users", "Utilisateurs"], ["reports", "Signalements"], ["appeals", "Contestations"], ["content", "Contenu"], ["rules", "Règles"], ["audit", "Journal"]];
  const STATUS_LABEL = { active: "Actif", quarantined: "Quarantaine", suspended: "Suspendu", banned: "Banni" };
  const ROLE_LABEL = { user: "Utilisateur", moderator: "Modérateur", admin: "Admin" };
  const isAdmin = () => !!account?.is_admin;
  const list = { search: "", role: "", status: "", provider: "", offset: 0 };

  async function view(tab = "dashboard") {
    if (!account?.is_staff) return cpage(empty("🔒", "Accès réservé", "Cette page est réservée à l'équipe de Sona."));
    if (!TABS.some(([t]) => t === tab) || (tab === "audit" && !isAdmin())) tab = "dashboard";
    $("#content").innerHTML = skeleton("Administration");
    const tabs = `<nav class="admin-tabs" aria-label="Sections de l'administration">${TABS.filter(([t]) => t !== "audit" || isAdmin()).map(([t, l]) => `<a href="#/admin/${t}" class="${t === tab ? "on" : ""}" ${t === tab ? 'aria-current="page"' : ""}>${l}</a>`).join("")}</nav>`;
    const body = await ({ dashboard, users, reports, appeals, content, rules, audit }[tab])();
    return cpage(`<h1 class="page-title">Administration</h1>${tabs}<div class="admin">${body}</div>`);
  }

  // ── Tableau de bord ──────────────────────────────────────────────────────

  async function dashboard() {
    const [d, alerts] = await Promise.all([social.rpc("admin_dashboard"), social.table("admin_alerts").select("*").order("created_at", { ascending: false }).limit(8).then((r) => r.data || [])]);
    const days = d.signups_per_day || [];
    const tile = (n, label, href = "", warn = false) => `<a class="tile stat ${warn && n ? "warn" : ""}" ${href ? `href="${href}"` : ""}><b>${n}</b><span>${h(label)}</span></a>`;
    return `<div class="stat-grid">
        ${tile(d.total_users, "Comptes")}${tile(d.active_24h, "Actifs (24 h)")}${tile(d.active_7d, "Actifs (7 j)")}
        ${tile(d.open_reports, "Signalements en attente", "#/admin/reports", true)}${tile(d.open_appeals, "Contestations", "#/admin/appeals", true)}
        ${tile(d.banned, "Bannis")}${tile(d.suspended, "Suspendus")}${tile(d.quarantined, "En quarantaine", "#/admin/users", true)}</div>
      <section class="section"><div class="section-head"><h2>Nouveaux inscrits (14 jours)</h2></div>
        ${barChart(days.map((x) => x.count), days.map((x) => x.day.slice(8)), { highlight: days.length - 1 })}</section>
      <section class="section"><div class="section-head"><h2>Dernières alertes</h2></div><div class="set-group">
        ${alerts.length ? alerts.map((a) => `<div class="set-row"><span class="set-text"><b>${h({ new_report: "Nouveau signalement", new_appeal: "Nouvelle contestation", auto_quarantine: "Quarantaine automatique", signup_spike: "Pic d'inscriptions", signup_burst: "Inscriptions en rafale" }[a.kind] || a.kind)}</b><small>${date(a.created_at)}</small></span></div>`).join("") : `<p class="set-row muted">Aucune alerte.</p>`}</div></section>`;
  }

  // ── Utilisateurs ─────────────────────────────────────────────────────────

  async function users() {
    const rows = await social.rpc("admin_list_users", { p_search: list.search || null, p_role: list.role || null, p_status: list.status || null, p_provider: list.provider || null, p_limit: 20, p_offset: list.offset });
    const total = rows[0]?.total ?? 0;
    setTimeout(() => bindUsers(total));
    const opt = (cur, items) => items.map(([v, l]) => `<option value="${v}" ${cur === v ? "selected" : ""}>${h(l)}</option>`).join("");
    return `<form class="admin-filters" id="user-filters"><input class="field" name="q" value="${h(list.search)}" placeholder="Pseudo, e-mail ou identifiant" aria-label="Rechercher un utilisateur" enterkeyhint="search">
        <select class="field small" name="role" aria-label="Rôle">${opt(list.role, [["", "Tous les rôles"], ["user", "Utilisateurs"], ["moderator", "Modérateurs"], ["admin", "Admins"]])}</select>
        <select class="field small" name="status" aria-label="Statut">${opt(list.status, [["", "Tous les statuts"], ["active", "Actifs"], ["quarantined", "Quarantaine"], ["suspended", "Suspendus"], ["banned", "Bannis"]])}</select>
        <select class="field small" name="provider" aria-label="Méthode de connexion">${opt(list.provider, [["", "Toutes méthodes"], ["email", "E-mail"], ["google", "Google"], ["discord", "Discord"], ["github", "GitHub"]])}</select>
        <button class="btn">Chercher</button></form>
      <p class="muted">${total} compte${total > 1 ? "s" : ""}</p>
      <div class="set-group">${rows.map((u) => `<a class="set-row user-row" data-user="${u.id}">${avatar(u.avatar_url, u.username)}<span class="set-text"><b>${h(u.username)} <span class="badge ${u.status}">${STATUS_LABEL[u.status]}</span>${u.role !== "user" ? ` <span class="badge role">${ROLE_LABEL[u.role]}</span>` : ""}</b>
        <small>${h(u.email || "—")} · inscrit le ${date(u.created_at)} · ${u.providers.length ? u.providers.join(", ") : "—"}</small></span>${icons.right}</a>`).join("") || `<p class="set-row muted">Aucun résultat.</p>`}</div>
      <div class="pill-row center">${list.offset > 0 ? `<button class="btn ghost" data-page="-1">Précédent</button>` : ""}${list.offset + 20 < total ? `<button class="btn ghost" data-page="1">Suivant</button>` : ""}</div>`;
  }

  function bindUsers() {
    $("#user-filters")?.addEventListener("submit", (e) => {
      e.preventDefault();
      const f = new FormData(e.target);
      Object.assign(list, { search: String(f.get("q") || "").trim(), role: f.get("role"), status: f.get("status"), provider: f.get("provider"), offset: 0 });
      route();
    });
    $$("[data-page]").forEach((b) => (b.onclick = () => { list.offset = Math.max(0, list.offset + 20 * +b.dataset.page); route(); }));
    $$("[data-user]").forEach((r) => (r.onclick = guard(() => userSheet(r.dataset.user))));
  }

  /** Demande un motif (obligatoire) avant toute action sensible. */
  function reasonSheet({ title, text = "", confirm = "Confirmer", danger = false, extra = "" }) {
    return new Promise((resolve) => {
      let done = false;
      const wrap = openSheet(`<h2 class="sheet-title">${h(title)}</h2>${text ? `<p class="muted">${h(text)}</p>` : ""}
        <form class="ask">${extra}<textarea class="field area" name="reason" rows="3" maxlength="1000" placeholder="Motif (obligatoire, visible dans le journal)" aria-label="Motif" required></textarea>
        <div class="pill-row"><button type="button" class="btn ghost" data-cancel>Annuler</button><button class="btn ${danger ? "danger" : ""}" type="submit">${h(confirm)}</button></div></form>`,
        { onClose: () => { if (!done) { done = true; resolve(null); } } });
      $("[data-cancel]", wrap).onclick = () => wrap.close();
      $("form", wrap).onsubmit = (e) => {
        e.preventDefault();
        const f = new FormData(e.target);
        const reason = String(f.get("reason") || "").trim();
        if (reason.length < 3) { toast("Un motif est obligatoire."); return; }
        done = true;
        resolve({ reason, form: f });
        wrap.close();
      };
    });
  }

  const DURATIONS = [["3600", "1 heure"], ["86400", "24 heures"], ["604800", "7 jours"], ["2592000", "30 jours"], ["custom", "Durée personnalisée…"]];

  async function act(path, body, ok = "C'est fait") {
    await svc(path, { method: "POST", body });
    toast(ok);
  }

  async function sanction(target, kind, report) {
    const labels = { warning: "Avertir", suspension: "Suspendre", ban: "Bannir définitivement", quarantine: "Mettre en quarantaine" };
    const extra = kind === "suspension" ? `<select class="field" name="duration" aria-label="Durée">${DURATIONS.map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}</select><input class="field" name="hours" type="number" min="1" max="8760" placeholder="Heures (durée personnalisée)" hidden>` : "";
    const answer = await reasonSheet({ title: labels[kind], text: { warning: "Le message sera affiché dans l'app de la personne.", suspension: "La personne est déconnectée immédiatement.", ban: "Définitif : son e-mail et ses identifiants OAuth sont retenus pour empêcher de recréer un compte.", quarantine: "Invisible des autres en attendant ta décision." }[kind], confirm: labels[kind], danger: kind === "ban", extra });
    if (!answer) return false;
    let seconds;
    if (kind === "suspension") {
      const d = String(answer.form.get("duration"));
      seconds = d === "custom" ? Math.round(Number(answer.form.get("hours")) * 3600) : Number(d);
      if (!seconds || seconds < 60) { toast("Durée invalide."); return false; }
    }
    await act("/admin/sanction", { target, kind, reason: answer.reason, duration_seconds: seconds, report_id: report || null }, "Sanction appliquée");
    return true;
  }

  async function userSheet(id) {
    const d = await social.rpc("admin_user_detail", { p_user: id });
    const p = d.profile;
    const live = ["banned", "suspended", "quarantined"].includes(p.status);
    const target = p.role === "user" || (isAdmin() && p.role !== "admin");
    const items = [
      { label: "Avertir", run: () => sanction(id, "warning") },
      { label: "Suspendre…", run: () => sanction(id, "suspension") },
      isAdmin() && { label: "Bannir définitivement", danger: true, run: () => sanction(id, "ban") },
      { label: "Mettre en quarantaine", run: () => sanction(id, "quarantine") },
      live && { label: "Lever la sanction en cours", run: async () => { const a = await reasonSheet({ title: "Lever la sanction", confirm: "Lever" }); if (a) await act("/admin/lift", { target: id, reason: a.reason }); } },
      { label: "Forcer le changement de pseudo", run: () => reset(id, ["username"], true, "Le pseudo est remplacé ; la personne doit en choisir un nouveau.") },
      { label: "Forcer le changement de photo", run: () => reset(id, ["avatar"], true, "La photo est retirée ; la personne doit en choisir une autre.") },
      { label: "Réinitialiser pseudo, photo et bio", run: () => reset(id, ["username", "avatar", "bio"], false, "Remplace le pseudo, efface la photo et la bio.") },
      { label: "Déconnecter de tous les appareils", run: async () => { const a = await reasonSheet({ title: "Déconnecter de tous les appareils", confirm: "Déconnecter" }); if (a) await act("/admin/revoke-sessions", { target: id, reason: a.reason }); } },
      isAdmin() && p.role !== "admin" && { label: "Changer le rôle…", run: () => roleSheet(id, p.role) },
      isAdmin() && p.role !== "admin" && { label: "Supprimer le compte et ses données", danger: true, run: async () => { const a = await reasonSheet({ title: "Supprimer le compte", text: "Irréversible : profil, amitiés, bibliothèque, playlists et historique sont effacés.", confirm: "Supprimer", danger: true }); if (a) await act("/admin/delete-user", { target: id, reason: a.reason }, "Compte supprimé"); } },
    ].filter(Boolean);
    const wrap = openSheet(`<div class="user-head">${avatar(p.avatar_url, p.username, "profile-avatar small")}<div><h2 class="sheet-title">${h(p.username)}</h2><small class="muted">${h(d.email || "—")}</small></div></div>
      <dl class="facts"><div><dt>Statut</dt><dd><span class="badge ${p.status}">${STATUS_LABEL[p.status]}</span>${p.status_reason ? ` — ${h(p.status_reason)}` : ""}${p.status_until ? ` jusqu'au ${date(p.status_until)}` : ""}</dd></div>
        <div><dt>Rôle</dt><dd>${ROLE_LABEL[p.role]}</dd></div><div><dt>Connexion</dt><dd>${d.providers.map(h).join(", ") || "—"}</dd></div>
        <div><dt>Inscrit</dt><dd>${date(p.created_at)} · vu ${date(p.last_seen_at)}</dd></div>
        <div><dt>Activité</dt><dd>${d.friends} ami(s) · ${d.reports_received} signalement(s) reçu(s) · ${d.reports_made} fait(s)</dd></div></dl>
      <h3 class="set-head">Historique des sanctions</h3>
      <div class="set-group">${d.sanctions.length ? d.sanctions.map((s) => `<div class="set-row"><span class="set-text"><b>${{ warning: "Avertissement", suspension: "Suspension", ban: "Bannissement", quarantine: "Quarantaine" }[s.kind]}${s.revoked_at ? " (levée)" : ""}</b><small>${date(s.created_at)} — ${h(s.reason)}${s.created_by ? "" : " (automatique)"}</small></span></div>`).join("") : `<p class="set-row muted">Aucune.</p>`}</div>
      <h3 class="set-head">Actions</h3><div class="menu">${target ? items.map((it, i) => `<button class="menu-item ${it.danger ? "danger" : ""}" data-act="${i}"><span class="mi-text"><span class="mi-label">${h(it.label)}</span></span></button>`).join("") : `<p class="muted">Tu ne peux pas agir sur ce compte (rôle égal ou supérieur).</p>`}</div>`);
    $$("[data-act]", wrap).forEach((b) => (b.onclick = guard(async () => { const done = await items[+b.dataset.act].run(); if (done !== false) { wrap.close(); setTimeout(route, 200); } })));
  }

  async function reset(id, fields, force, text) {
    const a = await reasonSheet({ title: "Modifier le profil", text, confirm: "Appliquer" });
    if (a) await act("/admin/reset-profile", { target: id, fields, force, reason: a.reason });
  }

  async function roleSheet(id, current) {
    const a = await reasonSheet({ title: "Changer le rôle", confirm: "Appliquer", extra: `<select class="field" name="role" aria-label="Rôle">${["user", "moderator", "admin"].map((r) => `<option value="${r}" ${r === current ? "selected" : ""}>${ROLE_LABEL[r]}</option>`).join("")}</select>` });
    if (a) await act("/admin/role", { target: id, role: a.form.get("role"), reason: a.reason }, "Rôle modifié");
  }

  // ── Signalements ─────────────────────────────────────────────────────────

  const REPORT_FILTER = { status: "open" };
  const REASON_LABEL = { spam: "Spam", harassment: "Harcèlement", inappropriate: "Contenu inapproprié", impersonation: "Usurpation", other: "Autre" };
  const TYPE_LABEL = { profile: "Profil", playlist: "Playlist", username: "Pseudo", avatar: "Photo", session: "Session", message: "Message" };

  async function reports() {
    let q = social.table("reports").select("*, reporter:profiles!reports_reporter_id_fkey(username), target:profiles!reports_target_user_id_fkey(id,username,avatar_url,status), notes:report_notes(id)").order("created_at", { ascending: false }).limit(50);
    if (REPORT_FILTER.status) q = q.eq("status", REPORT_FILTER.status);
    const { data, error } = await q;
    if (error) throw new Error(error.message);
    setTimeout(() => bindReports(data));
    return `<div class="segmented small admin-seg">${[["open", "Ouverts"], ["in_progress", "En cours"], ["resolved", "Résolus"], ["dismissed", "Rejetés"], ["", "Tous"]].map(([v, l]) => `<button data-rfilter="${v}" class="${REPORT_FILTER.status === v ? "on" : ""}">${l}</button>`).join("")}</div>
      <div class="set-group">${data.map((r) => `<a class="set-row user-row" data-report="${r.id}"><span class="set-text"><b>${TYPE_LABEL[r.target_type]} · ${REASON_LABEL[r.reason]} <span class="badge ${r.status}">${{ open: "Ouvert", in_progress: "En cours", resolved: "Résolu", dismissed: "Rejeté" }[r.status]}</span></b>
        <small>${r.target ? `contre @${h(r.target.username)}` : "cible supprimée"} · par ${r.reporter ? `@${h(r.reporter.username)}` : "—"} · ${date(r.created_at)}${r.assigned_to ? " · assigné" : ""}</small></span>${icons.right}</a>`).join("") || `<p class="set-row muted">Aucun signalement.</p>`}</div>`;
  }

  function bindReports(data) {
    $$("[data-rfilter]").forEach((b) => (b.onclick = () => { REPORT_FILTER.status = b.dataset.rfilter; route(); }));
    $$("[data-report]").forEach((r) => (r.onclick = guard(async () => reportSheet(data.find((x) => x.id === r.dataset.report)))));
  }

  async function reportSheet(r) {
    const { data: notes } = await social.table("report_notes").select("note, created_at").eq("report_id", r.id).order("created_at");
    const snap = r.snapshot && Object.keys(r.snapshot).length ? `<pre class="snap">${h(JSON.stringify(r.snapshot, null, 2))}</pre>` : "";
    const t = r.target;
    const items = [
      { label: "Prendre en charge", run: () => update(r.id, "in_progress", account.id) },
      t && r.target_type !== "playlist" && { label: "Avertir", run: () => sanction(t.id, "warning", r.id) },
      t && r.target_type !== "playlist" && { label: "Suspendre…", run: () => sanction(t.id, "suspension", r.id) },
      t && r.target_type !== "playlist" && isAdmin() && { label: "Bannir", danger: true, run: () => sanction(t.id, "ban", r.id) },
      t && r.target_type === "playlist" && r.target_ref && { label: "Masquer la playlist", run: () => contentAction("hide", t.id, r.target_ref) },
      t && r.target_type === "playlist" && r.target_ref && { label: "Supprimer la playlist", danger: true, run: () => contentAction("delete", t.id, r.target_ref) },
      t && ["username", "avatar"].includes(r.target_type) && { label: r.target_type === "username" ? "Forcer un nouveau pseudo" : "Forcer une nouvelle photo", run: () => reset(t.id, [r.target_type === "username" ? "username" : "avatar"], true, "") },
      r.target_type === "session" && r.target_ref && { label: "Fermer la session", danger: true, run: () => sessionAction(r.target_ref, "close") },
      { label: "Résoudre sans sanction", run: () => update(r.id, "resolved") },
      { label: "Rejeter", run: () => update(r.id, "dismissed") },
      t && { label: "Voir le compte", run: () => userSheet(t.id) },
    ].filter(Boolean);
    const wrap = openSheet(`<h2 class="sheet-title">${TYPE_LABEL[r.target_type]} · ${REASON_LABEL[r.reason]}</h2>
      <dl class="facts"><div><dt>Cible</dt><dd>${t ? `@${h(t.username)} (${STATUS_LABEL[t.status]})` : "supprimée"}${r.target_ref ? ` · réf. ${h(r.target_ref)}` : ""}</dd></div>
        <div><dt>Signalé par</dt><dd>${r.reporter ? `@${h(r.reporter.username)}` : "—"}</dd></div><div><dt>Date</dt><dd>${date(r.created_at)}</dd></div>
        ${r.details ? `<div><dt>Précisions</dt><dd>${h(r.details)}</dd></div>` : ""}${r.resolution ? `<div><dt>Résolution</dt><dd>${h(r.resolution)}</dd></div>` : ""}</dl>${snap}
      <h3 class="set-head">Notes internes</h3><div class="set-group">${(notes || []).map((n) => `<div class="set-row"><span class="set-text"><b>${h(n.note)}</b><small>${date(n.created_at)}</small></span></div>`).join("") || `<p class="set-row muted">Aucune note.</p>`}</div>
      <form class="ask" data-note><input class="field" name="n" placeholder="Ajouter une note interne" maxlength="2000"><button class="btn small">Ajouter</button></form>
      <h3 class="set-head">Actions (le signalant est prévenu à la clôture)</h3><div class="menu">${items.map((it, i) => `<button class="menu-item ${it.danger ? "danger" : ""}" data-ra="${i}"><span class="mi-text"><span class="mi-label">${h(it.label)}</span></span></button>`).join("")}</div>`);
    $("[data-note]", wrap).onsubmit = guard(async (e) => {
      e.preventDefault();
      const n = String(new FormData(e.target).get("n") || "").trim();
      if (!n) return;
      await act("/admin/report", { report: r.id, status: r.status, note: n }, "Note ajoutée");
      wrap.close();
      reportSheet(r);
    });
    $$("[data-ra]", wrap).forEach((b) => (b.onclick = guard(async () => { const done = await items[+b.dataset.ra].run(); if (done !== false) { wrap.close(); setTimeout(route, 200); } })));
  }

  async function update(report, status, assign) {
    let resolution;
    if (["resolved", "dismissed"].includes(status)) { const a = await reasonSheet({ title: status === "resolved" ? "Résoudre" : "Rejeter", text: "Une phrase pour le journal.", confirm: "Valider" }); if (!a) return false; resolution = a.reason; }
    await act("/admin/report", { report, status, assign_to: assign || null, resolution }, "Signalement mis à jour");
  }

  // ── Contestations ────────────────────────────────────────────────────────

  async function appeals() {
    const { data, error } = await social.table("appeals").select("*, user:profiles!appeals_user_id_fkey(username), sanction:sanctions!appeals_sanction_id_fkey(kind, reason, created_at)").eq("status", "open").order("created_at");
    if (error) throw new Error(error.message);
    setTimeout(() => $$("[data-appeal]").forEach((b) => (b.onclick = guard(async () => {
      const a = data.find((x) => x.id === b.dataset.appeal);
      const accept = b.dataset.accept === "1";
      const ans = await reasonSheet({ title: accept ? "Accepter la contestation" : "Refuser la contestation", text: accept ? "La sanction est levée." : "", confirm: accept ? "Accepter" : "Refuser" });
      if (ans) { await act("/admin/appeal", { appeal: a.id, accept, response: ans.reason }); route(); }
    }))));
    return `<div class="set-group">${data.map((a) => `<div class="set-row appeal"><span class="set-text"><b>@${h(a.user?.username || "?")} — ${{ warning: "Avertissement", suspension: "Suspension", ban: "Bannissement", quarantine: "Quarantaine" }[a.sanction?.kind] || ""}</b>
        <small>Sanction : ${h(a.sanction?.reason || "")}</small><small class="quote">« ${h(a.message)} »</small></span>
        <span class="pill-row tight"><button class="btn small" data-appeal="${a.id}" data-accept="1">Accepter</button><button class="btn small ghost" data-appeal="${a.id}" data-accept="0">Refuser</button></span></div>`).join("") || `<p class="set-row muted">Aucune contestation en attente.</p>`}</div>`;
  }

  // ── Contenu et sessions ──────────────────────────────────────────────────

  async function contentAction(action, owner, ref) {
    const a = await reasonSheet({ title: action === "hide" ? "Masquer la playlist" : "Supprimer la playlist", confirm: action === "hide" ? "Masquer" : "Supprimer", danger: action === "delete" });
    if (!a) return false;
    await act("/admin/content", { action, kind: "playlist", owner, ref: String(ref), reason: a.reason });
  }

  async function sessionAction(code, action, user) {
    const a = await reasonSheet({ title: action === "close" ? "Fermer la session" : "Expulser de la session", confirm: "Valider", danger: true });
    if (!a) return false;
    await act("/admin/session", { code, action, user: user || null, reason: a.reason });
  }

  async function content() {
    setTimeout(() => {
      $("#content-form")?.addEventListener("submit", guard(async (e) => {
        e.preventDefault();
        const f = new FormData(e.target);
        await contentAction(String(f.get("action")), String(f.get("owner")).trim(), String(f.get("ref")).trim());
      }));
      $("#session-form")?.addEventListener("submit", guard(async (e) => {
        e.preventDefault();
        const f = new FormData(e.target);
        await sessionAction(String(f.get("code")).trim().toUpperCase(), String(f.get("action")), String(f.get("user") || "").trim() || null);
      }));
    });
    return `<section class="section"><div class="section-head"><h2>Playlist publique</h2></div>
        <form class="admin-filters" id="content-form"><input class="field" name="owner" placeholder="Identifiant du propriétaire" required><input class="field" name="ref" placeholder="Numéro de la playlist" required>
        <select class="field small" name="action"><option value="hide">Masquer</option><option value="delete">Supprimer</option></select><button class="btn">Appliquer</button></form>
        <p class="muted">Un profil se masque en le mettant en quarantaine depuis la fiche de l'utilisateur.</p></section>
      <section class="section"><div class="section-head"><h2>Session d'écoute</h2></div>
        <form class="admin-filters" id="session-form"><input class="field" name="code" placeholder="Code de la session" required maxlength="16">
        <input class="field" name="user" placeholder="Identifiant à expulser (facultatif)"><select class="field small" name="action"><option value="close">Fermer</option><option value="kick">Expulser</option><option value="delete_message">Supprimer un message</option></select><button class="btn">Appliquer</button></form></section>`;
  }

  // ── Règles : mots interdits, identifiants bannis ─────────────────────────

  async function rules() {
    if (!isAdmin()) return `<p class="muted">Réservé aux administrateurs.</p>`;
    setTimeout(() => {
      $("#term-form")?.addEventListener("submit", guard(async (e) => { e.preventDefault(); const f = new FormData(e.target); await act("/admin/forbidden-term", { term: String(f.get("term")), kind: String(f.get("kind")) }, "Ajouté"); e.target.reset(); }));
      $("#ban-form")?.addEventListener("submit", guard(async (e) => {
        e.preventDefault();
        const f = new FormData(e.target);
        const a = await reasonSheet({ title: "Bloquer cet identifiant", confirm: "Bloquer", danger: true });
        if (!a) return;
        const hours = Number(f.get("hours"));
        await act("/admin/ban-identifier", { kind: String(f.get("kind")), value: String(f.get("value")).trim(), reason: a.reason, duration_seconds: hours > 0 ? Math.round(hours * 3600) : null }, "Bloqué");
        e.target.reset();
      }));
    });
    return `<section class="section"><div class="section-head"><h2>Pseudos et mots interdits</h2></div>
        <form class="admin-filters" id="term-form"><input class="field" name="term" placeholder="Mot ou pseudo" required minlength="3" maxlength="40"><select class="field small" name="kind"><option value="offensive">Mot offensant (contenu dans un pseudo)</option><option value="reserved">Pseudo réservé (exact)</option></select><button class="btn">Ajouter</button></form>
        <p class="muted">Comparé sans accents, majuscules ni séparateurs, « leet speak » défait. Évite les termes courts qui se cachent dans des prénoms.</p></section>
      <section class="section"><div class="section-head"><h2>Empêcher une inscription</h2></div>
        <form class="admin-filters" id="ban-form"><select class="field small" name="kind"><option value="email">Adresse e-mail</option><option value="email_domain">Domaine d'e-mail</option><option value="ip">Adresse ou plage IP (ex. 192.0.2.0/24)</option></select>
        <input class="field" name="value" placeholder="Valeur" required maxlength="200"><input class="field small" name="hours" type="number" min="0" placeholder="Heures (IP, vide = illimité)"><button class="btn">Bloquer</button></form>
        <p class="muted">Un bannissement ajoute automatiquement l'e-mail et les identifiants OAuth du compte (hachés). Les domaines d'e-mails jetables courants sont déjà bloqués.</p></section>
      <section class="section"><div class="section-head"><h2>Durées de conservation</h2></div><div class="set-group">
        <div class="set-row"><span class="set-text"><b>Journal d'audit</b><small>12 mois, puis supprimé automatiquement</small></span></div>
        <div class="set-row"><span class="set-text"><b>Signalements clos · contestations traitées</b><small>6 mois · 12 mois</small></span></div>
        <div class="set-row"><span class="set-text"><b>Événements d'inscription (IP)</b><small>30 jours</small></span></div></div></section>`;
  }

  // ── Journal d'audit ──────────────────────────────────────────────────────

  async function audit() {
    const { data, error } = await social.table("audit_log").select("*").order("at", { ascending: false }).limit(100);
    if (error) throw new Error(error.message);
    return `<p class="muted">Non modifiable, non supprimable. Conservation : 12 mois.</p><div class="set-group">${data.map((a) => `<div class="set-row audit"><span class="set-text"><b>${h(a.action)}</b><small>${date(a.at)} · par ${a.actor_id ? h(a.actor_id.slice(0, 8)) : "système"} (${h(a.actor_role || "—")})${a.target_user_id ? ` · sur ${h(a.target_user_id.slice(0, 8))}` : ""}</small>${a.reason ? `<small class="quote">${h(a.reason)}</small>` : ""}</span></div>`).join("") || `<p class="set-row muted">Vide.</p>`}</div>`;
  }

  return { view, sanction, userSheet };
})();
