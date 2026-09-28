"""Génère l'icône d'app Sona (1024 px, opaque), le logo de l'écran de
lancement, et la géométrie du logo pour SwiftUI.

Le logo : un « S » dessiné par des barres verticales arrondies — la forme
d'onde d'un morceau, ou un égaliseur — qui suivent la courbe de la lettre.
Chaque colonne du S devient une ou plusieurs barres (une par passage du
trait), blanches sur noir profond.

Usage : python Scripts/make_icon.py (depuis ios/Encre)
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

SS = 4
ROOT = Path(__file__).resolve().parent.parent

# S de référence (unités 0..1 du carré de dessin).
RADIUS = 0.2
STROKE = 0.17
# Arcs parcourus dans le sens des angles croissants (repère image, y vers le bas).
ARCS = (((0.5, 0.5 - RADIUS), 90, 330), ((0.5, 0.5 + RADIUS), 270, 510))
# Barres : nombre de colonnes et largeur (en part de l'espacement).
COLUMNS = 15
BAR_FILL = 0.62
MIN_BAR = 0.05  # hauteur minimale d'une barre (unités)


def _inside_s(x: float, y: float) -> bool:
    """Point dans le trait du S (anneaux partiels + extrémités arrondies)."""
    half = STROKE / 2
    for (cx, cy), start, end in ARCS:
        dx, dy = x - cx, y - cy
        dist = math.hypot(dx, dy)
        angle = math.degrees(math.atan2(dy, dx)) % 360
        span = end - start
        rel = (angle - start) % 360
        if abs(dist - RADIUS) <= half and rel <= span:
            return True
        for a in (start, end):
            ex = cx + RADIUS * math.cos(math.radians(a))
            ey = cy + RADIUS * math.sin(math.radians(a))
            if math.hypot(x - ex, y - ey) <= half:
                return True
    return False


def bars() -> list[tuple[float, float, float]]:
    """Barres (x centre, y haut, y bas), unités 0..1."""
    left, right = 0.5 - RADIUS - STROKE / 2, 0.5 + RADIUS + STROKE / 2
    pitch = (right - left) / COLUMNS
    result = []
    steps = 800
    for c in range(COLUMNS):
        x = left + pitch * (c + 0.5)
        inside = [_inside_s(x, i / steps) for i in range(steps + 1)]
        start = None
        for i, v in enumerate(inside + [False]):
            if v and start is None:
                start = i
            elif not v and start is not None:
                y0, y1 = start / steps, (i - 1) / steps
                if y1 - y0 < MIN_BAR:
                    mid = (y0 + y1) / 2
                    y0, y1 = mid - MIN_BAR / 2, mid + MIN_BAR / 2
                result.append((round(x, 4), round(y0, 4), round(y1, 4)))
                start = None
    return result, pitch * BAR_FILL


def draw_logo(size: int, color=(255, 255, 255, 255)) -> Image.Image:
    big = size * SS
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    items, width = bars()
    w = width * big
    for x, y0, y1 in items:
        draw.rounded_rectangle(
            (x * big - w / 2, y0 * big, x * big + w / 2, y1 * big), radius=w / 2, fill=color
        )
    return img.resize((size, size), Image.LANCZOS)


def make_icon(size: int = 1024) -> Image.Image:
    bg = Image.new("RGB", (size, size))
    px = bg.load()
    for y in range(size):
        t = y / (size - 1)
        v = int(26 * (1 - t) + 4 * t)
        for x in range(size):
            px[x, y] = (v, v, v + 2)
    mark = draw_logo(int(size * 0.8))
    offset = ((size - mark.width) // 2, (size - mark.height) // 2)
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    glow.paste(mark, offset, mark)
    glow = glow.filter(ImageFilter.GaussianBlur(size * 0.04))
    glow.putalpha(glow.getchannel("A").point(lambda a: int(a * 0.35)))
    out = bg.convert("RGBA")
    out.alpha_composite(glow)
    out.alpha_composite(mark, offset)
    return out.convert("RGB")


def write_swift(path: Path) -> None:
    items, width = bars()
    rows = ",\n".join(f"        .init(x: {x}, top: {y0}, bottom: {y1})" for x, y0, y1 in items)
    path.write_text(
        "// Généré par Scripts/make_icon.py — ne pas modifier à la main.\n"
        "import CoreGraphics\n\n"
        "enum SonaLogoGeometry {\n"
        "    struct Bar {\n        let x: CGFloat\n        let top: CGFloat\n        let bottom: CGFloat\n    }\n\n"
        f"    static let barWidth: CGFloat = {round(width, 4)}\n\n"
        f"    static let bars: [Bar] = [\n{rows},\n    ]\n}}\n",
        encoding="utf-8",
    )


def main() -> None:
    make_icon().save(ROOT / "Assets.xcassets/AppIcon.appiconset/AppIcon.png", optimize=True)
    draw_logo(360).save(ROOT / "Assets.xcassets/LaunchLogo.imageset/LaunchLogo.png", optimize=True)
    write_swift(ROOT / "Sources/DesignSystem/SonaLogoGeometry.swift")
    print(f"Icône, logo de lancement et géométrie générés ({len(bars()[0])} barres).")


if __name__ == "__main__":
    main()
