"""Icônes d'apps de la Nuit (Atelier Glyphe), au trait (IconTrace.swift et IconOutline de Styles.swift), et leur
version ASCII pour le fondu des grilles (AsciiArt de Motion.swift).

Le contour : un filet le long du bord intérieur de la partie opaque de l'icône (son ombre portée, à moitié
transparente, n'en fait pas partie), et au besoin ses traits intérieurs, comme un dessin à l'encre : différence de deux
flous gaussiens (XDoG, la technique classique du rendu « au trait »). Chaque bord donne un seul trait, posé de son côté
sombre, d'épaisseur régulière et adouci par nature. Avant : le contraste de l'icône est étiré (une icône grise sur gris
garde ses formes) et son bord est prolongé vers l'extérieur (le filet s'occupe du bord). Après : les taches isolées
sont retirées. Le résultat est un masque (opacité seule), teint à l'encre du style au dessin.

Calculé hors du fil principal (deux calculs à la fois : une page de grille en demande des dizaines d'un coup), avec
numpy ; sans numpy, les icônes restent simplement atténuées."""
import threading
from concurrent.futures import ThreadPoolExecutor

try:
    import numpy as np
except ImportError:   # pragma: no cover - numpy est presque toujours là
    np = None

RAMP = " .:-=+*#%@"
ASCII_SIDE = 12


def available():
    return np is not None


# MARK: - Calcul (tableaux numpy, rangées de haut en bas)

def _shift(array, dx, dy, fill):
    """result[y, x] = array[y + dy, x + dx], `fill` hors de l'image."""
    h, w = array.shape
    out = np.full_like(array, fill)
    ys = slice(max(0, -dy), min(h, h - dy))
    xs = slice(max(0, -dx), min(w, w - dx))
    ys2 = slice(max(0, dy), min(h, h + dy))
    xs2 = slice(max(0, dx), min(w, w + dx))
    out[ys, xs] = array[ys2, xs2]
    return out


def _blur(values, sigma):
    """Flou gaussien séparable, bords prolongés."""
    radius = max(int(np.ceil(sigma * 3)), 1)
    k = np.exp(-(np.arange(-radius, radius + 1) ** 2) / (2 * sigma * sigma)).astype(np.float32)
    k /= k.sum()
    h, w = values.shape
    padded = np.pad(values, ((0, 0), (radius, radius)), mode="edge")
    rows = sum(k[i] * padded[:, i:i + w] for i in range(2 * radius + 1))
    padded = np.pad(rows, ((radius, radius), (0, 0)), mode="edge")
    return sum(k[i] * padded[i:i + h, :] for i in range(2 * radius + 1))


def _extend_outward(values, inside, passes):
    """Prolonge les valeurs du bord vers l'extérieur (moyenne des voisins déjà connus, passe après passe) : le
    contour de l'icône ne fait pas de trait, seul ce qui est dedans en fait."""
    known = inside.copy()
    values = values.copy()
    for _ in range(passes):
        total = np.zeros_like(values)
        count = np.zeros_like(values)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            k = _shift(known, dx, dy, False)
            total += np.where(k, _shift(values, dx, dy, 0.0), 0.0)
            count += k
        update = ~known & (count > 0)
        if not update.any():
            break
        values[update] = total[update] / count[update]
        known |= update
    return values


def _remove_specks(ink, min_area):
    """Retire les taches d'encre (pixels encrés qui se touchent) plus petites que `min_area` pixels : grain,
    reflets et bouts de texture."""
    h, w = ink.shape
    flat = ink.ravel()
    marked = np.flatnonzero(flat > 0.05)
    if marked.size == 0:
        return ink
    pending = set(marked.tolist())
    while pending:
        start = pending.pop()
        stack = [start]
        group = [start]
        weight = 0.0
        while stack:
            index = stack.pop()
            weight += flat[index]
            y, x = divmod(index, w)
            for ny in (y - 1, y, y + 1):
                if ny < 0 or ny >= h:
                    continue
                for nx in (x - 1, x, x + 1):
                    if nx < 0 or nx >= w:
                        continue
                    n = ny * w + nx
                    if n in pending:
                        pending.discard(n)
                        stack.append(n)
                        group.append(n)
        if weight < min_area:
            flat[group] = 0
    return flat.reshape(h, w)


def lines(rgba, detail, width):
    """Traits intérieurs (0…1), même taille que `rgba` (couleurs 0…1 non prémultipliées, opacité 0…1).
    `detail` (0…1) : seuil du trait et taille minimale d'une tache gardée. `width` : épaisseur, en pixels."""
    detail = min(max(detail, 0.0), 1.0)
    side = rgba.shape[0]
    alpha8 = np.round(rgba[..., 3] * 255)
    inside = alpha8 >= 128
    if inside.sum() <= side:
        return None
    r, g, b = rgba[..., 0], rgba[..., 1], rgba[..., 2]
    luma = np.sqrt(0.2126 * r * r + 0.7152 * g * g + 0.0722 * b * b).astype(np.float32)
    # Contraste étiré entre les 2 % les plus sombres et les 2 % les plus clairs (pas au-delà de ×4 : une icône
    # presque unie ne doit pas faire ressortir son grain).
    values = np.sort(luma[inside])
    low = values[values.size // 50]
    high = values[values.size - 1 - values.size // 50]
    spread = max(high - low, 0.25)
    luma = np.where(inside, np.clip((luma - low) / spread, 0, 1), 0).astype(np.float32)
    luma = _extend_outward(luma, inside, int(width * 3) + 4)
    # XDoG : flou fin moins flou large. Positif du côté sombre d'un bord, d'autant plus que le bord contraste.
    sigma = width * 0.55
    response = _blur(luma, sigma * 1.6) - _blur(luma, sigma)
    threshold = 0.05 - 0.035 * detail
    soft = threshold * 0.6
    t = np.clip((response - threshold) / soft + 0.5, 0, 1)
    ink = np.where(inside, t * t * (3 - 2 * t), 0).astype(np.float32)
    return _remove_specks(ink, int(width * width * (14 - 10 * detail)))


def outline(rgba, radius, detail=None, line_width=3.0):
    """Masque du dessin (0…1) : chaque pixel opaque à moins de `radius` pixels du dehors fait partie du filet ; le
    bord intérieur est adouci selon la distance, le bord extérieur reprend celui de l'icône. `detail` : s'y
    ajoutent les traits intérieurs (au-delà du filet, pour ne pas le doubler)."""
    alpha8 = np.round(rgba[..., 3] * 255)
    inside = alpha8 >= 128
    reach = int(np.ceil(radius)) + 1
    offsets = sorted(((dx, dy, (dx * dx + dy * dy) ** 0.5) for dy in range(-reach, reach + 1)
                      for dx in range(-reach, reach + 1) if (dx or dy) and (dx * dx + dy * dy) ** 0.5 <= reach),
                     key=lambda o: o[2])
    # Distance au premier pixel du dehors, du plus proche au plus loin.
    nearest = np.full(inside.shape, reach + 1.0, dtype=np.float32)
    unknown = np.ones(inside.shape, dtype=bool)
    for dx, dy, distance in offsets:
        hit = unknown & ~_shift(inside, dx, dy, False)
        nearest[hit] = distance
        unknown &= ~hit
    value = np.where(inside, np.clip(radius + 0.5 - nearest, 0, 1), 0).astype(np.float32)
    if detail is not None:
        drawn = lines(rgba, detail, line_width)
        if drawn is not None:
            value = np.where(inside, np.maximum(value, drawn), value)
    # Bord adouci de l'icône, juste contre sa partie opaque.
    touches = np.zeros(inside.shape, dtype=bool)
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        touches |= _shift(inside, dx, dy, False)
    edge = ~inside & (alpha8 >= 40) & touches
    value = np.where(edge, alpha8 / 128, value)
    return np.clip(value, 0, 1)


def ascii_cells(premultiplied):
    """Version ASCII d'une image réduite à ASCII_SIDE × ASCII_SIDE (liste de rangées de (r, g, b, a) prémultipliés,
    0…255) : chaque case prend le caractère de la rampe qui correspond à sa densité (opacité × clarté)."""
    cells = []
    for row, pixels in enumerate(premultiplied):
        for column, (r, g, b, a) in enumerate(pixels):
            alpha = a / 255
            if alpha <= 0.02:
                continue
            light = (0.3 * r + 0.59 * g + 0.11 * b) / 255 / alpha
            density = alpha * (0.35 + 0.65 * min(light, 1))
            index = min(len(RAMP) - 1, int(density * (len(RAMP) - 1) + 0.5))
            if index > 0:
                cells.append((row, column, RAMP[index]))
    return cells


# MARK: - Images

def load_rgba(path, side):
    """L'icône dans un carré de `side` pixels (proportions gardées, centrée) : tableau (side, side, 4), 0…1."""
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf
    if path.startswith("resource://"):
        pixbuf = GdkPixbuf.Pixbuf.new_from_resource_at_scale(path[len("resource://"):], side, side, True)
    else:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, side, side, True)
    if pixbuf is None:
        return None
    if pixbuf.get_width() != side or pixbuf.get_height() != side:
        # Pas carrée (ou pas encore à la taille) : posée au centre d'un carré transparent, comme GTK l'affiche.
        scale = min(side / pixbuf.get_width(), side / pixbuf.get_height())
        w, h = max(1, round(pixbuf.get_width() * scale)), max(1, round(pixbuf.get_height() * scale))
        scaled = pixbuf.scale_simple(w, h, GdkPixbuf.InterpType.HYPER)
        canvas = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, side, side)
        canvas.fill(0)
        scaled.copy_area(0, 0, w, h, canvas, (side - w) // 2, (side - h) // 2)
        pixbuf = canvas
    if not pixbuf.get_has_alpha():
        pixbuf = pixbuf.add_alpha(False, 0, 0, 0)
    data = pixbuf.read_pixel_bytes().get_data()
    stride = pixbuf.get_rowstride()
    if np is None:
        return (data, stride, side)
    array = np.frombuffer(data, dtype=np.uint8, count=stride * (side - 1) + side * 4)
    array = np.lib.stride_tricks.as_strided(array, shape=(side, side, 4), strides=(stride, 4, 1))
    return array.astype(np.float32) / 255


def _premultiplied_cells_from_rgba(rgba):
    """Réduction à ASCII_SIDE cases par côté : la couleur moyenne (prémultipliée) de chaque case."""
    side = rgba.shape[0]
    n = ASCII_SIDE
    step = side // n
    pre = rgba[: step * n, : step * n].copy()
    pre[..., :3] *= pre[..., 3:4]
    small = pre.reshape(n, step, n, step, 4).mean(axis=(1, 3)) * 255
    return [[tuple(float(v) for v in small[r, c]) for c in range(n)] for r in range(n)]


def _premultiplied_cells_plain(data, stride, side):
    n = ASCII_SIDE
    step = side // n
    out = []
    for r in range(n):
        row = []
        for c in range(n):
            acc = [0.0, 0.0, 0.0, 0.0]
            for y in range(r * step, (r + 1) * step):
                base = y * stride
                for x in range(c * step, (c + 1) * step):
                    i = base + x * 4
                    a = data[i + 3] / 255
                    acc[0] += data[i] * a
                    acc[1] += data[i + 1] * a
                    acc[2] += data[i + 2] * a
                    acc[3] += data[i + 3]
            count = step * step
            row.append(tuple(v / count for v in acc))
        out.append(row)
    return out


def ascii_for_file(path):
    loaded = load_rgba(path, ASCII_SIDE * 4)
    if loaded is None:
        return None
    if np is not None:
        return ascii_cells(_premultiplied_cells_from_rgba(loaded))
    return ascii_cells(_premultiplied_cells_plain(*loaded))


def ascii_for_char(char):
    """Un emoji ou un symbole dessiné seul, centré (les emoji gardent leurs couleurs), réduit en ASCII.
    Sur le fil principal (Pango)."""
    import cairo
    import gi
    gi.require_version("PangoCairo", "1.0")
    from gi.repository import Pango, PangoCairo
    px = ASCII_SIDE * 6
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, px, px)
    ctx = cairo.Context(surface)
    layout = PangoCairo.create_layout(ctx)
    font = Pango.FontDescription.from_string("sans")
    font.set_absolute_size(px * 0.72 * Pango.SCALE)
    layout.set_font_description(font)
    layout.set_text(char, -1)
    ink, _ = layout.get_pixel_extents()
    if ink.width <= 0 or ink.height <= 0:
        return None
    ctx.set_source_rgb(1, 1, 1)
    ctx.move_to((px - ink.width) / 2 - ink.x, (px - ink.height) / 2 - ink.y)
    PangoCairo.show_layout(ctx, layout)
    surface.flush()
    data = surface.get_data()
    stride = surface.get_stride()
    n = ASCII_SIDE
    step = px // n
    rows = []
    for r in range(n):
        row = []
        for c in range(n):
            acc = [0, 0, 0, 0]
            for y in range(r * step, (r + 1) * step):
                base = y * stride
                for x in range(c * step, (c + 1) * step):
                    i = base + x * 4
                    # ARGB32 natif (petit-boutiste) : B, G, R, A prémultipliés.
                    acc[0] += data[i + 2]
                    acc[1] += data[i + 1]
                    acc[2] += data[i]
                    acc[3] += data[i + 3]
            count = step * step
            row.append(tuple(v / count for v in acc))
        rows.append(row)
    return ascii_cells(rows)


# MARK: - Caches et calculs en arrière-plan

class Kind:
    """Taille de calcul et épaisseurs : le dessin garde le même trait à l'écran, quelle que soit la taille de l'icône
    (lignes de la liste ≈ 26 px, cases de la grille ≈ 64 px)."""
    __slots__ = ("large", "detail")

    def __init__(self, large, detail):
        self.large = large
        self.detail = detail

    @property
    def side(self):
        return 256 if self.large else 128

    @property
    def radius(self):
        return 4.8 if self.large else 4.5

    @property
    def line_width(self):
        return 2.7 if self.large else 2.6

    @property
    def key(self):
        return ("L" if self.large else "S") + ("" if self.detail is None else f"{self.detail:.2f}")


_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="hello-outline")
_lock = threading.Lock()
_outlines = {}    # (kind.key, chemin) -> (octets A8, pas, côté) ou None (icône illisible)
_MISSING = object()
_ascii = {}       # chemin ou "C:" + caractère -> cases


def cached_outline(path, kind):
    """Le contour s'il est déjà calculé, None s'il n'y en a pas, _MISSING s'il reste à calculer."""
    with _lock:
        return _outlines.get((kind.key, path), _MISSING)


def _outline_bytes(path, kind):
    rgba = load_rgba(path, kind.side)
    if rgba is None:
        return None
    mask = outline(rgba, kind.radius, kind.detail, kind.line_width)
    side = kind.side
    stride = (side + 3) & ~3   # pas d'une image A8 de Cairo (multiple de 4)
    out = np.zeros((side, stride), dtype=np.uint8)
    out[:, :side] = np.round(mask * 255).astype(np.uint8)
    return bytearray(out.tobytes()), stride, side


def request_outline(path, kind, done):
    """`done(résultat)` sur le fil principal (résultat : None si l'icône ne se lit pas). Renvoie une fonction qui
    annule le calcul s'il n'a pas commencé (case sortie de l'écran)."""
    from gi.repository import GLib
    if np is None or not path:
        return lambda: None
    key = (kind.key, path)
    with _lock:
        if key in _outlines:
            hit = _outlines[key]
            GLib.idle_add(lambda: (done(hit), False)[1])
            return lambda: None

    def work():
        with _lock:
            result = _outlines.get(key, _MISSING)
        if result is _MISSING:
            try:
                result = _outline_bytes(path, kind)
            except Exception:   # icône illisible : pas de contour, l'icône reste atténuée
                result = None
            with _lock:
                if len(_outlines) > 600:
                    _outlines.clear()
                _outlines[key] = result
        GLib.idle_add(lambda: (done(result), False)[1])
    future = _executor.submit(work)
    return future.cancel


def cached_ascii(key):
    with _lock:
        return _ascii.get(key)


def request_ascii(path, done=None):
    """Version ASCII d'une icône d'app, calculée à part ; `done(cases)` sur le fil principal."""
    from gi.repository import GLib
    with _lock:
        hit = _ascii.get(path)
    if hit is not None:
        if done:
            done(hit)
        return

    def work():
        try:
            cells = ascii_for_file(path) or []
        except Exception:
            cells = []
        with _lock:
            _ascii[path] = cells
        if done:
            GLib.idle_add(lambda: (done(cells), False)[1])
    _executor.submit(work)


def ascii_char(char):
    key = "C:" + char
    with _lock:
        hit = _ascii.get(key)
    if hit is None:
        try:
            hit = ascii_for_char(char) or []
        except Exception:
            hit = []
        with _lock:
            _ascii[key] = hit
    return hit


def icon_path(gicon, size):
    """Fichier de l'icône (thème, Flatpak, chemin) affichée pour ce GIcon ; None s'il n'y en a pas.
    Sur le fil principal (thème d'icônes)."""
    from gi.repository import Gdk, Gio, Gtk
    if gicon is None:
        return None
    if isinstance(gicon, Gio.FileIcon):
        return gicon.get_file().get_path()
    display = Gdk.Display.get_default()
    if display is None:
        return None
    try:
        paintable = Gtk.IconTheme.get_for_display(display).lookup_by_gicon(gicon, size, 1, Gtk.TextDirection.NONE, 0)
    except Exception:
        return None
    file = paintable.get_file() if paintable else None
    if file is None:
        return None
    uri = file.get_uri() or ""
    if uri.startswith("resource://"):
        return uri
    return file.get_path()
