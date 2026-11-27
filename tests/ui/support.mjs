// Outils communs des tests d'interface : serveur statique de web/, faux Supabase
// (injecté à la place de vendor/supabase.js), faux serveur de musique et de comptes.
import { createServer } from "node:http";
import { readFileSync, existsSync } from "node:fs";
import { dirname, extname, join } from "node:path";
import { fileURLToPath } from "node:url";

export const WEB = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "web");
const types = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".png": "image/png", ".svg": "image/svg+xml", ".webmanifest": "application/json" };

/** Faux client Supabase : tout l'état vit dans `window.__mock` (réglé par chaque test). */
const MOCK_SUPABASE = `
(() => {
  const M = (window.__mock = window.__mock || {});
  const defaults = {
    session: null, listeners: [], rpcCalls: [], authCalls: [], updates: [], failNext: null,
    profile: { id: "u1", username: "alice", display_name: null, avatar_url: null, bio: null, role: "user", status: "active",
      status_reason: null, status_until: null, onboarding_completed: true, force_username_change: false, force_avatar_change: false,
      friend_code: "abc123def456", created_at: "2026-01-01T00:00:00Z", last_seen_at: null },
    privacy: { profile_visibility: "minimal", who_can_request: "everyone", presence_visibility: "nobody", history_visibility: "friends", stats_visibility: "friends", playlists_visibility: "friends", invisible_mode: false, do_not_disturb: false },
    settings: { theme: "system", audio_quality: "best", car_mode_auto: false, scrobbling_enabled: true },
    identities: [{ provider: "email", id: "i1" }], passkeys: [], sanctions: [], notifications: [], services: [], appeals: [],
    friends: [], requests: [], blocked: [], takenUsernames: ["bob", "admin"], reports: [], alerts: [], audit: [], users: [], dashboard: null,
  };
  for (const k in defaults) if (!(k in M)) M[k] = defaults[k];
  const user = () => (M.session ? { id: M.profile.id, email: M.email === undefined ? "alice@example.org" : M.email, is_anonymous: !!M.anonymous } : null);
  const sess = () => (M.session ? { access_token: "jwt-test", user: user() } : null);
  const emit = (event) => M.listeners.forEach((fn) => fn(event, sess()));
  const ok = (data) => Promise.resolve({ data, error: null });
  const fail = (message, code) => Promise.resolve({ data: null, error: { message, code } });
  const gate = (name, args) => { M.authCalls.push([name, args]); if (M.failNext && M.failNext.name === name) { const f = M.failNext; M.failNext = null; return fail(f.message, f.code); } return null; };

  const auth = {
    onAuthStateChange(fn) { M.listeners.push(fn); return { data: { subscription: { unsubscribe() {} } } }; },
    getSession: () => ok({ session: sess() }),
    getUserIdentities: () => ok({ identities: M.identities }),
    signInWithPassword: async (a) => { const g = gate("signIn", a); if (g) return g; if (a.password === "wrong") return fail("Invalid login credentials"); M.session = true; emit("SIGNED_IN"); return { data: { session: sess() }, error: null }; },
    signUp: async (a) => { const g = gate("signUp", a); if (g) return g; M.pendingEmail = a.email; M.profile.onboarding_completed = false; return { data: { session: null, user: { id: "u1" } }, error: null }; },
    signInWithOtp: async (a) => { const g = gate("otp", a); if (g) return g; M.pendingEmail = a.email; return { data: {}, error: null }; },
    verifyOtp: async (a) => { const g = gate("verify", a); if (g) return g; if (a.token === "000000") return fail("Token has expired or is invalid"); if (a.type === "recovery") { M.session = true; return { data: { session: sess() }, error: null }; } M.session = true; emit("SIGNED_IN"); return { data: { session: sess() }, error: null }; },
    signInWithOAuth: async (a) => { M.authCalls.push(["oauth", a]); return { data: { url: "https://example.org/oauth" }, error: null }; },
    linkIdentity: async (a) => { M.authCalls.push(["link", a]); return { data: { url: "x" }, error: null }; },
    unlinkIdentity: async (i) => { M.authCalls.push(["unlink", i]); M.identities = M.identities.filter((x) => x.provider !== i.provider); return { data: {}, error: null }; },
    signInAnonymously: async (a) => { M.authCalls.push(["guest", a]); M.session = true; M.anonymous = true; M.email = null; emit("SIGNED_IN"); return { data: { session: sess() }, error: null }; },
    updateUser: async (a) => { const g = gate("updateUser", a); if (g) return g; return { data: { user: user() }, error: null }; },
    resetPasswordForEmail: async (e) => { M.authCalls.push(["reset", e]); return { data: {}, error: null }; },
    resend: async (a) => { M.authCalls.push(["resend", a]); return { data: {}, error: null }; },
    exchangeCodeForSession: async (c) => { M.authCalls.push(["exchange", c]); M.session = true; emit("SIGNED_IN"); return { data: { session: sess() }, error: null }; },
    signOut: async (o) => { M.authCalls.push(["signOut", o]); M.session = null; emit("SIGNED_OUT"); return { error: null }; },
  };

  function builder(table) {
    const q = { table, op: "select", filters: {}, patch: null, single: false };
    const run = () => {
      if (q.op === "update") {
        M.updates.push({ table, patch: q.patch });
        if (M.updateError) return fail(M.updateError.message, M.updateError.code);
        if (table === "profiles") { if ("username" in q.patch && M.takenUsernames.includes(q.patch.username)) return fail("username_taken"); Object.assign(M.profile, q.patch); return ok([M.profile]); }
        if (table === "privacy_settings") { Object.assign(M.privacy, q.patch); return ok([M.privacy]); }
        if (table === "user_settings") { Object.assign(M.settings, q.patch); return ok([M.settings]); }
        return ok([{}]);
      }
      if (q.op === "delete") { if (table === "passkey_credentials") M.passkeys = M.passkeys.filter((p) => p.id !== q.filters.id); return ok(null); }
      const rows = {
        profiles: [M.profile], privacy_settings: [M.privacy], user_settings: [M.settings], sanctions: M.sanctions, notifications: M.notifications,
        connected_services: M.services, passkey_credentials: M.passkeys, appeals: M.appeals, reports: M.reports, admin_alerts: M.alerts, audit_log: M.audit, report_notes: [],
      }[table] || [];
      return ok(q.single ? rows[0] : rows).then((r) => (table === "appeals" && q.filters.sanction_id ? { data: rows, error: null } : r));
    };
    const api = {
      select() { return api; }, eq(k, v) { q.filters[k] = v; return api; }, in() { return api; }, order() { return api; }, limit() { return api; },
      single() { q.single = true; return api; }, update(p) { q.op = "update"; q.patch = p; return api; }, delete() { q.op = "delete"; return api; },
      then(res, rej) { return run().then(res, rej); },
    };
    return api;
  }

  const rpc = async (name, args) => {
    M.rpcCalls.push([name, args]);
    if (M.failRpc && M.failRpc.name === name) { const f = M.failRpc; M.failRpc = null; return fail(f.message, f.code); }
    switch (name) {
      case "username_available": { const n = String(args.p_name); if (!/^[A-Za-z0-9_.-]{3,20}$/.test(n)) return ok({ available: false, reason: "format" }); if (M.takenUsernames.includes(n.toLowerCase())) return ok({ available: false, reason: "taken" }); return ok({ available: true }); }
      case "list_friends": return ok(M.friends);
      case "list_friend_requests": return ok(M.requests);
      case "list_blocked": return ok(M.blocked);
      case "send_friend_request": case "redeem_friend_code": case "respond_friend_request": case "cancel_friend_request": case "remove_friend": case "block_user": case "unblock_user": case "create_report": case "create_appeal": return ok(name === "send_friend_request" ? "ok" : null);
      case "rotate_friend_code": return ok("newcode000000");
      case "get_profile": return ok({ id: args.p_user, username: "bob", avatar_url: null });
      case "admin_dashboard": return ok(M.dashboard);
      case "admin_list_users": return ok(M.users);
      case "admin_user_detail": return ok(M.userDetail);
      default: return ok(null);
    }
  };

  const storage = { from: () => ({ upload: async () => ({ error: null }), getPublicUrl: (p) => ({ data: { publicUrl: "https://cdn.example/avatars/" + p } }) }) };
  window.supabase = { createClient: () => ({ auth, from: builder, rpc, storage }) };
})();
`;

export const METAS = { "sona-supabase-url": "https://abcdefgh.supabase.co", "sona-supabase-key": "anon-key-anon-key-anon-key-anon", "sona-accounts": "http://accounts.test" };

export function startServer({ configured = true } = {}) {
  const server = createServer((req, res) => {
    let p = req.url.split("?")[0].replace(/^\/web/, "") || "/";
    if (p === "/vendor/supabase.js") { res.writeHead(200, { "Content-Type": "text/javascript" }); return res.end(MOCK_SUPABASE); }
    const file = join(WEB, p === "/" ? "index.html" : p);
    if (!existsSync(file)) { res.writeHead(404); return res.end("{}"); }
    let body = readFileSync(file);
    if (file.endsWith("index.html")) {
      let html = body.toString();
      if (configured) for (const [name, value] of Object.entries(METAS)) html = html.replace(new RegExp(`(<meta name="${name}" content=")[^"]*`), `$1${value}`);
      body = Buffer.from(html);
    }
    res.writeHead(200, { "Content-Type": types[extname(file)] || "text/plain" });
    res.end(body);
  }).listen(0);
  return { server, port: server.address().port, close: () => server.close() };
}

/** Routes réseau communes : tout ce qui n'est pas web/ est un faux serveur. */
export async function routeApi(ctx, { music = {}, accounts = {}, calls = [] } = {}) {
  await ctx.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    const method = route.request().method();
    if (url.hostname === "accounts.test") {
      calls.push({ host: "accounts", method, path: url.pathname, body: route.request().postData() });
      const handler = accounts[`${method} ${url.pathname}`];
      if (handler) return route.fulfill({ status: handler.status || 200, json: handler.json ?? handler, headers: { "access-control-allow-origin": "*" } });
      return route.fulfill({ status: 404, json: { error: "not_found", message: "inconnu" }, headers: { "access-control-allow-origin": "*" } });
    }
    if (url.hostname !== "localhost" && url.hostname !== "127.0.0.1") return route.fulfill({ status: 200, body: "" });
    if (url.pathname.startsWith("/web") || url.pathname === "/" || url.pathname.startsWith("/vendor") || /\.(js|css|png|svg|webmanifest|ico|woff2)$/.test(url.pathname)) return route.continue();
    calls.push({ host: "music", method, path: url.pathname });
    const key = `${method} ${url.pathname}`;
    const hit = music[key] ?? music[url.pathname];
    if (hit !== undefined) return route.fulfill({ status: hit.__status || 200, json: hit.__json ?? hit });
    const defaults = { "/settings": { autoplay: true, quality: "best" }, "/health": { version: "x", streaming: "ok" }, "/me/playlists": [], "/smart": [], "/friends": [], "/party/active": [], "/connect/devices": { devices: [], session: null } };
    if (defaults[url.pathname]) return route.fulfill({ json: defaults[url.pathname] });
    if (/^\/library\//.test(url.pathname)) return route.fulfill({ json: { items: [], total: 0 } });
    return route.fulfill({ status: 404, json: { detail: "nope" } });
  });
}
