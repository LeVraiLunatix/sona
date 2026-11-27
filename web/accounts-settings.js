/* Sona : réglages du compte, confidentialité, services connectés, notifications,
   signalements, obligations de modération (avertissement, pseudo à changer). */

"use strict";

const SonaSettings = (() => {
  const { auth, social, passkeys } = window.Sona;
  const h = (s) => esc(s);
  const sub = (t) => `<p class="page-sub">${h(t)}</p>`;
  const row = (title, subtitle, right = "") => `<div class="set-row"><span class="set-text"><b>${h(title)}</b>${subtitle ? `<small>${h(subtitle)}</small>` : ""}</span>${right}</div>`;
  const select = (key, value, options) => `<select class="field small" data-select="${key}" aria-label="${h(key)}">${options.map(([v, l]) => `<option value="${v}" ${v === value ? "selected" : ""}>${h(l)}</option>`).join("")}</select>`;
  const when = (iso) => (iso ? new Date(iso).toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" }) : "—");

  const guard = (fn) => async (...a) => { try { return await fn(...a); } catch (e) { toast(e.message); } };

  // ── Réglages > Compte ────────────────────────────────────────────────────

  async function viewAccount() {
    $("#content").innerHTML = skeleton("Compte");
    const guest = auth.isGuest();
    const [profile, identities, keys] = await Promise.all([
      social.me(),
      guest ? [] : auth.identities().catch(() => []),
      guest || !passkeys.supported() ? [] : passkeys.list().catch(() => []),
    ]);
    const email = auth.user()?.email;
    const hasPassword = identities.some((i) => i.provider === "email");
    const linked = new Set(identities.map((i) => i.provider));
    setTimeout(() => bindAccount(profile, identities));
    if (guest) {
      return cpage(`<h1 class="page-title">Compte</h1>${sub("Tu utilises Sona sans compte.")}
        <div class="set-group">${row("Crée ton compte", "Ta bibliothèque, tes playlists et ton historique sont conservés.", `<button class="btn small" data-upgrade>Créer</button>`)}</div>
        <h3 class="set-head">Mes données</h3><div class="set-group">${linkRow("data-export", icons.download, "Exporter mes données", "Un fichier JSON")}${linkRow("data-delete", icons.trash, "Supprimer mes données", "Efface tout, définitivement")}</div>`);
    }
    return cpage(`<h1 class="page-title">Compte</h1>${sub("Ton profil, tes méthodes de connexion et tes données.")}
      <h3 class="set-head">Profil</h3><div class="set-group">
        <div class="set-row"><button class="acc-photo" data-photo aria-label="Changer de photo">${avatar(profile.avatar_url, profile.username, "profile-avatar small")}</button><span class="set-text"><b>Photo</b><small>${profile.force_avatar_change ? "À changer : la précédente a été retirée" : "Touche pour changer"}</small></span>
          ${profile.avatar_url ? `<button class="btn small ghost" data-photo-remove>Retirer</button>` : ""}<input type="file" accept="image/*" hidden data-file></div>
        ${linkRow("data-edit-name", icons.pencil, "Pseudo", `@${profile.username}${profile.force_username_change ? " · à changer" : ""}`)}
        ${linkRow("data-edit-bio", icons.pencil, "Bio", profile.bio || "Une phrase pour te présenter (160 caractères)")}
      </div>
      <h3 class="set-head">Connexion</h3><div class="set-group">
        ${linkRow("data-edit-email", icons.user, "Adresse e-mail", email || "Aucune")}
        ${linkRow("data-edit-password", icons.lock, hasPassword ? "Changer le mot de passe" : "Définir un mot de passe", hasPassword ? "Dernière méthode « e-mail »" : "Pour te connecter aussi avec ton e-mail")}
        ${PROVIDERS_LIST().map(([id, name, logo]) => `<div class="set-row"><span class="mi-icon">${logo}</span><span class="set-text"><b>${h(name)}</b><small>${linked.has(id) ? "Relié" : "Non relié"}</small></span>
          ${linked.has(id) ? `<button class="btn small ghost" data-unlink="${id}">Délier</button>` : `<button class="btn small" data-link="${id}">Lier</button>`}</div>`).join("")}
        <p class="set-note">Si tu te connectes avec une autre méthode utilisant la même adresse e-mail vérifiée, c'est le même compte. Tu ne peux jamais retirer ta dernière méthode.</p>
      </div>
      ${passkeys.supported() && window.Sona.config.accountsUrl ? `<h3 class="set-head">Clés d'accès</h3><div class="set-group">
        ${keys.map((k) => `<div class="set-row"><span class="set-text"><b>${h(k.device_name || "Clé d'accès")}</b><small>Ajoutée le ${when(k.created_at)}${k.last_used_at ? ` · utilisée le ${when(k.last_used_at)}` : ""}</small></span><button class="btn small ghost" data-key-del="${k.id}">Supprimer</button></div>`).join("")}
        ${linkRow("data-key-add", icons.plus, "Ajouter une clé d'accès", "Face ID, Touch ID, Windows Hello")}</div>` : ""}
      <h3 class="set-head">Sessions</h3><div class="set-group">
        ${linkRow("data-signout-all", icons.close, "Me déconnecter de tous les appareils", "Ferme toutes les sessions ouvertes, y compris celle-ci")}</div>
      <h3 class="set-head">Mes données</h3><div class="set-group">
        ${linkRow("data-export", icons.download, "Exporter mes données", "Un fichier JSON avec tout ce que Sona sait de toi")}
        ${linkRow("data-delete", icons.trash, "Supprimer mon compte", "Efface le compte et toutes les données, définitivement")}</div>`);
  }

  const PROVIDERS_LIST = () => SonaUI.PROVIDERS;

  function bindAccount(profile) {
    const $r = (s) => document.querySelector(s);
    const refresh = () => route();
    $r("[data-upgrade]")?.addEventListener("click", SonaUI.upgradeSheet);
    $r("[data-export]")?.addEventListener("click", SonaUI.exportData);
    $r("[data-delete]")?.addEventListener("click", SonaUI.deleteAccount);
    $r("[data-photo]")?.addEventListener("click", () => $r("[data-file]").click());
    $r("[data-file]")?.addEventListener("change", guard(async (e) => {
      const f = e.target.files[0];
      if (!f) return;
      toast("Envoi de la photo…");
      const url = await social.uploadAvatar(f);
      account = SonaUI.accountFrom(await social.updateProfile({ avatar_url: url }));
      refreshChrome();
      refresh();
    }));
    $r("[data-photo-remove]")?.addEventListener("click", guard(async () => {
      account = SonaUI.accountFrom(await social.updateProfile({ avatar_url: null }));
      refreshChrome();
      refresh();
    }));
    $r("[data-edit-name]")?.addEventListener("click", () => usernameSheet(profile.username).then((ok) => ok && refresh()));
    $r("[data-edit-bio]")?.addEventListener("click", guard(async () => {
      const bio = await askText({ title: "Ta bio", value: profile.bio || "", placeholder: "Une phrase pour te présenter", confirm: "Enregistrer", hint: "160 caractères maximum, visible selon tes réglages de confidentialité." });
      if (bio == null) return;
      if (bio.length > 160) throw new Error("160 caractères maximum.");
      await social.updateProfile({ bio });
      refresh();
    }));
    $r("[data-edit-email]")?.addEventListener("click", guard(async () => {
      const email = await askText({ title: "Nouvelle adresse e-mail", placeholder: "toi@exemple.fr", confirm: "Changer", hint: "Un message de confirmation est envoyé à la nouvelle adresse." });
      if (!email) return;
      await auth.updateEmail(email);
      toast("Vérifie ta boîte mail pour confirmer");
    }));
    $r("[data-edit-password]")?.addEventListener("click", () => passwordSheet());
    $$("[data-link]").forEach((b) => (b.onclick = guard(() => auth.linkOAuth(b.dataset.link))));
    $$("[data-unlink]").forEach((b) => (b.onclick = guard(async () => {
      const all = await auth.identities();
      const identity = all.find((i) => i.provider === b.dataset.unlink);
      if (!identity) return;
      // Jamais la dernière méthode de connexion : refusé avant même de demander confirmation.
      if (all.length <= 1) throw new Error("Tu ne peux pas retirer ta dernière méthode de connexion.");
      if (!(await confirmSheet(`Délier ${SonaUI.providerName(b.dataset.unlink)} de ton compte ?`, "Délier"))) return;
      await auth.unlink(identity);
      toast("Méthode retirée");
      refresh();
    })));
    $r("[data-key-add]")?.addEventListener("click", guard(async () => {
      const name = await askText({ title: "Nom de cet appareil", value: /iPhone|iPad/.test(navigator.userAgent) ? "Mon iPhone" : "Cet appareil", confirm: "Continuer" });
      if (name == null) return;
      await passkeys.register(name);
      toast("Clé d'accès ajoutée");
      refresh();
    }));
    $$("[data-key-del]").forEach((b) => (b.onclick = guard(async () => {
      if (!(await confirmSheet("Supprimer cette clé d'accès ?", "Supprimer"))) return;
      await passkeys.remove(b.dataset.keyDel);
      refresh();
    })));
    $r("[data-signout-all]")?.addEventListener("click", guard(async () => {
      if (!(await confirmSheet("Te déconnecter de tous tes appareils ?", "Déconnecter"))) return;
      await auth.signOut(true);
      signOutLocal(true);
    }));
  }

  /** Photo et pseudo dans la barre latérale et ailleurs. */
  function refreshChrome() {
    if (typeof renderSidebarAccount === "function") renderSidebarAccount();
    else document.querySelector(".side-user")?.replaceChildren();
  }

  function usernameSheet(current, { forced = false } = {}) {
    return new Promise((resolve) => {
      let done = false;
      let ok = false;
      const wrap = openSheet(`<h2 class="sheet-title">${forced ? "Choisis un nouveau pseudo" : "Changer de pseudo"}</h2>
        ${forced ? `<p class="muted">Ton ancien pseudo n'était pas conforme aux règles de Sona. Tu dois en choisir un nouveau pour continuer.</p>` : ""}
        <form class="ask"><input class="field" name="u" value="${h(forced ? "" : current)}" maxlength="20" autocomplete="off" autocapitalize="none" spellcheck="false" placeholder="ex. alice_92" aria-label="Pseudo" required>
        <p class="ob-check" id="un-check" role="status" aria-live="polite">3 à 20 caractères : lettres, chiffres, _ . -</p>
        <div class="pill-row">${forced ? "" : `<button type="button" class="btn ghost" data-cancel>Annuler</button>`}<button class="btn" type="submit" disabled>Enregistrer</button></div></form>`,
        { onClose: () => { if (!done) { done = true; resolve(false); } } });
      const input = $("input", wrap);
      const submit = $("button[type=submit]", wrap);
      const say = (cls, text) => { const el = $("#un-check", wrap); el.className = `ob-check ${cls}`; el.textContent = text; };
      let timer;
      input.oninput = () => {
        clearTimeout(timer);
        const v = input.value.trim();
        submit.disabled = true;
        ok = false;
        if (!v || v === current) return say("", "3 à 20 caractères : lettres, chiffres, _ . -");
        say("", "Vérification…");
        timer = setTimeout(async () => {
          try {
            const r = await social.usernameAvailable(v);
            const why = { format: "3 à 20 caractères : lettres, chiffres, _ . -", taken: "Ce pseudo est déjà pris.", reserved: "Ce pseudo est réservé.", offensive: "Ce pseudo n'est pas accepté." };
            if (input.value.trim() !== v) return;
            ok = r.available;
            submit.disabled = !ok;
            say(ok ? "ok" : "bad", ok ? "Disponible" : why[r.reason] || "Indisponible.");
          } catch (e) { say("bad", e.message); }
        }, 300);
      };
      $("[data-cancel]", wrap)?.addEventListener("click", () => wrap.close());
      $("form", wrap).onsubmit = async (e) => {
        e.preventDefault();
        if (!ok) return;
        submit.disabled = true;
        try {
          account = SonaUI.accountFrom(await social.updateProfile({ username: input.value.trim() }));
          done = true;
          resolve(true);
          wrap.close();
          refreshChrome();
          toast("Pseudo modifié");
        } catch (err) { say("bad", /username_|duplicate|unique/i.test(err.original?.message || err.message) ? "Ce pseudo n'est pas disponible." : err.message); }
      };
      setTimeout(() => input.focus(), 250);
    });
  }

  function passwordSheet() {
    const wrap = openSheet(`<h2 class="sheet-title">Mot de passe</h2>
      <form class="ask" novalidate><input class="field" name="p" type="password" autocomplete="new-password" placeholder="Nouveau mot de passe" aria-label="Nouveau mot de passe" required>
      <p class="pw-hint" id="pw-hint">10 caractères minimum, avec minuscules, majuscules et chiffres.</p>
      <div class="pill-row"><button type="button" class="btn ghost" data-cancel>Annuler</button><button class="btn" type="submit">Enregistrer</button></div></form>`);
    const input = $("input", wrap);
    input.oninput = () => { const p = input.value ? auth.passwordProblem(input.value, auth.user()?.email || "") : null; const el = $("#pw-hint", wrap); el.textContent = p || "10 caractères minimum, avec minuscules, majuscules et chiffres."; el.classList.toggle("bad", !!p); };
    $("[data-cancel]", wrap).onclick = () => wrap.close();
    $("form", wrap).onsubmit = guard(async (e) => {
      e.preventDefault();
      await auth.updatePassword(input.value);
      wrap.close();
      toast("Mot de passe changé");
      route();
    });
  }

  // ── Réglages > Confidentialité ───────────────────────────────────────────

  const WHO = [["everyone", "Tout le monde"], ["friends", "Mes amis"], ["nobody", "Personne"]];

  async function viewPrivacy() {
    $("#content").innerHTML = skeleton("Confidentialité");
    if (auth.isGuest()) return cpage(`<h1 class="page-title">Confidentialité</h1>${sub("Sans compte, personne ne te voit : tu n'apparais nulle part.")}`);
    const [p, blocked] = await Promise.all([social.privacy(), social.blocked().catch(() => [])]);
    setTimeout(() => bindPrivacy(p));
    return cpage(`<h1 class="page-title">Confidentialité</h1>${sub("Par défaut, tout est réservé à tes amis. Ces règles sont appliquées par le serveur, pas seulement par l'interface.")}
      <h3 class="set-head">Profil</h3><div class="set-group">
        ${row("Visibilité du profil", "", select("profile_visibility", p.profile_visibility, [["public", "Public"], ["minimal", "Pseudo et photo seulement"], ["friends", "Amis seulement"], ["private", "Privé"]]))}
        ${row("Qui peut m'envoyer une demande d'ami", "", select("who_can_request", p.who_can_request, [["everyone", "Tout le monde"], ["friends_of_friends", "Amis d'amis"], ["nobody", "Personne"]]))}
      </div>
      <h3 class="set-head">Écoute</h3><div class="set-group">
        ${row("Qui voit ce que j'écoute en ce moment", "Désactivé par défaut", select("presence_visibility", p.presence_visibility, WHO))}
        ${row("Qui voit mon historique", "", select("history_visibility", p.history_visibility, WHO))}
        ${row("Qui voit mes statistiques", "", select("stats_visibility", p.stats_visibility, WHO))}
        ${row("Qui voit mes playlists", "", select("playlists_visibility", p.playlists_visibility, WHO))}
        <label class="switch-row"><span><b>Mode invisible</b><small>J'écoute sans apparaître nulle part</small></span><input type="checkbox" data-toggle="invisible_mode" ${p.invisible_mode ? "checked" : ""}><i></i></label>
        <label class="switch-row"><span><b>Ne pas déranger</b><small>Aucune invitation à une session d'écoute</small></span><input type="checkbox" data-toggle="do_not_disturb" ${p.do_not_disturb ? "checked" : ""}><i></i></label>
      </div>
      <h3 class="set-head">Comptes bloqués</h3><div class="set-group" id="blocked-list">${blockedRows(blocked)}</div>`);
  }

  const blockedRows = (list) => list.length
    ? list.map((b) => `<div class="set-row">${avatar(b.avatar_url, b.username)}<span class="set-text"><b>@${h(b.username)}</b></span><button class="btn small ghost" data-unblock="${b.user_id}">Débloquer</button></div>`).join("")
    : `<p class="set-row muted">Personne n'est bloqué.</p>`;

  function bindPrivacy() {
    $$("[data-select]").forEach((el) => (el.onchange = guard(async () => { await social.updatePrivacy({ [el.dataset.select]: el.value }); toast("Enregistré"); })));
    $$("[data-toggle]").forEach((el) => (el.onchange = guard(async () => {
      try { await social.updatePrivacy({ [el.dataset.toggle]: el.checked }); } catch (e) { el.checked = !el.checked; throw e; }
    })));
    $$("[data-unblock]").forEach((b) => (b.onclick = guard(async () => { await social.unblock(b.dataset.unblock); $("#blocked-list").innerHTML = blockedRows(await social.blocked()); bindPrivacy(); })));
  }

  // ── Réglages > Services connectés (Last.fm) ──────────────────────────────

  const lastfm = { polling: false };

  async function viewServices() {
    $("#content").innerHTML = skeleton("Services connectés");
    if (auth.isGuest()) return cpage(`<h1 class="page-title">Services connectés</h1>${sub("Crée un compte pour connecter tes services.")}`);
    const [services, settings] = await Promise.all([social.services().catch(() => []), social.settings().catch(() => ({ scrobbling_enabled: true }))]);
    const lfm = services.find((s) => s.provider === "lastfm");
    let status = lfm ? { connected: true, ...lfm } : { connected: false };
    // Une clé révoquée laisse une ligne sans secret : on la présente comme non connectée avec son message.
    try { status = await window.Sona.svc("/lastfm/status"); } catch { /* service indisponible : on garde la lecture directe */ }
    setTimeout(() => bindServices(status));
    return cpage(`<h1 class="page-title">Services connectés</h1>${sub("Tout est facultatif. Sona garde lui-même ton historique d'écoute : se connecter à Last.fm sert seulement à y envoyer tes écoutes.")}
      <h3 class="set-head">Last.fm</h3><div class="set-group">
        ${status.connected
          ? `${row(`Connecté : ${status.username || ""}`, status.last_sync_at ? `Dernier envoi : ${new Date(status.last_sync_at).toLocaleString("fr-FR", { dateStyle: "medium", timeStyle: "short" })}` : "Aucun envoi pour l'instant")}
             ${status.last_error ? `<p class="set-row bad-note" role="alert">${h(status.last_error)}</p>` : ""}
             <label class="switch-row"><span><b>Envoyer mes écoutes à Last.fm</b><small>Chaque titre écouté à moitié (ou 4 minutes) est ajouté à ton profil</small></span><input type="checkbox" data-scrobble ${settings.scrobbling_enabled ? "checked" : ""}><i></i></label>
             ${linkRow("data-import-history", icons.download, "Importer mon historique Last.fm", "En tâche de fond, pour des statistiques complètes")}
             <div class="set-row"><span class="set-text" id="import-status"></span></div>
             ${linkRow("data-disconnect", icons.close, "Déconnecter Last.fm", "Supprime la clé de session")}`
          : `${status.last_error ? `<p class="set-row bad-note" role="alert">${h(status.last_error)}</p>` : ""}
             ${row("Last.fm", "Envoie tes écoutes à ton profil Last.fm", `<button class="btn small" data-connect>Connecter</button>`)}`}
      </div>
      <h3 class="set-head">Import de playlists</h3><div class="set-group">
        ${row("Spotify, Deezer, Apple Music, YouTube, SoundCloud", "Colle le lien d'une playlist publique : chaque titre est retrouvé, ce qui est à vérifier t'est signalé, et elle se resynchronise chaque jour", `<button class="btn small" data-import-playlist>Importer</button>`)}
      </div>
      <h3 class="set-head">Ancien compte Sona</h3><div class="set-group">
        ${row("Récupérer mon ancien compte", "Tu te connectais avec Last.fm avant ? Retrouve ta bibliothèque, tes playlists et ton historique", `<button class="btn small" data-link-legacy>Récupérer</button>`)}
      </div>`);
  }

  /** Connexion à Last.fm. Site web : redirection (flux officiel avec adresse de retour).
      Appli installée ou Windows : le service obtient un jeton, on ouvre la page et on attend. */
  async function connectLastfm() {
    const installed = standalone || !!window.sonaDesktop;
    if (!installed) {
      const back = location.origin + location.pathname;
      const { auth_url } = await window.Sona.svc("/lastfm/start", { method: "POST", body: { return_to: back } });
      store.set("sona.lastfmPending", String(Date.now()));
      location.href = auth_url;
      return;
    }
    const { auth_url, token } = await window.Sona.svc("/lastfm/start", { method: "POST", body: {} });
    if (window.sonaDesktop) window.sonaDesktop.openExternal(auth_url); else window.open(auth_url, "_blank", "noopener") || (location.href = auth_url);
    toast("Autorise Sona sur la page Last.fm, puis reviens ici");
    await waitLastfm(token);
  }

  async function waitLastfm(token) {
    if (lastfm.polling) return;
    lastfm.polling = true;
    const until = Date.now() + 10 * 60 * 1000;
    try {
      while (Date.now() < until) {
        await new Promise((r) => setTimeout(r, 2500));
        try { await window.Sona.svc("/lastfm/connect", { method: "POST", body: { token } }); toast("Last.fm connecté"); if (location.hash.startsWith("#/settings")) route(); return true; }
        catch (e) { if (!/Autorise d'abord/.test(e.message)) throw e; }
      }
      throw new Error("Délai dépassé : relance la connexion à Last.fm.");
    } finally { lastfm.polling = false; }
  }

  /** Retour du site Last.fm avec ?token=… (flux web). */
  async function finishLastfm(token) {
    store.set("sona.lastfmPending", null);
    try { await window.Sona.svc("/lastfm/connect", { method: "POST", body: { token } }); toast("Last.fm connecté"); location.hash = "#/settings/services"; }
    catch (e) { toast(e.message); }
  }

  /** Rattache un ancien compte (connexion Last.fm d'avant) : on le prouve en autorisant Last.fm avec son pseudo. */
  async function linkLegacy() {
    const { token, auth_url } = await api("/auth/lastfm/token", { method: "POST" });
    if (window.sonaDesktop) window.sonaDesktop.openExternal(auth_url); else window.open(auth_url, "_blank", "noopener") || (location.href = auth_url);
    toast("Autorise Sona sur la page Last.fm avec ton ancien pseudo, puis reviens ici");
    const until = Date.now() + 10 * 60 * 1000;
    while (Date.now() < until) {
      await new Promise((r) => setTimeout(r, 2500));
      try {
        await api("/auth/link-legacy", { method: "POST", body: JSON.stringify({ token }) });
        toast("Ancien compte récupéré");
        location.hash = "#/library";
        return;
      } catch (e) {
        // Last.fm n'a pas encore autorisé : on attend. Toute autre réponse du serveur (introuvable, déjà pris…) s'affiche.
        if (!/Autorise d'abord/.test(e.message)) throw e;
      }
    }
    throw new Error("Délai dépassé : relance la récupération.");
  }

  function bindServices() {
    $("[data-import-playlist]")?.addEventListener("click", guard(async () => { await importPlaylist(); }));
    $("[data-link-legacy]")?.addEventListener("click", guard(linkLegacy));
    $("[data-connect]")?.addEventListener("click", guard(connectLastfm));
    $("[data-disconnect]")?.addEventListener("click", guard(async () => {
      if (!(await confirmSheet("Déconnecter Last.fm ? La clé de session est supprimée de Sona.", "Déconnecter"))) return;
      await window.Sona.svc("/lastfm", { method: "DELETE" });
      route();
    }));
    $("[data-scrobble]")?.addEventListener("change", guard(async (e) => { await social.updateSettings({ scrobbling_enabled: e.target.checked }); }));
    $("[data-import-history]")?.addEventListener("click", guard(async () => {
      const line = $("#import-status");
      let st = await api("/stats/import/lastfm", { method: "POST" });
      while (st.running && $("#import-status")) {
        $("#import-status").textContent = `Import en cours… ${plural(st.imported, "écoute")}`;
        await new Promise((r) => setTimeout(r, 2000));
        st = await api("/stats/import/lastfm");
      }
      if (line && $("#import-status")) $("#import-status").textContent = st.error || `Terminé : ${plural(st.imported, "écoute")} ajoutée${st.imported > 1 ? "s" : ""}`;
    }));
  }

  // ── Notifications ────────────────────────────────────────────────────────

  const KIND = {
    friend_request: (n) => ["Demande d'ami", "Quelqu'un souhaite t'ajouter. Ouvre l'onglet Amis.", "#/friends"],
    friend_accepted: () => ["Demande acceptée", "Vous êtes maintenant amis.", "#/friends"],
    session_invite: (n) => ["Invitation à une session d'écoute", n.payload?.code ? `Code : ${n.payload.code}` : "Un ami t'invite à écouter ensemble.", n.payload?.code ? `#/party/${n.payload.code}` : "#/party"],
    warning: (n) => ["Avertissement", n.payload?.reason || "Un modérateur t'a envoyé un avertissement.", "#/settings/account"],
    moderation: (n) => ["Modération", moderationText(n.payload), "#/settings/account"],
    report_update: () => ["Signalement traité", "Merci : ton signalement a été examiné.", ""],
    appeal_update: (n) => ["Contestation", n.payload?.accepted ? "Ta contestation est acceptée." : `Ta contestation est refusée : ${n.payload?.response || ""}`, ""],
  };
  function moderationText(p = {}) {
    if (p.kind === "lifted") return "Ta restriction a été levée.";
    if (p.kind === "profile_reset") return `Ton profil a été modifié par la modération${p.reason ? ` : ${p.reason}` : "."}`;
    return p.reason ? `Mesure appliquée : ${p.reason}` : "Une mesure de modération a été appliquée à ton compte.";
  }

  const notif = { unread: 0, timer: null, list: [] };

  async function pollNotifications() {
    if (!account || account.guest || document.hidden) return;
    try {
      notif.list = await social.notifications();
      notif.unread = notif.list.filter((n) => !n.read_at).length;
      document.dispatchEvent(new CustomEvent("sona:notifications", { detail: { unread: notif.unread, list: notif.list, friendRequests: notif.list.filter((n) => !n.read_at && n.kind === "friend_request").length, invites: notif.list.filter((n) => !n.read_at && n.kind === "session_invite").length } }));
    } catch { /* hors ligne : on réessaie au prochain tour */ }
  }

  function startNotifications() {
    clearInterval(notif.timer);
    pollNotifications();
    notif.timer = setInterval(pollNotifications, 45000);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) pollNotifications(); });
  }

  function notificationsSheet() {
    const items = notif.list;
    const wrap = openSheet(`<h2 class="sheet-title">Notifications</h2>
      ${items.length ? `<div class="menu">${items.map((n, i) => { const [t, text, href] = (KIND[n.kind] || (() => [n.kind, "", ""]))(n); return `<button class="menu-item ${n.read_at ? "" : "unread"}" data-n="${i}"><span class="mi-text"><span class="mi-label">${h(t)}</span><span class="mi-sub">${h(text)} · ${since(n.created_at)}</span></span></button>`; }).join("")}</div>` : `<p class="muted">Rien de nouveau.</p>`}`);
    $$("[data-n]", wrap).forEach((b) => (b.onclick = () => {
      const n = items[+b.dataset.n];
      const href = (KIND[n.kind] || (() => ["", "", ""]))(n)[2];
      wrap.close();
      if (href) location.hash = href;
    }));
    social.markRead(items.filter((n) => !n.read_at).map((n) => n.id)).then(pollNotifications).catch(() => {});
  }

  // ── Obligations de modération ────────────────────────────────────────────

  /** Avertissements non lus, pseudo / photo à changer : affichés avant d'utiliser l'app. */
  async function enforce(profile) {
    if (profile.force_username_change) await usernameSheet(profile.username, { forced: true });
    if (profile.force_avatar_change) toast("Ta photo a été retirée par la modération : tu peux en choisir une dans Réglages › Compte.");
    try {
      const warnings = (await social.sanctions()).filter((s) => s.kind === "warning" && !s.acknowledged_at);
      for (const w of warnings) await warningSheet(w);
    } catch { /* non bloquant */ }
    if (profile.status === "quarantined") toast("Ton compte est en cours de vérification : tes interactions sociales sont limitées.");
  }

  function warningSheet(w) {
    return new Promise((resolve) => {
      let done = false;
      const wrap = openSheet(`<h2 class="sheet-title">Avertissement</h2>
        <p class="muted">Un modérateur t'a adressé cet avertissement le ${when(w.created_at)} :</p>
        <blockquote class="warn-reason">${h(w.reason)}</blockquote>
        <p class="muted">Plusieurs avertissements peuvent mener à une suspension ou à un bannissement.</p>
        <div class="pill-row"><button class="btn" data-ok>J'ai compris</button></div>`, { onClose: () => { if (!done) { done = true; resolve(); } } });
      $("[data-ok]", wrap).onclick = async () => { try { await social.acknowledge(w.id); } catch {} done = true; resolve(); wrap.close(); };
    });
  }

  // ── Signalement ──────────────────────────────────────────────────────────

  const REASONS = [["spam", "Spam"], ["harassment", "Harcèlement"], ["inappropriate", "Contenu inapproprié"], ["impersonation", "Usurpation d'identité"], ["other", "Autre"]];

  /** type : profile | playlist | username | avatar | session | message. */
  function reportSheet({ type, userId, ref, snapshot, title = "Signaler" }) {
    if (auth.isGuest()) { toast("Crée un compte pour signaler un contenu."); return; }
    const wrap = openSheet(`<h2 class="sheet-title">${h(title)}</h2>
      <p class="muted">Un modérateur examinera ce signalement. Le contenu signalé est conservé comme preuve.</p>
      <form class="ask"><fieldset class="reasons"><legend class="sr">Motif</legend>${REASONS.map(([v, l], i) => `<label class="reason"><input type="radio" name="reason" value="${v}" ${i === 0 ? "checked" : ""}><span>${h(l)}</span></label>`).join("")}</fieldset>
      <textarea class="field area" name="details" rows="3" maxlength="500" placeholder="Précisions (facultatif)" aria-label="Précisions"></textarea>
      <div class="pill-row"><button type="button" class="btn ghost" data-cancel>Annuler</button><button class="btn" type="submit">Envoyer</button></div></form>`);
    $("[data-cancel]", wrap).onclick = () => wrap.close();
    $("form", wrap).onsubmit = async (e) => {
      e.preventDefault();
      const f = new FormData(e.target);
      try {
        await social.report({ type, userId, ref, reason: f.get("reason"), details: String(f.get("details") || ""), snapshot });
        wrap.close();
        toast("Merci, ton signalement a été envoyé");
      } catch (err) { toast(err.message); }
    };
  }

  return { viewAccount, viewPrivacy, viewServices, connectLastfm, finishLastfm, startNotifications, pollNotifications, notificationsSheet, enforce, reportSheet, usernameSheet, notif };
})();
