/* Discord Rich Presence contre un faux client Discord (même protocole :
   trames [op][longueur][JSON] sur un socket local). */

const test = require("node:test");
const assert = require("node:assert/strict");
const net = require("node:net");
const os = require("node:os");
const path = require("node:path");
const fs = require("node:fs");
const { DiscordPresence, activityFor, encode, OP } = require("../src/discord");

function fakeDiscord(file) {
  const frames = [];
  const server = net.createServer((socket) => {
    let buffer = Buffer.alloc(0);
    socket.on("data", (chunk) => {
      buffer = Buffer.concat([buffer, chunk]);
      while (buffer.length >= 8) {
        const op = buffer.readInt32LE(0);
        const len = buffer.readInt32LE(4);
        if (buffer.length < 8 + len) return;
        const msg = JSON.parse(buffer.subarray(8, 8 + len).toString());
        buffer = buffer.subarray(8 + len);
        frames.push({ op, msg });
        if (op === OP.HANDSHAKE) socket.write(encode(OP.FRAME, { cmd: "DISPATCH", evt: "READY", data: { v: 1 } }));
      }
    });
  });
  return new Promise((resolve) => server.listen(file, () => resolve({ server, frames })));
}

const until = async (fn, ms = 2000) => {
  const end = Date.now() + ms;
  while (Date.now() < end) { if (fn()) return true; await new Promise((r) => setTimeout(r, 20)); }
  return false;
};

test("l'activité montre le titre, l'artiste, la pochette et la progression", () => {
  const a = activityFor({ track: { title: "Onizuka", artist: "PNL", cover_url: "https://e-cdns/1.jpg", duration_seconds: 200 }, position: 50, paused: false }, 1_000_000);
  assert.equal(a.type, 2);
  assert.equal(a.details, "Onizuka");
  assert.equal(a.state, "PNL");
  assert.equal(a.assets.large_image, "https://e-cdns/1.jpg");
  assert.deepEqual(a.timestamps, { start: 950_000, end: 1_150_000 });
  const paused = activityFor({ track: { title: "T", artist: "A" }, paused: true });
  assert.equal(paused.state, "A · en pause");
  assert.equal(paused.timestamps, undefined);
  assert.equal(activityFor({ track: null }), null);
});

test("se connecte à Discord, s'annonce et envoie l'activité seulement quand elle change", async (t) => {
  if (process.platform === "win32") return t.skip("socket Unix");
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "sona-discord-"));
  const file = path.join(dir, "discord-ipc-0");
  const { server, frames } = await fakeDiscord(file);
  const presence = new DiscordPresence({ connectTo: () => file, retry: 100 });
  presence.configure(true, "123456789012345678");
  try {
    assert.ok(await until(() => presence.status().connected));
    assert.deepEqual(frames[0], { op: OP.HANDSHAKE, msg: { v: 1, client_id: "123456789012345678" } });
    const state = { track: { title: "Onizuka", artist: "PNL", duration_seconds: 200 }, position: 10, paused: false };
    presence.update(state);
    presence.update({ ...state, position: 10.5 }); // même chose, à peine plus loin : rien de renvoyé
    assert.ok(await until(() => frames.length === 2));
    await new Promise((r) => setTimeout(r, 100));
    assert.equal(frames.length, 2);
    assert.equal(frames[1].msg.cmd, "SET_ACTIVITY");
    assert.equal(frames[1].msg.args.activity.details, "Onizuka");
    presence.update({ ...state, paused: true });
    assert.ok(await until(() => frames.length === 3));
    assert.equal(frames[2].msg.args.activity.state, "PNL · en pause");
    presence.update({ track: null });
    assert.ok(await until(() => frames.length === 4));
    assert.equal(frames[3].msg.args.activity, undefined);
  } finally {
    presence.configure(false, "");
    server.close();
  }
  assert.equal(presence.status().connected, false);
});

test("identifiant invalide ou Discord fermé : erreur claire", async () => {
  const presence = new DiscordPresence({ connectTo: () => path.join(os.tmpdir(), "absent-discord-ipc"), retry: 50 });
  presence.configure(true, "pas-un-id");
  assert.match(presence.status().error, /Identifiant/);
  presence.configure(true, "123456789012345678");
  assert.ok(await until(() => /pas ouvert/.test(presence.status().error || "")));
  presence.configure(false, "");
});
