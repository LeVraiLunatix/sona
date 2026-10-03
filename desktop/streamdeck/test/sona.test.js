/* Le client du plugin contre le vrai serveur de télécommande de l'app
   (desktop/src/remote-server.js) : découverte, état en direct, commandes. */

import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import path from "node:path";
import fs from "node:fs";
import os from "node:os";
import { SonaClient, readSonaSettings } from "../src/sona.js";

const require = createRequire(import.meta.url);
const { RemoteServer } = require("../../src/remote-server.js");
const here = path.dirname(new URL(import.meta.url).pathname);

const until = async (fn, ms = 3000) => {
  const end = Date.now() + ms;
  while (Date.now() < end) { if (fn()) return true; await new Promise((r) => setTimeout(r, 20)); }
  return false;
};

test("les réglages de Sona donnent la clé et le port", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "sona-sd-"));
  const file = path.join(dir, "settings.json");
  fs.writeFileSync(file, JSON.stringify({ remoteKey: "k", remotePort: 7651, remoteEnabled: false }));
  assert.deepEqual(readSonaSettings(file), { key: "k", port: 7651, activePort: null, enabled: false });
  fs.writeFileSync(file, JSON.stringify({ remoteKey: "k", remotePort: 7650, remoteActivePort: 7663 }));
  assert.equal(readSonaSettings(file).activePort, 7663);
  assert.equal(readSonaSettings(path.join(dir, "absent.json")), null);
});

test("le plugin trouve Sona, suit la lecture et envoie les commandes", async () => {
  let state = { track: { title: "Titre", artist: "Artiste" }, paused: false, volume: 0.5, liked: false };
  const seen = [];
  const server = new RemoteServer({
    getState: () => state,
    command: async (body) => { seen.push(body); return true; },
    remoteRoot: path.join(here, "..", "..", "remote"),
    iconsRoot: path.join(here, "..", "..", "..", "web", "icons"),
  });
  await server.start(0, "cle-0123456789");
  const statuses = [];
  const client = new SonaClient({ settings: () => ({ key: "cle-0123456789", port: server.port, enabled: true }), retry: 50 });
  client.on("status", (s) => statuses.push(s));
  client.start();
  try {
    assert.ok(await until(() => client.status === "online" && client.state?.track?.title === "Titre"));
    await client.command("volume", { volume: 0.7 });
    assert.deepEqual(seen, [{ action: "volume", volume: 0.7 }]);
    state = { ...state, paused: true, liked: true };
    server.broadcast(state);
    assert.ok(await until(() => client.state.paused && client.state.liked));
    // Sona fermé : le plugin le voit, puis retrouve Sona quand il revient.
    await server.stop();
    assert.ok(await until(() => client.status === "offline"));
    await assert.rejects(client.command("toggle"), /pas ouvert/);
  } finally {
    client.stop();
    await server.stop();
  }
  assert.deepEqual(statuses.slice(0, 2), ["online", "offline"]);
});

test("sans clé lisible, le plugin pilote quand même Sona sur ce PC", async () => {
  const seen = [];
  const server = new RemoteServer({
    getState: () => ({ track: { title: "Titre" }, paused: false }),
    command: async (body) => { seen.push(body); return true; },
    remoteRoot: path.join(here, "..", "..", "remote"),
    iconsRoot: path.join(here, "..", "..", "..", "web", "icons"),
  });
  await server.start(0, "cle-inconnue-du-plugin");
  // Réglages illisibles, mais Sona a noté son vrai port.
  const client = new SonaClient({ settings: () => ({ key: "", port: 1, activePort: server.port, enabled: true, unreadable: "EPERM" }), retry: 50 });
  client.start();
  try {
    assert.ok(await until(() => client.status === "online"));
    await client.command("toggle");
    assert.deepEqual(seen, [{ action: "toggle" }]);
  } finally {
    client.stop();
    await server.stop();
  }
});

test("télécommande coupée ou Sona absent : état clair", async () => {
  const off = new SonaClient({ settings: () => ({ key: "k", port: 1, enabled: false }) });
  await off.connect();
  assert.equal(off.status, "off");
  const absent = new SonaClient({ settings: () => null });
  await absent.connect();
  assert.equal(absent.status, "absent");
});
