/* Fond d'écran « pochette » : pendant la lecture, le fond d'écran de
   Windows devient la pochette du titre en cours, floue et assombrie ; le
   fond d'écran d'avant revient quand on coupe l'option ou qu'on quitte.

   Le flou vient d'un aller-retour de taille (pochette réduite à 32 px puis
   agrandie à la taille de l'écran) : lisse, sans module natif. */

const { spawn, execFile } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const psQuote = (s) => `'${String(s).replace(/'/g, "''")}'`;

/** Commande PowerShell qui pose `file` en fond d'écran (SPI_SETDESKWALLPAPER). */
function setScript(file) {
  return `Add-Type -Namespace SonaWin -Name Wall -MemberDefinition '[DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int SystemParametersInfo(int a, int b, string c, int d);'
[void][SonaWin.Wall]::SystemParametersInfo(20, 0, ${psQuote(file)}, 3)`;
}

/** Image floue et assombrie (BGRA/RGBA : les 3 canaux couleur sont traités pareil). */
function blurredCover(nativeImage, buffer, { width, height, dim = 0.55 }) {
  const cover = nativeImage.createFromBuffer(buffer);
  if (cover.isEmpty()) return null;
  const tiny = cover.resize({ width: 32, height: 32, quality: "best" });
  const mid = tiny.resize({ width: 240, height: Math.round((240 * height) / width), quality: "best" });
  const big = mid.resize({ width, height, quality: "good" });
  const bitmap = Buffer.from(big.toBitmap());
  for (let i = 0; i < bitmap.length; i += 4) {
    bitmap[i] = bitmap[i] * dim;
    bitmap[i + 1] = bitmap[i + 1] * dim;
    bitmap[i + 2] = bitmap[i + 2] * dim;
  }
  return nativeImage.createFromBitmap(bitmap, { width, height });
}

class CoverWallpaper {
  /**
   * @param {object} o
   * @param {string} o.dir  dossier des images (userData)
   * @param {object} o.settings  get/set des réglages (fond d'écran d'origine)
   * @param {object} o.nativeImage
   * @param {(url: string) => Promise<Buffer>} o.fetchImage
   * @param {() => {width: number, height: number}} o.screenSize
   */
  constructor({ dir, settings, nativeImage, fetchImage, screenSize, run } = {}) {
    Object.assign(this, { dir, settings, nativeImage, fetchImage, screenSize });
    this.run = run || ((script) => new Promise((resolve) => {
      const child = spawn("powershell.exe", ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script], { windowsHide: true, stdio: "ignore" });
      child.on("exit", resolve);
      child.on("error", resolve);
    }));
    this.enabled = false;
    this.cover = null;
    this.flip = false;
  }

  async setEnabled(on, platform = process.platform) {
    const enabled = !!on && platform === "win32";
    if (enabled === this.enabled) return;
    this.enabled = enabled;
    clearTimeout(this.timer);
    if (enabled) {
      if (!this.settings.get("wallpaperOriginal")) this.settings.set("wallpaperOriginal", (await currentWallpaper()) || "");
    } else await this.restore();
  }

  /** Nouvel état de lecture : la pochette passe en fond d'écran après 3 s de lecture. */
  update(state) {
    if (!this.enabled) return;
    const url = state?.track?.cover_url;
    if (!url || state.paused || url === this.cover) return;
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.apply(url).catch(() => {}), 3000);
  }

  async apply(url) {
    if (!this.enabled || url === this.cover) return;
    const big = url.replace(/\/(\d+)x(\d+)(-[^/]*)?\.jpg/, "/1000x1000$3.jpg");
    const buffer = await this.fetchImage(big).catch(() => this.fetchImage(url));
    const { width, height } = this.screenSize();
    const image = blurredCover(this.nativeImage, buffer, { width, height });
    if (!image || !this.enabled) return;
    // Deux noms en alternance : Windows recharge bien l'image.
    this.flip = !this.flip;
    const file = path.join(this.dir, `fond-sona-${this.flip ? "a" : "b"}.jpg`);
    fs.mkdirSync(this.dir, { recursive: true });
    fs.writeFileSync(file, image.toJPEG(90));
    await this.run(setScript(file));
    this.cover = url;
  }

  /** Remet le fond d'écran d'avant. */
  async restore() {
    clearTimeout(this.timer);
    const original = this.settings.get("wallpaperOriginal");
    this.cover = null;
    if (original == null) return;
    this.settings.set("wallpaperOriginal", null);
    if (original) await this.run(setScript(original));
  }
}

/** Fond d'écran actuel de Windows (chemin du fichier), d'après le registre. */
function currentWallpaper() {
  return new Promise((resolve) => {
    if (process.platform !== "win32") return resolve(null);
    execFile("reg", ["query", "HKCU\\Control Panel\\Desktop", "/v", "WallPaper"], { windowsHide: true }, (err, out) => {
      if (err) return resolve(null);
      const m = /WallPaper\s+REG_SZ\s+(.*)/i.exec(out);
      resolve(m ? m[1].trim() : null);
    });
  });
}

module.exports = { CoverWallpaper, setScript, blurredCover };
