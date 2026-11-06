#!/usr/bin/env python3
"""Bannière du README (make-banner.swift de la version Mac) : python3 scripts/make-banner.py → docs/banner.png

Le logo (anneau ouvert et son point) sur sa grille de 200, posé à gauche, avec son halo ; le logotype et l'accroche
à droite. Demande Cairo, Pango (PyGObject) et numpy (flou du halo)."""
import math
import os

import cairo
import gi
import numpy as np

gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Pango, PangoCairo  # noqa: E402

WIDTH, HEIGHT = 2560, 960
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "banner.png")
FONT = "SF Pro Display, Inter, Noto Sans, sans-serif"

SCALE = 2.9
# Repère de CoreGraphics (y vers le haut) ramené à celui de Cairo.
CX, CY = 700, HEIGHT - 480
DOT = (CX + 43.84 * SCALE, CY - 43.84 * SCALE)
STOPS = [(0, 0x5B4CFA), (0.45, 0xED5CBF), (0.8, 0xFFA866), (1, 0xFFE9CF)]


def rgb(hex_value, alpha=1.0):
    return ((hex_value >> 16) & 0xFF) / 255, ((hex_value >> 8) & 0xFF) / 255, (hex_value & 0xFF) / 255, alpha


def layer():
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, WIDTH, HEIGHT)
    return surface, cairo.Context(surface)


def ring_path(ctx):
    # De 12,7° à -282,7° dans le sens horaire (y vers le haut) : l'anneau ouvert en haut à droite.
    ctx.new_path()
    ctx.arc(CX, CY, 62 * SCALE, -12.7 * math.pi / 180, 282.7 * math.pi / 180)


def gradient():
    g = cairo.LinearGradient(CX - 220, CY + 220, CX + 220, CY - 220)
    for offset, color in STOPS:
        g.add_color_stop_rgba(offset, *rgb(color))
    return g


def blurred(surface, sigma):
    """Flou gaussien séparable (numpy) d'une couche ARGB prémultipliée."""
    data = np.ndarray((HEIGHT, WIDTH, 4), dtype=np.uint8, buffer=surface.get_data()).astype(np.float32)
    radius = int(sigma * 3)
    kernel = np.exp(-(np.arange(-radius, radius + 1) ** 2) / (2 * sigma * sigma))
    kernel /= kernel.sum()
    # Réduction par 4 : le flou est large, le détail ne compte pas.
    small = data.reshape(HEIGHT // 4, 4, WIDTH // 4, 4, 4).mean(axis=(1, 3))
    r = max(radius // 4, 1)
    k = np.exp(-(np.arange(-r, r + 1) ** 2) / (2 * (sigma / 4) ** 2))
    k /= k.sum()
    for axis in (0, 1):
        pad = [(0, 0)] * 3
        pad[axis] = (r, r)
        padded = np.pad(small, pad, mode="constant")
        n = small.shape[axis]
        small = sum(k[i] * np.take(padded, range(i, i + n), axis=axis) for i in range(2 * r + 1))
    big = np.repeat(np.repeat(small, 4, axis=0), 4, axis=1)
    out = cairo.ImageSurface(cairo.FORMAT_ARGB32, WIDTH, HEIGHT)
    np.ndarray((HEIGHT, WIDTH, 4), dtype=np.uint8, buffer=out.get_data())[:] = np.clip(big, 0, 255).astype(np.uint8)
    out.mark_dirty()
    return out


def text(ctx, string, size, weight, color, x, bottom, letter_spacing):
    """Comme `NSAttributedString.draw(at:)` : le bas de la ligne (descente comprise) posé en `bottom`."""
    layout = PangoCairo.create_layout(ctx)
    font = Pango.FontDescription.from_string(FONT)
    font.set_absolute_size(size * Pango.SCALE)
    font.set_weight(weight)
    layout.set_font_description(font)
    attrs = Pango.AttrList()
    attrs.insert(Pango.attr_letter_spacing_new(int(letter_spacing * Pango.SCALE)))
    layout.set_attributes(attrs)
    layout.set_text(string, -1)
    ctx.set_source_rgba(*color)
    _, logical = layout.get_pixel_extents()
    ctx.move_to(x, bottom - logical.height)
    PangoCairo.show_layout(ctx, layout)


def main():
    ring, rctx = layer()
    ring_path(rctx)
    rctx.set_line_width(26 * SCALE)
    rctx.set_line_cap(cairo.LINE_CAP_ROUND)
    rctx.set_source(gradient())
    rctx.stroke()
    dot, dctx = layer()
    dctx.arc(*DOT, 13 * SCALE, 0, 2 * math.pi)
    dctx.set_source_rgb(1, 1, 1)
    dctx.fill()

    image, ctx = layer()
    ctx.set_source_rgba(*rgb(0x0E0D13))
    ctx.paint()
    # Halo diffus derrière le logo.
    halo = cairo.RadialGradient(CX, CY, 0, CX, CY, 760)
    halo.add_color_stop_rgba(0, *rgb(0x7B4CF0, 0.22))
    halo.add_color_stop_rgba(1, *rgb(0x7B4CF0, 0))
    ctx.set_source(halo)
    ctx.paint()
    ctx.set_source_surface(blurred(ring, 40))
    ctx.paint_with_alpha(0.7)
    ctx.set_source_surface(blurred(dot, 30))
    ctx.paint_with_alpha(0.6)
    ctx.set_source_surface(ring)
    ctx.paint()
    # Reflet sur le bord extérieur, en haut à gauche.
    ctx.new_path()
    ctx.arc_negative(CX, CY, 62 * SCALE + 13 * SCALE - 6, -108 * math.pi / 180, -200 * math.pi / 180)
    ctx.set_source_rgba(1, 1, 1, 0.6)
    ctx.set_line_width(6)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.stroke()
    ctx.set_source_surface(dot)
    ctx.paint()

    # Logotype et accroche (positions de la version Mac).
    text(ctx, "hello", 300, Pango.Weight.SEMIBOLD, (0.96, 0.95, 0.98, 1), 1060, HEIGHT - 430, -14)
    text(ctx, "Le lanceur Linux qui change de peau.", 64, Pango.Weight.NORMAL, (0.75, 0.73, 0.82, 1), 1072,
         HEIGHT - 330, -0.5)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    image.write_to_png(OUT)
    print("✓ docs/banner.png")


if __name__ == "__main__":
    main()
