"""Les réponses de l'IA en GTK (MarkdownText de Markdown.swift) : chaque bloc Markdown devient un widget — titres,
listes, cases à cocher, citations, code, tableaux, filets — et les formules LaTeX sont composées par latex.py, puis
dessinées en vectoriel à la couleur du texte (l'encre du style).

Dans un paragraphe, une formule simple s'écrit en caractères Unicode (sélectionnable) ; une autre (fraction, racine…)
est posée sur la ligne de base du texte : Pango lui réserve sa place (attribut de forme) et elle est dessinée par-dessus.
Pendant que la réponse arrive, seuls les blocs qui ont changé sont reconstruits."""
from html import escape

from gi.repository import Gdk, GLib, Gtk, Pango, PangoCairo

from . import latex, markdown

BODY = 13.5          # taille du texte des réponses (.hello-agent)
PLACEHOLDER = "\uFFFC"


def _children(widget):
    child = widget.get_first_child()
    while child:
        yield child
        child = child.get_next_sibling()


def _ink(widget):
    try:
        color = widget.get_color()
        return color.red, color.green, color.blue, color.alpha
    except AttributeError:   # GTK < 4.10
        return 0.9, 0.9, 0.9, 1


def _copy(text):
    display = Gdk.Display.get_default()
    if display:
        display.get_clipboard().set(text)


def inline_math_markup(latex_text, size):
    """Une formule simple en caractères (𝑥² + 𝑦₁), à la police mathématique ; None si elle doit être composée."""
    plain = latex.plain(latex_text)
    if plain is None:
        return None
    return (f'<span font_family="{escape(latex.MATH_FAMILY)}" size="112%">'
            f"{escape(plain, quote=False)}</span>")


class Formula(Gtk.DrawingArea):
    """Formule composée sur sa propre ligne, centrée. Clic droit : copier le LaTeX."""

    def __init__(self, source, size=16):
        super().__init__()
        self.source = source.strip()
        self.box = latex.render(source, size, True)
        self.add_css_class("hello-md-formula")
        width = int(self.box.width + 4) if self.box else 0
        height = int(self.box.ascent + self.box.descent + 6) if self.box else 0
        self.set_content_width(width)
        self.set_content_height(height)
        self.set_size_request(width, height)
        self.set_halign(Gtk.Align.CENTER)
        self.set_tooltip_text(self.source)
        self.set_draw_func(self._draw)
        click = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        click.connect("pressed", lambda *_: _copy(self.source))
        self.add_controller(click)

    def _draw(self, _area, ctx, width, height):
        if not self.box:
            return
        ctx.set_source_rgba(*_ink(self))
        x = max((width - self.box.width) / 2, 2)
        self.box.draw(ctx, x, 3 + self.box.ascent)


def formula_block(source):
    """La formule, ou son LaTeX en chasse fixe si elle ne se compose pas ; trop large, elle défile."""
    formula = Formula(source)
    if formula.box is None:
        return text_label(escape(source), "hello-md-codetext")
    scroller = Gtk.ScrolledWindow(child=formula)
    scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
    scroller.set_propagate_natural_height(True)
    scroller.set_propagate_natural_width(False)
    scroller.set_hexpand(True)
    scroller.add_css_class("hello-md-formula-scroll")
    return scroller


class RichText(Gtk.Widget):
    """Un paragraphe avec des formules composées dans le texte : le balisage Pango, et pour chaque formule une forme
    (attribut Pango) de sa taille exacte, sur laquelle elle est dessinée. Renvoie à la ligne comme un label."""

    def __init__(self, markup, formulas, css=None, xalign=0.0):
        super().__init__()
        self.formulas = formulas   # [(Box, latex)]
        for c in (css or "").split():
            self.add_css_class(c)
        self.layout = self.create_pango_layout(None)
        self.layout.set_wrap(Pango.WrapMode.WORD_CHAR)
        self.layout.set_alignment(Pango.Alignment.CENTER if xalign == 0.5 else Pango.Alignment.RIGHT if xalign == 1
                                  else Pango.Alignment.LEFT)
        self.layout.set_markup(markup, -1)
        self._offsets = []
        text = self.layout.get_text()
        attrs = self.layout.get_attributes() or Pango.AttrList()
        raw = text.encode("utf-8")
        start = 0
        placeholder = PLACEHOLDER.encode("utf-8")
        for box, _source in formulas:
            index = raw.find(placeholder, start)
            if index < 0:
                break
            start = index + len(placeholder)
            rect = Pango.Rectangle()
            rect.x = 0
            rect.y = -int((box.ascent + 1) * Pango.SCALE)
            rect.width = int((box.width + 2) * Pango.SCALE)
            rect.height = int((box.ascent + box.descent + 2) * Pango.SCALE)
            attr = Pango.attr_shape_new(rect, rect)
            attr.start_index = index
            attr.end_index = start
            attrs.insert(attr)
            self._offsets.append(index)
        self.layout.set_attributes(attrs)
        self.set_tooltip_text("\n".join(source for _, source in formulas) or None)
        click = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        click.connect("pressed", lambda *_: _copy("\n".join(source for _, source in formulas)))
        self.add_controller(click)

    def do_get_request_mode(self):
        return Gtk.SizeRequestMode.HEIGHT_FOR_WIDTH

    def do_measure(self, orientation, for_size):
        layout = self.layout
        if orientation == Gtk.Orientation.HORIZONTAL:
            layout.set_width(-1)
            _, logical = layout.get_pixel_extents()
            widest = max((box.width for box, _ in self.formulas), default=0)
            return int(min(logical.width, max(widest + 2, 60))), logical.width, -1, -1
        layout.set_width(for_size * Pango.SCALE if for_size > 0 else -1)
        _, logical = layout.get_pixel_extents()
        return logical.height, logical.height, -1, -1

    def do_size_allocate(self, width, height, baseline):
        self.layout.set_width(width * Pango.SCALE)

    def do_snapshot(self, snapshot):
        from gi.repository import Graphene
        width, height = self.get_width(), self.get_height()
        rect = Graphene.Rect().init(0, 0, width, height)
        ctx = snapshot.append_cairo(rect)
        ink = _ink(self)
        ctx.set_source_rgba(*ink)
        self.layout.set_width(width * Pango.SCALE)
        PangoCairo.update_layout(ctx, self.layout)
        # Plus de place que le texte (cellule d'un tableau) : centré verticalement, comme un label.
        _, logical = self.layout.get_pixel_extents()
        top = max((height - logical.height) / 2, 0)
        ctx.translate(0, top)
        ctx.move_to(0, 0)
        PangoCairo.show_layout(ctx, self.layout)
        # Lignes de base, pour poser chaque formule à la sienne.
        baselines = []
        it = self.layout.get_iter()
        while True:
            baselines.append(it.get_baseline() / Pango.SCALE)
            if not it.next_line():
                break
        for (box, _), index in zip(self.formulas, self._offsets):
            pos = self.layout.index_to_pos(index)
            line, _x = self.layout.index_to_line_x(index, False)
            baseline = baselines[min(line, len(baselines) - 1)]
            ctx.set_source_rgba(*ink)
            box.draw(ctx, pos.x / Pango.SCALE + 1, baseline)


def text_label(markup, css=None, xalign=0.0):
    label = Gtk.Label()
    label.set_use_markup(True)
    try:
        label.set_markup(markup)
    except GLib.Error:
        label.set_text(markup)
    label.set_wrap(True)
    label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    label.set_xalign(xalign)
    label.set_selectable(True)
    label.set_can_focus(False)
    label.set_hexpand(True)
    for c in (css or "").split():
        label.add_css_class(c)
    return label


def inline(text, size=BODY, css=None, wrap_markup=None, xalign=0.0):
    """Texte en ligne : le Markdown (gras, italique, code, liens) et les formules, à la taille du texte."""
    pieces = markdown.split(text)
    parts = []
    formulas = []
    for piece in pieces:
        if piece[0] == "markdown":
            parts.append(markdown.inline_markup(piece[1]))
            continue
        _, source, display = piece
        simple = None if display else inline_math_markup(source, size)
        if simple is not None:
            parts.append(simple)
            continue
        box = latex.render(source, size * 1.1, display)
        if box is None:
            parts.append(f"<tt>{escape(source, quote=False)}</tt>")
        else:
            parts.append(PLACEHOLDER)
            formulas.append((box, source))
    markup = "".join(parts)
    if wrap_markup:
        markup = wrap_markup(markup)
    if not formulas:
        return text_label(markup, css, xalign)
    widget = RichText(markup, formulas, css, xalign)
    widget.set_hexpand(True)
    return widget


# MARK: - Blocs

def _code(content, language):
    box = Gtk.Overlay()
    text = text_label(escape(content, quote=False), "hello-md-codetext")
    frame = Gtk.Box()
    frame.add_css_class("hello-md-code")
    frame.append(text)
    box.set_child(frame)
    if language:
        tag = Gtk.Label(label=language.lower())
        tag.add_css_class("hello-md-lang")
        tag.set_halign(Gtk.Align.END)
        tag.set_valign(Gtk.Align.START)
        tag.set_can_target(False)
        box.add_overlay(tag)
    return box


def _table(table):
    columns = max([len(table.header)] + [len(r) for r in table.rows])
    grid = Gtk.Grid()
    grid.add_css_class("hello-md-table")
    grid.set_overflow(Gtk.Overflow.HIDDEN)
    grid.set_hexpand(True)

    def cell(text, column, row, header):
        align = table.align[column] if column < len(table.align) else "leading"
        xalign = {"leading": 0.0, "center": 0.5, "trailing": 1.0}[align]
        widget = inline(text, 12.5, "hello-md-cell" + (" head" if header else "") + (" first" if row == 1 else ""),
                        (lambda m: f"<b>{m}</b>") if header else None, xalign)
        if isinstance(widget, Gtk.Label):
            widget.set_justify({"leading": Gtk.Justification.LEFT, "center": Gtk.Justification.CENTER,
                                "trailing": Gtk.Justification.RIGHT}[align])
        widget.set_hexpand(True)
        widget.set_valign(Gtk.Align.FILL)
        grid.attach(widget, column, row, 1, 1)

    for column in range(columns):
        cell(table.header[column] if column < len(table.header) else "", column, 0, True)
    for r, values in enumerate(table.rows, start=1):
        for column in range(columns):
            cell(values[column] if column < len(values) else "", column, r, False)
    # Pas de défilement horizontal : mesuré à sa largeur minimale, le tableau prenait la hauteur de cellules repliées
    # mot par mot. Trop large, ses cellules passent à la ligne.
    return grid


def block_widget(block):
    kind = block[0]
    if kind == "heading":
        level, content = block[1], block[2]
        size = 17 if level == 1 else 15 if level == 2 else 14
        widget = inline(content, size, f"hello-md-h{min(level, 3)}")
        return widget
    if kind == "bullet":
        _, indent, marker, content = block
        row = Gtk.Box(spacing=8)
        row.set_margin_start(indent * 16)
        mark = Gtk.Label(label=marker)
        mark.add_css_class("hello-md-marker")
        mark.set_valign(Gtk.Align.START)
        mark.set_yalign(0)
        row.append(mark)
        row.append(inline(content))
        return row
    if kind == "task":
        _, indent, done, content = block
        row = Gtk.Box(spacing=7)
        row.set_margin_start(indent * 16)
        mark = Gtk.Label(label="☑" if done else "☐")
        mark.add_css_class("hello-md-marker")
        mark.set_valign(Gtk.Align.START)
        row.append(mark)
        row.append(inline(content, css="hello-md-done" if done else None,
                          wrap_markup=(lambda m: f"<s>{m}</s>") if done else None))
        return row
    if kind == "quote":
        box = Gtk.Box()
        box.add_css_class("hello-md-quote")
        box.append(inline(block[1], css="hello-md-quotetext"))
        return box
    if kind == "code":
        return _code(block[1], block[2])
    if kind == "math":
        return formula_block(block[1])
    if kind == "table":
        return _table(block[1])
    if kind == "rule":
        rule = Gtk.Box()
        rule.add_css_class("hello-md-rule")
        return rule
    return inline(block[1])


class MarkdownView(Gtk.Box):
    """Une réponse de l'IA. `set_text` peut être appelé à chaque mot reçu : les blocs déjà affichés et inchangés
    sont gardés."""

    def __init__(self, css=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.add_css_class("hello-md")
        for c in (css or "").split():
            self.add_css_class(c)
        self.set_hexpand(True)
        self._blocks = []    # [(bloc, widget)]
        self._raw = None

    def set_text(self, text):
        if text == self._raw:
            return
        self._raw = text
        self._show(markdown.parse(text or ""))

    def set_plain(self, text, monospace=False):
        """Texte brut (erreur, délégation au terminal) : sans Markdown."""
        key = ("plain", monospace, text)
        if self._raw == key:
            return
        self._raw = key
        self._show([("plain", text, monospace)])

    def _show(self, blocks):
        keep = 0
        while keep < len(blocks) and keep < len(self._blocks) and self._blocks[keep][0] == blocks[keep]:
            keep += 1
        for _, widget in self._blocks[keep:]:
            self.remove(widget)
        self._blocks = self._blocks[:keep]
        for block in blocks[keep:]:
            if block[0] == "plain":
                widget = text_label(escape(block[1], quote=False), "hello-md-codetext" if block[2] else None)
            else:
                widget = block_widget(block)
            if block[0] == "heading":
                widget.set_margin_top(4)
            self.append(widget)
            self._blocks.append((block, widget))
