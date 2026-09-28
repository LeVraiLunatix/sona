"""Génère l'icône d'app Encre (1024 px, opaque) et le logo de l'écran de lancement."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

SS = 4  # suréchantillonnage pour l'anticrénelage


def cubic(p0, p1, p2, p3, n=200):
    pts = []
    for i in range(n + 1):
        t = i / n
        mt = 1 - t
        x = mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0]
        y = mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1]
        pts.append((x, y))
    return pts


def drop_points():
    """Goutte en coordonnées unitaires (0..1), pointe en haut — même tracé
    que `EncreDropShape` côté SwiftUI."""
    k = 0.5523 * 0.34
    pts = []
    pts += cubic((0.5, 0.02), (0.62, 0.22), (0.84, 0.40), (0.84, 0.64))
    pts += cubic((0.84, 0.64), (0.84, 0.64 + k), (0.5 + k, 0.98), (0.5, 0.98))
    pts += cubic((0.5, 0.98), (0.5 - k, 0.98), (0.16, 0.64 + k), (0.16, 0.64))
    pts += cubic((0.16, 0.64), (0.16, 0.40), (0.38, 0.22), (0.5, 0.02))
    return pts


BARS = [(0.30, 0.16), (0.40, 0.30), (0.50, 0.44), (0.60, 0.30), (0.70, 0.16)]
BAR_W = 0.062
BAR_CY = 0.64


def gradient(size: int, left: float, top: float, side: float) -> Image.Image:
    """Dégradé diagonal rose → violet → cyan (couleurs de marque), calé sur
    la boîte de la goutte pour que les trois teintes y soient visibles."""
    y, x = np.mgrid[0:size, 0:size].astype(np.float32)
    x = (x - left) / side
    y = (y - top) / side
    t = np.clip((x * 0.45 + y * 0.85 - 0.12) / 1.05, 0, 1)
    pink = np.array([255, 46, 97], np.float32)
    violet = np.array([140, 92, 255], np.float32)
    cyan = np.array([33, 199, 255], np.float32)
    a = np.clip(t / 0.55, 0, 1)[..., None]
    b = np.clip((t - 0.55) / 0.45, 0, 1)[..., None]
    rgb = pink * (1 - a) + violet * a
    rgb = rgb * (1 - b) + cyan * b
    return Image.fromarray(rgb.astype(np.uint8), "RGB")


def glyph(size: int, box: tuple[float, float, float]) -> tuple[Image.Image, Image.Image]:
    """Renvoie (couleurs RGBA de la goutte, masque) à la taille demandée.
    `box` = (gauche, haut, côté) de la boîte unitaire en pixels finaux."""
    big = size * SS
    left, top, side = (v * SS for v in box)
    to_px = lambda p: (left + p[0] * side, top + p[1] * side)

    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).polygon([to_px(p) for p in drop_points()], fill=255)

    fill = gradient(big, left, top, side).convert("RGBA")

    # Reflet « verre liquide » : halo clair en haut à gauche de la panse.
    hl = Image.new("L", (big, big), 0)
    d = ImageDraw.Draw(hl)
    cx, cy = to_px((0.40, 0.50))
    r = 0.26 * side
    d.ellipse((cx - r, cy - r * 0.8, cx + r, cy + r * 0.8), fill=120)
    hl = hl.filter(ImageFilter.GaussianBlur(0.09 * side))
    white = Image.new("RGBA", (big, big), (255, 255, 255, 255))
    fill = Image.composite(white, fill, hl.point(lambda v: int(v * 0.35)))

    # Ombre interne en bas à droite pour le volume.
    sh = Image.new("L", (big, big), 0)
    d = ImageDraw.Draw(sh)
    cx, cy = to_px((0.68, 0.86))
    r = 0.30 * side
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=150)
    sh = sh.filter(ImageFilter.GaussianBlur(0.10 * side))
    dark = Image.new("RGBA", (big, big), (40, 10, 90, 255))
    fill = Image.composite(dark, fill, sh.point(lambda v: int(v * 0.45)))

    # Barres de l'onde sonore, blanches.
    bars = Image.new("L", (big, big), 0)
    d = ImageDraw.Draw(bars)
    w = BAR_W * side
    for bx, bh in BARS:
        x0, _ = to_px((bx, 0))
        _, y0 = to_px((0, BAR_CY - bh / 2))
        _, y1 = to_px((0, BAR_CY + bh / 2))
        d.rounded_rectangle((x0 - w / 2, y0, x0 + w / 2, y1), radius=w / 2, fill=255)
    fill = Image.composite(Image.new("RGBA", (big, big), (255, 255, 255, 255)), fill, bars.point(lambda v: int(v * 0.96)))

    fill.putalpha(mask)
    return fill.resize((size, size), Image.LANCZOS), mask.resize((size, size), Image.LANCZOS)


def app_icon(path: Path) -> None:
    size = 1024
    y, x = np.mgrid[0:size, 0:size].astype(np.float32)
    bg = np.zeros((size, size, 3), np.float32)
    bg[:] = (8, 6, 14)
    for (cx, cy, rad, col, k) in [
        (512, 600, 560, (70, 30, 140), 0.85),
        (250, 230, 420, (150, 20, 70), 0.45),
        (820, 860, 380, (10, 90, 140), 0.40),
    ]:
        dist = np.sqrt((x - cx) ** 2 + (y - cy) ** 2) / rad
        g = np.clip(1 - dist, 0, 1) ** 2 * k
        bg = bg * (1 - g[..., None]) + np.array(col, np.float32) * g[..., None]
    base = Image.fromarray(bg.astype(np.uint8), "RGB").convert("RGBA")

    box = (172, 136, 680)
    drop, mask = glyph(size, box)

    glow = Image.new("RGBA", (size, size), (255, 60, 140, 0))
    glow.putalpha(mask.point(lambda v: int(v * 0.55)))
    glow = glow.filter(ImageFilter.GaussianBlur(46))
    base = Image.alpha_composite(base, glow.transform(glow.size, Image.AFFINE, (1, 0, 0, 0, 1, -22)))
    base = Image.alpha_composite(base, drop)
    base.convert("RGB").save(path, "PNG")


def launch_logo(path: Path, size: int = 360) -> None:
    drop, _ = glyph(size, (size * 0.08, size * 0.04, size * 0.84))
    drop.save(path, "PNG")


if __name__ == "__main__":
    out = Path(sys.argv[1])
    app_icon(out / "AppIcon.png")
    launch_logo(out / "LaunchLogo.png")
    print("ok")
