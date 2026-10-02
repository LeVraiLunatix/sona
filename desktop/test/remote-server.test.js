/* Télécommande du réseau local : association, réseau local seulement,
   commandes relayées à Sona, état en direct. Sans Electron (node --test). */

const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { RemoteServer, isLocalAddress, phoneName } = require("../src/remote-server");

const KEY = "cle-de-test-0123456789";

async function withServer(fn, { command = async () => true } = {}) {
  const seen = [];
  const clients = [];
  const server = new RemoteServer({
    getState: () => ({ track: { title: "Titre", artist: "Artiste" }, paused: false }),
    command: async (body) => { seen.push(body); return command(body); },
    onClients: (list) => clients.push(list.length),
    remoteRoot: path.join(__dirname, "..", "remote"),
    iconsRoot: path.join(__dirname, "..", "..", "web", "icons"),
  });
  assert.equal(await server.start(0, KEY), true);
  try {
    await fn(`http://127.0.0.1:${server.port}`, { server, seen, clients });
  } finally {
    await server.stop();
  }
}

test("adresses du réseau local acceptées, Internet refusé", () => {
  for (const ok of ["127.0.0.1", "::1", "::ffff:192.168.1.20", "10.0.0.4", "172.16.3.2", "172.31.255.1", "100.101.102.103", "fe80::1", "fd12::3"]) {
    assert.equal(isLocalAddress(ok), true, ok);
  }
  for (const bad of ["8.8.8.8", "172.32.0.1", "100.128.0.1", "2a01:cb00::1", "", undefined]) {
    assert.equal(isLocalAddress(bad), false, String(bad));
  }
});

test("nom du téléphone d'après le navigateur", () => {
  assert.equal(phoneName("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)"), "iPhone");
  assert.equal(phoneName("Mozilla/5.0 (Linux; Android 15) Mobile Safari"), "Téléphone Android");
});

test("la page est publique, l'état demande la clé", () => withServer(async (base) => {
  const page = await fetch(`${base}/`);
  assert.equal(page.status, 200);
  assert.match(await page.text(), /Sona Remote/);
  assert.equal((await fetch(`${base}/api/state`)).status, 401);
  assert.equal((await fetch(`${base}/api/state`, { headers: { "X-Sona-Key": "mauvaise" } })).status, 401);
  const state = await fetch(`${base}/api/state`, { headers: { "X-Sona-Key": KEY } });
  assert.equal(state.status, 200);
  assert.equal((await state.json()).track.title, "Titre");
  // Rien d'autre du disque n'est servi.
  assert.equal((await fetch(`${base}/../src/main.js`)).status, 404);
  assert.equal((await fetch(`${base}/icons/../../package.json`)).status, 404);
}));

test("les commandes passent à Sona et renvoient sa réponse", () => withServer(async (base, { seen }) => {
  const res = await fetch(`${base}/api/command`, {
    method: "POST", headers: { "X-Sona-Key": KEY, "Content-Type": "application/json" },
    body: JSON.stringify({ action: "search", query: "daft punk" }),
  });
  assert.equal(res.status, 200);
  assert.deepEqual(await res.json(), { ok: true, result: [{ title: "Get Lucky" }] });
  assert.deepEqual(seen, [{ action: "search", query: "daft punk" }]);
  const bad = await fetch(`${base}/api/command`, { method: "POST", headers: { "X-Sona-Key": KEY }, body: "pas du json" });
  assert.equal(bad.status, 400);
}, { command: async (body) => (body.action === "search" ? [{ title: "Get Lucky" }] : true) }));

test("l'état arrive en direct, et une nouvelle clé déconnecte le téléphone", () => withServer(async (base, { server, clients }) => {
  const controller = new AbortController();
  const res = await fetch(`${base}/api/events?k=${KEY}`, { signal: controller.signal });
  assert.equal(res.status, 200);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let text = "";
  while (!text.includes("event: state")) text += decoder.decode((await reader.read()).value);
  assert.match(text, /"title":"Titre"/);
  assert.equal(clients.at(-1), 1);
  server.broadcast({ track: { title: "Suivant" } });
  while (!text.includes("Suivant")) text += decoder.decode((await reader.read()).value);
  server.setKey("nouvelle-cle-0123456789");
  const { done } = await reader.read().then(async (r) => (r.done ? r : reader.read()));
  assert.equal(done, true);
  assert.equal(clients.at(-1), 0);
  assert.equal((await fetch(`${base}/api/state`, { headers: { "X-Sona-Key": KEY } })).status, 401);
  controller.abort();
}));
