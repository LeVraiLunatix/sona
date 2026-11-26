/* Sona : comptes (Supabase Auth), services du compte (sona-accounts) et social.

   Chargé AVANT app.js : ce fichier ne dépend de rien d'autre que du navigateur
   et de vendor/supabase.js. L'interface (écrans) est dans accounts-ui.js.

   Rien de secret ici : l'URL du projet et la clé « anon » sont publiques par
   conception (la sécurité repose sur les règles RLS côté base). Le secret Last.fm,
   la clé « service role » et la clé de chiffrement n'existent que sur le serveur. */

"use strict";

(() => {
  const meta = (name) => document.querySelector(`meta[name="${name}"]`)?.content?.trim() || "";
  const SUPABASE_URL = meta("sona-supabase-url");
  const SUPABASE_KEY = meta("sona-supabase-key");
  const ACCOUNTS_URL = meta("sona-accounts").replace(/\/$/, "");
  const TURNSTILE_KEY = meta("sona-turnstile-sitekey");
  const desktop = window.sonaDesktop || null;
  const configured = /^https:\/\/[a-z0-9-]+\.supabase\.(co|in)$/i.test(SUPABASE_URL) && SUPABASE_KEY.length > 20 && !!window.supabase?.createClient;

  const listeners = new Set();
  const emit = (event, payload) => listeners.forEach((fn) => { try { fn(event, payload); } catch (e) { console.error(e); } });

  // Stockage de session tolérant (navigation privée, stockage bloqué).
  const memory = new Map();
  const storage = {
    getItem: (k) => { try { return localStorage.getItem(k); } catch { return memory.get(k) ?? null; } },
    setItem: (k, v) => { try { localStorage.setItem(k, v); } catch { memory.set(k, v); } },
    removeItem: (k) => { try { localStorage.removeItem(k); } catch { memory.delete(k); } },
  };

  let client = null;
  let current = null; // session en cours

  /** Adresse où Supabase nous ramène. Application Windows : lien profond
      (`sona://auth/callback`) ; sinon la page courante, sans fragment. */
  function redirectTo() {
    if (desktop) return "sona://auth/callback";
    return location.origin + location.pathname;
  }

  function init() {
    if (!configured || client) return !!client;
    client = window.supabase.createClient(SUPABASE_URL, SUPABASE_KEY, {
      auth: {
        persistSession: true, autoRefreshToken: true, flowType: "pkce",
        // Dans l'app Windows, le retour arrive par lien profond (traité plus bas).
        detectSessionInUrl: !desktop, storage, storageKey: "sona.auth",
      },
    });
    client.auth.onAuthStateChange((event, session) => {
      current = session;
      emit(event, session);
    });
    return true;
  }

  const need = () => { if (!init()) throw new Error("Les comptes ne sont pas configurés sur ce site."); return client; };

  function friendly(error) {
    const m = String(error?.message || error || "");
    const code = error?.code || "";
    const table = [
      [/invalid login credentials/i, "E-mail ou mot de passe incorrect."],
      [/email not confirmed/i, "Confirme d'abord ton adresse e-mail (le code ou le lien reçu)."],
      [/user already registered|already been registered/i, "Un compte existe déjà avec cette adresse : connecte-toi."],
      [/password should be at least|weak_password|password is too weak/i, "Mot de passe trop faible : 10 caractères minimum, avec minuscules, majuscules et chiffres."],
      [/rate limit|over_email_send_rate_limit|too many/i, "Trop d'essais pour le moment : réessaie dans quelques minutes."],
      [/captcha/i, "La vérification anti-robot a échoué : réessaie."],
      [/token has expired|otp_expired|invalid.*(token|otp)/i, "Code invalide ou expiré : demandes-en un nouveau."],
      [/signup.*disabled|signups not allowed/i, "Les inscriptions sont fermées pour le moment."],
      [/banned/i, "Ce compte est banni ou suspendu."],
      [/database error saving new user|signup_blocked/i, "Inscription impossible avec ces informations (adresse temporaire, ou accès refusé)."],
      [/identity.*(already|linked)/i, "Ce compte est déjà relié à un autre compte Sona."],
      [/last identity|at least one identity|cannot unlink/i, "Tu ne peux pas retirer ta dernière méthode de connexion."],
      [/failed to fetch|networkerror|load failed/i, "Connexion impossible : vérifie ta connexion Internet."],
    ];
    for (const [re, text] of table) if (re.test(m) || re.test(code)) return text;
    return m || "Une erreur est survenue.";
  }

  async function run(promise) {
    const { data, error } = await promise;
    if (error) { const e = new Error(friendly(error)); e.original = error; throw e; }
    return data;
  }

  // ── Mot de passe ─────────────────────────────────────────────────────────

  const COMMON = ["password", "motdepasse", "azertyuiop", "qwertyuiop", "123456789", "0123456789", "sona", "trysona"];

  /** Renvoie un message d'erreur, ou null si le mot de passe est acceptable.
      Même règle que celle imposée par Supabase (config.toml). */
  function passwordProblem(pw, email = "") {
    if (pw.length < 10) return "10 caractères minimum.";
    if (!/[a-z]/.test(pw) || !/[A-Z]/.test(pw) || !/[0-9]/.test(pw)) return "Il faut des minuscules, des majuscules et des chiffres.";
    const low = pw.toLowerCase();
    if (COMMON.some((c) => low.includes(c))) return "Ce mot de passe est trop courant.";
    const local = (email.split("@")[0] || "").toLowerCase();
    if (local.length >= 4 && low.includes(local)) return "Ne reprends pas ton adresse e-mail.";
    return null;
  }

  /** 0 à 4, pour la jauge. */
  function passwordScore(pw) {
    let s = 0;
    if (pw.length >= 10) s++;
    if (pw.length >= 14) s++;
    if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) s++;
    if (/[0-9]/.test(pw) && /[^A-Za-z0-9]/.test(pw)) s++;
    return passwordProblem(pw) ? Math.min(s, 1) : Math.max(s, 2);
  }

  // ── Anti-robot (Cloudflare Turnstile, invisible) ─────────────────────────

  let turnstileLoading = null;
  function loadTurnstile() {
    if (window.turnstile) return Promise.resolve();
    turnstileLoading ||= new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
      s.async = true;
      s.onload = resolve;
      s.onerror = () => reject(new Error("La vérification anti-robot n'a pas pu se charger."));
      document.head.append(s);
    });
    return turnstileLoading;
  }

  /** Jeton anti-robot, ou undefined si Turnstile n'est pas configuré. */
  async function captcha() {
    if (!TURNSTILE_KEY) return undefined;
    await loadTurnstile();
    return new Promise((resolve, reject) => {
      const host = document.createElement("div");
      host.style.cssText = "position:fixed;bottom:12px;right:12px;z-index:200";
      document.body.append(host);
      const done = (fn) => (v) => { clearTimeout(timer); try { window.turnstile.remove(id); } catch {} host.remove(); fn(v); };
      const timer = setTimeout(() => done(reject)(new Error("La vérification anti-robot a pris trop de temps : réessaie.")), 25000);
      const id = window.turnstile.render(host, {
        sitekey: TURNSTILE_KEY, appearance: "interaction-only",
        callback: done(resolve), "error-callback": () => done(reject)(new Error("La vérification anti-robot a échoué : réessaie.")),
      });
    });
  }

  // ── Connexion ────────────────────────────────────────────────────────────

  const auth = {
    configured,
    init,
    desktop: !!desktop,
    redirectTo,
    onChange(fn) { listeners.add(fn); return () => listeners.delete(fn); },
    friendly,
    passwordProblem,
    passwordScore,

    async session() {
      if (!init()) return null;
      const { data } = await client.auth.getSession();
      current = data.session;
      return current;
    },
    /** Jeton d'accès valable (renouvelé automatiquement par supabase-js). */
    async accessToken() { return (await auth.session())?.access_token || null; },
    user: () => current?.user || null,
    isGuest: () => !!current?.user?.is_anonymous,

    async signIn(email, password) {
      const captchaToken = await captcha();
      return run(need().auth.signInWithPassword({ email, password, options: { captchaToken } }));
    },
    /** Code à 6 chiffres (et lien) par e-mail. Sur l'appli installée, le code évite
        de dépendre du navigateur qui ouvre le lien. */
    async sendCode(email) {
      const captchaToken = await captcha();
      return run(need().auth.signInWithOtp({ email, options: { shouldCreateUser: true, emailRedirectTo: redirectTo(), captchaToken } }));
    },
    /** type : « email » (connexion ou inscription) ou « recovery » (mot de passe oublié). */
    verifyCode(email, token, type = "email") {
      return run(need().auth.verifyOtp({ email, token: token.replace(/\s+/g, ""), type }));
    },
    async resetPassword(email) {
      const captchaToken = await captcha();
      return run(need().auth.resetPasswordForEmail(email, { redirectTo: redirectTo(), captchaToken }));
    },
    updatePassword(password) {
      const problem = passwordProblem(password);
      if (problem) return Promise.reject(new Error(problem));
      return run(need().auth.updateUser({ password }));
    },
    updateEmail(email) { return run(need().auth.updateUser({ email }, { emailRedirectTo: redirectTo() })); },

    /** Fournisseurs OAuth (Google, Discord, GitHub). Application Windows : navigateur
        du système + lien profond, jamais une WebView. */
    async oauth(provider) {
      const { data, error } = await need().auth.signInWithOAuth({
        provider, options: { redirectTo: redirectTo(), skipBrowserRedirect: !!desktop, scopes: SCOPES[provider] },
      });
      if (error) throw new Error(friendly(error));
      if (desktop && data?.url) desktop.openExternal(data.url);
    },
    async linkOAuth(provider) {
      const { data, error } = await need().auth.linkIdentity({
        provider, options: { redirectTo: redirectTo(), skipBrowserRedirect: !!desktop, scopes: SCOPES[provider] },
      });
      if (error) throw new Error(friendly(error));
      if (desktop && data?.url) desktop.openExternal(data.url);
    },
    async identities() { return (await run(need().auth.getUserIdentities())).identities || []; },
    /** Jamais la dernière méthode : une identité e-mail sans mot de passe compte
        comme une méthode (code par e-mail), mais on garde toujours au moins une identité. */
    async unlink(identity) {
      const all = await auth.identities();
      if (all.length <= 1) throw new Error("Tu ne peux pas retirer ta dernière méthode de connexion.");
      return run(need().auth.unlinkIdentity(identity));
    },

    /** Lien profond reçu par l'application Windows (`sona://auth/callback?code=…`). */
    async handleDeepLink(url) {
      let u;
      try { u = new URL(url); } catch { return false; }
      if (u.protocol !== "sona:" || u.host !== "auth") return false;
      const handoff = u.searchParams.get("handoff");
      if (handoff) { await appLink.finish(handoff); return true; }
      const code = u.searchParams.get("code");
      if (!code) throw new Error(friendly(u.searchParams.get("error_description") || "Connexion annulée."));
      await run(need().auth.exchangeCodeForSession(code));
      return true;
    },

    /** Mode invité : connexion anonyme (mêmes données, rattachées au compte créé ensuite). */
    async guest() {
      const captchaToken = await captcha();
      return run(need().auth.signInAnonymously({ options: { captchaToken } }));
    },
    /** Transforme l'invité en vrai compte : même identifiant, donc rien à migrer. */
    async upgradeGuest(email, password) {
      const problem = passwordProblem(password, email);
      if (problem) throw new Error(problem);
      return run(need().auth.updateUser({ email, password }, { emailRedirectTo: redirectTo() }));
    },

    async signOut(everywhere = false) {
      if (!client) return;
      try { await client.auth.signOut({ scope: everywhere ? "global" : "local" }); } catch { /* déjà déconnecté */ }
      current = null;
    },
  };

  // Scopes minimaux : aucune vérification Google ni Discord nécessaire.
  const SCOPES = { google: "openid email profile", discord: "identify email", github: "read:user user:email" };

  // ── Passkeys (WebAuthn) ──────────────────────────────────────────────────

  // ── Connexion de l'application par le navigateur (docs/AUTH_SETUP.md) ──────
  // L'application garde un secret, le site n'en voit que l'empreinte : un code
  // intercepté ne sert à rien, et aucun jeton de session ne passe dans une adresse.
  const SITE = meta("sona-site") || "https://www.trysona.fr/";
  const APP_SECRET = "sona.appLink";
  const appLink = {
    /** Dans l'application : ouvre le site dans le navigateur du système. */
    async start() {
      const secret = b64.enc(crypto.getRandomValues(new Uint8Array(32)));
      localStorage.setItem(APP_SECRET, secret);
      const challenge = b64.enc(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(secret)));
      desktop.openExternal(`${SITE}?connexion&app=${challenge}`);
    },
    /** Sur le site, une fois connecté et après confirmation : l'adresse qui rend la main à l'application. */
    async approve(challenge) {
      const { code } = await svc("/app-link", { method: "POST", body: { challenge } });
      return `sona://auth/callback?handoff=${encodeURIComponent(code)}`;
    },
    /** Dans l'application : le code revenu du navigateur devient une session. */
    async finish(code) {
      const verifier = localStorage.getItem(APP_SECRET);
      if (!verifier) throw new Error("Aucune connexion demandée depuis cette application : recommence.");
      const out = await svc("/app-link/exchange", { method: "POST", anonymous: true, body: { code, verifier } });
      localStorage.removeItem(APP_SECRET);
      await run(need().auth.verifyOtp({ token_hash: out.token_hash, type: out.type || "email" }));
    },
  };

  const b64 = {
    enc: (buf) => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, ""),
    dec: (s) => {
      s = s.replace(/-/g, "+").replace(/_/g, "/");
      s += "=".repeat((4 - (s.length % 4)) % 4);
      return Uint8Array.from(atob(s), (c) => c.charCodeAt(0)).buffer;
    },
  };

  const passkeys = {
    supported: () => !!window.PublicKeyCredential && !!navigator.credentials?.create,
    async register(deviceName) {
      const start = await svc("/passkey/register/start", { method: "POST" });
      const pk = start.options.publicKey;
      pk.challenge = b64.dec(pk.challenge);
      pk.user.id = b64.dec(pk.user.id);
      (pk.excludeCredentials || []).forEach((c) => (c.id = b64.dec(c.id)));
      let cred;
      try { cred = await navigator.credentials.create({ publicKey: pk }); }
      catch (e) { throw new Error(e?.name === "NotAllowedError" ? "Création annulée." : "Cet appareil n'a pas pu créer la clé d'accès."); }
      await svc("/passkey/register/finish", { method: "POST", body: {
        challenge_id: start.challenge_id, device_name: deviceName || null,
        credential: {
          id: cred.id, rawId: b64.enc(cred.rawId), type: cred.type, extensions: cred.getClientExtensionResults?.() || {},
          response: { attestationObject: b64.enc(cred.response.attestationObject), clientDataJSON: b64.enc(cred.response.clientDataJSON) },
        },
      } });
    },
    /** Connexion sans e-mail : Face ID, Touch ID, Windows Hello. */
    async login() {
      const start = await svc("/passkey/login/start", { method: "POST", anonymous: true });
      const pk = start.options.publicKey;
      pk.challenge = b64.dec(pk.challenge);
      (pk.allowCredentials || []).forEach((c) => (c.id = b64.dec(c.id)));
      let cred;
      try { cred = await navigator.credentials.get({ publicKey: pk }); }
      catch (e) { throw new Error(e?.name === "NotAllowedError" ? "Connexion annulée." : "Aucune clé d'accès utilisable sur cet appareil."); }
      const out = await svc("/passkey/login/finish", { method: "POST", anonymous: true, body: {
        challenge_id: start.challenge_id,
        credential: {
          id: cred.id, rawId: b64.enc(cred.rawId), type: cred.type, extensions: cred.getClientExtensionResults?.() || {},
          response: {
            authenticatorData: b64.enc(cred.response.authenticatorData), clientDataJSON: b64.enc(cred.response.clientDataJSON),
            signature: b64.enc(cred.response.signature), userHandle: cred.response.userHandle ? b64.enc(cred.response.userHandle) : null,
          },
        },
      } });
      // Le service a fabriqué un lien magique : on l'échange contre une vraie session.
      return run(need().auth.verifyOtp({ token_hash: out.token_hash, type: out.type || "email" }));
    },
    async list() {
      return run(need().from("passkey_credentials").select("id, device_name, created_at, last_used_at").order("created_at"));
    },
    async remove(id) { await run(need().from("passkey_credentials").delete().eq("id", id)); },
  };

  // ── Service de comptes (Rust) ────────────────────────────────────────────

  /** Erreur de sanction reçue d'un service : l'interface affiche l'écran dédié. */
  let sanctionHandler = null;

  async function svc(path, { method = "GET", body, anonymous = false, raw = false } = {}) {
    if (!ACCOUNTS_URL) throw new Error("Le service de comptes n'est pas configuré sur ce site.");
    const headers = { "Content-Type": "application/json" };
    if (!anonymous) {
      const t = await auth.accessToken();
      if (!t) throw new Error("Connexion requise.");
      headers.Authorization = `Bearer ${t}`;
    }
    let res;
    try { res = await fetch(ACCOUNTS_URL + path, { method, headers, body: body ? JSON.stringify(body) : undefined }); }
    catch { throw new Error("Le service de comptes est injoignable."); }
    if (raw && res.ok) return res;
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      if (data.error === "sanctioned") sanctionHandler?.(data);
      const e = new Error(data.message || `Erreur ${res.status}`);
      e.status = res.status;
      e.code = data.error;
      throw e;
    }
    return data;
  }

  // ── Social et profil (RPC SQL, protégées par RLS) ────────────────────────

  async function rpc(name, args) {
    const { data, error } = await need().rpc(name, args || {});
    if (error) {
      const m = error.message || "";
      let text = friendly(error);
      if (/rate_limited/.test(m)) text = "Trop de demandes pour le moment : réessaie plus tard.";
      else if (/friends_limit/.test(m)) text = "Limite d'amis atteinte.";
      else if (/forbidden/.test(m) || error.code === "42501") text = "Action impossible avec ce compte.";
      else if (/cannot_report_self/.test(m)) text = "Tu ne peux pas te signaler toi-même.";
      const e = new Error(text);
      e.original = error;
      throw e;
    }
    return data;
  }

  const table = (name) => need().from(name);
  const unwrap = (promise) => run(promise);

  const social = {
    rpc,
    table,
    unwrap,
    usernameAvailable: (name) => rpc("username_available", { p_name: name }),
    friends: () => rpc("list_friends"),
    requests: () => rpc("list_friend_requests"),
    blocked: () => rpc("list_blocked"),
    sendRequest: (username) => rpc("send_friend_request", { p_username: username }),
    redeemCode: (code) => rpc("redeem_friend_code", { p_code: code }),
    rotateCode: () => rpc("rotate_friend_code"),
    respond: (id, action) => rpc("respond_friend_request", { p_request: id, p_action: action }),
    cancel: (id) => rpc("cancel_friend_request", { p_request: id }),
    remove: (userId) => rpc("remove_friend", { p_user: userId }),
    block: (userId) => rpc("block_user", { p_user: userId }),
    unblock: (userId) => rpc("unblock_user", { p_user: userId }),
    profileOf: (userId) => rpc("get_profile", { p_user: userId }),
    report: ({ type, userId, ref, reason, details, snapshot }) => rpc("create_report", {
      p_target_type: type, p_target_user: userId || null, p_target_ref: ref || null, p_reason: reason,
      p_details: details || null, p_snapshot: snapshot || {},
    }),
    appeal: (sanctionId, message) => rpc("create_appeal", { p_sanction: sanctionId, p_message: message }),

    async me() {
      const u = auth.user();
      if (!u) return null;
      return unwrap(table("profiles").select("*").eq("id", u.id).single());
    },
    updateProfile: async (patch) => {
      const u = auth.user();
      const rows = await unwrap(table("profiles").update(patch).eq("id", u.id).select());
      if (!rows.length) throw new Error("Modification refusée : ton compte est restreint.");
      return rows[0];
    },
    async privacy() { return unwrap(table("privacy_settings").select("*").single()); },
    async updatePrivacy(patch) {
      const rows = await unwrap(table("privacy_settings").update(patch).eq("user_id", auth.user().id).select());
      if (!rows.length) throw new Error("Modification refusée.");
      return rows[0];
    },
    async settings() { return unwrap(table("user_settings").select("*").single()); },
    async updateSettings(patch) {
      const rows = await unwrap(table("user_settings").update(patch).eq("user_id", auth.user().id).select());
      return rows[0];
    },
    async sanctions() { return unwrap(table("sanctions").select("*").order("created_at", { ascending: false })); },
    async acknowledge(id) { await unwrap(table("sanctions").update({ acknowledged_at: new Date().toISOString() }).eq("id", id)); },
    async notifications(limit = 30) { return unwrap(table("notifications").select("*").order("created_at", { ascending: false }).limit(limit)); },
    async markRead(ids) {
      if (ids.length) await unwrap(table("notifications").update({ read_at: new Date().toISOString() }).in("id", ids));
    },
    async services() { return unwrap(table("connected_services").select("provider, external_username, connected_at, last_sync_at, last_error")); },

    /** Photo de profil : réduite à 256 px (webp) puis envoyée dans le dossier de l'utilisateur. */
    async uploadAvatar(file) {
      if (!/^image\//.test(file.type)) throw new Error("Choisis une image.");
      const blob = await resizeImage(file, 256);
      if (blob.size > 200 * 1024) throw new Error("Image trop lourde, même réduite : choisis-en une autre.");
      const path = `${auth.user().id}/avatar.webp`;
      await unwrap(need().storage.from("avatars").upload(path, blob, { contentType: "image/webp", upsert: true, cacheControl: "300" }));
      const { data } = need().storage.from("avatars").getPublicUrl(path);
      return `${data.publicUrl}?v=${Date.now()}`;
    },
  };

  async function resizeImage(file, size) {
    const bitmap = await createImageBitmap(file);
    const side = Math.min(bitmap.width, bitmap.height);
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = size;
    canvas.getContext("2d").drawImage(bitmap, (bitmap.width - side) / 2, (bitmap.height - side) / 2, side, side, 0, 0, size, size);
    return new Promise((resolve, reject) => canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("Image illisible."))), "image/webp", 0.85));
  }

  /** Téléchargement d'un fichier JSON (export RGPD). */
  async function download(path, filename) {
    const res = await svc(path, { raw: true });
    const url = URL.createObjectURL(await res.blob());
    const a = Object.assign(document.createElement("a"), { href: url, download: filename });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }

  /** Page de l'app à l'espacement resserré (mêmes composants, moins de vide). */
  window.cpage = (inner) => `<div class="page compact">${inner}</div>`;

  window.Sona = {
    configured, auth, passkeys, social, svc, download, b64, appLink,
    config: { accountsUrl: ACCOUNTS_URL, turnstile: !!TURNSTILE_KEY },
    onSanction(fn) { sanctionHandler = fn; },
  };
})();
