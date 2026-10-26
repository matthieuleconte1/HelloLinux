"""Le logo de Hello (Mark.swift) et le reflet qui fait le tour du panneau à l'ouverture (HaloSweep).

Le logo : un anneau ouvert et son point, sur une grille de 200 — anneau de rayon 62 et d'épaisseur 26,
point de diamètre 26. L'anneau part juste après le point (-12,7°) et en fait le tour sur 295,4°."""
import math

import cairo
from gi.repository import Adw, Gtk

from .decode import noise
from .settings import motion_enabled, motion_speed
from .styles import GLASS_COLORS, rgb

RING_RADIUS = 62 / 200
STROKE = 26 / 200
DOT_RADIUS = 13 / 200
DOT_CENTER = (143.84 / 200, 56.16 / 200)
START = math.radians(-12.7)
SPAN = math.radians(295.4)


def _source(ctx, hex_color, alpha=1.0):
    r, g, b = rgb(hex_color)
    ctx.set_source_rgba(r / 255, g / 255, b / 255, alpha)


def _ring_outline(ctx, cx, cy, radius, line, end):
    """Contour de l'anneau plein tracé jusqu'à `end` (bouts ronds compris), pour le dessiner évidé."""
    outer, inner, half = radius + line / 2, radius - line / 2, line / 2
    ctx.new_path()
    ctx.arc(cx, cy, outer, START, end)
    ctx.arc(cx + radius * math.cos(end), cy + radius * math.sin(end), half, end, end + math.pi)
    ctx.arc_negative(cx, cy, inner, end, START)
    ctx.arc(cx + radius * math.cos(START), cy + radius * math.sin(START), half, START + math.pi, START + 2 * math.pi)
    ctx.close_path()


def draw_mark(ctx, side, skin, progress=1.0, dot_scale=1.0, ox=0.0, oy=0.0):
    """Dessine le logo dans un carré de `side` px. skin = (nom, couleur 1, couleur 2)."""
    kind, c1, c2 = skin
    line = side * STROKE
    cx, cy = ox + side / 2, oy + side / 2
    ctx.save()
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_line_width(line)
    if progress > 0:
        ctx.new_path()
        ctx.arc(cx, cy, side * RING_RADIUS, START, START + SPAN * progress)
        if kind == "glyph":
            # Atelier Glyphe : l'anneau évidé, au filet fin (environ 1 px dans la barre de recherche).
            _ring_outline(ctx, cx, cy, side * RING_RADIUS, line, START + SPAN * progress)
            ctx.set_line_width(max(1.0, line * 0.22))
            ctx.set_line_join(cairo.LINE_JOIN_ROUND)
            _source(ctx, c1)
            ctx.stroke()
        elif kind == "glass":
            grad = cairo.LinearGradient(ox + side * 0.12, oy + side * 0.92, ox + side * 0.9, oy + side * 0.08)
            for i, color in enumerate(GLASS_COLORS):
                r, g, b = rgb(color)
                grad.add_color_stop_rgb(i / (len(GLASS_COLORS) - 1), r / 255, g / 255, b / 255)
            ctx.set_source(grad)
            ctx.stroke()
        elif kind == "brutal":
            # Anneau de couleur cerclé de noir.
            path = ctx.copy_path()
            ctx.set_line_width(line + side * 0.06)
            ctx.set_source_rgb(0, 0, 0)
            ctx.stroke()
            ctx.append_path(path)
            ctx.set_line_width(line)
            _source(ctx, c1)
            ctx.stroke()
        else:
            _source(ctx, c1)
            ctx.stroke()
    # Le point
    r = side * DOT_RADIUS * dot_scale
    px, py = ox + side * DOT_CENTER[0], oy + side * DOT_CENTER[1]
    if r > 0:
        ctx.new_path()
        if kind == "phosphor":
            # Le point devient le curseur bloc.
            ctx.rectangle(px - r * 0.8, py - r * 1.2, r * 1.6, r * 2.4)
            _source(ctx, c1)
            ctx.fill()
        elif kind == "atelier":
            # Cookie Material : un cercle festonné à 9 lobes.
            steps = 72
            for step in range(steps + 1):
                a = 2 * math.pi * step / steps - math.pi / 2
                rr = r * 1.15 * (1 - 0.16 * (1 - math.cos(9 * a)) / 2)
                x, y = px + rr * math.cos(a), py + rr * math.sin(a)
                ctx.move_to(x, y) if step == 0 else ctx.line_to(x, y)
            ctx.close_path()
            _source(ctx, c2)
            ctx.fill()
        else:
            ctx.arc(px, py, r, 0, 2 * math.pi)
            if kind == "glass":
                ctx.set_source_rgb(1, 1, 1)
            elif kind == "brutal":
                ctx.set_source_rgb(0, 0, 0)
                ctx.fill_preserve()
                ctx.new_path()
                ctx.arc(px, py, r * 0.72, 0, 2 * math.pi)
                _source(ctx, c2)
            else:
                _source(ctx, c2 or c1)
            ctx.fill()
    ctx.restore()


class AnimatedMark(Gtk.DrawingArea):
    """Logo de la barre de recherche : à chaque ouverture, le point s'allume et l'anneau en part pour faire le tour."""

    def __init__(self, size=22):
        super().__init__()
        self.set_content_width(size)
        self.set_content_height(size)
        self.set_valign(Gtk.Align.CENTER)
        self.skin = ("glass", None, None)
        self.progress = 1.0
        self.dot = 1.0
        self.spin = 0.0
        self.set_draw_func(self._draw)
        target = Adw.CallbackAnimationTarget.new(self._step)
        self.animation = Adw.TimedAnimation.new(self, 0, 1, 700, target)
        self.animation.set_easing(Adw.Easing.EASE_OUT_CUBIC)

    def _step(self, value):
        self.dot = min(1.0, value * 4)
        self.progress = max(0.0, (value - 0.15) / 0.85)
        # Glyphe : comme le chargeur de l'artifact, l'anneau file en comète avant de se poser.
        self.spin = -150 * (1 - value) if self.skin[0] == "glyph" else 0.0
        self.queue_draw()

    def play(self, enabled=True):
        if enabled and motion_enabled():
            self.animation.set_duration(int((900 if self.skin[0] == "glyph" else 700) / motion_speed()))
            self.animation.reset()
            self.animation.play()
        else:
            self._step(1)

    def _draw(self, _area, ctx, width, height):
        side = min(width, height)
        if self.spin:
            ctx.translate(width / 2, height / 2)
            ctx.rotate(math.radians(self.spin))
            ctx.translate(-width / 2, -height / 2)
        draw_mark(ctx, side, self.skin, self.progress, self.dot, (width - side) / 2, (height - side) / 2)


class DotWave(Gtk.DrawingArea):
    """Glyphe : une onde de points part du logo et traverse le panneau (la « révélation » de l'artifact).
    Front net et dense, traîne longue qui s'émiette comme un signal qu'on décode : la taille des points monte par
    paliers (une trame, pas un dégradé) et un bruit en éteint au hasard dans la traîne."""
    STEP, LEAD, TRAIL = 13, 14, 110
    LEVELS = (0.55, 0.95, 1.4, 1.95)

    def __init__(self):
        super().__init__()
        self.set_can_target(False)
        self.t = -1.0
        self.origin = (29, 30)
        self.color = "#ED6A0C"
        self.radius = 22
        self.set_draw_func(self._draw)
        target = Adw.CallbackAnimationTarget.new(self._step)
        self.animation = Adw.TimedAnimation.new(self, 0, 1, 950, target)
        self.animation.set_easing(Adw.Easing.EASE_IN_OUT_CUBIC)
        self.animation.connect("done", lambda *_: self._step(-1))

    def _step(self, value):
        self.t = value
        self.queue_draw()

    def play(self, origin, color, radius):
        self.origin, self.color, self.radius = origin, color, radius
        self.animation.set_duration(int(950 / motion_speed()))
        self.animation.reset()
        self.animation.play()

    def _draw(self, _area, ctx, width, height):
        p = self.t
        if not 0.001 < p < 0.999:
            return
        ox, oy = self.origin
        reach = max(math.hypot(x - ox, y - oy) for x, y in ((0, 0), (width, 0), (0, height), (width, height)))
        front = p * (reach + self.TRAIL)
        fade = 1 - p * 0.55
        # Le bruit change par à-coups (≈ 20 fois par seconde), comme des glyphes qui défilent.
        tick = int(p * 18)
        r = min(self.radius, width / 2, height / 2)
        ctx.new_path()
        ctx.arc(width - r, r, r, -math.pi / 2, 0)
        ctx.arc(width - r, height - r, r, 0, math.pi / 2)
        ctx.arc(r, height - r, r, math.pi / 2, math.pi)
        ctx.arc(r, r, r, math.pi, 3 * math.pi / 2)
        ctx.close_path()
        ctx.clip()
        cr, cg, cb = rgb(self.color)
        step = self.STEP
        # Les rangées que l'onde n'a pas encore atteintes sont sautées.
        max_y = min(height, oy + front + self.LEAD)
        row, y = 0, step / 2
        while y < max_y:
            column, x = 0, step / 2
            while x < width:
                d = math.hypot(x - ox, y - oy)
                lit = 1 - (d - front) / self.LEAD if d > front else 1 - (front - d) / self.TRAIL
                # Dans la traîne, les points s'éteignent au hasard à mesure que le signal faiblit.
                if lit > 0 and (d > front - 20 or noise(column, row, tick) < lit * 1.3):
                    radius = self.LEVELS[min(len(self.LEVELS) - 1, int(lit * len(self.LEVELS)))]
                    ctx.set_source_rgba(cr / 255, cg / 255, cb / 255, (0.35 + 0.65 * lit) * fade)
                    ctx.arc(x, y, radius, 0, 2 * math.pi)
                    ctx.fill()
                x += step
                column += 1
            y += step
            row += 1


class Sweep(Gtk.DrawingArea):
    """Reflet multicolore qui fait le tour du bord du panneau quand il apparaît (style Verre)."""

    def __init__(self):
        super().__init__()
        self.set_can_target(False)
        self.radius = 26
        self.t = -1.0
        self.set_draw_func(self._draw)
        target = Adw.CallbackAnimationTarget.new(self._step)
        self.animation = Adw.TimedAnimation.new(self, 0, 1, 1100, target)
        self.animation.set_easing(Adw.Easing.EASE_IN_OUT_CUBIC)
        self.animation.connect("done", lambda *_: self._step(-1))

    def _step(self, value):
        self.t = value
        self.queue_draw()

    def play(self, radius):
        self.radius = radius
        self.animation.set_duration(int(1100 / motion_speed()))
        self.animation.reset()
        self.animation.play()

    def _draw(self, _area, ctx, width, height):
        if self.t < 0:
            return
        inset = 1.0
        w, h, r = width - 2 * inset, height - 2 * inset, min(self.radius, (min(width, height) - 2) / 2)
        perimeter = 2 * (w + h - 4 * r) + 2 * math.pi * r
        # Point de la tête sur le contour, en partant du coin supérieur droit (là où se trouve le point du logo).
        head = (self.t * perimeter) % perimeter
        tail = perimeter * 0.22
        segments = 28
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        fade = 1.0 if self.t < 0.8 else max(0.0, (1 - self.t) / 0.2)
        for i in range(segments):
            a = head - tail * i / segments
            b = head - tail * (i + 1) / segments
            x1, y1 = self._point(a % perimeter, inset, w, h, r)
            x2, y2 = self._point(b % perimeter, inset, w, h, r)
            color = GLASS_COLORS[min(len(GLASS_COLORS) - 1, i * len(GLASS_COLORS) // segments)]
            cr, cg, cb = rgb(color)
            ctx.set_source_rgba(cr / 255, cg / 255, cb / 255, fade * (1 - i / segments) * 0.95)
            ctx.set_line_width(2.4 * (1 - i / segments) + 0.6)
            ctx.move_to(x1, y1)
            ctx.line_to(x2, y2)
            ctx.stroke()

    @staticmethod
    def _point(d, o, w, h, r):
        """Point à la distance `d` le long du rectangle arrondi, sens horaire depuis le haut à droite."""
        straight_top = w - 2 * r
        straight_side = h - 2 * r
        quarter = math.pi * r / 2
        legs = [
            ("arc", o + w - r, o + r, -math.pi / 2), ("line", o + w, o + r, o + w, o + h - r),
            ("arc", o + w - r, o + h - r, 0), ("line", o + w - r, o + h, o + r, o + h),
            ("arc", o + r, o + h - r, math.pi / 2), ("line", o, o + h - r, o, o + r),
            ("arc", o + r, o + r, math.pi), ("line", o + r, o, o + w - r, o),
        ]
        lengths = [quarter, straight_side, quarter, straight_top, quarter, straight_side, quarter, straight_top]
        for leg, length in zip(legs, lengths):
            if d <= length or leg is legs[-1]:
                f = 0 if length == 0 else min(d / length, 1)
                if leg[0] == "arc":
                    _, cx, cy, start = leg
                    a = start + f * math.pi / 2
                    return cx + r * math.cos(a), cy + r * math.sin(a)
                _, x1, y1, x2, y2 = leg
                return x1 + (x2 - x1) * f, y1 + (y2 - y1) * f
            d -= length
        return o + w, o + r


def cairo_rgba(value):
    """« #RRGGBB » ou « rgba(r,g,b,a) » (jetons de style) → composantes cairo."""
    if value.startswith("rgba"):
        r, g, b, a = (float(x) for x in value[value.index("(") + 1:-1].split(","))
        return r / 255, g / 255, b / 255, a
    r, g, b = rgb(value)
    return r / 255, g / 255, b / 255, 1.0


def _span(p, a, b):
    """Avancement de p entre a et b, borné à [0, 1]."""
    return min(1.0, max(0.0, (p - a) / (b - a)))


def _out(x):
    return 1 - (1 - x) ** 3


def _in_out(x):
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def _rounded(ctx, x, y, w, h, r):
    r = max(0.0, min(r, w / 2, h / 2))
    ctx.new_path()
    ctx.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    ctx.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    ctx.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    ctx.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    ctx.close_path()


class Flourish(Gtk.DrawingArea):
    """Signature dessinée de l'ouverture, par-dessus le panneau (Glyphe a son onde de points, le Verre garde aussi
    son reflet du bord) : filet d'accent de Plasma, reflet sur le verre, anneau de focus d'Atelier, allumage du
    tube Phosphore, trait d'encre du Papier, impact du Néo-brutal."""
    DURATIONS = {"kde": 640, "glass": 950, "atelier": 820, "phosphor": 900, "paper": 1700, "brutal": 560}

    def __init__(self):
        super().__init__()
        self.set_can_target(False)
        self.t = -1.0
        self.style = None
        self.set_draw_func(self._draw)
        target = Adw.CallbackAnimationTarget.new(self._step)
        self.animation = Adw.TimedAnimation.new(self, 0, 1, 800, target)
        self.animation.set_easing(Adw.Easing.LINEAR)
        self.animation.connect("done", lambda *_: self._step(-1))

    def _step(self, value):
        self.t = value
        self.queue_draw()

    def play(self, style, tokens, header):
        """`header` : (x, y, largeur, hauteur) de la barre de recherche dans le panneau."""
        if style not in self.DURATIONS:
            return
        self.style, self.tokens, self.header = style, tokens, header
        self.animation.set_duration(int(self.DURATIONS[style] / motion_speed()))
        self.animation.reset()
        self.animation.play()

    def stop(self):
        self.animation.skip()

    def _draw(self, _area, ctx, width, height):
        p = self.t
        if not 0 <= p < 1 or self.style is None:
            return
        t = self.tokens
        _rounded(ctx, 0, 0, width, height, t["radius"])
        ctx.clip()
        getattr(self, "_" + self.style)(ctx, p, width, height, t)

    def _kde(self, ctx, p, w, h, t):
        # Un filet d'accent part du centre de la barre de recherche, s'étire jusqu'aux bords puis s'efface.
        hx, hy, hw, hh = self.header
        half = hw / 2 * _out(_span(p, 0.05, 0.5))
        alpha = 1 - _span(p, 0.55, 1)
        r, g, b, _ = cairo_rgba(t["accent"])
        ctx.set_source_rgba(r, g, b, alpha)
        ctx.rectangle(hx + hw / 2 - half, hy + hh - 2, 2 * half, 2)
        ctx.fill()

    def _glass(self, ctx, p, w, h, t):
        # Un reflet clair, en biais, balaie la vitre de gauche à droite.
        q = _in_out(_span(p, 0.08, 0.9))
        band = w * 0.38
        x = -band + (w + 2 * band) * q
        fade = 1 - _span(p, 0.8, 1)
        gradient = cairo.LinearGradient(x - band / 2, 0, x + band / 2, h * 0.35)
        gradient.add_color_stop_rgba(0, 1, 1, 1, 0)
        gradient.add_color_stop_rgba(0.5, 1, 1, 1, 0.13 * fade)
        gradient.add_color_stop_rgba(1, 1, 1, 1, 0)
        ctx.set_source(gradient)
        ctx.paint()

    def _atelier(self, ctx, p, w, h, t):
        # Anneau de focus : il apparaît sur la pilule de recherche et s'en écarte en s'effaçant.
        hx, hy, hw, hh = self.header
        spread = 1.5 + 7 * _out(_span(p, 0.18, 1))
        alpha = _span(p, 0.12, 0.24) * (1 - _span(p, 0.45, 1))
        r, g, b, _ = cairo_rgba(t["accent2"])
        ctx.set_source_rgba(r, g, b, alpha)
        ctx.set_line_width(2.5)
        _rounded(ctx, hx - spread, hy - spread, hw + 2 * spread, hh + 2 * spread, hh / 2 + spread)
        ctx.stroke()

    def _phosphor(self, ctx, p, w, h, t):
        sr, sg, sb, _ = cairo_rgba(t["surface"])
        gr, gg, gb, _ = cairo_rgba(t["accent"])
        cy = h * 0.42
        if p < 0.16:
            # Écran éteint, puis un trait lumineux s'étire depuis le centre.
            ctx.set_source_rgb(sr, sg, sb)
            ctx.paint()
            half = w / 2 * _out(p / 0.16)
            for thickness, alpha in ((14, 0.12), (6, 0.3), (2, 1.0)):
                ctx.set_source_rgba(gr, gg, gb, alpha)
                ctx.rectangle(w / 2 - half, cy - thickness / 2, 2 * half, thickness)
                ctx.fill()
            ctx.set_source_rgba(1, 1, 1, 0.8)
            ctx.rectangle(w / 2 - half * 0.6, cy - 0.5, half * 1.2, 1)
            ctx.fill()
            return
        # Le tube s'ouvre verticalement…
        q = _out(_span(p, 0.16, 0.42))
        top, bottom = cy * (1 - q), cy + (h - cy) * q
        ctx.set_source_rgb(sr, sg, sb)
        ctx.rectangle(0, 0, w, top)
        ctx.rectangle(0, bottom, w, h - bottom)
        ctx.fill()
        if q < 1:
            ctx.set_source_rgba(gr, gg, gb, 0.7 * (1 - q))
            ctx.rectangle(0, top, w, 1.5)
            ctx.rectangle(0, bottom - 1.5, w, 1.5)
            ctx.fill()
        # … puis un faisceau descend : ce qu'il n'a pas encore balayé reste dans l'ombre.
        beam = _span(p, 0.3, 0.96)
        if 0 < beam < 1:
            y = h * _in_out(beam)
            ctx.set_source_rgba(sr, sg, sb, 0.72)
            ctx.rectangle(0, max(y, top), w, max(0, min(bottom, h) - max(y, top)))
            ctx.fill()
            glow = cairo.LinearGradient(0, y - 34, 0, y)
            glow.add_color_stop_rgba(0, gr, gg, gb, 0)
            glow.add_color_stop_rgba(1, gr, gg, gb, 0.2)
            ctx.set_source(glow)
            ctx.rectangle(0, y - 34, w, 34)
            ctx.fill()
            ctx.set_source_rgba(gr, gg, gb, 0.55)
            ctx.rectangle(0, y - 1, w, 1.5)
            ctx.fill()
        elif beam == 0:
            ctx.set_source_rgba(sr, sg, sb, 0.72)
            ctx.rectangle(0, top, w, bottom - top)
            ctx.fill()

    def _paper(self, ctx, p, w, h, t):
        # Trait d'encre tracé à la plume sous la recherche : épais au départ, il s'affine en avançant.
        hx, hy, hw, hh = self.header
        x0, x1, base = hx + 18, hx + hw - 18, hy + hh - 7
        drawn = _out(_span(p, 0.14, 0.42))
        alpha = 1 - _span(p, 0.72, 1)
        if drawn <= 0 or alpha <= 0:
            return
        r, g, b, _ = cairo_rgba(t["accent"])
        ctx.set_source_rgba(r, g, b, alpha)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        steps = 80
        last = None
        for i in range(int(steps * drawn) + 1):
            s = i / steps
            point = (x0 + (x1 - x0) * s, base + 0.9 * math.sin(s * 7 + 1) + 0.4 * math.sin(s * 23))
            if last:
                ctx.set_line_width(max(0.8, 2.8 - 1.7 * s + 0.4 * math.sin(s * 11)))
                ctx.move_to(*last)
                ctx.line_to(*point)
                ctx.stroke()
            last = point
        ctx.arc(x0, base + 0.9 * math.sin(1), 1.9, 0, 2 * math.pi)
        ctx.fill()

    def _brutal(self, ctx, p, w, h, t):
        # À l'atterrissage (≈ 42 % de la chute) : le contour claque, des traits d'impact partent des coins.
        q = _span(p, 0.3, 0.75)
        if not 0 < q < 1:
            return
        ink = cairo_rgba(t["ink"])
        ctx.set_source_rgba(ink[0], ink[1], ink[2], 1 - q)
        ctx.set_line_width(6 * (1 - q))
        _rounded(ctx, 0, 0, w, h, t["radius"])
        ctx.stroke()
        ctx.set_source_rgba(ink[0], ink[1], ink[2], 1)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.set_line_width(3)
        reach = 6 + 16 * _out(q)
        length = 12 * (1 - q)
        for cx, cy, sx, sy in ((0, 0, 1, 1), (w, h, -1, -1), (w, 0, -1, 1), (0, h, 1, -1)):
            for angle in (0.25, 0.785, 1.32):
                dx, dy = math.cos(angle) * sx, math.sin(angle) * sy
                ox, oy = cx + sx * 10, cy + sy * 10
                ctx.move_to(ox + dx * reach, oy + dy * reach)
                ctx.line_to(ox + dx * (reach + length), oy + dy * (reach + length))
        ctx.stroke()



def write_icon_svg(path):
    """Icône de l'app (dégradé du Verre sur fond sombre), pour le fichier .desktop."""
    side = 200
    cx = cy = side / 2
    r = side * RING_RADIUS
    a0, a1 = START, START + SPAN
    x0, y0 = cx + r * math.cos(a0), cy + r * math.sin(a0)
    x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
    stops = "".join(f'<stop offset="{i / 3:.2f}" stop-color="{c}"/>' for i, c in enumerate(GLASS_COLORS))
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">
<defs><linearGradient id="g" x1="0.12" y1="0.92" x2="0.9" y2="0.08">{stops}</linearGradient>
<linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#26232F"/>
<stop offset="1" stop-color="#0E0D13"/></linearGradient></defs>
<rect x="8" y="8" width="240" height="240" rx="56" fill="url(#bg)"/>
<g transform="translate(28 28)">
<path d="M {x0:.2f} {y0:.2f} A {r:.2f} {r:.2f} 0 1 1 {x1:.2f} {y1:.2f}" fill="none" stroke="url(#g)"
 stroke-width="{side * STROKE:.2f}" stroke-linecap="round"/>
<circle cx="{side * DOT_CENTER[0]:.2f}" cy="{side * DOT_CENTER[1]:.2f}" r="{side * DOT_RADIUS:.2f}" fill="#fff"/>
</g></svg>
"""
    with open(path, "w") as f:
        f.write(svg)
