/* Mode jeu : l'état de Windows (SHQueryUserNotificationState), lu ligne à
   ligne, allume et éteint le mode — ici avec un faux PowerShell. */

const test = require("node:test");
const assert = require("node:assert/strict");
const { spawn } = require("node:child_process");
const { GameMode } = require("../src/gamemode");

const fakeWindows = (states) => () => spawn(process.execPath, ["-e", `
  const states = ${JSON.stringify(states)};
  let i = 0;
  const t = setInterval(() => { if (i >= states.length) { clearInterval(t); return; } process.stdout.write(states[i++] + "\\n"); }, 30);
`], { stdio: ["ignore", "pipe", "ignore"] });

test("plein écran : mode jeu ; retour au bureau : mode normal", async () => {
  const changes = [];
  const mode = new GameMode({ onChange: (on) => changes.push(on), launch: fakeWindows([5, 3, 3, 5, 2, 5]) });
  mode.setEnabled(true, "win32");
  await new Promise((r) => setTimeout(r, 600));
  mode.setEnabled(false, "win32");
  assert.deepEqual(changes, [true, false, true, false]);
});

test("ailleurs que sous Windows, ou désactivé : rien ne tourne", () => {
  let launched = 0;
  const mode = new GameMode({ launch: () => { launched++; return spawn(process.execPath, ["-e", ""]); } });
  mode.setEnabled(true, "linux");
  mode.setEnabled(false, "win32");
  assert.equal(launched, 0);
  assert.equal(mode.active, false);
});
