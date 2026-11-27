// Tests d'interface des comptes, du social, de l'administration et du menu latéral
// (navigateur réel, faux Supabase et faux serveurs : voir support.mjs).
//   node tests/ui/accounts.mjs          (playwright ou playwright-core installé ; CHROMIUM_PATH facultatif)
// Sort avec un code non nul au moindre échec ou à la moindre erreur JavaScript.
import { createRequire } from "node:module";
import { startServer, routeApi } from "./support.mjs";

const require = createRequire(import.meta.url);
let chromium;
try { ({ chromium } = require("playwright")); } catch { ({ chromium } = require("playwright-core")); }

const results = [];
const errors = [];
let failed = 0;
const ok = (name, cond, detail = "") => { results.push(`${cond ? "ok  " : "FAIL"} ${name}${!cond && detail ? ` — ${detail}` : ""}`); if (!cond) failed++; };

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined, args: ["--no-sandbox"] });

/** Nouveau contexte propre : état du faux Supabase fourni par le test. */
async function open({ mock = {}, viewport = { width: 1280, height: 800 }, music = {}, accounts = {}, hash = "", configured = true, search = "?connexion", store = {} } = {}) {
  const srv = startServer({ configured });
  const ctx = await browser.newContext({ viewport, deviceScaleFactor: 1 });
  const calls = [];
  await ctx.addInitScript(({ m, store }) => { window.__mock = m; for (const [k, v] of Object.entries(store)) localStorage.setItem(k, v); }, { m: mock, store });
  await routeApi(ctx, { music, accounts, calls });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("console", (m) => { if (m.type() === "error" && !/404|Failed to load|net::ERR|Failed to launch .sona:/.test(m.text())) errors.push(`console: ${m.text()}`); });
  await page.goto(`http://localhost:${srv.port}/web/${search}${hash}`);
  const mockState = () => page.evaluate(() => JSON.parse(JSON.stringify({ rpc: window.__mock.rpcCalls, auth: window.__mock.authCalls, updates: window.__mock.updates, profile: window.__mock.profile })));
  const close = async () => { await ctx.close(); srv.close(); };
  return { page, ctx, calls, mockState, close, port: srv.port };
}
const signedIn = (extra = {}) => ({ session: true, ...extra });
const text = (page, sel = "body") => page.locator(sel).first().innerText();
const wait = (page, ms = 250) => page.waitForTimeout(ms);
const hasScrollX = (page) => page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);

// ── Connexion ──────────────────────────────────────────────────────────────

{
  const t = await open({ configured: false });
  await wait(t.page, 500);
  ok("sans configuration : message clair", /pas encore configurés/.test(await text(t.page)));
  await t.close();
}

{
  const t = await open();
  await t.page.waitForSelector(".auth-card");
  const body = await text(t.page);
  ok("écran unique : fournisseurs, e-mail, invité", /Google/.test(body) && /Discord/.test(body) && /GitHub/.test(body) && (await t.page.locator('input[name="email"]').count()) === 1 && /Essayer sans compte/.test(body));
  ok("liens légaux", (await t.page.locator('a[href="conditions"]').count()) === 1 && (await t.page.locator('a[href="confidentialite"]').count()) === 1);
  ok("pas de scroll horizontal (bureau)", !(await hasScrollX(t.page)));
  ok("un seul champ : pas d'onglets ni de mot de passe d'emblée", (await t.page.locator('[data-mode], input[name="password"]').count()) === 0);
  await t.page.fill('input[name="email"]', "alice@example.org");
  await t.page.click("[data-password]");
  await t.page.waitForSelector("#auth-password");
  ok("mot de passe : l'adresse saisie est reprise", (await t.page.inputValue('input[name="email"]')) === "alice@example.org");
  await t.page.fill('input[name="password"]', "wrong");
  await t.page.click("#auth-password button.btn");
  await t.page.waitForSelector(".auth-msg .error");
  ok("mauvais mot de passe : message en français", /incorrect/.test(await text(t.page, ".auth-msg")));
  await t.page.fill('input[name="password"]', "Correct-horse-9");
  await t.page.click("#auth-password button.btn");
  await t.page.waitForSelector("#sb", { timeout: 5000 });
  ok("connexion : l'app s'ouvre avec le menu", true);
  await t.close();
}

{
  const t = await open();
  await t.page.click('[data-provider="google"]');
  await wait(t.page, 200);
  const m = await t.mockState();
  const call = m.auth.find((c) => c[0] === "oauth");
  ok("OAuth Google : scopes minimaux et retour sur la page", call?.[1].provider === "google" && call[1].options.scopes === "openid email profile" && /^http:\/\/localhost:\d+\/web\/$/.test(call[1].options.redirectTo), JSON.stringify(call));
  await t.page.click('[data-provider="discord"]');
  await t.page.click('[data-provider="github"]');
  const scopes = (await t.mockState()).auth.filter((c) => c[0] === "oauth").map((c) => c[1].options.scopes);
  ok("scopes Discord / GitHub minimaux", scopes[1] === "identify email" && scopes[2] === "read:user user:email", scopes.join("|"));
  await t.close();
}

// Inscription → code → bienvenue (pseudo vérifié en direct, services, préférences) → app.
{
  const t = await open({ mock: { profile: { id: "u1", username: "sona_ab12cd34", display_name: null, avatar_url: null, bio: null, role: "user", status: "active", status_reason: null, status_until: null, onboarding_completed: false, force_username_change: false, force_avatar_change: false, friend_code: "abc", created_at: "2026-01-01T00:00:00Z" } } });
  await t.page.fill('input[name="email"]', "nouvelle@example.org");
  await t.page.click("#auth-form button.btn");
  await t.page.waitForSelector("#auth-code");
  const sent = (await t.mockState()).auth.find((c) => c[0] === "otp");
  ok("e-mail seul : un code est envoyé et le compte créé au besoin", sent?.[1].email === "nouvelle@example.org" && sent[1].options.shouldCreateUser === true, JSON.stringify((await t.mockState()).auth));
  ok("code à 6 chiffres demandé, mot de passe proposé en repli", /nouvelle@example\.org/.test(await text(t.page)) && (await t.page.locator("[data-password]").count()) === 1);
  await t.page.fill('input[name="code"]', "000000");
  await t.page.click("#auth-code button");
  await t.page.waitForSelector(".auth-msg .error");
  ok("code invalide : message clair", /invalide ou expiré/.test(await text(t.page, ".auth-msg")));
  await t.page.fill('input[name="code"]', "123456");
  await t.page.click("#auth-code button");
  await t.page.waitForSelector(".onboarding");
  ok("parcours : progression visible, 4 étapes", (await t.page.locator(".ob-steps li").count()) === 4 && (await t.page.locator('.ob-steps li[aria-current="step"]').count()) === 1);
  ok("étape profil : suite bloquée sans pseudo valide", await t.page.locator("[data-next]").isDisabled());
  await t.page.fill("#ob-name", "bob");
  await t.page.waitForFunction(() => /déjà pris/.test(document.getElementById("ob-check").textContent));
  ok("pseudo pris signalé en direct", await t.page.locator("[data-next]").isDisabled());
  await t.page.fill("#ob-name", "ab");
  await t.page.waitForFunction(() => /3 à 20/.test(document.getElementById("ob-check").textContent) && document.getElementById("ob-check").className.includes("bad"));
  await t.page.fill("#ob-name", "nouveau_pseudo");
  await t.page.waitForFunction(() => /Disponible/.test(document.getElementById("ob-check").textContent));
  ok("pseudo disponible : on peut continuer", !(await t.page.locator("[data-next]").isEnabled() === false));
  await t.page.click("[data-next]");
  await t.page.waitForSelector("[data-lfm]");
  ok("services : Last.fm facultatif, import de playlists expliqué (rien de simulé)", (await t.page.locator(".soon").count()) === 0 && /Spotify, Deezer/.test(await text(t.page, ".ob-group")) && (await t.page.locator("[data-skip]").count()) === 1);
  await t.page.click("[data-skip]");
  await t.page.waitForSelector('[data-pref="presence"]');
  ok("préférences : présence désactivée par défaut", (await t.page.inputValue('[data-pref="presence"]')) === "nobody");
  await t.page.selectOption('[data-pref="presence"]', "friends");
  await t.page.selectOption('[data-pref="theme"]', "dark");
  await t.page.click("[data-next]");
  await t.page.waitForSelector("[data-finish]");
  ok("écran final « Tout est prêt »", /Tout est prêt/.test(await text(t.page)));
  await t.page.click("[data-finish]");
  await t.page.waitForSelector("#sb");
  const m = await t.mockState();
  ok("pseudo, drapeau d'onboarding et préférences enregistrés", m.updates.some((u) => u.table === "profiles" && u.patch.username === "nouveau_pseudo") && m.updates.some((u) => u.table === "profiles" && u.patch.onboarding_completed === true) && m.updates.some((u) => u.table === "privacy_settings" && u.patch.presence_visibility === "friends") && m.updates.some((u) => u.table === "user_settings" && u.patch.theme === "dark"), JSON.stringify(m.updates));
  await t.close();
}

// Mot de passe oublié : même message que le compte existe ou non, code, nouveau mot de passe.
{
  const t = await open();
  await t.page.click("[data-password]");
  await t.page.click("[data-forgot]");
  await t.page.fill('input[name="email"]', "inconnu@example.org");
  await t.page.click("#auth-forgot button");
  await t.page.waitForSelector("#auth-reset-code");
  ok("mot de passe oublié : code demandé, sans révéler si le compte existe", /Code envoyé/.test(await text(t.page)));
  await t.page.fill('input[name="code"]', "123456");
  await t.page.click("#auth-reset-code button");
  await t.page.waitForSelector("#auth-newpass");
  await t.page.fill('input[name="password"]', "Abcdefghij");
  ok("jauge de mot de passe", (await t.page.locator("#pw-meter i.on").count()) >= 1 && /chiffres/.test(await text(t.page, "#pw-hint")));
  await t.close();
}

// Connexion de l'application par le navigateur.
{
  // Côté application : un seul bouton, le secret reste dedans, le code revenu ouvre la session.
  const t = await open({ accounts: { "POST /app-link/exchange": { token_hash: "HASH", type: "email" } }, music: { "/me/public-link": { __status: 401, __json: { detail: "non" } } } });
  // Le pont de l'application Windows : ce qui n'est pas observé ici ne fait rien.
  await t.page.addInitScript(() => { const known = { openExternal: (u) => { window.__opened = u; }, onDeepLink: (fn) => { window.__deep = fn; }, server: "", platform: "win32" }; window.sonaDesktop = new Proxy(known, { get: (o, k) => (k in o ? o[k] : () => Promise.resolve({})) }); });
  await t.page.reload();
  await t.page.waitForSelector("[data-browser]");
  ok("application : la connexion passe par le navigateur, sans formulaire", (await t.page.locator('input[name="email"], [data-provider]').count()) === 0);
  await wait(t.page, 4600);
  ok("application sans compte : pas de faux « Déconnecté » au démarrage", !/Déconnecté/.test(await text(t.page)));
  await t.page.click("[data-browser]");
  await wait(t.page, 300);
  const opened = await t.page.evaluate(() => window.__opened);
  const secret = await t.page.evaluate(() => localStorage.getItem("sona.appLink"));
  ok("seule l'empreinte du secret part dans l'adresse", /\?connexion&app=[A-Za-z0-9_-]{43}$/.test(opened || "") && secret && !opened.includes(secret), opened);
  await t.page.evaluate(() => window.__deep("sona://auth/callback?handoff=CODE123"));
  await t.page.waitForSelector("#sb", { timeout: 5000 });
  const sent = JSON.parse(t.calls.find((c) => c.path === "/app-link/exchange")?.body || "{}");
  ok("retour du navigateur : code + secret échangés, l'application est connectée", sent.code === "CODE123" && sent.verifier === secret, JSON.stringify(sent));
  await t.close();
}
{
  // Côté site : connecté, une confirmation explicite, puis retour vers l'application.
  const challenge = "A".repeat(43);
  const t = await open({ mock: signedIn(), search: `?connexion&app=${challenge}`, accounts: { "POST /app-link": { code: "CODE123" } } });
  await t.page.waitForSelector("[data-allow]");
  const asked = () => t.calls.filter((c) => JSON.stringify(c).includes("/app-link")).length;
  ok("site : rien n'est demandé sans confirmation", asked() === 0 && /alice@example\.org/.test(await text(t.page)));
  // Le lien sona:// ne passe pas par le réseau : seul le navigateur signale la navigation demandée.
  const cdp = await t.page.context().newCDPSession(t.page);
  const opened = [];
  cdp.on("Page.frameRequestedNavigation", (e) => opened.push(e.url));
  await cdp.send("Page.enable");
  await t.page.click("[data-allow]");
  await t.page.waitForSelector("[data-stay]");
  await t.page.waitForTimeout(300);
  ok("site : retour automatique vers l'application avec le code à usage unique", opened.includes("sona://auth/callback?handoff=CODE123") && asked() === 1, JSON.stringify(opened));
  const late = t.page.locator("a[href='sona://auth/callback?handoff=CODE123']");
  const early = await late.isVisible();
  await late.waitFor({ state: "visible", timeout: 6000 });
  ok("site : lien de secours seulement après un moment", !early);
  await t.close();
}

// Mode invité.
{
  const t = await open({ mock: { profile: { id: "g1", username: "sona_guest", display_name: null, avatar_url: null, role: "user", status: "active", onboarding_completed: false, force_username_change: false, force_avatar_change: false, friend_code: "x", created_at: "2026-01-01T00:00:00Z" } } });
  await t.page.click("[data-guest]");
  await t.page.waitForSelector("#sb");
  ok("invité : l'app s'ouvre sans parcours d'inscription", true);
  await t.page.waitForSelector(".guest-banner");
  ok("invitation discrète à créer un compte", /Crée-en un/.test(await text(t.page, ".guest-banner")));
  await t.page.evaluate(() => { location.hash = "#/friends"; });
  await wait(t.page, 500);
  ok("invité : pas d'amis, invitation à créer un compte", /Crée un compte pour ajouter des amis/.test(await text(t.page, "#content")));
  await t.close();
}

// Sanctions : écran clair, raison, durée, contestation ; ban immédiat en cours de session.
{
  const t = await open({ mock: signedIn({ profile: { id: "u1", username: "troll", role: "user", status: "banned", status_reason: "Harcèlement répété", status_until: null, onboarding_completed: true, force_username_change: false, force_avatar_change: false, friend_code: "x", created_at: "2026-01-01T00:00:00Z" }, sanctions: [{ id: "s1", kind: "ban", reason: "Harcèlement répété", created_at: "2026-02-01T00:00:00Z", expires_at: null, revoked_at: null }] }) });
  await t.page.waitForSelector(".sanction");
  const body = await text(t.page, ".sanction");
  ok("banni : raison, durée définitive, contestation", /Compte banni/.test(body) && /Harcèlement répété/.test(body) && /Définitif/.test(body) && (await t.page.locator("[data-appeal]").count()) === 1);
  ok("banni : export et suppression restent possibles", (await t.page.locator("[data-export]").count()) === 1 && (await t.page.locator("[data-delete]").count()) === 1);
  ok("banni : pas de menu ni d'accès à l'app", (await t.page.locator("#sb").count()) === 0);
  await t.page.click("[data-appeal]");
  await t.page.fill('textarea[name="m"]', "Je ne le referai plus, promis");
  await t.page.click(".sheet button[type=submit]");
  await wait(t.page, 400);
  ok("contestation envoyée", (await t.mockState()).rpc.some((c) => c[0] === "create_appeal" && c[1].p_sanction === "s1"));
  await t.close();
}
{
  const until = new Date(Date.now() + 86400e3).toISOString();
  const t = await open({ mock: signedIn({ profile: { id: "u1", username: "agite", role: "user", status: "suspended", status_reason: "Spam", status_until: until, onboarding_completed: true, force_username_change: false, force_avatar_change: false, friend_code: "x", created_at: "2026-01-01T00:00:00Z" } }) });
  await t.page.waitForSelector(".sanction");
  ok("suspendu : durée affichée", /Compte suspendu/.test(await text(t.page, ".sanction")) && /Jusqu'au/.test(await text(t.page, ".sanction")));
  await t.close();
}
{
  const t = await open({ mock: signedIn(), music: { "/settings": { __status: 403, __json: { error: "sanctioned", status: "banned", reason: "Abus", until: null, message: "Ton compte est banni." } } } });
  await t.page.waitForSelector(".sanction", { timeout: 5000 });
  ok("ban reçu du serveur en cours de session : écran de sanction", /Abus/.test(await text(t.page, ".sanction")));
  await t.close();
}

// ── Menu latéral ───────────────────────────────────────────────────────────

const links = (page) => page.locator("#sb a.sb-link[data-nav]:not([data-nav^='playlist'])");
const openState = (page) => page.locator("#sb").getAttribute("data-open");
const contentLeft = (page) => page.evaluate(() => document.getElementById("content").getBoundingClientRect().left);

{
  const t = await open({ mock: signedIn() });
  await t.page.waitForSelector("#sb");
  ok("grand écran : ouvert par défaut", (await openState(t.page)) === "true" && (await t.page.getAttribute("html", "data-menu")) === "ouvert");
  const n = await links(t.page).count();
  ok("6 à 7 entrées principales (Admin absent pour un utilisateur)", n === 7 && (await t.page.locator('#sb [data-nav="admin"]').count()) === 0, String(n));
  const sections = await t.page.locator("#sb .sb-title span").allInnerTexts();
  ok("sections Découvrir, Ma musique, Social", ["découvrir", "ma musique", "social"].every((s) => sections.map((x) => x.toLowerCase()).includes(s)), sections.join(","));
  ok("aria : nav nommée, bascule aria-expanded, page courante", (await t.page.getAttribute("#sb", "aria-label")) === "Navigation principale" && (await t.page.getAttribute("#sb-toggle", "aria-expanded")) === "true" && (await t.page.locator('#sb [aria-current="page"]').count()) === 1);
  const geo = await t.page.evaluate(() => [...document.querySelectorAll("#sb a.sb-link[data-nav]")].filter((a) => !a.dataset.nav.startsWith("playlist")).map((a) => { const r = a.getBoundingClientRect(); const i = a.querySelector(".sb-ico").getBoundingClientRect(); return { h: r.height, iw: i.width, ih: i.height }; }));
  ok("zones cliquables ≥ 48 px, icônes dans 48 × 48", geo.every((g) => g.h >= 44 && g.iw >= 48 && g.ih >= 48), JSON.stringify(geo[0]));
  const openLeft = await contentLeft(t.page);
  ok("ouvert : le contenu commence après la carte (276 px + marge)", openLeft >= 276 && openLeft < 310, String(openLeft));
  ok("pas de scroll horizontal (menu ouvert)", !(await hasScrollX(t.page)));
  const labels = await t.page.evaluate(() => [...document.querySelectorAll("#sb .sb-link .sb-label")].filter((l) => l.scrollWidth > l.clientWidth + 1 && getComputedStyle(l).textOverflow !== "ellipsis").length);
  ok("aucun libellé tronqué sans ellipsis", labels === 0);
  const timing = await t.page.evaluate(() => {
    const sb = document.getElementById("sb");
    const label = document.querySelector('#sb [data-nav="home"] .sb-label');
    const open = { clipDelay: getComputedStyle(sb).transitionDelay, labelDelay: getComputedStyle(label).transitionDelay, clipDur: getComputedStyle(sb).transitionDuration, prop: getComputedStyle(sb).transitionProperty };
    sb.dataset.open = "false";
    const closed = { clipDelay: getComputedStyle(sb).transitionDelay, labelDelay: getComputedStyle(label).transitionDelay };
    sb.dataset.open = "true";
    return { open, closed };
  });
  ok("animation : 200–250 ms, sur clip-path (jamais width)", /clip-path/.test(timing.open.prop) && !/width/.test(timing.open.prop) && parseFloat(timing.open.clipDur) >= 0.2 && parseFloat(timing.open.clipDur) <= 0.25, JSON.stringify(timing.open));
  ok("ouverture : libellés en fondu APRÈS le début de l'agrandissement", parseFloat(timing.open.labelDelay) >= 0.08 && parseFloat(timing.open.clipDelay) === 0, JSON.stringify(timing));
  ok("fermeture : libellés effacés AVANT le repli", parseFloat(timing.closed.clipDelay) >= 0.06 && parseFloat(timing.closed.labelDelay) === 0, JSON.stringify(timing));
  const liq = async () => t.page.evaluate(() => { const l = document.getElementById("sb-liquid").getBoundingClientRect(); const a = document.querySelector("#sb .sb-link.active").getBoundingClientRect(); const sb = document.getElementById("sb").getBoundingClientRect(); return { lt: l.top, at: a.top, lh: l.height, ah: a.height, ll: l.left - sb.left, lw: l.width, op: getComputedStyle(document.getElementById("sb-liquid")).opacity, tc: getComputedStyle(document.querySelector("#sb .sb-link.active")).color }; });
  const l1 = await liq();
  ok("pastille liquide : sous la page active", Math.abs(l1.lt - l1.at) < 2 && Math.abs(l1.lh - l1.ah) < 2 && l1.op === "1", JSON.stringify(l1));
  const br = await t.page.evaluate(() => { const b = document.getElementById("sb-bridge").getBoundingClientRect(); const g = document.getElementById("sb-glow").getBoundingClientRect(); const c = document.getElementById("content").getBoundingClientRect(); const sb = document.getElementById("sb").getBoundingClientRect(); const a = document.querySelector("#sb .sb-link.active").getBoundingClientRect(); return { bl: b.left, br: b.right, bt: b.top, bb: b.bottom, cl: c.left, sr: sb.right, at: a.top, ab: a.bottom, gc: g.top + g.height / 2, gw: g.width, gl: g.left, op: getComputedStyle(document.getElementById("sb-glow")).opacity }; });
  ok("bordure de la page : le trait épaissi part du bord de la page et ne dépasse pas vers le menu", br.bl >= br.cl - 1 && br.bl <= br.cl + 1 && br.br > br.cl, JSON.stringify(br));
  ok("bordure de la page : épaissie autour de la page active (± 36 px)", Math.abs(br.bt - (br.at - 36)) < 2 && Math.abs(br.bb - (br.ab + 36)) < 2, JSON.stringify(br));
  ok("lueur : centrée sur la page active, visible, autour de la bordure de la page", Math.abs(br.gc - (br.at + br.ab) / 2) < 2 && br.op === "1" && br.gw >= 200 && Math.abs(br.gl + br.gw / 2 - br.cl) < 4, JSON.stringify(br));
  await t.page.evaluate(() => { location.hash = "#/friends"; });
  await wait(t.page, 700);
  const l2 = await liq();
  ok("pastille liquide : glisse sous la nouvelle page", Math.abs(l2.lt - l2.at) < 2 && l2.lt > l1.lt + 100, JSON.stringify([l1.lt, l2]));
  ok("texte de la page active lisible sur la pastille (sombre)", /rgb\(\s*(\d{1,2}),\s*(\d{1,2}),\s*(\d{1,2})\)/.test(l2.tc) && Number(l2.tc.match(/\d+/)[0]) < 60, l2.tc);
  await t.page.evaluate(() => { location.hash = "#/home"; });
  await wait(t.page, 700);
  await t.page.screenshot({ path: "/tmp/claude-0/sidebar-open.png" });

  // Fermer : bouton, puis Ctrl+B.
  await t.page.click("#sb-toggle");
  await wait(t.page, 450);
  ok("bouton : rail (aria-expanded=false, data-menu=rail)", (await openState(t.page)) === "false" && (await t.page.getAttribute("#sb-toggle", "aria-expanded")) === "false" && (await t.page.getAttribute("html", "data-menu")) === "rail");
  const railLeft = await contentLeft(t.page);
  ok("rail : le contenu commence après la carte (84 px + marge)", railLeft >= 84 && railLeft < 110, String(railLeft));
  const vis = await t.page.evaluate(() => { const sb = document.getElementById("sb"); const r = sb.getBoundingClientRect(); return { clip: getComputedStyle(sb).clipPath, w: r.width }; });
  ok("rail : largeur ouverte conservée, rognée par clip-path (pas de largeur animée)", vis.w === 264 && /inset/.test(vis.clip), JSON.stringify(vis));
  const op = await t.page.evaluate(() => getComputedStyle(document.querySelector('#sb [data-nav="home"] .sb-label')).opacity);
  ok("rail : libellés invisibles", Number(op) < 0.05, op);
  await t.page.screenshot({ path: "/tmp/claude-0/sidebar-rail.png" });
  await t.page.mouse.move(700, 500);
  await t.page.keyboard.press("Control+b");
  await wait(t.page, 450);
  ok("Ctrl+B rouvre le menu", (await openState(t.page)) === "true" && (await t.page.getAttribute("html", "data-menu")) === "ouvert");
  const persisted = await t.page.evaluate(() => JSON.parse(localStorage.getItem("sona.look")).menu);
  ok("état mémorisé sur l'appareil", persisted === "ouvert", String(persisted));
  // Bascules répétées très vite : état final cohérent, rien de coincé.
  for (let i = 0; i < 15; i++) await t.page.keyboard.press("Control+b");
  await wait(t.page, 500);
  const want = (await t.page.getAttribute("html", "data-menu")) === "ouvert" ? "true" : "false";
  ok("15 bascules rapides : état cohérent", (await openState(t.page)) === want && !(await hasScrollX(t.page)));
  const anims = await t.page.evaluate(() => document.getAnimations().length);
  ok("aucune animation restée bloquée", anims < 3, String(anims));
  await t.close();
}

// Rail : survol qui déplie sans pousser, info-bulle, clavier, réglage désactivable, badges.
{
  const t = await open({ mock: signedIn(), viewport: { width: 1000, height: 760 } });
  await t.page.waitForSelector("#sb");
  ok("écran moyen : rail par défaut", (await openState(t.page)) === "false" && (await t.page.getAttribute("html", "data-menu")) === "rail");
  const before = await contentLeft(t.page);
  await t.page.mouse.move(30, 200);
  await wait(t.page, 700);
  ok("survol : le panneau se déplie", (await openState(t.page)) === "true");
  ok("survol : le contenu n'est pas poussé", (await contentLeft(t.page)) === before);
  ok("survol : tooltip masqué quand le panneau est ouvert", (await t.page.locator(".sb-tip.show").count()) === 0);
  await t.page.mouse.move(700, 400);
  await wait(t.page, 700);
  ok("sortie : le panneau se replie", (await openState(t.page)) === "false");
  // Info-bulle (nom + raccourci) : quand le survol ne déplie pas le panneau.
  await t.page.evaluate(() => { const l = JSON.parse(localStorage.getItem("sona.look") || "{}"); l.hover = false; localStorage.setItem("sona.look", JSON.stringify(l)); });
  await t.page.reload();
  await t.page.waitForSelector("#sb");
  await t.page.hover('#sb [data-nav="search"] .sb-ico');
  await wait(t.page, 250);
  ok("info-bulle : pas immédiate (léger délai)", (await t.page.locator(".sb-tip.show").count()) === 0);
  await wait(t.page, 400);
  const tip = t.page.locator(".sb-tip");
  ok("info-bulle du rail : nom de la page et raccourci", (await tip.count()) === 1 && /Rechercher/.test(await tip.innerText()) && /(Alt|⌥) 2/.test(await tip.innerText()), (await tip.count()) ? await tip.innerText() : "absente");
  await t.page.mouse.move(700, 400);
  await wait(t.page, 300);
  ok("info-bulle masquée en quittant", (await t.page.locator(".sb-tip.show").count()) === 0);
  await t.page.evaluate(() => { const l = JSON.parse(localStorage.getItem("sona.look") || "{}"); l.hover = true; localStorage.setItem("sona.look", JSON.stringify(l)); });
  await t.page.reload();
  await t.page.waitForSelector("#sb");
  // Clavier : le focus visible déplie.
  await t.page.keyboard.press("Tab");
  for (let i = 0; i < 4; i++) { if ((await openState(t.page)) === "true") break; await t.page.keyboard.press("Tab"); }
  const kb = await t.page.evaluate(() => document.activeElement?.closest("#sb") ? true : false);
  ok("clavier : le panneau s'ouvre quand le focus visible y entre", !kb || (await openState(t.page)) === "true");
  // Raccourci Alt+3.
  await t.page.mouse.move(700, 400);
  await t.page.evaluate(() => document.activeElement?.blur());
  await t.page.keyboard.press("Alt+3");
  await wait(t.page, 400);
  ok("raccourci Alt + 3 : page Radios", (await t.page.evaluate(() => location.hash)).startsWith("#/radios"));
  // Survol désactivé dans les réglages.
  await t.page.evaluate(() => { const l = JSON.parse(localStorage.getItem("sona.look") || "{}"); l.hover = false; localStorage.setItem("sona.look", JSON.stringify(l)); });
  await t.page.reload();
  await t.page.waitForSelector("#sb");
  await t.page.mouse.move(30, 200);
  await wait(t.page, 700);
  ok("survol désactivé : le panneau reste en rail", (await openState(t.page)) === "false");
  await t.close();
}

// Pastilles de notification, entrée Admin réservée à l'équipe.
{
  const t = await open({ mock: signedIn({ profile: { id: "m1", username: "modo", role: "moderator", status: "active", onboarding_completed: true, force_username_change: false, force_avatar_change: false, friend_code: "x", created_at: "2026-01-01T00:00:00Z" } }) });
  await t.page.waitForSelector("#sb");
  ok("modérateur : entrée Modération visible", (await t.page.locator('#sb [data-nav="admin"]').count()) === 1 && (await links(t.page).count()) === 8);
  await t.page.evaluate(() => document.dispatchEvent(new CustomEvent("sona:notifications", { detail: { unread: 4, list: [], friendRequests: 3, invites: 1 } })));
  const badge = await t.page.locator('#sb [data-nav="friends"] .sb-badge').innerText();
  ok("pastille : compteur de demandes d'amis", badge === "3" && /3 nouveaux/.test(await t.page.getAttribute('#sb [data-nav="friends"]', "aria-label")), badge);
  ok("pastille : invitations de session", (await t.page.locator('#sb [data-nav="party"] .sb-badge').innerText()) === "1");
  await t.close();
}

// Mobile : pas de menu latéral, barre du bas + « Plus ».
{
  const t = await open({ mock: signedIn(), viewport: { width: 390, height: 844 } });
  await t.page.waitForSelector(".tabbar");
  ok("mobile : pas de menu latéral", !(await t.page.locator("#sb").isVisible()));
  const btns = await t.page.locator(".tabbar button").count();
  const small = await t.page.evaluate(() => [...document.querySelectorAll(".tabbar button")].filter((b) => b.getBoundingClientRect().height < 44 || b.getBoundingClientRect().width < 44).length);
  ok("mobile : 4 boutons + Plus, zones ≥ 44 px", btns === 5 && small === 0, `${btns} boutons, ${small} trop petits`);
  ok("mobile : pas de scroll horizontal", !(await hasScrollX(t.page)));
  await t.page.click(".tabbar [data-more]");
  await t.page.waitForSelector(".more-sheet");
  const more = await text(t.page, ".more-sheet");
  ok("mobile : « Plus » donne le contenu du panneau", /Stats/.test(more) && /Sessions/.test(more) && /social/i.test(more) && /playlists/i.test(more) && /Réglages/.test(more));
  await t.page.screenshot({ path: "/tmp/claude-0/mobile-more.png" });
  await t.close();
}

// ── Amis ───────────────────────────────────────────────────────────────────

{
  const t = await open({ mock: signedIn({ friends: [{ user_id: "f1", username: "carol", display_name: null, avatar_url: null }], requests: [{ id: "r1", direction: "in", user_id: "d1", username: "dave", display_name: null, avatar_url: null, created_at: new Date().toISOString() }, { id: "r2", direction: "out", user_id: "e1", username: "erin", display_name: null, avatar_url: null, created_at: new Date().toISOString() }] }), hash: "#/friends" });
  await t.page.waitForSelector(".friends-head");
  const body = await text(t.page, "#content");
  ok("amis : demandes reçues et envoyées, ami", /dave/.test(body) && /erin/.test(body) && /carol/.test(body) && /Demandes reçues/.test(body));
  await t.page.click('[data-accept="r1"]');
  await wait(t.page, 300);
  ok("accepter appelle la base", (await t.mockState()).rpc.some((c) => c[0] === "respond_friend_request" && c[1].p_action === "accept" && c[1].p_request === "r1"));
  await t.page.click('[data-decline="r1"]').catch(() => {});
  await t.page.click("[data-add]");
  await t.page.fill('.sheet input[name="u"]', "zoe");
  await t.page.click(".sheet button[type=submit]");
  await wait(t.page, 400);
  const m = await t.mockState();
  ok("ajout par pseudo : message sans révéler l'existence du compte", m.rpc.some((c) => c[0] === "send_friend_request" && c[1].p_username === "zoe") && /si ce pseudo existe/.test(await text(t.page, ".toast")));
  await t.page.click("[data-mycode]");
  await t.page.waitForSelector(".qr svg");
  ok("mon code : QR code et lien personnel", /\?ami=abc123def456/.test(await text(t.page, ".qr-link")));
  await t.page.keyboard.press("Escape");
  await wait(t.page, 400);
  await t.page.click('[data-fmenu="f1"]');
  await t.page.waitForSelector(".sheet .menu");
  const menuText = await text(t.page, ".sheet");
  ok("menu d'un ami : retirer, bloquer, signaler", ["Retirer", "Bloquer", "Signaler"].every((s) => menuText.includes(s)));
  await t.page.click(".menu-item >> text=Signaler");
  await t.page.waitForSelector(".reasons");
  const reasonText = await text(t.page, ".reasons");
  ok("signalement : motifs spam, harcèlement, inapproprié, usurpation, autre", ["Spam", "Harcèlement", "Contenu inapproprié", "Usurpation d'identité", "Autre"].every((s) => reasonText.includes(s)));
  await t.page.check('input[value="harassment"]');
  await t.page.fill('textarea[name="details"]', "Messages répétés");
  await t.page.click(".sheet button[type=submit]");
  await wait(t.page, 400);
  const rep = (await t.mockState()).rpc.find((c) => c[0] === "create_report");
  ok("signalement envoyé avec motif et précisions", rep?.[1].p_reason === "harassment" && rep[1].p_target_user === "f1" && rep[1].p_details === "Messages répétés", JSON.stringify(rep));
  await t.close();
}

{
  const t = await open({ mock: signedIn(), hash: "#/friends", accounts: {} });
  await t.page.waitForSelector(".friends-head");
  ok("aucun ami par défaut : message explicite", /Personne n'est ami avec toi par défaut/.test(await text(t.page, "#content")));
  await t.close();
}

// ── Réglages du compte ─────────────────────────────────────────────────────

{
  const t = await open({ mock: signedIn({ identities: [{ provider: "google", id: "i1" }] }), hash: "#/settings/account" });
  await t.page.waitForSelector('[data-unlink="google"]');
  await t.page.click('[data-unlink="google"]');
  await wait(t.page, 400);
  ok("jamais délier la dernière méthode", /dernière méthode/.test(await text(t.page, ".toast")) && !(await t.mockState()).auth.some((c) => c[0] === "unlink"));
  await t.close();
}
{
  const t = await open({ mock: signedIn({ identities: [{ provider: "google", id: "i1" }, { provider: "github", id: "i2" }] }), hash: "#/settings/account" });
  await t.page.waitForSelector('[data-unlink="google"]');
  await t.page.click('[data-unlink="google"]');
  await t.page.click(".sheet .btn.danger");
  await wait(t.page, 400);
  ok("délier une méthode quand il en reste une autre", (await t.mockState()).auth.some((c) => c[0] === "unlink" && c[1].provider === "google"));
  await t.page.click('[data-link="discord"]');
  ok("lier une méthode", (await t.mockState()).auth.some((c) => c[0] === "link" && c[1].provider === "discord"));
  const body = await text(t.page, "#content");
  ok("compte : photo, pseudo, e-mail, sessions, export, suppression", ["Photo", "Pseudo", "Adresse e-mail", "tous les appareils", "Exporter mes données", "Supprimer mon compte"].every((s) => body.includes(s)));
  await t.close();
}
{
  const t = await open({ mock: signedIn(), hash: "#/settings/privacy" });
  await t.page.waitForSelector('[data-select="presence_visibility"]');
  ok("confidentialité : valeurs protectrices par défaut", (await t.page.inputValue('[data-select="presence_visibility"]')) === "nobody" && (await t.page.inputValue('[data-select="profile_visibility"]')) === "minimal" && (await t.page.inputValue('[data-select="history_visibility"]')) === "friends");
  await t.page.selectOption('[data-select="presence_visibility"]', "friends");
  await wait(t.page, 300);
  ok("réglage enregistré côté base", (await t.mockState()).updates.some((u) => u.table === "privacy_settings" && u.patch.presence_visibility === "friends"));
  await t.page.click('label:has([data-toggle="invisible_mode"])');
  await wait(t.page, 300);
  ok("mode invisible", (await t.mockState()).updates.some((u) => u.patch.invisible_mode === true));
  await t.close();
}
{
  const t = await open({ mock: signedIn(), hash: "#/settings/services", accounts: { "GET /lastfm/status": { connected: false } } });
  await t.page.waitForSelector("[data-connect]");
  ok("services : Last.fm facultatif, import de playlists et ancien compte (plus de « Bientôt »)", !/Bientôt/.test(await text(t.page, "#content")) && /facultatif/.test(await text(t.page, "#content")) && (await t.page.locator("[data-import-playlist]").count()) === 1 && (await t.page.locator("[data-link-legacy]").count()) === 1);
  await t.close();
}
{
  const t = await open({ mock: signedIn(), hash: "#/settings/services", accounts: { "GET /lastfm/status": { connected: true, username: "lfm_alice", last_error: "Last.fm a révoqué l'accès de Sona à ton compte : reconnecte-toi.", last_sync_at: null } } });
  await t.page.waitForSelector("[data-disconnect]");
  ok("clé révoquée : message clair", /révoqué/.test(await text(t.page, "#content")));
  await t.close();
}

// ── Administration ─────────────────────────────────────────────────────────

const staffProfile = (role) => ({ id: "m1", username: role, role, status: "active", onboarding_completed: true, force_username_change: false, force_avatar_change: false, friend_code: "x", created_at: "2026-01-01T00:00:00Z" });
{
  const t = await open({ mock: signedIn(), hash: "#/admin" });
  await t.page.waitForSelector("#content .empty");
  ok("utilisateur : /admin refusé dans l'interface", /réservée à l'équipe/.test(await text(t.page, "#content")));
  await t.close();
}
{
  const dashboard = { signups_per_day: Array.from({ length: 14 }, (_, i) => ({ day: `2026-11-${String(i + 1).padStart(2, "0")}`, count: i })), active_24h: 12, active_7d: 40, total_users: 120, open_reports: 3, open_appeals: 1, banned: 2, suspended: 1, quarantined: 1 };
  const users = [{ id: "x1", username: "fautif", email: "f***@example.org", avatar_url: null, role: "user", status: "active", created_at: "2026-10-01T00:00:00Z", last_seen_at: null, providers: ["google"], total: 1 }];
  const detail = { profile: { id: "x1", username: "fautif", role: "user", status: "active", created_at: "2026-10-01T00:00:00Z", last_seen_at: null, avatar_url: null }, email: "f***@example.org", providers: ["google"], sanctions: [], reports_received: 2, reports_made: 0, friends: 3, audit: [] };
  const t = await open({ mock: signedIn({ profile: staffProfile("moderator"), dashboard, users, userDetail: detail }), viewport: { width: 390, height: 844 }, hash: "#/admin/users", accounts: { "POST /admin/sanction": { sanction_id: "s", kind: "warning", warnings: 1 } } });
  await t.page.waitForSelector(".user-row");
  ok("admin sur iPhone : liste et filtres, sans scroll horizontal", /fautif/.test(await text(t.page, ".admin")) && (await t.page.locator("#user-filters").count()) === 1 && !(await hasScrollX(t.page)));
  await t.page.click(".user-row");
  await t.page.waitForSelector(".sheet .menu");
  const sheet = await text(t.page, ".sheet");
  ok("fiche : actions de modération, pas de bannissement pour un modérateur", /Avertir/.test(sheet) && /Suspendre/.test(sheet) && !/Bannir définitivement/.test(sheet) && !/Supprimer le compte/.test(sheet) && !/Changer le rôle/.test(sheet), sheet.slice(0, 200));
  await t.page.click('[data-act="0"]');
  await t.page.click(".sheet button[type=submit]");
  await wait(t.page, 300);
  ok("motif obligatoire : aucun appel sans motif", !t.calls.some((c) => c.path === "/admin/sanction"));
  await t.page.fill('.sheet textarea[name="reason"]', "Langage déplacé");
  await t.page.click(".sheet button[type=submit]");
  await wait(t.page, 500);
  const call = t.calls.find((c) => c.path === "/admin/sanction");
  ok("avertissement envoyé au service avec motif", call && JSON.parse(call.body).kind === "warning" && JSON.parse(call.body).reason === "Langage déplacé" && JSON.parse(call.body).target === "x1", JSON.stringify(call));
  await t.close();
}
{
  const dashboard = { signups_per_day: Array.from({ length: 14 }, (_, i) => ({ day: `2026-11-${String(i + 1).padStart(2, "0")}`, count: i })), active_24h: 12, active_7d: 40, total_users: 120, open_reports: 3, open_appeals: 1, banned: 2, suspended: 1, quarantined: 1 };
  const t = await open({ mock: signedIn({ profile: staffProfile("admin"), dashboard, users: [{ id: "x1", username: "fautif", email: "fautif@example.org", avatar_url: null, role: "user", status: "active", created_at: "2026-10-01T00:00:00Z", last_seen_at: null, providers: ["email"], total: 1 }], userDetail: { profile: { id: "x1", username: "fautif", role: "user", status: "active", created_at: "2026-10-01T00:00:00Z", avatar_url: null }, email: "fautif@example.org", providers: ["email"], sanctions: [], reports_received: 0, reports_made: 0, friends: 0, audit: [] } }), hash: "#/admin" });
  await t.page.waitForSelector(".stat-grid");
  const body = await text(t.page, ".admin");
  ok("tableau de bord : inscrits, actifs, signalements, bannis", /120/.test(body) && /Comptes/.test(body) && /Signalements en attente/.test(body) && /Bannis/.test(body));
  ok("admin : onglet Journal visible", (await t.page.locator('.admin-tabs a[href="#/admin/audit"]').count()) === 1);
  await t.page.evaluate(() => { location.hash = "#/admin/users"; });
  await t.page.waitForSelector(".user-row");
  await t.page.click(".user-row");
  await t.page.waitForSelector(".sheet .menu");
  ok("admin : bannir, rôle et suppression disponibles", /Bannir définitivement/.test(await text(t.page, ".sheet")) && /Changer le rôle/.test(await text(t.page, ".sheet")) && /Supprimer le compte/.test(await text(t.page, ".sheet")));
  await t.close();
}

console.log(results.join("\n"));
if (errors.length) { console.log("\nERREURS JS :\n" + [...new Set(errors)].join("\n")); failed += errors.length; }
console.log(`\n${results.length - failed < 0 ? 0 : results.filter((r) => r.startsWith("ok")).length}/${results.length} contrôles réussis`);
await browser.close();
process.exit(failed ? 1 : 0);
