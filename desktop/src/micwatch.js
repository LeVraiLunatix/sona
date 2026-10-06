/* Mode vocal : savoir quand une autre app (Discord, Teams…) utilise le
   micro, pour baisser la musique pendant l'appel.

   Windows note lui-même quelle app a le micro (la petite icône de micro
   près de l'horloge) : pour chaque app, `LastUsedTimeStop` vaut 0 tant
   qu'elle s'en sert, dans
   HKCU\Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone.
   Un petit PowerShell relit ça toutes les 3 s, sans module natif. */

const { spawn } = require("node:child_process");
const path = require("node:path");

const SCRIPT = `
$base = 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\CapabilityAccessManager\\ConsentStore\\microphone'
while ($true) {
  $apps = @()
  Get-ChildItem $base -Recurse -ErrorAction SilentlyContinue | ForEach-Object {
    $start = $_.GetValue('LastUsedTimeStart'); $stop = $_.GetValue('LastUsedTimeStop')
    if ($start -ne $null -and $stop -eq 0) { $apps += $_.PSChildName }
  }
  [Console]::Out.WriteLine('MIC ' + ($apps -join '|'))
  [Console]::Out.Flush()
  Start-Sleep -Seconds 3
}`;

/**
 * Noms lisibles des apps qui ont le micro, d'après une ligne du script.
 * Sona lui-même (karaoké) ne compte pas.
 *   « C:#Users#moi#AppData#Local#Discord#app-1.0.9#Discord.exe » → « Discord »
 *   « Microsoft.SkypeApp_kzf8qxf38zg5c » → « SkypeApp »
 */
function parseLine(line) {
  if (!/^MIC(\s|$)/.test(line)) return null;
  const apps = [];
  for (const raw of line.slice(3).trim().split("|")) {
    if (!raw) continue;
    let name = raw.includes("#") ? path.win32.basename(raw.replace(/#/g, "\\")) : raw.split("_")[0].split(".").pop();
    name = name.replace(/\.exe$/i, "");
    if (!name || /^(sona|electron)$/i.test(name)) continue;
    if (!apps.includes(name)) apps.push(name);
  }
  return apps;
}

class MicWatch {
  /**
   * @param {object} o
   * @param {(state: {inUse: boolean, apps: string[]}) => void} o.onChange
   * @param {() => import("node:child_process").ChildProcess} [o.launch]  pour les tests
   */
  constructor({ onChange, launch } = {}) {
    this.onChange = onChange || (() => {});
    this.launch = launch || (() => spawn("powershell.exe", ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", SCRIPT], { windowsHide: true, stdio: ["ignore", "pipe", "ignore"] }));
    this.apps = [];
    this.child = null;
    this.enabled = false;
  }

  get inUse() { return this.apps.length > 0; }

  setEnabled(on, platform = process.platform) {
    this.enabled = !!on && platform === "win32";
    if (!this.enabled) {
      this.stop();
      this.set([]);
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
        const apps = parseLine(buffer.slice(0, i).trim());
        buffer = buffer.slice(i + 1);
        if (apps) this.set(apps);
      }
    });
    child.on("error", () => {});
    child.on("exit", () => {
      if (this.child !== child) return;
      this.child = null;
      if (this.enabled) this.timer = setTimeout(() => this.enabled && !this.child && this.start(), 30000);
    });
  }

  set(apps) {
    const was = this.inUse;
    const changed = apps.join("|") !== this.apps.join("|");
    this.apps = apps;
    if (changed && (was !== this.inUse || this.inUse)) this.onChange({ inUse: this.inUse, apps });
  }

  stop() {
    clearTimeout(this.timer);
    const child = this.child;
    this.child = null;
    try { child?.kill(); } catch {}
  }
}

module.exports = { MicWatch, parseLine };
