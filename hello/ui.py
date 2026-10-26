"""Le panneau en GTK 4 (Views.swift) : en-tête de recherche, liste, grille d'applications, emoji,
aperçus, terminal, agent et pied de page avec les touches.

Sous Wayland, la fenêtre est une surface « layer-shell » qui couvre l'écran (transparente) : le panneau flotte
au-dessus de tout, un clic à côté le referme, et l'agrandissement vers la grille d'applications ne déplace rien."""
import math
import os
import re
from html import escape

from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from . import blur as blurmod
from . import decode, engines, shell, styles, usage
from .agent import Hermes
from .glyphs import FILTERS
from .mark import AnimatedMark, DotWave, Flourish, Sweep
from .model import EMPTY_TEXT, MODES, mode_title
from .settings import decodes, grid_columns, icon_size, motion_enabled, motion_speed, panel_size, settings
from .styles import ARRIVAL_ROWS, ARRIVALS, rgb, section_title, tokens
from .term import TermStyle, hex_color

try:
    from gi.repository import Gtk4LayerShell as LayerShell
except (ImportError, ValueError):
    LayerShell = None

HEADER, FOOTER = 60, 40


def layer_shell_supported():
    return LayerShell is not None and LayerShell.is_supported()


# MARK: - Petits composants

def keycap(text, primary=False):
    label = Gtk.Label(label=text)
    label.add_css_class("hello-key")
    if primary:
        label.add_css_class("primary")
    label.set_valign(Gtk.Align.CENTER)
    return label


def swatch(color, size):
    area = Gtk.DrawingArea()
    area.set_content_width(size)
    area.set_content_height(size)
    r, g, b = color

    def draw(_a, ctx, w, h):
        radius = min(w, h) * 0.28
        ctx.new_path()
        ctx.arc(w - radius, radius, radius, -math.pi / 2, 0)
        ctx.arc(w - radius, h - radius, radius, 0, math.pi / 2)
        ctx.arc(radius, h - radius, radius, math.pi / 2, math.pi)
        ctx.arc(radius, radius, radius, math.pi, 3 * math.pi / 2)
        ctx.close_path()
        ctx.set_source_rgb(r, g, b)
        ctx.fill_preserve()
        ctx.set_source_rgba(1, 1, 1, 0.18)
        ctx.set_line_width(1)
        ctx.stroke()

    area.set_draw_func(draw)
    return area


def icon_widget(icon, size):
    """Icône d'un élément : gicon (app), fichier, symbole teinté, couleur ou image."""
    kind = icon[0]
    if kind == "gicon":
        img = Gtk.Image.new_from_gicon(icon[1]) if icon[1] else Gtk.Image.new_from_icon_name(
            "application-x-executable")
        img.set_pixel_size(size)
        img.add_css_class("hello-appicon")
        return img
    if kind == "file":
        path = icon[1]
        gicon = None
        try:
            info = Gio.File.new_for_path(path).query_info("standard::icon", Gio.FileQueryInfoFlags.NONE, None)
            gicon = info.get_icon()
        except GLib.Error:
            pass
        img = Gtk.Image.new_from_gicon(gicon) if gicon else Gtk.Image.new_from_icon_name("text-x-generic")
        img.set_pixel_size(size)
        return img
    if kind == "color":
        return swatch(icon[1], size) if icon[1] else Gtk.Image.new_from_icon_name("image-missing")
    if kind == "image":
        pic = Gtk.Picture()
        if icon[1] and os.path.exists(icon[1]):
            pic.set_filename(icon[1])
        pic.set_content_fit(Gtk.ContentFit.COVER)
        pic.set_size_request(size, size)
        pic.set_can_shrink(True)
        frame = Gtk.Frame(child=pic)
        frame.set_size_request(size, size)
        frame.add_css_class("hello-tile")
        frame.set_overflow(Gtk.Overflow.HIDDEN)
        return frame
    # Symbole dans une pastille teintée (ou à l'encre pour les styles monochromes)
    _, name, color = icon
    t = tokens()
    img = Gtk.Image.new_from_icon_name(name)
    img.set_pixel_size(int(size * 0.58))
    box = Gtk.CenterBox()
    box.set_size_request(size, size)
    box.set_hexpand(False)
    box.set_halign(Gtk.Align.START)
    box.set_valign(Gtk.Align.CENTER)
    box.set_center_widget(img)
    if t.get("tile"):
        # Glyphe : carré aux coins doux qui s'arrondit et prend l'accent une fois choisi (styles.css).
        box.add_css_class("hello-gtile")
        return box
    provider = Gtk.CssProvider()
    r, g, b = rgb(color)
    if t["style"] == "phosphor":
        css = f"box {{ border: 1px solid {t['ink']}; border-radius: 4px; color: {t['ink']}; }}"
    elif t["style"] == "brutal":
        css = f"box {{ background: rgb({r},{g},{b}); border: 2px solid #000; border-radius: 8px; color: #000; }}"
    elif t["style"] == "atelier":
        css = f"box {{ background: {t['accent2']}; border-radius: 999px; color: #111112; }}"
    elif t["style"] == "paper":
        css = f"box {{ border: 1px solid alpha({t['ink']}, 0.25); border-radius: 6px; color: {t['accent']}; }}"
    else:
        css = (f"box {{ background: linear-gradient(to bottom, rgba({r},{g},{b},0.95), rgba({r},{g},{b},0.75)); "
               f"border-radius: {max(6, size // 4)}px; color: white; }}")
    provider.load_from_string(css)
    box.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)
    return box


class AsciiCover(Gtk.DrawingArea):
    """Trame de décodage posée sur une icône (Glyphe) ; `selected` : la ligne est sélectionnée (fond inversé)."""

    def __init__(self):
        super().__init__()
        self.set_can_target(False)
        self.progress = 1.0
        self.selected = False
        self.set_draw_func(self._draw)

    def _draw(self, _a, ctx, w, h):
        if self.progress >= 1:
            return
        t = tokens()
        background = _alpha(t["selection"] if self.selected else (t["pane"] or t["surface"]), 1)
        ink = _alpha(t["selection_ink"] if self.selected and t.get("selection_ink") else t["ink"], 1)
        decode.draw_cover(ctx, w, h, self.progress, (background.red, background.green, background.blue, 1),
                          (ink.red, ink.green, ink.blue, 1))


def covered(widget):
    """L'icône dans un calque, avec sa trame de décodage (Glyphe). Renvoie (calque, trame)."""
    overlay = Gtk.Overlay(child=widget)
    overlay.set_halign(widget.get_halign())
    overlay.set_valign(widget.get_valign())
    cover = AsciiCover()
    overlay.add_overlay(cover)
    return overlay, cover


def label(text, css=None, xalign=0.0, ellipsize=True, wrap=False, selectable=False):
    lbl = Gtk.Label(label=text or "")
    lbl.set_xalign(xalign)
    if ellipsize:
        lbl.set_ellipsize(Pango.EllipsizeMode.END)
        # Largeur naturelle minime : un long texte ne doit jamais élargir le panneau.
        lbl.set_max_width_chars(1)
    if wrap:
        lbl.set_wrap(True)
        lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if selectable:
        lbl.set_selectable(True)
    if css:
        for c in css.split():
            lbl.add_css_class(c)
    return lbl


def markdown_to_markup(text):
    """Markdown simple → balisage Pango : titres, gras, italique, code, liens, puces."""
    out = []
    in_code = False
    for line in text.split("\n"):
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            out.append(f"<tt>{escape(line)}</tt>")
            continue
        s = escape(line)
        s = re.sub(r"`([^`]+)`", r"<tt>\1</tt>", s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
        s = re.sub(r"(?<![*\w])\*([^*\n]+)\*(?!\w)", r"<i>\1</i>", s)
        s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', s)
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            size = {1: "x-large", 2: "large"}.get(len(m.group(1)), "medium")
            s = f'<span size="{size}" weight="bold">{m.group(2)}</span>'
        elif re.match(r"^\s*[-*]\s+", s):
            s = re.sub(r"^(\s*)[-*]\s+", r"\1•  ", s)
        out.append(s)
    return "\n".join(out)


# MARK: - Fenêtre

class LauncherWindow(Gtk.ApplicationWindow):
    def __init__(self, app, controller):
        super().__init__(application=app, title="Hello")
        self.c = controller
        self.model = controller.model
        self.add_css_class("hello-window")
        self.set_decorated(False)
        self.layer = layer_shell_supported()
        self._syncing_entry = False
        self._shown = None   # (mode, id(items)) du contenu affiché
        self._rows = []
        self._glyph_store = None
        self._panel_w, self._panel_h = panel_size()
        self._morph_anim = None
        self.apps_mode = False
        self.blur = None
        self._blur_tried = False
        self._blur_scheduled = False
        self.list = self.scrolled = self.carousel = self.preview = None
        self._preview_for = None
        self._glyph_selection = None
        self._held = set()           # touches enfoncées : une seconde pression sans relâcher est une répétition
        self.decoder = decode.Decoder(motion_speed)
        self._reveal_time = 0.0      # début de la dernière ouverture complète (la cascade de Glyphe part de là)
        self._decoded = (None, set())
        self._decoded_selection = None
        self._agent_shape = None

        if self.layer:
            LayerShell.init_for_window(self)
            LayerShell.set_namespace(self, "hello")
            LayerShell.set_layer(self, LayerShell.Layer.OVERLAY)
            LayerShell.set_keyboard_mode(self, LayerShell.KeyboardMode.EXCLUSIVE)
            LayerShell.set_exclusive_zone(self, -1)
            for edge in (LayerShell.Edge.TOP, LayerShell.Edge.BOTTOM, LayerShell.Edge.LEFT, LayerShell.Edge.RIGHT):
                LayerShell.set_anchor(self, edge, True)
        else:
            # Repli (X11, GNOME sans layer-shell) : une fenêtre sans bordure, qui se ferme quand elle perd le focus.
            self.connect("notify::is-active", self._focus_changed)

        # Panneau
        self.panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.panel.add_css_class("hello-panel")
        self.panel.set_overflow(Gtk.Overflow.HIDDEN)
        self.sweep = Sweep()
        self.wave = DotWave()
        self.flourish = Flourish()
        overlay = Gtk.Overlay(child=self.panel)
        overlay.add_overlay(self.sweep)
        overlay.add_overlay(self.wave)
        overlay.add_overlay(self.flourish)
        self.drop_label = Gtk.Label(label="")
        self.drop_label.add_css_class("hello-drop-label")
        self.drop_label.set_halign(Gtk.Align.CENTER)
        self.drop_label.set_valign(Gtk.Align.END)
        self.drop_label.set_can_target(False)
        self.drop_label.set_visible(False)
        overlay.add_overlay(self.drop_label)
        overlay.set_halign(Gtk.Align.CENTER)
        overlay.set_valign(Gtk.Align.START)
        self.panel_holder = overlay

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.append(overlay)
        self.set_child(root)

        # En-tête
        self.header = Gtk.Box(spacing=10)
        self.header.add_css_class("hello-header")
        self.mark = AnimatedMark(22)
        self.back_button = Gtk.Button()
        self.back_button.add_css_class("hello-back")
        self.back_button.set_valign(Gtk.Align.CENTER)
        self.back_button.set_focusable(False)
        self.back_button.connect("clicked", lambda *_: self.model.back())
        back_box = Gtk.Box(spacing=5)
        back_box.append(Gtk.Image.new_from_icon_name("hello-back-symbolic"))
        self.back_icon = Gtk.Image()
        back_box.append(self.back_icon)
        self.back_label = Gtk.Label()
        back_box.append(self.back_label)
        self.back_button.set_child(back_box)

        self.entry = Gtk.Text()
        self.entry.add_css_class("hello-search")
        self.entry.set_hexpand(True)
        self.entry.set_valign(Gtk.Align.CENTER)
        self.entry.connect("changed", self._entry_changed)
        self.entry.connect("activate", lambda *_: None)
        self.title_label = label("", "hello-title")
        self.title_label.set_hexpand(True)
        self.status = Gtk.Box(spacing=6)
        self.spinner = Adw.Spinner()
        self.spinner.set_size_request(16, 16)

        self.filter_box = Gtk.Box(spacing=4)
        self.filter_box.add_css_class("hello-filter")
        self.filter_box.set_valign(Gtk.Align.CENTER)
        group = None
        self.filter_buttons = {}
        for key, title in FILTERS:
            button = Gtk.ToggleButton(label=title)
            button.set_focusable(False)
            if group:
                button.set_group(group)
            group = group or button
            button.connect("toggled", self._filter_toggled, key)
            self.filter_box.append(button)
            self.filter_buttons[key] = button

        def header_button(icon, tooltip, action):
            button = Gtk.Button.new_from_icon_name(icon)
            button.add_css_class("hello-appsbutton")
            button.set_valign(Gtk.Align.CENTER)
            button.set_focusable(False)
            button.set_tooltip_text(tooltip)
            button.connect("clicked", lambda *_: action())
            return button

        # Pièces jointes de la prochaine demande à l'IA : vignettes, avec une croix pour en retirer une.
        self.attachment_strip = Gtk.Box(spacing=6)
        self.attachment_strip.set_valign(Gtk.Align.CENTER)
        self.clip_button = header_button("hello-attach-symbolic", "", self.model.pick_files_for_agent)
        self.capture_button = header_button("hello-screenshot-symbolic", "", self.model.capture_for_agent)
        self.apps_button = header_button("hello-apps-symbolic", "Toutes les applications",
                                         lambda: self.model.enter("apps"))
        self._strip_for = None

        for w in (self.mark, self.back_button, self.entry, self.title_label, self.status, self.filter_box,
                  self.attachment_strip, self.clip_button, self.capture_button, self.apps_button):
            self.header.append(w)
        self.panel.append(self.header)

        self.div1 = Gtk.Box()
        self.div1.add_css_class("hello-divider")
        self.panel.append(self.div1)
        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.content.add_css_class("hello-content")
        self.content.set_vexpand(True)
        self.panel.append(self.content)
        self.div2 = Gtk.Box()
        self.div2.add_css_class("hello-divider")
        self.panel.append(self.div2)
        self.footer = Gtk.Box(spacing=16)
        self.footer.add_css_class("hello-footer")
        self.panel.append(self.footer)

        # Clavier : intercepté avant le champ de recherche (flèches, ↵, Échap…).
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._key)
        keys.connect("key-released", lambda _c, keyval, _code, _state: self._held.discard(keyval))
        self.add_controller(keys)

        # Fichiers glissés sur le panneau : joints à la demande pour l'IA.
        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("enter", self._drop_enter)
        drop.connect("leave", lambda *_: self._drop_hover(False))
        drop.connect("drop", self._dropped)
        self.panel_holder.add_controller(drop)

        # Clic à côté du panneau : on referme.
        click = Gtk.GestureClick()
        click.connect("pressed", self._clicked)
        root.add_controller(click)

        self.model.on_change = self.render

    # MARK: Ouverture / fermeture

    def monitor_geometry(self):
        display = Gdk.Display.get_default()
        surface = self.get_surface()
        monitor = display.get_monitor_at_surface(surface) if surface else None
        if monitor is None:
            monitors = display.get_monitors()
            monitor = monitors.get_item(0) if monitors.get_n_items() else None
        if monitor is None:
            return 1920, 1080
        geo = monitor.get_geometry()
        return geo.width, geo.height

    def target_size(self):
        w, h = panel_size()
        if self.apps_mode:
            mw, mh = self.monitor_geometry()
            w = int(min(max(mw * 0.72, w), 1180))
            h = int(min(max(mh * 0.78, h), 800))
        return w, h

    def place(self):
        """Position du panneau : tiers supérieur ou centre de l'écran."""
        mw, mh = self.monitor_geometry()
        _, h = self.target_size()
        if settings.panelPosition == "center":
            top = max(24, (mh - h) // 2)
        else:
            top = max(24, int(mh * 0.18) if not self.apps_mode else (mh - h) // 2)
        self.panel_holder.set_margin_top(top)
        if not self.layer:
            w, _ = self.target_size()
            self.set_default_size(w + 40, h + 40)
            self.panel_holder.set_margin_top(20)

    def begin_reveal(self):
        """Avant le rendu d'une ouverture complète : la liste est reconstruite pour que ses lignes arrivent en
        cascade (ou se décodent, avec Glyphe) depuis cet instant."""
        self._reveal_time = GLib.get_monotonic_time() / 1e6
        self._decoded = (None, set())
        self._shown = None

    def reveal(self, light=False):
        t = tokens()
        style = t["style"]
        for name in ("reveal", "reveal-light"):
            self.panel.remove_css_class(name)
        self.footer.remove_css_class("arrive")
        self.panel.remove_css_class("closing")
        self.flourish.stop()
        animate = motion_enabled()
        # Réouverture rapide : un simple fondu (le Verre seulement) ; sinon, l'ouverture complète du style.
        name = "reveal-light" if light and style == "glass" else None if light else "reveal"
        if animate and name:
            # Retirée puis remise au tour suivant : l'animation CSS repart de zéro à chaque ouverture.
            def start():
                self.panel.add_css_class(name)
                if name == "reveal" and style in ARRIVALS:
                    self.footer.add_css_class("arrive")
                return False
            GLib.idle_add(start)
        if animate and not light and style == "atelier" and not self.model.collapsed:
            self._unfold()
        if animate and not light and settings.haloSweep:
            ok, bounds = self.header.compute_bounds(self.panel)
            header = ((bounds.get_x(), bounds.get_y(), bounds.get_width(), bounds.get_height()) if ok
                      else (0, 0, self._panel_w, HEADER))
            if style == "glass":
                GLib.timeout_add(int(90 / motion_speed()), lambda: (self.sweep.play(t["radius"]), False)[1])
            if style == "glyph":
                accent = (t["primary_key"] or (t["accent"],))[0]
                GLib.timeout_add(int(80 / motion_speed()),
                                 lambda: (self.wave.play((29, 30), accent, t["radius"]), False)[1])
            else:
                delay = {"glass": 60, "atelier": 120, "paper": 120}.get(style, 0)
                GLib.timeout_add(max(1, int(delay / motion_speed())),
                                 lambda: (self.flourish.play(style, t, header), False)[1])
        self.mark.play(animate and not light)
        self.entry.grab_focus_without_selecting()

    def _unfold(self):
        """Atelier Expressif : le panneau se déploie depuis la barre de recherche, avec un ressort."""
        width, height = self._panel_w, self._panel_h
        start = min(height, HEADER + 16)
        if height - start < 40:
            return
        self._set_panel_size(width, start)
        speed = motion_speed()
        params = Adw.SpringParams.new(0.74, 1, 420 * speed * speed)
        self._morph_anim = Adw.SpringAnimation.new(
            self, start, height, params, Adw.CallbackAnimationTarget.new(lambda v: self._set_panel_size(width, int(v))))
        self._morph_anim.set_clamp(False)
        self._morph_anim.connect("done", lambda *_: self._set_panel_size(width, height))
        self._morph_anim.play()

    def _arrive(self, widget, order):
        """Ouverture complète en cours (hors Glyphe, qui décode) : la ligne arrive à son tour dans la cascade."""
        if order is not None:
            widget.add_css_class("arrive")
            widget.add_css_class(f"arrive-{min(order, ARRIVAL_ROWS - 1)}")

    def _focus_changed(self, *_):
        if not self.is_active() and self.get_visible():
            self.c.hide(away=True)

    def _clicked(self, gesture, _n, x, y):
        ok, bounds = self.panel_holder.compute_bounds(self.get_child())
        if ok and not bounds.contains_point(_point(x, y)):
            self.c.hide(away=True)

    # MARK: Taille

    def morph(self, apps):
        """Agrandissement vers la grille d'applications (ou retour), animé."""
        self.apps_mode = apps
        target_w, target_h = self.target_size()
        start_w, start_h = self._panel_w, self._panel_h
        self.place()
        if not settings.animations:
            self._set_panel_size(target_w, target_h)
            return

        def step(t):
            self._set_panel_size(int(start_w + (target_w - start_w) * t), int(start_h + (target_h - start_h) * t))

        self._morph_anim = Adw.TimedAnimation.new(self, 0, 1, int(260 / max(settings.animationSpeed, 0.1)),
                                                  Adw.CallbackAnimationTarget.new(step))
        self._morph_anim.set_easing(Adw.Easing.EASE_OUT_CUBIC)
        self._morph_anim.play()

    def _set_panel_size(self, w, h):
        self._panel_w, self._panel_h = w, h
        self.panel.set_size_request(w, h)
        content_h = max(0, h - HEADER - FOOTER - 2)
        self.content.set_size_request(w, content_h)
        self.schedule_blur()

    # MARK: Flou (KWin)

    def ensure_blur(self):
        """Prépare le flou de KWin une fois la surface créée. Renvoie True si sa disponibilité a changé."""
        if self._blur_tried or not self.layer:
            return False
        self._blur_tried = True
        self.blur = blurmod.for_window(self)
        styles.BLUR["available"] = self.blur is not None
        return self.blur is not None

    def schedule_blur(self):
        """Zone floutée = le panneau ; recalculée après la mise en page (taille, position, style)."""
        if self.blur is None or self._blur_scheduled:
            return
        self._blur_scheduled = True
        GLib.idle_add(self._update_blur, priority=GLib.PRIORITY_LOW)

    def _update_blur(self):
        self._blur_scheduled = False
        t = tokens()
        if not t.get("blur") or not self.get_visible():
            self.blur.set_rect(0, 0, 0, 0, 0)
        else:
            ok, b = self.panel.compute_bounds(self)
            if ok:
                self.blur.set_rect(round(b.get_x()), round(b.get_y()), round(b.get_width()),
                                   round(b.get_height()), t["radius"])
        self.queue_draw()  # le flou prend effet au prochain envoi de la surface
        return False

    def fit(self):
        """Hauteur du panneau : à l'accueil, juste ce qu'il faut pour les résultats."""
        if self._morph_anim and self._morph_anim.get_state() == Adw.AnimationState.PLAYING:
            return
        w, h = self.target_size()
        self._set_panel_size(w, self.model.preferred_height(h))

    # MARK: Rendu

    def _entry_changed(self, *_):
        if self._syncing_entry:
            return
        self.model.set_query(self.entry.get_text())

    def sync_entry(self):
        if self.entry.get_text() != self.model.query:
            self._syncing_entry = True
            self.entry.set_text(self.model.query)
            self.entry.set_position(-1)
            self._syncing_entry = False

    def _filter_toggled(self, button, key):
        if button.get_active() and self.model.glyph_filter != key:
            self.model.set_glyph_filter(key)
            self.entry.grab_focus_without_selecting()

    def _key(self, _ctrl, keyval, _code, state):
        repeat = keyval in self._held
        self._held.add(keyval)
        return self.model.key(keyval, state, repeat)

    def _drop_enter(self, *_):
        ok = Hermes.available() and self.model.mode == "root"
        self._drop_hover(ok)
        return Gdk.DragAction.COPY if ok else 0

    def _drop_hover(self, on):
        (self.panel.add_css_class if on else self.panel.remove_css_class)("drop")
        self.drop_label.set_label(f"📎  Joindre à {engines.assistant()[0]}")
        self.drop_label.set_visible(on)

    def _dropped(self, _target, value, _x, _y):
        self._drop_hover(False)
        paths = [f.get_path() for f in value.get_files() if f.get_path()]
        return self.model.drop_files(paths)

    def render(self):
        m = self.model
        t = tokens()
        mode = m.mode
        self._render_header(t)
        collapsed = m.collapsed
        for w in (self.div1, self.content, self.div2, self.footer):
            w.set_visible(not collapsed)

        # « / » dans le champ de question de suite : la liste des commandes remplace un instant la conversation.
        slash = mode == "agent" and m.query.startswith("/")
        special = mode == "output" or (mode == "agent" and not slash)
        items = id(m.glyphs) if mode == "emoji" else None if special else id(m.items)
        key = (mode, items, id(m.run), id(m.agent), slash)
        if special:
            if key != self._shown:
                self._build_special(mode)
            self._update_special(mode)
        elif key != self._shown:
            self._build_content(mode)
        self._shown = key
        self._update_selection()
        self._render_footer()
        self.fit()
        self.schedule_blur()

    def invalidate(self):
        """Le style a changé : tout reconstruire au prochain rendu."""
        self._shown = None

    def _render_header(self, t):
        m = self.model
        root = m.mode == "root"
        self.mark.skin = t["mark"] if t["mark"][0] != "glass" else ("glass", None, None)
        self.mark.queue_draw()
        self.mark.set_visible(root)
        self.back_button.set_visible(not root)
        _, icon, _ = MODES[m.mode]
        self.back_icon.set_from_icon_name(icon)
        self.back_label.set_label(mode_title(m.mode))
        # Pendant que l'IA travaille, la demande ; ensuite, le champ pour une question de suite.
        thinking = m.mode == "agent" and m.agent is not None and m.agent.is_thinking
        special = m.mode == "output" or thinking
        was_hidden = not self.entry.get_visible()
        self.entry.set_visible(not special)
        self.title_label.set_visible(special)
        self.status.set_visible(special)
        self.filter_box.set_visible(m.mode == "emoji")
        agent = Hermes.available()
        name = engines.assistant()[0]
        self.clip_button.set_visible(root and agent and (not m.query or bool(m.attachments)))
        self.capture_button.set_visible(root and agent and (not m.query or bool(m.attachments)))
        self.clip_button.set_tooltip_text(f"Joindre des fichiers pour {name} (Ctrl O)")
        self.capture_button.set_tooltip_text(f"Capture d'écran pour {name} (Ctrl ⇧ S)")
        self.apps_button.set_visible(root)
        self._render_attachments(root)
        if not special:
            self.entry.set_placeholder_text(m.placeholder)
            self.sync_entry()
            if was_hidden and self.get_visible():
                self.entry.grab_focus_without_selecting()
        if m.mode == "emoji":
            button = self.filter_buttons[m.glyph_filter]
            if not button.get_active():
                button.set_active(True)

    def _render_attachments(self, root):
        m = self.model
        shown = tuple(a.path for a in m.attachments) if root else ()
        self.attachment_strip.set_visible(bool(shown))
        if shown == self._strip_for:
            return
        self._strip_for = shown
        for w in list(_children(self.attachment_strip)):
            self.attachment_strip.remove(w)
        for a in m.attachments[-4:] if root else []:
            thumb = icon_widget(("image", a.path) if a.is_image else ("file", a.path), 30)
            thumb.add_css_class("hello-attachment")
            thumb.set_tooltip_text("Capture d'écran" if a.screenshot else a.path)
            holder = Gtk.Overlay(child=thumb)
            close = Gtk.Button.new_from_icon_name("hello-close-symbolic")
            close.add_css_class("hello-detach")
            close.set_halign(Gtk.Align.END)
            close.set_valign(Gtk.Align.START)
            close.set_focusable(False)
            close.set_tooltip_text("Retirer")
            close.connect("clicked", lambda *_, a=a: m.detach(a))
            holder.add_overlay(close)
            self.attachment_strip.append(holder)
        if len(m.attachments) > 4 and root:
            self.attachment_strip.append(label(f"+{len(m.attachments) - 4}", "hello-accessory", ellipsize=False))

    def _clear_content(self):
        self.decoder.cancel()
        self._decoded_selection = None
        child = self.content.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.content.remove(child)
            child = nxt
        self._rows = []
        self.list = None
        self.carousel = None
        self.preview = None
        self._glyph_store = None

    def _build_content(self, mode):
        self._clear_content()
        m = self.model
        if mode == "emoji":
            self.content.append(self._glyph_grid())
        elif mode == "apps":
            self.content.append(self._app_grid())
        elif mode in ("clipboard", "colors", "stats"):
            box = Gtk.Box()
            box.set_vexpand(True)
            lst = self._list(clicks_activate=False)
            lst.set_size_request(300, -1)
            lst.set_hexpand(False)
            box.append(lst)
            div = Gtk.Box()
            div.add_css_class("hello-divider")
            box.append(div)
            self.preview = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            self.preview.set_hexpand(True)
            box.append(self.preview)
            self.content.append(box)
        else:
            self.content.append(self._list(clicks_activate=True))
        count = len(m.glyphs) if mode == "emoji" else len(m.items)
        if count == 0 and mode != "apps":
            self._clear_content()
            empty = label(EMPTY_TEXT.get(mode, "Aucun résultat"), "hello-empty", xalign=0.5)
            empty.set_vexpand(True)
            self.content.append(empty)
        self._preview_for = None

    # Liste

    def _list(self, clicks_activate):
        m = self.model
        t = tokens()
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        lst = Gtk.ListBox()
        lst.add_css_class("hello-list")
        lst.set_selection_mode(Gtk.SelectionMode.NONE)
        lst.set_focusable(False)
        lst.set_activate_on_single_click(True)
        scrolled.set_child(lst)
        size = icon_size()
        self._rows = []
        previous_section = None
        group_rows = []
        arrivals = self._arrivals([item.id for item in m.items])
        # Autres styles : les lignes construites juste après l'ouverture arrivent en cascade (CSS, styles.py).
        cascade = (motion_enabled() and not decodes() and t["style"] in ARRIVALS
                   and GLib.get_monotonic_time() / 1e6 - self._reveal_time < 0.3)
        order = iter(range(10 ** 6)) if cascade else None

        def close_group():
            if group_rows:
                group_rows[0].add_css_class("first")
                group_rows[-1].add_css_class("last")
            group_rows.clear()

        for i, item in enumerate(m.items):
            if item.section and item.section != previous_section:
                close_group()
                header = Gtk.ListBoxRow()
                header.set_selectable(False)
                header.set_activatable(False)
                header.set_focusable(False)
                header.add_css_class("hello-section")
                if i == 0:
                    header.add_css_class("first")
                section = label(section_title(item.section, t), "hello-section-label")
                header.set_child(section)
                self._arrive(header, next(order) if order else None)
                lst.append(header)
                if arrivals[i]:
                    self.decoder.text(section, section.get_label(), *arrivals[i])
            previous_section = item.section
            row = Gtk.ListBoxRow()
            row.add_css_class("hello-row")
            row.set_focusable(False)
            row.index = i
            box = Gtk.Box(spacing=11)
            box.set_margin_start(10)
            box.set_margin_end(12)
            if item.checked is not None:
                check = Gtk.Image.new_from_icon_name("hello-check-symbolic" if item.checked else "")
                check.add_css_class("hello-check")
                check.set_size_request(16, 16)
                box.append(check)
            ic = icon_widget(item.icon, size)
            ic.set_valign(Gtk.Align.CENTER)
            cover = None
            if t.get("ascii"):
                ic, cover = covered(ic)
            box.append(ic)
            texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            texts.set_valign(Gtk.Align.CENTER)
            texts.set_hexpand(True)
            parts = [label(item.title, "hello-title")]
            texts.append(parts[0])
            if item.subtitle and settings.showSubtitles:
                parts.append(label(item.subtitle, "hello-subtitle"))
                texts.append(parts[-1])
            box.append(texts)
            if item.accessory and settings.showAccessories:
                parts.append(label(item.accessory, "hello-accessory", ellipsize=False))
                box.append(parts[-1])
            row.set_child(box)
            # Glyphe : titre, sous-titre, étiquette et icône se décodent (voir _arrivals).
            row.decode = (item.id, [(p, p.get_label()) for p in parts], cover)
            if arrivals[i]:
                self._decode_row(row, *arrivals[i])
            row.set_opacity(1.0 if item.checked is not False else 0.55)
            self._arrive(row, next(order) if order else None)
            lst.append(row)
            self._rows.append(row)
            group_rows.append(row)
        close_group()

        def activated(_lst, row):
            idx = getattr(row, "index", None)
            if idx is None:
                return
            if clicks_activate or idx == m.selection:
                m.selection = idx
                m.activate("primary")
            else:
                m.select(idx)
            if self.get_visible():
                self.entry.grab_focus_without_selecting()

        lst.connect("row-activated", activated)
        self.list = lst
        self.scrolled = scrolled
        return scrolled

    def _arrivals(self, ids):
        """Glyphe : (délai, version brève) du décodage de chaque élément, ou None. Tout se décode dans la cascade de
        l'ouverture complète, puis seulement ce qui arrive en tapant, en version brève."""
        if not decodes():
            self._decoded = (None, set())
            return [None] * len(ids)
        now = GLib.get_monotonic_time() / 1e6
        since = now - self._reveal_time
        mode = self.model.mode
        seen = self._decoded[1] if self._decoded[0] == mode else set()
        self._decoded = (mode, set(ids))
        if since < 0.9:
            return [(max(0.0, decode.wave_delay(i) / motion_speed() - since), False) for i in range(len(ids))]
        return [None if i in seen else (0.0, True) for i in ids]

    def _decode_row(self, row, delay=0.0, quick=False):
        _, parts, cover = row.decode
        for widget, text in parts:
            self.decoder.text(widget, text, delay, quick)
        if cover is not None:
            self.decoder.icon(cover, delay, quick)

    def _update_selection(self):
        m = self.model
        if m.mode == "emoji" and self._glyph_store is not None and self.content.get_first_child():
            if m.glyphs and self._glyph_selection.get_selected() != m.selection:
                self._glyph_selection.set_selected(m.selection)
                self.glyph_view.scroll_to(m.selection, Gtk.ListScrollFlags.NONE, None)
            return
        if m.mode == "apps" and getattr(self, "carousel", None):
            for i, cell in enumerate(self._rows):
                (cell.add_css_class if i == m.selection else cell.remove_css_class)("selected")
            page = m.app_page
            if page < self.carousel.get_n_pages() and round(self.carousel.get_position()) != page:
                self.carousel.scroll_to(self.carousel.get_nth_page(page), settings.animations)
            return
        for i, row in enumerate(self._rows):
            (row.add_css_class if i == m.selection else row.remove_css_class)("selected")
            cover = getattr(row, "decode", (None, None, None))[2]
            if cover is not None and cover.selected != (i == m.selection):
                cover.selected = i == m.selection
                cover.queue_draw()
        if self._rows and 0 <= m.selection < len(self._rows):
            GLib.idle_add(self._scroll_to_selection)
            # Glyphe : la ligne qu'on sélectionne se décode à nouveau, brièvement.
            row = self._rows[m.selection]
            selected = getattr(row, "decode", (None,))[0]
            if decodes() and selected != self._decoded_selection:
                if self._decoded_selection is not None and GLib.get_monotonic_time() / 1e6 - self._reveal_time > 0.9:
                    self._decode_row(row, 0.0, True)
                self._decoded_selection = selected
        if self.preview is not None and self._preview_for != (m.selection, id(m.items)):
            self._preview_for = (m.selection, id(m.items))
            self._render_preview()

    def _scroll_to_selection(self):
        m = self.model
        if not self._rows or not (0 <= m.selection < len(self._rows)) or not self.list:
            return False
        row = self._rows[m.selection]
        ok, rect = row.compute_bounds(self.list)
        if not ok:
            return False
        adj = self.scrolled.get_vadjustment()
        y, h = rect.get_y(), rect.get_height()
        if m.selection == 0:
            y = 0  # garder l'en-tête de section visible
        if y < adj.get_value():
            adj.set_value(y)
        elif y + h > adj.get_value() + adj.get_page_size():
            adj.set_value(y + h - adj.get_page_size() + 8)
        return False

    # Grille d'applications

    def _app_grid(self):
        m = self.model
        w, h = self.target_size()
        columns = min(max(int((w - 36) / 128), 5), 9)
        rows = min(max(int((h - HEADER - FOOTER - 2 - 28 - 12) / 134), 3), 5)
        m.app_columns, m.app_rows = columns, rows
        per = columns * rows
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.set_vexpand(True)
        carousel = Adw.Carousel()
        carousel.set_vexpand(True)
        carousel.set_allow_scroll_wheel(True)
        carousel.set_spacing(0)
        self._rows = []
        ascii_icons = bool(tokens().get("ascii"))
        for page_start in range(0, max(len(m.items), 1), per):
            grid = Gtk.Grid()
            grid.set_row_homogeneous(True)
            grid.set_column_homogeneous(True)
            grid.set_hexpand(True)
            grid.set_vexpand(True)
            grid.set_margin_start(18)
            grid.set_margin_end(18)
            grid.set_margin_top(12)
            for slot in range(per):
                i = page_start + slot
                if i >= len(m.items):
                    filler = Gtk.Box()
                    grid.attach(filler, slot % columns, slot // columns, 1, 1)
                    continue
                item = m.items[i]
                cell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
                cell.add_css_class("hello-cell")
                cell.set_halign(Gtk.Align.CENTER)
                cell.set_valign(Gtk.Align.CENTER)
                cell.set_size_request(112, 112)
                img = icon_widget(item.icon, 64)
                img.set_halign(Gtk.Align.CENTER)
                cover = None
                if ascii_icons:
                    img, cover = covered(img)
                cell.append(img)
                name = label(item.title, "hello-cell-label", xalign=0.5)
                name.set_max_width_chars(12)
                cell.append(name)
                # Glyphe : les icônes se décodent quand la page apparaît, en diagonale.
                cell.decode = (item.id, [(name, item.title)], cover)
                if ascii_icons and decodes() and slot < per:
                    self._decode_row(cell, (slot % columns + slot // columns) * 0.03 / motion_speed(), True)
                if item.accessory:
                    dot = Gtk.Box()
                    dot.add_css_class("hello-dot")
                    dot.add_css_class("active")
                    dot.set_halign(Gtk.Align.CENTER)
                    cell.append(dot)
                cell.index = i
                click = Gtk.GestureClick()
                click.connect("released", lambda _g, _n, _x, _y, idx=i: self._cell_clicked(idx))
                cell.add_controller(click)
                grid.attach(cell, slot % columns, slot // columns, 1, 1)
                self._rows.append(cell)
            carousel.append(grid)
        carousel.connect("page-changed", self._page_changed)
        box.append(carousel)
        dots = Adw.CarouselIndicatorDots(carousel=carousel)
        dots.add_css_class("hello-dots")
        box.append(dots)
        self.carousel = carousel
        if not m.items:
            empty = label("Aucune application", "hello-empty", xalign=0.5)
            empty.set_vexpand(True)
            return empty
        GLib.idle_add(lambda: (carousel.scroll_to(carousel.get_nth_page(min(m.app_page, carousel.get_n_pages() - 1)),
                                                  False), False)[1])
        return box

    def _cell_clicked(self, idx):
        self.model.selection = idx
        self.model.activate("primary")

    def _page_changed(self, carousel, page):
        m = self.model
        if m.mode == "apps" and m.app_page != page:
            m.select(min(page * m.apps_per_page, len(m.items) - 1))

    # Emoji

    def _glyph_grid(self):
        m = self.model
        self._glyph_store = Gtk.StringList.new([str(i) for i in range(len(m.glyphs))])
        self._glyph_selection = Gtk.SingleSelection(model=self._glyph_store)
        self._glyph_selection.set_autoselect(False)
        factory = Gtk.SignalListItemFactory()

        def setup(_f, item):
            lbl = Gtk.Label()
            lbl.add_css_class("hello-glyph")
            item.set_child(lbl)

        def bind(_f, item):
            idx = int(item.get_item().get_string())
            g = m.glyphs[idx] if idx < len(m.glyphs) else None
            item.get_child().set_label(g.char if g else "")
            item.get_child().set_tooltip_text(g.name if g else None)

        factory.connect("setup", setup)
        factory.connect("bind", bind)
        view = Gtk.GridView(model=self._glyph_selection, factory=factory)
        view.add_css_class("hello-glyphs")
        view.set_min_columns(grid_columns())
        view.set_max_columns(grid_columns())
        view.set_single_click_activate(True)
        view.set_focusable(False)

        def activated(_v, pos):
            m.selection = pos
            m.activate("primary")

        view.connect("activate", activated)
        self.glyph_view = view
        scrolled = Gtk.ScrolledWindow(child=view)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_margin_start(8)
        scrolled.set_margin_end(8)
        return scrolled

    # Aperçus

    def _render_preview(self):
        box = self.preview
        child = box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            box.remove(child)
            child = nxt
        item = self.model.selected_item
        if not item or not item.preview:
            return
        kind, value = item.preview
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        inner.add_css_class("hello-preview")
        inner.set_vexpand(True)
        if kind == "clip":
            self._clip_preview(inner, value)
        elif kind == "color":
            self._color_preview(inner, value)
        elif kind == "stats":
            self._stats_preview(inner, value, item)
        box.append(inner)

    @staticmethod
    def _meta(rows):
        grid = Gtk.Grid(column_spacing=12, row_spacing=4)
        for i, (k, v) in enumerate(rows):
            grid.attach(label(k, "hello-meta-key"), 0, i, 1, 1)
            value = label(v, "hello-meta-value")
            value.set_hexpand(True)
            grid.attach(value, 1, i, 1, 1)
        return grid

    def _clip_preview(self, box, e):
        from .model import relative
        if e["kind"] == "image" and e.image_path:
            pic = Gtk.Picture.new_for_filename(e.image_path)
            pic.set_content_fit(Gtk.ContentFit.CONTAIN)
            pic.set_vexpand(True)
            box.append(pic)
        elif e["kind"] == "files":
            for path in (e.get("files") or [])[:8]:
                row = Gtk.Box(spacing=8)
                row.append(icon_widget(("file", path), 22))
                row.append(label(shell.abbreviate(path), "hello-meta-value"))
                box.append(row)
            box.set_valign(Gtk.Align.START)
        else:
            text = (e.get("text") or "")[:6000]
            if e.hex_color:
                box.append(swatch(e.hex_color, 72))
            lbl = label(text, "hello-preview-text" if e.looks_like_code else "hello-agent", ellipsize=False,
                        wrap=True, selectable=False)
            lbl.set_valign(Gtk.Align.START)
            scrolled = Gtk.ScrolledWindow(child=lbl)
            scrolled.set_vexpand(True)
            scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            box.append(scrolled)
        box.append(self._meta([("Type", e.detail), ("Copié", relative(e["date"]))] +
                              ([("Source", e["source"])] if e.get("source") else [])))

    def _color_preview(self, box, color):
        area = swatch((color["r"], color["g"], color["b"]), 96)
        area.set_halign(Gtk.Align.START)
        box.append(area)
        box.append(label(color.hex, "hello-preview-title"))
        for name, value in color.formats:
            row = Gtk.Box(spacing=10)
            key = label(name, "hello-meta-key")
            key.set_size_request(70, -1)
            row.append(key)
            row.append(label(value, "hello-meta-value", selectable=True))
            box.append(row)

    def _stats_preview(self, box, item_id, item):
        record = usage.records.get(item_id, {})
        box.append(label(item.title.split(". ", 1)[-1], "hello-preview-title"))
        days = usage.daily(item_id, 14)
        chart = Gtk.DrawingArea()
        chart.set_content_height(90)
        chart.set_hexpand(True)
        accent = rgb(tokens()["accent"])

        def draw(_a, ctx, w, h):
            peak = max(days) or 1
            gap = 4
            bar = (w - gap * (len(days) - 1)) / len(days)
            for i, v in enumerate(days):
                bh = max(2, (h - 4) * v / peak) if v else 2
                ctx.set_source_rgba(accent[0] / 255, accent[1] / 255, accent[2] / 255, 1 if v else 0.25)
                ctx.rectangle(i * (bar + gap), h - bh, bar, bh)
                ctx.fill()

        chart.set_draw_func(draw)
        box.append(chart)
        box.append(label("14 derniers jours", "hello-meta-key"))
        shortcuts = usage.shortcuts(item_id, 5)
        box.append(self._meta([
            ("Total", str(record.get("count", 0))),
            ("7 jours", str(usage.launches(item_id, 7))),
            ("30 jours", str(usage.launches(item_id, 30))),
            ("Appris", " ".join(f"« {s} »" for s in shortcuts) or "—"),
        ]))

    # Terminal et agent

    def _build_special(self, mode):
        self._clear_content()
        if mode == "output":
            view = Gtk.TextView()
            view.set_editable(False)
            view.set_cursor_visible(False)
            view.set_monospace(True)
            view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            view.add_css_class("hello-output")
            view.set_left_margin(16)
            view.set_right_margin(16)
            view.set_top_margin(10)
            view.set_bottom_margin(10)
            view.set_focusable(False)
            self.output_view = view
            self._tags = {}
            self._output_version = -1
            scrolled = Gtk.ScrolledWindow(child=view)
            scrolled.set_vexpand(True)
            self.output_scroll = scrolled
            self.content.append(scrolled)
        else:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            for side in ("start", "end", "top", "bottom"):
                getattr(box, f"set_margin_{side}")(20 if side in ("start", "end") else 16)
            run = self.model.agent
            for turn in run.earlier if run else []:
                box.append(self._past_turn(turn))
                rule = Gtk.Box()
                rule.add_css_class("hello-rule")
                box.append(rule)
            self.agent_request = label(run.request if run else "", "hello-request", ellipsize=False, wrap=True,
                                       selectable=True)
            box.append(self.agent_request)
            self.agent_badge = Gtk.Box(spacing=8)
            box.append(self.agent_badge)
            self.agent_stage = Gtk.Box(spacing=7)
            box.append(self.agent_stage)
            self.agent_steps = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            box.append(self.agent_steps)
            self.agent_text = label("", "hello-agent", ellipsize=False, wrap=True, selectable=True)
            self.agent_text.set_valign(Gtk.Align.START)
            self.agent_text.set_use_markup(True)
            box.append(self.agent_text)
            self.agent_details = label("", "hello-preview-text", ellipsize=False, wrap=True, selectable=True)
            box.append(self.agent_details)
            self.agent_elapsed = label("", "hello-step command", ellipsize=False)
            box.append(self.agent_elapsed)
            scrolled = Gtk.ScrolledWindow(child=box)
            scrolled.set_vexpand(True)
            scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            self.agent_scroll = scrolled
            self.content.append(scrolled)
            self._agent_shape = None
            self._agent_steps_shown = None
            self._agent_text_shown = None
            # Conversation rouverte ou question de suite : on arrive sur le dernier échange.
            if run and run.earlier:
                GLib.timeout_add(60, self._agent_to_bottom)

    def _agent_to_bottom(self):
        if getattr(self, "agent_scroll", None) is not None:
            adj = self.agent_scroll.get_vadjustment()
            adj.set_value(adj.get_upper())
        return False

    def _past_turn(self, turn):
        """Échange précédent d'une conversation : la demande, puis la réponse, en plus discret que l'échange en cours."""
        from .agent import LEVELS
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        top = Gtk.Box(spacing=8)
        request = label(turn.get("request") or "", "hello-title", ellipsize=False, wrap=True, selectable=True)
        request.set_hexpand(True)
        top.append(request)
        title, _, tint = LEVELS.get(turn.get("level"), LEVELS[1])
        level = label(title, "hello-past-level", ellipsize=False)
        level.set_markup(f"<span foreground='{tint}'>{escape(title)}</span>")
        level.set_valign(Gtk.Align.START)
        top.append(level)
        box.append(top)
        if turn.get("kind") == "code":
            box.append(label("Envoyé à une session de code dans le terminal", "hello-agent-stage"))
        else:
            answer = label("", "hello-agent hello-past", ellipsize=False, wrap=True, selectable=True)
            try:
                answer.set_markup(markdown_to_markup(turn.get("answer") or ""))
            except GLib.Error:
                answer.set_text(turn.get("answer") or "")
            box.append(answer)
        return box

    def _tag(self, style):
        tag = self._tags.get(style)
        if tag:
            return tag
        fg = hex_color(style.fg) if style.fg is not None else None
        bg = hex_color(style.bg) if style.bg is not None else None
        if style.inverse:
            fg, bg = bg or "#1a1a1a", fg or "#ffffff"
        tag = self.output_view.get_buffer().create_tag(None)
        if fg:
            tag.set_property("foreground", fg)
        if bg:
            tag.set_property("background", bg)
        if style.bold:
            tag.set_property("weight", Pango.Weight.BOLD)
        if style.italic:
            tag.set_property("style", Pango.Style.ITALIC)
        if style.underline:
            tag.set_property("underline", Pango.Underline.SINGLE)
        if style.dim:
            tag.set_property("foreground-rgba", _alpha(fg or tokens()["ink"], 0.55))
        self._tags[style] = tag
        return tag

    def _update_special(self, mode):
        m = self.model
        for w in list(_children(self.status)):
            self.status.remove(w)
        if mode == "output" and m.run:
            run = m.run
            self.title_label.set_label("$ " + run.command)
            self.title_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            if run.running:
                self.status.append(self.spinner)
                self.status.append(label(run.elapsed, "hello-accessory", ellipsize=False))
            elif run.status is not None:
                ok = run.status == 0
                self.status.append(label(("✓" if ok else f"✗ code {run.status}") + f"  ·  {run.elapsed}",
                                         "hello-toast" if ok else "hello-accessory", ellipsize=False))
            buf = self.output_view.get_buffer()
            if self._output_version != run.buffer.version:
                self._output_version = run.buffer.version
                adj = self.output_scroll.get_vadjustment()
                at_bottom = adj.get_value() >= adj.get_upper() - adj.get_page_size() - 24
                buf.set_text("")
                end = buf.get_end_iter()
                plain = TermStyle()
                lines = run.buffer.lines
                for i, line in enumerate(lines):
                    for text, style in line:
                        if style == plain:
                            buf.insert(end, text)
                        else:
                            buf.insert_with_tags(end, text, self._tag(style))
                    if i < len(lines) - 1:
                        buf.insert(end, "\n")
                if run.buffer.is_empty and not run.running:
                    buf.insert(end, "(aucune sortie)")
                if at_bottom:
                    GLib.idle_add(lambda: (adj.set_value(adj.get_upper()), False)[1])
        elif mode == "agent" and m.agent:
            self._update_agent(m.agent)

    def _update_agent(self, a):
        from .agent import LEVELS, level_model_label
        from .desktop import terminal
        self.title_label.set_label(a.request)
        self.title_label.set_ellipsize(Pango.EllipsizeMode.END)
        if a.is_thinking:
            self.status.append(self.spinner)
            if a.attachments:
                clip = label(f"📎 {len(a.attachments)}", "hello-accessory", ellipsize=False)
                clip.set_tooltip_text("\n".join(x.name for x in a.attachments))
                self.status.append(clip)
        self.agent_request.set_visible(not a.is_thinking or bool(a.earlier))
        title, icon, tint = LEVELS[a.level]
        auto = a.is_thinking and a.stage == "choisit le niveau"
        shape = (a.level, auto, tuple(x.path for x in a.attachments))
        if self._agent_shape != shape:
            self._agent_shape = shape
            for w in list(_children(self.agent_badge)):
                self.agent_badge.remove(w)
            badge = Gtk.Box(spacing=6)
            badge.append(icon_widget(("symbol", icon, tint), 20))
            text = "Auto · choix du niveau…" if auto else f"Niveau {a.level} · {title}"
            badge.append(label(text, "hello-agent-stage", ellipsize=False))
            self.agent_badge.append(badge)
            for x in a.attachments:
                thumb = icon_widget(("image", x.path) if x.is_image else ("file", x.path), 22)
                thumb.set_tooltip_text(x.path)
                self.agent_badge.append(thumb)
        model = a.model_label
        status = {
            "thinking": ("hello-loading-symbolic", "#9141AC", f"{model} {a.stage}…"),
            "streaming": ("hello-loading-symbolic", "#9141AC", f"{model} répond…"),
            "done": ("hello-ok-symbolic", "#26A269", "Fait"),
            "answer": ("hello-chats-symbolic", "#3584E4", f"Réponse de {model}"),
            "delegated": ("hello-terminal-symbolic", "#9141AC",
                          f"Envoyé à {level_model_label(3)} dans {terminal()[1]}"),
            "failed": ("hello-warning-symbolic", "#E66100", f"{engines.TITLES.get(a.engine, a.engine)} n'a pas pu répondre"),
        }[a.phase]
        for w in list(_children(self.agent_stage)):
            self.agent_stage.remove(w)
        img = Gtk.Image.new_from_icon_name(status[0])
        self.agent_stage.append(img)
        stage = label("", "hello-title", ellipsize=False, wrap=True)
        stage.set_markup(f"<span foreground='{status[1]}'>{escape(status[2])}</span>")
        self.agent_stage.append(stage)
        self._update_steps(a)
        if a.phase == "failed":
            text = f"<tt>{escape(a.text)}</tt>"
        elif a.phase == "delegated":
            text = escape(a.text)
        else:
            text = markdown_to_markup(a.text)
        if text != self._agent_text_shown:
            self._agent_text_shown = text
            try:
                self.agent_text.set_markup(text)
            except GLib.Error:
                self.agent_text.set_text(a.text)
            self._follow_stream()
        self.agent_text.set_visible(bool(a.text))
        self.agent_details.set_label(a.details if a.phase == "done" else "")
        self.agent_details.set_visible(a.phase == "done" and bool(a.details))
        self._tick_elapsed(a)

    def _update_steps(self, a):
        """Ce que l'IA a fait (commandes, lectures, recherches) ; la dernière étape tourne tant qu'elle travaille."""
        key = (len(a.steps), a.is_thinking)
        if key == self._agent_steps_shown:
            return
        self._agent_steps_shown = key
        for w in list(_children(self.agent_steps)):
            self.agent_steps.remove(w)
        shown = a.steps[-8:]
        hidden = len(a.steps) - len(shown)
        if hidden:
            self.agent_steps.append(label(f"+ {hidden} étape{'s' if hidden > 1 else ''} avant", "hello-step"))
        for i, step in enumerate(shown):
            current = a.is_thinking and i == len(shown) - 1
            row = Gtk.Box(spacing=7)
            mark = label("◌" if current else "✓", "hello-step-mark" + (" current" if current else ""), ellipsize=False)
            row.append(mark)
            text = label(step, "hello-step" + (" current" if current else "") + (" command" if step.startswith("$ ") else ""))
            text.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            text.set_hexpand(True)
            row.append(text)
            self.agent_steps.append(row)
        self.agent_steps.set_visible(bool(a.steps))
        self._follow_stream()

    def _follow_stream(self):
        adj = self.agent_scroll.get_vadjustment()
        if adj.get_value() >= adj.get_upper() - adj.get_page_size() - 48:
            GLib.idle_add(lambda: (adj.set_value(adj.get_upper()), False)[1])

    def _tick_elapsed(self, a):
        if not a.is_thinking:
            self.agent_elapsed.set_visible(False)
            return
        self.agent_elapsed.set_visible(True)
        import time
        self.agent_elapsed.set_label(f"{time.time() - a.started_at:.1f} s".replace(".", ","))
        if not getattr(self, "_elapsed_timer", None):
            def tick():
                run = self.model.agent
                if self.model.mode != "agent" or not run or not run.is_thinking or not self.get_visible():
                    self._elapsed_timer = None
                    if run and not run.is_thinking:
                        self.agent_elapsed.set_visible(False)
                    return False
                self.agent_elapsed.set_label(f"{time.time() - run.started_at:.1f} s".replace(".", ","))
                return True
            self._elapsed_timer = GLib.timeout_add(100, tick)

    # Pied de page

    def _render_footer(self):
        m = self.model
        for w in list(_children(self.footer)):
            self.footer.remove(w)
        left = None
        caps = tokens().get("chrome_caps")
        if m.toast:
            left = Gtk.Box(spacing=6)
            left.append(Gtk.Image.new_from_icon_name("hello-ok-symbolic"))
            text = label(m.toast.upper() if caps else m.toast)
            left.append(text)
            left.add_css_class("hello-toast")
            if decodes() and m.toast != getattr(self, "_toast_decoded", None):
                self.decoder.text(text, text.get_label(), 0.0, True)
            self._toast_decoded = m.toast
        elif m.mode == "emoji" and m.selected_glyph:
            g = m.selected_glyph
            left = Gtk.Label()
            left.set_markup(f"{escape(g.name)}   <span alpha='60%'>{escape(g.code)}</span>")
            left.set_ellipsize(Pango.EllipsizeMode.END)
            left.set_xalign(0)
        if left:
            left.set_hexpand(True)
            left.set_valign(Gtk.Align.CENTER)
            self.footer.append(left)
        else:
            spacer = Gtk.Box()
            spacer.set_hexpand(True)
            self.footer.append(spacer)
        if settings.showHints and not m.toast:
            for title, key in m.hints:
                hint = Gtk.Box(spacing=6)
                lbl = label(title.upper() if caps else title, "hello-hint", ellipsize=False)
                if key == "↵":
                    lbl.add_css_class("primary")
                hint.append(lbl)
                hint.append(keycap(key, primary=key == "↵"))
                self.footer.append(hint)


def _children(widget):
    child = widget.get_first_child()
    while child:
        yield child
        child = child.get_next_sibling()


def _alpha(hex_value, alpha):
    c = Gdk.RGBA()
    c.parse(hex_value)
    c.alpha = alpha
    return c


def _point(x, y):
    from gi.repository import Graphene
    return Graphene.Point().init(x, y)
