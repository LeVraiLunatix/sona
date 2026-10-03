/* Mode jeu : quand un jeu (ou toute app) passe en plein écran sous Windows,
   Sona se fait discret — plus de notifications, paroles en surimpression
   plus petites et plus transparentes — puis redevient normal après.

   Windows le dit lui-même (SHQueryUserNotificationState, la fonction qui
   coupe ses propres notifications en jeu) : un petit PowerShell la relève
   toutes les 5 s, sans module natif à compiler. */

const { spawn } = require("node:child_process");

// États de SHQueryUserNotificationState où l'on se fait discret :
// 2 appli plein écran, 3 jeu Direct3D plein écran, 4 présentation, 7 appli du Store plein écran.
const QUIET_STATES = new Set([2, 3, 4, 7]);

const SCRIPT = `
Add-Type -Namespace SonaWin -Name Notif -MemberDefinition '[DllImport("shell32.dll")] public static extern int SHQueryUserNotificationState(out int state);'
while ($true) {
  $s = 0
  [void][SonaWin.Notif]::SHQueryUserNotificationState([ref]$s)
  [Console]::Out.WriteLine($s)
  [Console]::Out.Flush()
  Start-Sleep -Seconds 5
}`;

class GameMode {
  /**
   * @param {object} o
   * @param {(active: boolean) => void} o.onChange
   * @param {() => import("node:child_process").ChildProcess} [o.launch]  pour les tests
   */
  constructor({ onChange, launch } = {}) {
    this.onChange = onChange || (() => {});
    this.launch = launch || (() => spawn("powershell.exe", ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", SCRIPT], { windowsHide: true, stdio: ["ignore", "pipe", "ignore"] }));
    this.active = false;
    this.child = null;
    this.enabled = false;
  }

  /** Allumé (réglage « Mode jeu automatique ») : la surveillance tourne. */
  setEnabled(on, platform = process.platform) {
    this.enabled = !!on && platform === "win32";
    if (!this.enabled) {
      this.stop();
      this.set(false);
    } else if (!this.child) this.start();
  }

  start() {
    let child;
    try { child = this.launch(); } catch { return; }
    this.child = child;
    let buffer = "";
    child.stdout?.setEncoding("utf8");
    child.stdout?.on("data", (chunk) => {
      buffer += chunk;
      let i;
      while ((i = buffer.indexOf("\n")) >= 0) {
        const value = Number(buffer.slice(0, i).trim());
        buffer = buffer.slice(i + 1);
        if (Number.isFinite(value)) this.set(QUIET_STATES.has(value));
      }
    });
    child.on("error", () => {});
    child.on("exit", () => {
      if (this.child !== child) return;
      this.child = null;
      // Arrêté par Windows ou planté : on relance dans 30 s.
      if (this.enabled) this.timer = setTimeout(() => this.enabled && !this.child && this.start(), 30000);
    });
  }

  set(active) {
    if (active === this.active) return;
    this.active = active;
    this.onChange(active);
  }

  stop() {
    clearTimeout(this.timer);
    const child = this.child;
    this.child = null;
    try { child?.kill(); } catch {}
  }
}

module.exports = { GameMode, QUIET_STATES };
