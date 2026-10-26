"""Atelier Glyphe : textes et icônes qui se décodent en ASCII (DecodeText, AsciiReveal de Motion.swift).

Le titre se décode à sa place, de gauche à droite : chaque lettre monte en densité (. : = # @), passe par quelques
glyphes puis se fige. L'icône se décode de même, sous une trame de cases, en diagonale depuis le coin haut gauche."""
import time

from gi.repository import GLib

RAMP = ".:-=+*#%@"
GLYPHS = "ABCDEFGHJKLMNPQRSTUVWXYZ0123456789#%&*+=?/"
MASK = 0xFFFFFFFFFFFFFFFF


def noise(a, b, tick):
    """Bruit déterministe dans [0, 1) : le même point (ou la même lettre) garde sa valeur pendant un « tick »."""
    h = ((a * 73_856_093) ^ (b * 19_349_663) ^ (tick * 83_492_791)) & MASK
    h = ((h ^ (h >> 13)) * 0x5BD1E995) & MASK
    h ^= h >> 15
    return (h % 10_000) / 10_000


def duration(text, quick=False):
    """Les titres longs prennent un peu plus de temps, sans dépasser 0,6 s (0,3 s pour la version brève)."""
    return min(0.16 + len(text) * 0.006, 0.3) if quick else min(0.3 + len(text) * 0.012, 0.6)


def symbol(phase, a, b, tick):
    """Caractère d'une lettre (ou d'une case d'icône) en cours de décodage : la rampe de densité, puis des glyphes
    qui défilent jusqu'à ce qu'elle se fige."""
    if phase < 0.45:
        return RAMP[min(len(RAMP) - 1, int(max(phase, 0) / 0.45 * len(RAMP)))]
    return GLYPHS[int(noise(a, b, tick) * len(GLYPHS)) % len(GLYPHS)]


def frame(text, progress):
    """Le texte à `progress` (0 à 1) : chaque lettre a sa fenêtre, décalée de gauche à droite."""
    count = max(len(text), 1)
    window = 0.4
    tick = int(max(progress, 0) * 26)
    out = []
    for i, char in enumerate(text):
        settle = window + (1 - window) * i / count
        phase = (progress - settle + window) / window
        if char == " " or progress >= settle:
            out.append(char)
        elif phase < 0:
            out.append(" ")
        else:
            out.append(symbol(phase, i, 0, tick))
    return "".join(out)


def wave_delay(order):
    """Départ d'une ligne dans la cascade de l'ouverture (34 ms d'un élément au suivant, comme l'artifact)."""
    return 0.06 + min(order, 12) * 0.034


class Decoder:
    """Anime les labels et les trames d'icônes en cours de décodage, sur un seul minuteur (~30 images/s)."""

    def __init__(self, speed=lambda: 1.0):
        self.speed = speed
        self._labels = {}   # label -> (texte, début, durée)
        self._covers = {}   # zone de dessin -> (début, durée)
        self._source = None

    def text(self, label, text, delay=0.0, quick=False):
        """Décode `text` dans `label`, après `delay` secondes."""
        if not text:
            label.set_label(text or "")
            return
        length = duration(text, quick) / self.speed()
        self._labels[label] = (text, time.monotonic() + delay, length)
        label.set_label(frame(text, 0))
        self._run()

    def icon(self, cover, delay=0.0, quick=False):
        cover.progress = 0.0
        self._covers[cover] = (time.monotonic() + delay, (0.24 if quick else 0.42) / self.speed())
        cover.queue_draw()
        self._run()

    def cancel(self):
        for label, (text, _, _) in self._labels.items():
            label.set_label(text)
        for cover in self._covers:
            cover.progress = 1.0
            cover.queue_draw()
        self._labels.clear()
        self._covers.clear()

    def _run(self):
        if self._source is None:
            self._source = GLib.timeout_add(33, self._tick)

    def _tick(self):
        now = time.monotonic()
        for label, (text, start, length) in list(self._labels.items()):
            progress = (now - start) / length
            if progress >= 1:
                label.set_label(text)
                del self._labels[label]
            elif progress >= 0:
                label.set_label(frame(text, progress))
        for cover, (start, length) in list(self._covers.items()):
            cover.progress = min(1.0, max(0.0, (now - start) / length))
            cover.queue_draw()
            if cover.progress >= 1:
                del self._covers[cover]
        if not self._labels and not self._covers:
            self._source = None
            return False
        return True


def draw_cover(ctx, width, height, progress, background, ink):
    """Trame posée sur une icône : les cases pas encore décodées sont recouvertes (couleur du fond) et montrent
    leur caractère ; les autres laissent voir l'image. Cases d'environ 5 px, entre 4 et 9 par côté."""
    if progress >= 1:
        return
    import cairo
    n = max(4, min(9, round(min(width, height) / 5)))
    w, h = width / n, height / n
    window = 0.45
    tick = int(max(progress, 0) * 26)
    ctx.select_font_face("monospace", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(h * 1.2)
    for row in range(n):
        for column in range(n):
            order = (column + row) / (2 * (n - 1))
            settle = window + (1 - window) * (0.7 * order + 0.3 * noise(column, row, 7))
            if progress >= settle:
                continue
            x, y = column * w, row * h
            ctx.set_source_rgba(*background)
            # Un rien plus grandes : pas de joint entre deux cases voisines.
            ctx.rectangle(x - 0.5, y - 0.5, w + 1, h + 1)
            ctx.fill()
            phase = (progress - settle + window) / window
            if phase < 0:
                continue
            char = symbol(phase, column, row, tick)
            ext = ctx.text_extents(char)
            ctx.set_source_rgba(*ink)
            ctx.move_to(x + (w - ext.x_advance) / 2, y + h * 0.85)
            ctx.show_text(char)

