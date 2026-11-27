/* Sona : écrans de compte — connexion / inscription (un seul écran), mode invité,
   écran de sanction, pastille de bienvenue et parcours de première inscription.

   Chargé avant app.js ; les fonctions d'app.js ($, esc, openSheet, toast, api…) ne
   sont utilisées qu'à l'appel, une fois app.js entièrement chargé. */

"use strict";

const SonaUI = (() => {
  const { auth, social } = window.Sona;
  const root = () => document.getElementById("root");
  const h = (s) => esc(s);
  const isIOSStandalone = () => typeof isIOS !== "undefined" && isIOS && typeof standalone !== "undefined" && standalone;

  // ── Fournisseurs ─────────────────────────────────────────────────────────

  const PROVIDERS = [
    ["google", "Google", '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#EA4335" d="M12 10.2v3.9h5.5c-.2 1.3-1.6 3.9-5.5 3.9a6 6 0 0 1 0-12c1.9 0 3.1.8 3.8 1.5l2.6-2.5A9.6 9.6 0 0 0 12 2.4a9.6 9.6 0 1 0 0 19.2c5.5 0 9.2-3.9 9.2-9.3 0-.6-.1-1.1-.2-1.6z"/></svg>'],
    ["discord", "Discord", '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#5865F2" d="M19.6 5.3A16 16 0 0 0 15.7 4l-.5 1a15 15 0 0 0-4.4 0l-.5-1a16 16 0 0 0-3.9 1.3C3.9 9 3.2 12.6 3.5 16.2a16 16 0 0 0 4.8 2.4l1-1.6-1.6-.8.4-.3a11.4 11.4 0 0 0 9.8 0l.4.3-1.6.8 1 1.6a16 16 0 0 0 4.8-2.4c.4-4.2-.7-7.8-2.9-10.9zM9.7 14c-.9 0-1.6-.8-1.6-1.8s.7-1.8 1.6-1.8 1.6.8 1.6 1.8-.7 1.8-1.6 1.8zm4.6 0c-.9 0-1.6-.8-1.6-1.8s.7-1.8 1.6-1.8 1.6.8 1.6 1.8-.7 1.8-1.6 1.8z"/></svg>'],
    ["github", "GitHub", '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12"/></svg>'],
  ];
  const providerName = (p) => (PROVIDERS.find((x) => x[0] === p) || [p, p])[1];

  // ── Écran unique : inscription et connexion ──────────────────────────────

  const ui = { mode: "signin", step: "form", email: "", notice: "", error: "", busy: false, reason: "" };

  function authScreen(next = {}) {
    Object.assign(ui, { step: "form", error: "", notice: "", busy: false }, next);
    if (typeof document !== "undefined") document.body.style.overflow = "hidden";
    paintAuth();
  }

  /** Coque commune (connexion, bienvenue, sanction) : panneau de marque à gauche sur grand écran, carte à droite. */
  function shell(inner, cls = "") {
    const points = [[icons.quote, "Paroles mot à mot", "Synchronisées, même en karaoké."], [icons.headphones, "Écoute ensemble", "Avec tes amis, selon tes règles."], [icons.lock, "Ta vie privée d'abord", "Rien n'est partagé tant que tu ne le décides pas."]];
    return `<div class="login auth"><div class="auth-glow" aria-hidden="true"></div>
      <div class="auth-layout">
        <aside class="auth-brand" aria-hidden="true">
          <span class="brand-tile"><svg viewBox="0 0 64 64"><use href="#sona-mark"/></svg></span>
          <h1>Ta musique,<br>en clair.</h1>
          <p class="brand-sub">Paroles, playlists, stats et écoute ensemble. Ouvert à tout le monde, sans pub.</p>
          <ul class="brand-points">${points.map(([i, t, d]) => `<li><span class="bp-ico">${i}</span><span><b>${t}</b><small>${d}</small></span></li>`).join("")}</ul>
          <div class="brand-eq"><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div>
        </aside>
        <main class="auth-card ${cls}">
          <div class="auth-top"><span class="brand-tile small"><svg viewBox="0 0 64 64" aria-hidden="true"><use href="#sona-mark"/></svg></span><span class="auth-name">Sona</span></div>
          ${inner}
        </main>
      </div></div>`;
  }

  const EYE = '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12zm10 3a3 3 0 1 0 0-6 3 3 0 0 0 0 6z"/></svg>';

  /** Champ à étiquette flottante. */
  function fld(name, label, { type = "text", value = "", auto = "", mode = "", extra = "", eye = false, cls = "" } = {}) {
    return `<div class="fld ${cls}"><input class="fi" id="f-${name}" name="${name}" type="${type}" value="${h(value)}" placeholder=" " ${auto ? `autocomplete="${auto}"` : ""} ${mode ? `inputmode="${mode}"` : ""} ${extra}>
      <label for="f-${name}">${h(label)}</label>${eye ? `<button type="button" class="eye" data-eye aria-label="Afficher le mot de passe">${EYE}</button>` : ""}</div>`;
  }

  const head = (title, sub = "") => `<h2 class="auth-h2">${h(title)}</h2>${sub ? `<p class="auth-hint">${sub}</p>` : ""}`;

  function paintAuth() {
    const guestOk = !!window.Sona.configured;
    const passkeyOk = window.Sona.passkeys.supported() && !!window.Sona.config.accountsUrl;
    const signup = ui.mode === "signup";
    const busy = ui.busy ? "disabled" : "";
    let body;
    if (!window.Sona.configured) {
      body = `${head("Bientôt prêt")}<p class="error" role="alert">Les comptes ne sont pas encore configurés sur ce site. Voir docs/AUTH_SETUP.md.</p>`;
    } else if (ui.step === "code") {
      body = `${head("Entre le code reçu", `Un code à 6 chiffres vient d'être envoyé à <b>${h(ui.email)}</b>. Il est valable quelques minutes.`)}
        <form id="auth-code" novalidate>
          ${fld("code", "Code à 6 chiffres", { auto: "one-time-code", mode: "numeric", extra: 'maxlength="8"', cls: "code" })}
          <button class="btn big wide-btn" ${busy}>Continuer</button>
        </form>
        <p class="auth-links"><button class="link-btn" data-back>Changer d'adresse</button><button class="link-btn" data-resend>Renvoyer le code</button></p>`;
    } else if (ui.step === "forgot") {
      body = `${head("Mot de passe oublié", "Entre ton adresse : on t'envoie un code (et un lien) pour choisir un nouveau mot de passe.")}
        <form id="auth-forgot" novalidate>
          ${fld("email", "Adresse e-mail", { type: "email", value: ui.email, auto: "email", mode: "email" })}
          <button class="btn big wide-btn" ${busy}>Envoyer</button>
        </form>
        <p class="auth-links"><button class="link-btn" data-back>Retour</button></p>`;
    } else if (ui.step === "newpass") {
      body = `${head("Nouveau mot de passe")}
        <form id="auth-newpass" novalidate>
          ${fld("password", "Nouveau mot de passe", { type: "password", auto: "new-password", eye: true })}
          ${meter()}
          <button class="btn big wide-btn" ${busy}>Enregistrer</button>
        </form>`;
    } else if (ui.step === "reset-code") {
      body = `${head("Entre le code reçu", `Code envoyé à <b>${h(ui.email)}</b>.`)}
        <form id="auth-reset-code" novalidate>
          ${fld("code", "Code à 6 chiffres", { auto: "one-time-code", mode: "numeric", extra: 'maxlength="8"', cls: "code" })}
          <button class="btn big wide-btn" ${busy}>Continuer</button>
        </form>`;
    } else {
      const [g, ...others] = PROVIDERS;
      const pbtn = ([id, name, svg], full) => `<button class="provider ${full ? "full" : ""}" data-provider="${id}" ${busy}>${svg}<span>${full ? `Continuer avec ${name}` : name}</span></button>`;
      const oauth = `<div class="auth-providers">${pbtn(g, true)}<div class="auth-pair">${others.map((o) => pbtn(o, false)).join("")}</div></div>`;
      body = `${head(signup ? "Crée ton compte" : "Content de te revoir", signup ? "Gratuit, sans pub, ouvert à tout le monde." : "Connecte-toi pour retrouver ta musique.")}
        ${isIOSStandalone()
          ? `<details class="auth-more"><summary>Google, Discord, GitHub</summary><p class="auth-hint">Dans l'app installée sur iPhone, ces connexions s'ouvrent dans Safari et ne reviennent pas ici. Choisis plutôt le code par e-mail ou une clé d'accès.</p>${oauth}</details>`
          : oauth}
        ${passkeyOk ? `<button class="provider passkey full" data-passkey ${busy}><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="8" cy="12" r="4" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 12h9m-3 0v4m-3-4v3" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg><span>Clé d'accès (Face ID, Touch ID…)</span></button>` : ""}
        <div class="auth-or"><span>ou avec ton e-mail</span></div>
        <div class="segmented auth-tabs" role="tablist">
          <button role="tab" aria-selected="${!signup}" class="${!signup ? "on" : ""}" data-mode="signin">Connexion</button>
          <button role="tab" aria-selected="${signup}" class="${signup ? "on" : ""}" data-mode="signup">Créer un compte</button>
        </div>
        <form id="auth-form" novalidate>
          ${fld("email", "Adresse e-mail", { type: "email", value: ui.email, auto: "email", mode: "email", extra: 'autocapitalize="none" spellcheck="false"' })}
          ${fld("password", "Mot de passe", { type: "password", auto: signup ? "new-password" : "current-password", eye: true })}
          ${signup ? meter() : ""}
          <button class="btn big wide-btn" ${busy}>${signup ? "Créer mon compte" : "Se connecter"}</button>
        </form>
        <div class="auth-alt">
          <button class="pill-btn" data-code>Recevoir un code par e-mail</button>${signup ? "" : `<button class="pill-btn" data-forgot>Mot de passe oublié</button>`}
        </div>
        ${guestOk ? `<button class="guest" data-guest>Essayer sans compte <span aria-hidden="true">→</span></button>` : ""}`;
    }
    root().innerHTML = shell(`${body}
      <div class="auth-msg" role="status" aria-live="polite">${ui.notice ? `<p class="notice">${h(ui.notice)}</p>` : ""}${ui.error ? `<p class="error" role="alert">${h(ui.error)}</p>` : ""}</div>
      <p class="fine legal">En continuant, tu acceptes les <a href="conditions" target="_blank" rel="noopener">conditions d'utilisation</a> et la <a href="confidentialite" target="_blank" rel="noopener">politique de confidentialité</a>.</p>`);
    bindAuth();
  }

  const meter = () => `<div class="pw-meter" id="pw-meter" aria-hidden="true"><i></i><i></i><i></i><i></i></div>
    <p class="pw-hint" id="pw-hint">10 caractères minimum, avec minuscules, majuscules et chiffres.</p>`;

  function setBusy(on) {
    ui.busy = on;
    document.querySelectorAll(".auth button.btn, .auth .provider").forEach((b) => (b.disabled = on));
  }

  async function attempt(fn, { keepForm = true } = {}) {
    ui.error = "";
    ui.notice = "";
    setBusy(true);
    try { await fn(); }
    catch (e) { ui.error = e.message || "Une erreur est survenue."; setBusy(false); paintAuth(); return false; }
    setBusy(false);
    return true;
  }

  function bindAuth() {
    const $r = (s) => document.querySelector(s);
    $r("[data-back]")?.addEventListener("click", () => authScreen({ step: "form" }));
    document.querySelectorAll("[data-mode]").forEach((b) => (b.onclick = () => { ui.mode = b.dataset.mode; ui.error = ""; ui.notice = ""; paintAuth(); }));
    document.querySelectorAll("[data-provider]").forEach((b) => (b.onclick = () => attempt(() => auth.oauth(b.dataset.provider))));
    $r("[data-passkey]")?.addEventListener("click", () => attempt(() => window.Sona.passkeys.login()));
    $r("[data-guest]")?.addEventListener("click", () => attempt(() => auth.guest()));
    $r("[data-forgot]")?.addEventListener("click", () => { ui.email = $r('[name="email"]')?.value.trim() || ui.email; ui.step = "forgot"; ui.error = ""; paintAuth(); });
    $r("[data-code]")?.addEventListener("click", async () => {
      const email = $r('[name="email"]')?.value.trim();
      if (!email) { ui.error = "Entre ton adresse e-mail d'abord."; return paintAuth(); }
      ui.email = email;
      if (await attempt(() => auth.sendCode(email))) { ui.step = "code"; paintAuth(); }
    });
    $r("[data-resend]")?.addEventListener("click", async () => {
      if (await attempt(() => (ui.mode === "signup-confirm" ? auth.resendSignup(ui.email) : auth.sendCode(ui.email)))) { ui.notice = "Nouveau code envoyé."; paintAuth(); }
    });

    const pw = $r('#auth-form [name="password"], #auth-newpass [name="password"]');
    pw?.addEventListener("input", () => {
      const score = auth.passwordScore(pw.value);
      document.querySelectorAll("#pw-meter i").forEach((el, i) => el.classList.toggle("on", i < score));
      const hint = $r("#pw-hint");
      if (hint) { const p = pw.value ? auth.passwordProblem(pw.value, $r('[name="email"]')?.value || ui.email) : null; hint.textContent = p || (pw.value ? "Mot de passe accepté." : "10 caractères minimum, avec minuscules, majuscules et chiffres."); hint.classList.toggle("bad", !!p); }
    });

    $r("#auth-form")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const f = new FormData(e.target);
      const email = String(f.get("email") || "").trim();
      const password = String(f.get("password") || "");
      ui.email = email;
      if (!/^\S+@\S+\.\S+$/.test(email)) { ui.error = "Adresse e-mail invalide."; return paintAuth(); }
      if (!password) { ui.error = ui.mode === "signup" ? "Choisis un mot de passe." : "Entre ton mot de passe, ou demande un code par e-mail."; return paintAuth(); }
      if (ui.mode === "signup") {
        if (await attempt(async () => {
          const data = await auth.signUp(email, password);
          // Confirmation d'e-mail activée : pas de session, un code a été envoyé.
          if (!data.session) { ui.mode = "signup-confirm"; ui.step = "code"; }
        })) paintAuth();
      } else {
        await attempt(() => auth.signIn(email, password));
      }
    });
    $r("#auth-code")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const code = new FormData(e.target).get("code");
      await attempt(() => auth.verifyCode(ui.email, String(code), ui.mode === "signup-confirm" ? "signup" : "email"));
    });
    $r("#auth-forgot")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const email = String(new FormData(e.target).get("email") || "").trim();
      if (!/^\S+@\S+\.\S+$/.test(email)) { ui.error = "Adresse e-mail invalide."; return paintAuth(); }
      ui.email = email;
      // Même message que l'adresse existe ou non : pas d'énumération des comptes.
      if (await attempt(() => auth.resetPassword(email))) { ui.step = "reset-code"; paintAuth(); }
    });
    $r("#auth-reset-code")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const code = String(new FormData(e.target).get("code"));
      if (await attempt(() => auth.verifyCode(ui.email, code, "recovery"))) { ui.step = "newpass"; paintAuth(); }
    });
    $r("#auth-newpass")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const pass = String(new FormData(e.target).get("password"));
      if (await attempt(() => auth.updatePassword(pass))) { toast("Mot de passe changé ✓"); await entry(); }
    });
    document.querySelectorAll("[data-eye]").forEach((btn) => (btn.onclick = () => {
      const input = btn.parentElement.querySelector("input");
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      btn.setAttribute("aria-label", show ? "Masquer le mot de passe" : "Afficher le mot de passe");
      btn.classList.toggle("on", show);
    }));
    document.querySelector("#auth-form [name=email], #auth-code [name=code], #auth-forgot [name=email]")?.focus({ preventScroll: true });
  }

  // ── Écran de sanction : raison, durée, moyen de contester ────────────────

  async function sanctionScreen(info = {}) {
    document.body.style.overflow = "hidden";
    let sanctions = [];
    try { sanctions = await social.sanctions(); } catch { /* écran minimal */ }
    const active = sanctions.find((s) => !s.revoked_at && s.kind !== "warning");
    const banned = (info.status || active?.kind) === "ban" || info.status === "banned";
    const until = info.until || active?.expires_at;
    const reason = info.reason || active?.reason || "Non précisé";
    const untilText = banned ? "Définitif" : until ? `Jusqu'au ${new Date(until).toLocaleString("fr-FR", { dateStyle: "long", timeStyle: "short" })}` : "Durée non précisée";
    const appealed = active && (await social.table("appeals").select("id,status,response").eq("sanction_id", active.id).then((r) => r.data || []).catch(() => []));
    const pending = appealed?.find((a) => a.status === "open");
    root().innerHTML = shell(`<div class="sanction-badge ${banned ? "ban" : "susp"}" aria-hidden="true">${banned ? "⛔" : "⏸"}</div>
      <h2 class="auth-h2">${banned ? "Compte banni" : "Compte suspendu"}</h2>
      <dl class="sanction-facts"><div><dt>Raison</dt><dd>${h(reason)}</dd></div><div><dt>Durée</dt><dd>${h(untilText)}</dd></div></dl>
      ${active ? (pending
        ? `<p class="notice">Ta contestation est en cours d'examen. Tu seras prévenu de la réponse.</p>`
        : `<button class="btn big wide-btn" data-appeal>Contester cette décision</button>`) : ""}
      <div class="auth-alt"><button class="pill-btn" data-export>Exporter mes données</button><button class="pill-btn" data-delete>Supprimer mon compte</button><button class="pill-btn" data-out>Se déconnecter</button></div>
      <p class="fine legal">Tu peux toujours exporter ou supprimer tes données, quelle que soit la sanction.</p>`, "sanction");
    const $r = (s) => document.querySelector(s);
    $r("[data-out]").onclick = () => signOut();
    $r("[data-export]").onclick = () => exportData();
    $r("[data-delete]").onclick = () => deleteAccount();
    $r("[data-appeal]")?.addEventListener("click", () => {
      const wrap = openSheet(`<h2 class="sheet-title">Contester la décision</h2>
        <p class="muted">Explique pourquoi cette sanction te semble injustifiée. Un membre de l'équipe relira ta demande.</p>
        <form class="ask"><textarea class="field area" name="m" rows="5" maxlength="1000" placeholder="Ton message (5 caractères minimum)" required></textarea>
        <div class="pill-row"><button type="button" class="btn ghost" data-cancel>Annuler</button><button class="btn" type="submit">Envoyer</button></div></form>`);
      $("[data-cancel]", wrap).onclick = () => wrap.close();
      $("form", wrap).onsubmit = async (e) => {
        e.preventDefault();
        try { await social.appeal(active.id, new FormData(e.target).get("m")); wrap.close(); toast("Contestation envoyée"); sanctionScreen(info); }
        catch (err) { toast(err.message); }
      };
    });
  }

  // ── Export et suppression (droits de la personne) ────────────────────────

  async function exportData() {
    try { await window.Sona.download("/account/export", "sona-mes-donnees.json"); toast("Export téléchargé"); }
    catch (e) { toast(e.message); }
  }

  async function deleteAccount() {
    const phrase = "SUPPRIMER MON COMPTE";
    const wrap = openSheet(`<h2 class="sheet-title">Supprimer mon compte</h2>
      <p class="muted">Ton profil, tes amitiés, ta bibliothèque, tes playlists et ton historique seront effacés définitivement. Cette action est irréversible. Pense à exporter tes données avant.</p>
      <form class="ask"><label class="muted" for="del-confirm">Pour confirmer, écris <b>${phrase}</b></label>
      <input class="field" id="del-confirm" autocomplete="off" autocapitalize="characters" placeholder="${phrase}">
      <div class="pill-row"><button type="button" class="btn ghost" data-cancel>Annuler</button><button class="btn danger" type="submit" disabled>Supprimer définitivement</button></div></form>`);
    const input = $("input", wrap);
    const submit = $("button[type=submit]", wrap);
    input.oninput = () => (submit.disabled = input.value.trim() !== phrase);
    $("[data-cancel]", wrap).onclick = () => wrap.close();
    $("form", wrap).onsubmit = async (e) => {
      e.preventDefault();
      submit.disabled = true;
      try {
        await window.Sona.svc("/account", { method: "DELETE", body: { confirm: phrase } });
        wrap.close();
        await auth.signOut();
        toast("Compte supprimé");
        signOut(true);
      } catch (err) { toast(err.message); submit.disabled = false; }
    };
  }

  // ── Profil et statut : passage obligé avant l'app ────────────────────────

  /** Compte tel qu'app.js l'attend (id, pseudo, photo, droits). */
  function accountFrom(profile, extra = {}) {
    return {
      id: profile.id, username: profile.username, display_name: profile.display_name, avatar_url: profile.avatar_url,
      status: "approved", role: profile.role, is_admin: profile.role === "admin" && profile.status === "active",
      is_staff: ["admin", "moderator"].includes(profile.role) && profile.status === "active",
      guest: auth.isGuest(), email: auth.user()?.email || null, profile, ...extra,
    };
  }

  /** Point d'entrée après connexion : charge le profil, affiche les écrans bloquants
      (sanction, pseudo / photo à changer, parcours de bienvenue). Renvoie le compte, ou null. */
  async function prepare() {
    let profile;
    try { profile = await social.me(); }
    catch (e) {
      if (!navigator.onLine || /fetch|network|Failed/i.test(e.message)) throw e;
      authScreen({ error: "Impossible de charger ton profil. Reconnecte-toi." });
      await auth.signOut();
      return null;
    }
    const effective = profile.status === "suspended" && profile.status_until && new Date(profile.status_until) <= new Date() ? "active" : profile.status;
    if (effective === "banned" || effective === "suspended") {
      await sanctionScreen({ status: effective === "banned" ? "banned" : "suspended", reason: profile.status_reason, until: profile.status_until });
      return null;
    }
    if (!profile.onboarding_completed && !auth.isGuest()) {
      await onboarding(profile);
      profile = await social.me();
    }
    return accountFrom(profile);
  }

  // ── Parcours de première inscription ─────────────────────────────────────

  function onboarding(profile) {
    return new Promise((resolve) => {
      document.body.style.overflow = "hidden";
      const steps = ["profile", "services", "prefs", "done"];
      const labels = ["Profil", "Services", "Préférences", "Prêt"];
      const data = { username: profile.username.startsWith("sona_") ? "" : profile.username, avatar: profile.avatar_url, theme: "system", quality: "best", car: false, scrobble: true, presence: "nobody", privacyOpen: false };
      let i = 0;
      let check = { ok: null, text: "" };

      const progress = () => `<ol class="ob-steps" aria-label="Progression">${steps.map((s, n) => `<li class="${n < i ? "done" : n === i ? "on" : ""}" ${n === i ? 'aria-current="step"' : ""}><i></i><span>${labels[n]}</span></li>`).join("")}</ol>`;
      const skip = `<button class="link-btn" data-skip>Ignorer</button>`;

      const body = () => {
        if (steps[i] === "profile") return `<h2 class="auth-h2">Ton profil</h2>
          <p class="auth-hint">Comment tes amis te retrouvent. Tu pourras tout changer plus tard.</p>
          <div class="ob-avatar"><button type="button" class="ob-photo" data-photo aria-label="Choisir une photo">${avatar(data.avatar, data.username || "?", "profile-avatar")}<em class="ob-photo-label">Photo</em></button>
            <input type="file" accept="image/*" hidden data-file></div>
          <div class="fld"><input class="fi" id="ob-name" value="${h(data.username)}" maxlength="20" autocomplete="off" autocapitalize="none" spellcheck="false" placeholder=" "><label for="ob-name">Pseudo</label></div>
          <p class="ob-check ${check.ok === true ? "ok" : check.ok === false ? "bad" : ""}" id="ob-check" role="status" aria-live="polite">${h(check.text || "3 à 20 caractères : lettres, chiffres, _ . -")}</p>
          <div class="ob-actions"><button class="btn big" data-next ${check.ok ? "" : "disabled"}>Continuer</button></div>`;
        if (steps[i] === "services") return `<h2 class="auth-h2">Connecter tes services</h2>
          <p class="auth-hint">Tout est facultatif. Sona garde ton historique d'écoute lui-même : Last.fm n'est qu'une option.</p>
          <div class="set-group ob-group">
            <div class="set-row"><span class="set-text"><b>Last.fm</b><small id="ob-lfm">Envoie tes écoutes à ton profil Last.fm</small></span><button class="btn small" data-lfm>Connecter</button></div>
            <div class="set-row"><span class="set-text"><b>Playlists Spotify, Deezer…</b><small>Plus tard, dans Réglages › Services connectés : colle un lien de playlist et Sona la retrouve titre par titre</small></span></div>
          </div>
          <div class="ob-actions">${skip}<button class="btn big" data-next>Continuer</button></div>`;
        if (steps[i] === "prefs") return `<h2 class="auth-h2">Préférences</h2>
          <p class="auth-hint">Par défaut, tout ce qui te concerne reste privé.</p>
          <div class="set-group ob-group">
            <div class="set-row"><span class="set-text"><b>Thème</b></span><select class="field small" data-pref="theme"><option value="system">Automatique</option><option value="dark">Sombre</option><option value="light">Clair</option></select></div>
            <div class="set-row"><span class="set-text"><b>Qualité audio</b></span><select class="field small" data-pref="quality"><option value="best">Meilleure</option><option value="standard">Standard</option><option value="lossless">Lossless</option></select></div>
            <label class="switch-row"><span><b>Mode voiture automatique</b><small>Interface simplifiée en conduisant</small></span><input type="checkbox" data-pref="car"><i></i></label>
            <label class="switch-row"><span><b>Scrobbling</b><small>Envoyer mes écoutes à Last.fm si connecté</small></span><input type="checkbox" data-pref="scrobble" checked><i></i></label>
          </div>
          <h3 class="set-head">Confidentialité</h3>
          <div class="set-group ob-group">
            <div class="set-row"><span class="set-text"><b>Voir ce que j'écoute en direct</b><small>Désactivé tant que tu ne l'actives pas</small></span><select class="field small" data-pref="presence"><option value="nobody">Personne</option><option value="friends">Mes amis</option><option value="everyone">Tout le monde</option></select></div>
          </div>
          <p class="auth-hint">Profil : pseudo et photo visibles, le reste réservé à tes amis. Réglable dans Réglages › Confidentialité.</p>
          <div class="ob-actions">${skip}<button class="btn big" data-next>Continuer</button></div>`;
        return `<div class="ob-done"><div class="ob-check-big" aria-hidden="true">✓</div><h2 class="auth-h2">Tout est prêt</h2>
          <p class="auth-hint">Bienvenue sur Sona${data.username ? `, ${h(data.username)}` : ""}. Tu peux modifier tout cela dans Réglages › Compte, Confidentialité et Services connectés.</p>
          <div class="ob-actions"><button class="btn big" data-finish>Commencer à écouter</button></div></div>`;
      };

      const paint = () => {
        root().innerHTML = shell(`${progress()}${body()}<div class="auth-msg" id="ob-msg" role="alert"></div>`, "onboarding");
        bind();
      };

      const finish = async () => {
        const btn = document.querySelector("[data-finish]");
        if (btn) btn.disabled = true;
        try {
          const patch = { onboarding_completed: true };
          if (data.username && data.username !== profile.username) patch.username = data.username;
          if (data.avatar && data.avatar !== profile.avatar_url) patch.avatar_url = data.avatar;
          await social.updateProfile(patch);
          await social.updateSettings({ theme: data.theme, audio_quality: data.quality, car_mode_auto: data.car, scrobbling_enabled: data.scrobble });
          await social.updatePrivacy({ presence_visibility: data.presence });
          document.body.style.overflow = "";
          resolve();
        } catch (e) {
          if (btn) btn.disabled = false;
          const m = document.getElementById("ob-msg");
          if (m) m.innerHTML = `<p class="error">${h(/username_/.test(e.original?.message || e.message) ? "Ce pseudo n'est pas accepté." : e.message)}</p>`;
          if (/pseudo/i.test(e.message) || /username_/.test(e.original?.message || "")) { i = 0; paint(); }
        }
      };

      let timer = null;
      const verify = (value) => {
        clearTimeout(timer);
        const next = document.querySelector("[data-next]");
        if (!value) { check = { ok: null, text: "" }; if (next) next.disabled = true; return paintCheck(); }
        check = { ok: null, text: "Vérification…" };
        paintCheck();
        timer = setTimeout(async () => {
          try {
            const r = await social.usernameAvailable(value);
            const reasons = { format: "3 à 20 caractères : lettres, chiffres, _ . -", taken: "Ce pseudo est déjà pris.", reserved: "Ce pseudo est réservé.", offensive: "Ce pseudo n'est pas accepté." };
            check = r.available ? { ok: true, text: "Disponible ✓" } : { ok: false, text: reasons[r.reason] || "Indisponible." };
          } catch (e) { check = { ok: false, text: e.message }; }
          if (document.getElementById("ob-name")?.value.trim() !== value) return;
          paintCheck();
        }, 350);
      };
      const paintCheck = () => {
        const el = document.getElementById("ob-check");
        if (el) { el.textContent = check.text || "3 à 20 caractères : lettres, chiffres, _ . -"; el.className = `ob-check ${check.ok === true ? "ok" : check.ok === false ? "bad" : ""}`; }
        const next = document.querySelector("[data-next]");
        if (next && steps[i] === "profile") next.disabled = !check.ok;
      };

      const bind = () => {
        const $r = (s) => document.querySelector(s);
        $r("[data-skip]")?.addEventListener("click", () => { i++; paint(); });
        $r("[data-finish]")?.addEventListener("click", finish);
        $r("[data-next]")?.addEventListener("click", async () => {
          if (steps[i] === "profile") {
            // Le pseudo (et la photo) sont enregistrés tout de suite : le reste est ignorable.
            try {
              const patch = { username: data.username };
              if (data.avatar) patch.avatar_url = data.avatar;
              await social.updateProfile(patch);
              profile.username = data.username;
            } catch (e) { check = { ok: false, text: /username_|duplicate|unique/i.test(e.original?.message || e.message) ? "Ce pseudo n'est pas disponible." : e.message }; return paint(); }
          }
          i++;
          paint();
        });
        const name = $r("#ob-name");
        if (name) { name.addEventListener("input", () => { data.username = name.value.trim(); verify(data.username); }); if (data.username && check.ok == null) verify(data.username); }
        $r("[data-photo]")?.addEventListener("click", () => $r("[data-file]").click());
        $r("[data-file]")?.addEventListener("change", async (e) => {
          const f = e.target.files[0];
          if (!f) return;
          try { data.avatar = await social.uploadAvatar(f); paint(); } catch (err) { const m = $r("#ob-msg"); if (m) m.innerHTML = `<p class="error">${h(err.message)}</p>`; }
        });
        $r("[data-lfm]")?.addEventListener("click", async () => {
          try { await SonaSettings.connectLastfm(); } catch (e) { const el = $r("#ob-lfm"); if (el) el.textContent = e.message; }
        });
        document.querySelectorAll("[data-pref]").forEach((el) => {
          const k = el.dataset.pref;
          if (el.type === "checkbox") { el.checked = !!data[k]; el.onchange = () => (data[k] = el.checked); } else { el.value = data[k]; el.onchange = () => (data[k] = el.value); }
        });
      };

      // Photo du fournisseur OAuth : déjà reprise par le profil. Pseudo conseillé : celui du fournisseur.
      paint();
    });
  }

  // ── Mode invité : invitation discrète à créer un compte ──────────────────

  function guestBanner() {
    if (!auth.isGuest() || sessionStorage.getItem("sona.guestBanner") === "off") return "";
    return `<div class="guest-banner" role="note"><span>Tu écoutes sans compte. <button class="link-btn" data-upgrade>Crée-en un</button> pour garder ta bibliothèque et retrouver tes amis.</span><button class="x" data-dismiss aria-label="Masquer">×</button></div>`;
  }

  function bindGuestBanner(root) {
    root.querySelector("[data-dismiss]")?.addEventListener("click", () => { try { sessionStorage.setItem("sona.guestBanner", "off"); } catch {} root.querySelector(".guest-banner")?.remove(); });
    root.querySelector("[data-upgrade]")?.addEventListener("click", upgradeSheet);
  }

  function upgradeSheet() {
    const wrap = openSheet(`<h2 class="sheet-title">Créer mon compte</h2>
      <p class="muted">Ta bibliothèque, tes playlists et ton historique actuels sont conservés : ils sont déjà rattachés à ce compte.</p>
      <div class="auth-providers">${PROVIDERS.map(([id, name, svg]) => `<button class="provider" data-provider="${id}">${svg}<span>${name}</span></button>`).join("")}</div>
      <div class="auth-or"><span>ou avec ton e-mail</span></div>
      <form class="ask" id="up-form" novalidate><input class="field" name="email" type="email" autocomplete="email" placeholder="Adresse e-mail" required>
      <input class="field" name="password" type="password" autocomplete="new-password" placeholder="Mot de passe" required>
      <p class="pw-hint" id="up-hint">10 caractères minimum, avec minuscules, majuscules et chiffres.</p>
      <div class="pill-row"><button type="button" class="btn ghost" data-cancel>Plus tard</button><button class="btn" type="submit">Créer mon compte</button></div></form>`);
    $("[data-cancel]", wrap).onclick = () => wrap.close();
    $$("[data-provider]", wrap).forEach((b) => (b.onclick = () => auth.linkOAuth(b.dataset.provider).catch((e) => toast(e.message))));
    $("#up-form", wrap).onsubmit = async (e) => {
      e.preventDefault();
      const f = new FormData(e.target);
      try {
        await auth.upgradeGuest(String(f.get("email")).trim(), String(f.get("password")));
        wrap.close();
        toast("Vérifie ta boîte mail pour confirmer ton adresse");
      } catch (err) { $("#up-hint", wrap).textContent = err.message; $("#up-hint", wrap).classList.add("bad"); }
    };
  }

  // ── Orchestration ────────────────────────────────────────────────────────

  /** Retour de la page après un fournisseur / un lien : jetons dans l'adresse. */
  function cleanUrl() {
    const u = new URL(location.href);
    ["code", "error", "error_code", "error_description"].forEach((k) => u.searchParams.delete(k));
    if (/access_token|refresh_token|type=recovery/.test(u.hash)) u.hash = "";
    history.replaceState(null, "", u.pathname + (u.search || "") + u.hash);
  }

  /** Après une session obtenue : lance l'app (définie dans app.js). */
  async function entry() {
    if (typeof startApp === "function") return startApp();
  }

  function signOut(silent) {
    if (typeof signOutLocal === "function") return signOutLocal(silent);
    return auth.signOut();
  }

  return { authScreen, sanctionScreen, prepare, accountFrom, guestBanner, bindGuestBanner, upgradeSheet, exportData, deleteAccount, providerName, PROVIDERS, cleanUrl, entry, ui };
})();
