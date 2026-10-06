/* Commandes vocales « Sona … » (« Sona, suivant », « Sona, mets du PNL ») :
   la reconnaissance vocale de Windows (System.Speech), hors ligne, dans un
   petit PowerShell — rien n'est envoyé sur Internet. Il faut la voix
   française de Windows (Paramètres → Heure et langue → Voix). */

const { spawn } = require("node:child_process");

const COMMANDS = {
  pause: { action: "pause" }, stop: { action: "pause" }, "mets pause": { action: "pause" },
  lecture: { action: "play" }, reprends: { action: "play" }, play: { action: "play" },
  suivant: { action: "next" }, "titre suivant": { action: "next" }, "chanson suivante": { action: "next" },
  "précédent": { action: "previous" }, "titre précédent": { action: "previous" },
  "plus fort": { action: "volumeStep", step: 0.08 }, "moins fort": { action: "volumeStep", step: -0.08 },
  "j'aime": { action: "like" }, "mode vocal": { action: "volumePreset", preset: "voc" },
  "radio": { action: "djradio" },
};
const PLAY_WORDS = ["mets", "joue", "lance"];

const esc = (s) => s.replace(/'/g, "''");
const SCRIPT = `
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Speech
$rec = [System.Speech.Recognition.SpeechRecognitionEngine]::InstalledRecognizers() | Where-Object { $_.Culture.Name -like 'fr*' } | Select-Object -First 1
if (-not $rec) { [Console]::Out.WriteLine('ERR nofr'); [Console]::Out.Flush(); exit 1 }
$engine = New-Object System.Speech.Recognition.SpeechRecognitionEngine($rec)
try { $engine.SetInputToDefaultAudioDevice() } catch { [Console]::Out.WriteLine('ERR nomic'); [Console]::Out.Flush(); exit 1 }
$cmds = New-Object System.Speech.Recognition.Choices
foreach ($c in @(${Object.keys(COMMANDS).map((c) => `'${esc(c)}'`).join(",")})) { $cmds.Add($c) }
$gb = New-Object System.Speech.Recognition.GrammarBuilder
$gb.Culture = $rec.Culture
$gb.Append('Sona'); $gb.Append($cmds)
$engine.LoadGrammar((New-Object System.Speech.Recognition.Grammar($gb)))
$gb2 = New-Object System.Speech.Recognition.GrammarBuilder
$gb2.Culture = $rec.Culture
$gb2.Append('Sona'); $gb2.Append((New-Object System.Speech.Recognition.Choices(${PLAY_WORDS.map((w) => `'${w}'`).join(",")}))); $gb2.AppendDictation()
$engine.LoadGrammar((New-Object System.Speech.Recognition.Grammar($gb2)))
[Console]::Out.WriteLine('READY ' + $rec.Culture.Name); [Console]::Out.Flush()
while ($true) {
  $r = $engine.Recognize([TimeSpan]::FromSeconds(30))
  if ($r -and $r.Confidence -ge 0.5) { [Console]::Out.WriteLine('HEARD ' + $r.Text); [Console]::Out.Flush() }
}`;

/** Ce que veut dire une phrase entendue (« Sona suivant ») : une commande, ou null. */
function interpret(text) {
  const t = String(text || "").trim().replace(/^sona[\s,]*/i, "").replace(/[.!?]+$/, "").trim();
  const lower = t.toLowerCase().replace(/’/g, "'");
  if (COMMANDS[lower]) return { ...COMMANDS[lower] };
  const word = PLAY_WORDS.find((w) => lower.startsWith(`${w} `));
  if (word) {
    const query = t.slice(word.length).trim().replace(/^(un peu de |un peu d'|du |de la |des |de l'|de |d'|le |la |les |l')/i, "").trim();
    if (query) return { action: "voiceSearch", query };
  }
  return null;
}

class VoiceControl {
  constructor({ onCommand, onStatus, launch } = {}) {
    this.onCommand = onCommand || (() => {});
    this.onStatus = onStatus || (() => {});
    this.launch = launch || (() => spawn("powershell.exe", ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", SCRIPT], { windowsHide: true, stdio: ["ignore", "pipe", "ignore"] }));
    this.child = null;
    this.enabled = false;
    this.status = { ready: false, error: null, culture: null, last: null };
  }

  setEnabled(on, platform = process.platform) {
    this.enabled = !!on && platform === "win32";
    if (!this.enabled) { this.stop(); this.setStatus({ ready: false, error: on ? "Seulement sous Windows." : null }); }
    else if (!this.child) this.start();
  }

  setStatus(patch) {
    this.status = { ...this.status, ...patch };
    this.onStatus(this.status);
  }

  start() {
    let child;
    try { child = this.launch(); } catch { this.setStatus({ error: "PowerShell introuvable." }); return; }
    this.child = child;
    let buffer = "";
    child.stdout?.setEncoding("utf8");
    child.stdout?.on("data", (chunk) => {
      buffer += chunk;
      let i;
      while ((i = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, i).trim();
        buffer = buffer.slice(i + 1);
        this.line(line);
      }
    });
    child.on("error", () => {});
    child.on("exit", () => {
      if (this.child !== child) return;
      this.child = null;
      if (this.status.ready) this.setStatus({ ready: false });
      // Voix française absente : inutile de relancer en boucle.
      if (this.enabled && !this.status.error) this.timer = setTimeout(() => this.enabled && !this.child && this.start(), 30000);
    });
  }

  line(line) {
    if (line.startsWith("READY")) this.setStatus({ ready: true, error: null, culture: line.slice(6).trim() || null });
    else if (line === "ERR nofr") this.setStatus({ ready: false, error: "Reconnaissance vocale française absente : Paramètres Windows → Heure et langue → Voix (ou Langue → Français → Reconnaissance vocale)." });
    else if (line === "ERR nomic") this.setStatus({ ready: false, error: "Aucun micro trouvé." });
    else if (line.startsWith("HEARD ")) {
      const text = line.slice(6);
      const command = interpret(text);
      this.setStatus({ last: text });
      if (command) this.onCommand(command, text);
    }
  }

  stop() {
    clearTimeout(this.timer);
    const child = this.child;
    this.child = null;
    try { child?.kill(); } catch {}
  }
}

module.exports = { VoiceControl, interpret, COMMANDS };
