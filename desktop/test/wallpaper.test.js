const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { CoverWallpaper, setScript } = require("../src/wallpaper");

test("le chemin du fond d'écran est bien protégé pour PowerShell", () => {
  assert.match(setScript("C:\\Users\\l'ami\\fond.jpg"), /'C:\\Users\\l''ami\\fond\.jpg'/);
});

test("pose la pochette floue, puis remet le fond d'écran d'avant", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "sona-wall-"));
  const store = { wallpaperOriginal: "C:\\Windows\\Web\\fond.jpg" };
  const settings = { get: (k) => store[k], set: (k, v) => (store[k] = v) };
  const fakeImage = { isEmpty: () => false, resize: () => fakeImage, toBitmap: () => Buffer.alloc(16, 200), toJPEG: () => Buffer.from("jpg") };
  const nativeImage = { createFromBuffer: () => fakeImage, createFromBitmap: () => fakeImage };
  const scripts = [];
  const wall = new CoverWallpaper({ dir, settings, nativeImage, fetchImage: async () => Buffer.from("x"), screenSize: () => ({ width: 2, height: 2 }), run: async (s) => scripts.push(s) });
  await wall.setEnabled(true, "win32");
  await wall.apply("https://cdn/images/cover/abc/250x250-000000-80-0-0.jpg");
  assert.equal(scripts.length, 1);
  assert.match(scripts[0], /fond-sona-a\.jpg/);
  assert.ok(fs.existsSync(path.join(dir, "fond-sona-a.jpg")));
  await wall.apply("https://cdn/images/cover/abc/250x250-000000-80-0-0.jpg");
  assert.equal(scripts.length, 1, "même pochette : rien de refait");
  await wall.setEnabled(false, "win32");
  assert.match(scripts[1], /C:\\Windows\\Web\\fond\.jpg/);
  assert.equal(store.wallpaperOriginal, null);
});
