"""Génère l'icône d'app Sona (1024 px, opaque) et le logo de l'écran de lancement.

Un « S » géométrique blanc — deux demi-cercles aux extrémités arrondies,
comme une onde qui ondule — posé sur un noir profond légèrement dégradé,
avec un halo discret. Même tracé que `SonaLogo` côté SwiftUI.

Usage : python Scripts/make_icon.py (depuis ios/Encre)
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

SS = 4  # suréchantillonnage pour l'anticrénelage
ROOT = Path(__file__).resolve().parent.parent

# Géométrie du S, en unités de la taille du motif (0..1).
RADIUS = 0.205          # rayon de chaque demi-cercle (centre du trait)
STROKE = 0.115          # épaisseur du trait
TOP_START, TOP_END = 90, 330      # arc du haut : du bas vers la droite, par la gauche et le haut
BOTTOM_START, BOTTOM_END = 270, 510  # arc du bas : du haut vers la gauche, par la droite et le bas


def _arc_points(cx, cy, r, start, end, steps=240):
    return [
        (cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
        for a in (start + (end - start) * i / steps for i in range(steps + 1))
    ]


def draw_s(size: int, color=(255, 255, 255, 255)) -> Image.Image:
    """Le S seul, sur fond transparent, dans un carré `size`."""
    big = size * SS
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    r = RADIUS * big
    width = STROKE * big
    cx = big / 2
    half = width / 2
    for (acx, acy), start, end in (((cx, big / 2 - r), TOP_START, TOP_END), ((cx, big / 2 + r), BOTTOM_START, BOTTOM_END)):
        # Anneau partiel plein (bord extérieur puis intérieur) : un trait
        # épais tracé en segments laisse des vides entre eux.
        outer = _arc_points(acx, acy, r + half, start, end)
        inner = _arc_points(acx, acy, r - half, start, end)[::-1]
        draw.polygon(outer + inner, fill=color)
        for a in (start, end):  # extrémités arrondies
            x = acx + r * math.cos(math.radians(a))
            y = acy + r * math.sin(math.radians(a))
            draw.ellipse((x - half, y - half, x + half, y + half), fill=color)
    return img.resize((size, size), Image.LANCZOS)


def make_icon(size: int = 1024) -> Image.Image:
    # Noir profond, à peine plus clair en haut : du relief sans couleur.
    bg = Image.new("RGB", (size, size))
    px = bg.load()
    for y in range(size):
        t = y / (size - 1)
        v = int(26 * (1 - t) + 4 * t)
        for x in range(size):
            px[x, y] = (v, v, v + 2)
    mark = draw_s(int(size * 0.78))
    offset = ((size - mark.width) // 2, (size - mark.height) // 2)
    # Halo très discret sous le S.
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    glow.paste(mark, offset, mark)
    glow = glow.filter(ImageFilter.GaussianBlur(size * 0.045))
    alpha = glow.getchannel("A").point(lambda a: int(a * 0.35))
    glow.putalpha(alpha)
    out = bg.convert("RGBA")
    out.alpha_composite(glow)
    out.alpha_composite(mark, offset)
    return out.convert("RGB")


def main() -> None:
    icon = make_icon()
    icon.save(ROOT / "Assets.xcassets/AppIcon.appiconset/AppIcon.png", optimize=True)
    draw_s(360).save(ROOT / "Assets.xcassets/LaunchLogo.imageset/LaunchLogo.png", optimize=True)
    print("Icône et logo de lancement générés.")


if __name__ == "__main__":
    main()
