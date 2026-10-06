const test = require("node:test");
const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const { PassThrough } = require("node:stream");
const { MicWatch, parseLine } = require("../src/micwatch");

test("lit les apps qui ont le micro, sans compter Sona", () => {
  assert.deepEqual(parseLine("MIC "), []);
  assert.deepEqual(parseLine("MIC C:#Users#moi#AppData#Local#Discord#app-1.0.9#Discord.exe"), ["Discord"]);
  assert.deepEqual(parseLine("MIC C:#Program Files#Sona#Sona.exe|Microsoft.SkypeApp_kzf8qxf38zg5c"), ["SkypeApp"]);
  assert.equal(parseLine("autre chose"), null);
});

test("prévient quand un appel commence et finit", (t) => {
  const out = new PassThrough();
  const child = Object.assign(new EventEmitter(), { stdout: out, kill() {} });
  const seen = [];
  const watch = new MicWatch({ onChange: (s) => seen.push(s), launch: () => child });
  watch.setEnabled(true, "win32");
  out.write("MIC \nMIC C:#x#Discord.exe\nMIC C:#x#Discord.exe\n");
  out.write("MIC \n");
  return new Promise((resolve) => setTimeout(() => {
    assert.deepEqual(seen, [{ inUse: true, apps: ["Discord"] }, { inUse: false, apps: [] }]);
    watch.setEnabled(false);
    resolve();
  }, 30));
});
