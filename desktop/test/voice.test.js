const test = require("node:test");
const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const { PassThrough } = require("node:stream");
const { VoiceControl, interpret } = require("../src/voice");

test("comprend les commandes et les demandes de titres", () => {
  assert.deepEqual(interpret("Sona suivant"), { action: "next" });
  assert.deepEqual(interpret("Sona, pause."), { action: "pause" });
  assert.deepEqual(interpret("Sona plus fort"), { action: "volumeStep", step: 0.08 });
  assert.deepEqual(interpret("Sona j’aime"), { action: "like" });
  assert.deepEqual(interpret("Sona mets du PNL"), { action: "voiceSearch", query: "PNL" });
  assert.deepEqual(interpret("Sona joue Bleu Nuit de Nova"), { action: "voiceSearch", query: "Bleu Nuit de Nova" });
  assert.equal(interpret("Sona bonjour"), null);
  assert.equal(interpret("Sona mets"), null);
});

test("relaie ce qui est entendu et l'état", async () => {
  const out = new PassThrough();
  const child = Object.assign(new EventEmitter(), { stdout: out, kill() {} });
  const commands = [];
  const states = [];
  const voice = new VoiceControl({ onCommand: (c) => commands.push(c), onStatus: (s) => states.push(s), launch: () => child });
  voice.setEnabled(true, "win32");
  out.write("READY fr-FR\nHEARD Sona suivant\nHEARD Sona n'importe quoi\n");
  await new Promise((r) => setTimeout(r, 30));
  assert.deepEqual(commands, [{ action: "next" }]);
  assert.equal(voice.status.ready, true);
  assert.equal(voice.status.culture, "fr-FR");
  voice.setEnabled(false);
  assert.equal(states.at(-1).ready, false);
});

test("voix française absente : message clair, pas de relance", async () => {
  const out = new PassThrough();
  const child = Object.assign(new EventEmitter(), { stdout: out, kill() {} });
  const voice = new VoiceControl({ launch: () => child });
  voice.setEnabled(true, "win32");
  out.write("ERR nofr\n");
  await new Promise((r) => setTimeout(r, 30));
  assert.match(voice.status.error, /française/);
  child.emit("exit");
  assert.equal(voice.timer, undefined);
  voice.setEnabled(false);
});
