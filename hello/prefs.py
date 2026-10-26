"""Réglages de Hello (Windows.swift), en libadwaita : une barre latérale (Général, Apparence, Animations, Recherche,
Presse-papiers, IA) et une page par rubrique. Chaque ligne écrit directement dans les réglages (appliqués tout de
suite) ; l'Apparence et les Animations ne montrent que ce qui concerne le style choisi."""
import os
import shutil
import uuid

from gi.repository import Adw, Gdk, GLib, GObject, Gtk

from . import __version__, desktop, engines, updater
from .agent import LEVELS, Hermes
from .chats import ChatStore
from .hotkey import CHOICES
from .mark import cairo_rgba
from .settings import PANEL_SIZES, ROW_DENSITY, settings
from .styles import APPEARANCES, BRUTAL, GLYPH_ACCENTS, GLYPH_APPEARANCES, PALETTES, PAPER, PHOSPHOR, STYLES, tokens
from .updater import Updater

PAGES = [
    ("general", "Général", "hello-general-symbolic"),
    ("appearance", "Apparence", "hello-appearance-symbolic"),
    ("motion", "Animations", "hello-motion-symbolic"),
    ("search", "Recherche", "hello-search-symbolic"),
    ("clipboard", "Presse-papiers", "hello-clipboard-symbolic"),
    ("agent", "IA", "hello-sparkle-symbolic"),
]

# Ce que dessine l'ouverture de chaque style (le réglage « Dessin d'ouverture »).
FLOURISH = {"kde": "Le filet d'accent sous la recherche", "glass": "Le reflet sur la vitre et le liseré du bord",
            "atelier": "L'anneau de focus autour de la recherche", "glyph": "L'onde de points",
            "phosphor": "L'allumage du tube et le faisceau", "paper": "Le trait d'encre",
            "brutal": "Le contour qui claque et les traits d'impact"}


def with_icon(row, icon):
    image = Gtk.Image.new_from_icon_name(icon)
    image.add_css_class("dim-label")
    row.add_prefix(image)
    return row


def switch(key, title, subtitle=None, icon=None):
    row = Adw.SwitchRow(title=title, use_markup=False)
    if subtitle:
        row.set_subtitle(subtitle)
    row.set_active(bool(getattr(settings, key)))
    row.connect("notify::active", lambda r, _p: setattr(settings, key, r.get_active()))
    return with_icon(row, icon) if icon else row


def combo(key, title, options, subtitle=None, icon=None, changed=None):
    """options : liste de (valeur, titre)."""
    row = Adw.ComboRow(title=title, use_markup=False)
    if subtitle:
        row.set_subtitle(subtitle)
    row.set_model(Gtk.StringList.new([t for _, t in options]))
    values = [v for v, _ in options]
    current = getattr(settings, key)
    row.set_selected(values.index(current) if current in values else 0)

    def selected(r, _p):
        setattr(settings, key, values[r.get_selected()])
        if changed:
            changed()
    row.connect("notify::selected", selected)
    return with_icon(row, icon) if icon else row


def spin(key, title, lower, upper, step, digits=0, subtitle=None):
    row = Adw.SpinRow.new_with_range(lower, upper, step)
    row.set_title(title)
    row.set_use_markup(False)
    if subtitle:
        row.set_subtitle(subtitle)
    row.set_digits(digits)
    row.set_value(float(getattr(settings, key)))
    cast = int if digits == 0 else float
    row.connect("notify::value", lambda r, _p: setattr(settings, key, cast(r.get_value())))
    return row


def slider(key, title, lower, upper, marks, subtitle=None, percent=False, icon=None):
    """Curseur, avec des repères nommés : marks = [(valeur, nom)]."""
    row = Adw.ActionRow(title=title, use_markup=False)
    if subtitle:
        row.set_subtitle(subtitle)
    scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lower, upper, (upper - lower) / 100)
    scale.set_size_request(240, -1)
    scale.set_valign(Gtk.Align.CENTER)
    scale.set_draw_value(False)
    for value, name in marks:
        scale.add_mark(value, Gtk.PositionType.BOTTOM, name)
    scale.set_value(float(getattr(settings, key)))
    scale.connect("value-changed", lambda s: setattr(settings, key, round(s.get_value(), 2)))
    row.add_suffix(scale)
    return with_icon(row, icon) if icon else row


def entry(key, title):
    row = Adw.EntryRow(title=title)
    row.set_text(str(getattr(settings, key)))
    row.connect("changed", lambda r: setattr(settings, key, r.get_text()))
    return row


def color(key, title):
    row = Adw.ActionRow(title=title, use_markup=False)
    button = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False))
    rgba = Gdk.RGBA()
    rgba.parse(getattr(settings, key))
    button.set_rgba(rgba)
    button.set_valign(Gtk.Align.CENTER)

    def changed(b, _p):
        c = b.get_rgba()
        setattr(settings, key, "#%02X%02X%02X" % (round(c.red * 255), round(c.green * 255), round(c.blue * 255)))

    button.connect("notify::rgba", changed)
    row.add_suffix(button)
    return row


def status_row(title, ok, detail, action=None):
    row = Adw.ActionRow(title=title, subtitle=detail, use_markup=False)
    icon = Gtk.Image.new_from_icon_name("hello-ok-symbolic" if ok else "hello-warning-symbolic")
    icon.add_css_class("success" if ok else "warning")
    row.add_prefix(icon)
    if action:
        label, callback = action
        button = Gtk.Button(label=label, valign=Gtk.Align.CENTER)
        button.connect("clicked", lambda *_: callback())
        row.add_suffix(button)
    return row


def button_row(title, callback, destructive=False):
    """Ligne-bouton (Adw.ButtonRow, ou une ligne avec un bouton sur les libadwaita plus anciennes)."""
    if hasattr(Adw, "ButtonRow"):
        row = Adw.ButtonRow(title=title)
        row.connect("activated", lambda *_: callback())
        if destructive:
            row.add_css_class("destructive-action")
        return row
    row = Adw.ActionRow()
    button = Gtk.Button(label=title, valign=Gtk.Align.CENTER, hexpand=True)
    if destructive:
        button.add_css_class("destructive-action")
    button.connect("clicked", lambda *_: callback())
    row.set_child(button)
    return row


def group(title, *rows, description=None, suffix=None):
    # Titre et description d'un groupe sont lus comme du balisage : « Recherche & Action » casserait l'affichage.
    g = Adw.PreferencesGroup(title=GLib.markup_escape_text(title or ""))
    if description:
        g.set_description(GLib.markup_escape_text(description))
    if suffix:
        g.set_header_suffix(suffix)
    for r in rows:
        g.add(r)
    return g


class StylePreview(Gtk.DrawingArea):
    """Miniature d'un style : son panneau sur un fond de bureau, une barre de recherche et trois lignes, dont une
    sélectionnée, avec ses vraies couleurs."""

    def __init__(self, style):
        super().__init__()
        self.style = style
        self.set_content_width(150)
        self.set_content_height(92)
        self.set_draw_func(self._draw)

    def _draw(self, _area, ctx, width, height):
        import cairo
        from .mark import _rounded
        t = tokens(self.style)
        # Bureau : un dégradé, pour voir la transparence du Verre et du style KDE.
        wallpaper = cairo.LinearGradient(0, 0, width, height)
        wallpaper.add_color_stop_rgb(0, 0.29, 0.31, 0.52)
        wallpaper.add_color_stop_rgb(1, 0.62, 0.38, 0.52)
        _rounded(ctx, 0, 0, width, height, 10)
        ctx.set_source(wallpaper)
        ctx.fill()
        x, y, w, h = 14, 12, width - 28, height - 22
        r = min(t["radius"] * 0.45, 14)
        if t["hard_shadow"]:
            ctx.set_source_rgba(*cairo_rgba(t.get("hard_shadow_color", "#000000")))
            _rounded(ctx, x + 4, y + 4, w, h, r)
            ctx.fill()
        ctx.set_source_rgba(*cairo_rgba(t["surface"]))
        _rounded(ctx, x, y, w, h, r)
        ctx.fill()
        if t.get("pane"):
            ctx.set_source_rgba(*cairo_rgba(t["pane"]))
            _rounded(ctx, x + 4, y + 20, w - 8, h - 24, r * 0.7)
            ctx.fill()
        if t["border"]:
            ctx.set_source_rgba(*cairo_rgba(t["border"][0]))
            ctx.set_line_width(min(t["border"][1], 2))
            _rounded(ctx, x, y, w, h, r)
            ctx.stroke()
        ink = cairo_rgba(t["ink"] if not t.get("pane") else t["chrome_ink"])
        accent = cairo_rgba((t["primary_key"] or (t["accent"],))[0])
        # Barre de recherche : le logo (un point d'accent) et le texte tapé.
        ctx.set_source_rgba(*accent)
        ctx.arc(x + 11, y + 10, 3, 0, 6.3)
        ctx.fill()
        ctx.set_source_rgba(ink[0], ink[1], ink[2], 0.55)
        ctx.rectangle(x + 19, y + 9, w * 0.42, 2.5)
        ctx.fill()
        row_ink = cairo_rgba(t["ink"])
        for i in range(3):
            ry = y + 25 + i * 15
            if i == 0:
                ctx.set_source_rgba(*cairo_rgba(t["selection"]))
                _rounded(ctx, x + 6, ry - 1, w - 12, 12, min(t["row_radius"] * 0.5, 6))
                ctx.fill()
                if t.get("selection_border"):
                    ctx.set_source_rgba(*cairo_rgba(t["selection_border"]))
                    ctx.set_line_width(1.2)
                    _rounded(ctx, x + 6, ry - 1, w - 12, 12, min(t["row_radius"] * 0.5, 6))
                    ctx.stroke()
                if t.get("selection_bar"):
                    ctx.set_source_rgba(*cairo_rgba(t["selection_bar"]))
                    ctx.rectangle(x + 6, ry - 1, 2, 12)
                    ctx.fill()
            text = cairo_rgba(t["selection_ink"]) if i == 0 and t.get("selection_ink") else row_ink
            icon = cairo_rgba(t["accent2"]) if not t.get("mono") else text
            ctx.set_source_rgba(icon[0], icon[1], icon[2], 0.9)
            _rounded(ctx, x + 10, ry + 1, 8, 8, 2)
            ctx.fill()
            ctx.set_source_rgba(text[0], text[1], text[2], 0.8)
            if t.get("mono"):
                for k in range(5):
                    ctx.rectangle(x + 23 + k * 7, ry + 4, 5, 2.5)
            else:
                ctx.rectangle(x + 23, ry + 4, w * (0.5 - 0.08 * i), 2.5)
            ctx.fill()


class SettingsWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Réglages de Hello")
        self.c = app
        self.set_default_size(980, 760)
        # Teinte des icônes des trois niveaux de l'IA.
        tints = Gtk.CssProvider()
        tints.load_from_string("".join(f".hello-level-{n} {{ color: {tint}; }}" for n, (_, _, tint) in LEVELS.items()))
        Gtk.StyleContext.add_provider_for_display(self.get_display(), tints, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._expanded = set()
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.sidebar = Gtk.ListBox()
        self.sidebar.add_css_class("navigation-sidebar")
        self._rows = {}
        for name, title, icon in PAGES:
            self.stack.add_named(self._build(name), name)
            box = Gtk.Box(spacing=12)
            box.append(Gtk.Image.new_from_icon_name(icon))
            box.append(Gtk.Label(label=title, xalign=0))
            row = Gtk.ListBoxRow(child=box)
            row.name = name
            self.sidebar.append(row)
            self._rows[name] = row
        self.sidebar.connect("row-selected", lambda _l, row: row and self._select(row.name))

        side = Adw.ToolbarView(content=Gtk.ScrolledWindow(child=self.sidebar, vexpand=True))
        side.add_top_bar(Adw.HeaderBar())
        self.content = Adw.NavigationPage(title="Général", tag="content")
        body = Adw.ToolbarView(content=self.stack)
        body.add_top_bar(Adw.HeaderBar())
        self.content.set_child(body)
        self.split = Adw.NavigationSplitView(sidebar=Adw.NavigationPage(title="Réglages", child=side),
                                             content=self.content)
        self.split.set_min_sidebar_width(200)
        self.split.set_max_sidebar_width(240)
        # Fenêtre étroite : la barre latérale et la page passent l'une après l'autre.
        breakpoint = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 640sp"))
        breakpoint.add_setter(self.split, "collapsed", GObject.Value(bool, True))
        self.add_breakpoint(breakpoint)
        self.set_content(self.split)
        self.show_page("general")
        Updater.on_change, self._previous_updater = self._updater_changed, Updater.on_change
        self.connect("close-request", self._closing)

    def _build(self, name):
        return {"general": self._general, "appearance": self._appearance, "motion": self._motion,
                "search": self._search, "clipboard": self._clipboard, "agent": self._agent}[name]()

    def show_page(self, name):
        if name in self._rows:
            self.sidebar.select_row(self._rows[name])
            self._select(name)

    def _select(self, name):
        self.stack.set_visible_child_name(name)
        self.content.set_title(next(t for n, t, _ in PAGES if n == name))
        self.split.set_show_content(True)

    def _closing(self, *_):
        Updater.on_change = self._previous_updater
        return False

    def _updater_changed(self):
        if self._previous_updater:
            self._previous_updater()
        self._update_status()

    def _rebuild(self, *names):
        """Reconstruit des pages (le style ou le fournisseur d'un niveau a changé : leurs réglages aussi)."""
        visible = self.stack.get_visible_child_name()
        for name in names:
            old = self.stack.get_child_by_name(name)
            # Garder la position de défilement : la page se reconstruit sous les yeux.
            scroll = old.get_vadjustment().get_value() if hasattr(old, "get_vadjustment") else 0
            self.stack.remove(old)
            page = self._build(name)
            self.stack.add_named(page, name)
            if scroll and hasattr(page, "get_vadjustment"):
                GLib.idle_add(lambda p=page, v=scroll: (p.get_vadjustment().set_value(v), False)[1])
        self.stack.set_visible_child_name(visible)

    def _later(self, *names):
        GLib.idle_add(lambda: (self._rebuild(*names), False)[1])

    # Général

    def _general(self):
        page = Adw.PreferencesPage()
        hk = self.c.hotkey
        page.add(group(
            "Raccourci pour ouvrir Hello",
            status_row("Raccourci", hk.active, f"{hk.description} · " + ("actif" if hk.active else "inactif"),
                       ("Changer…", hk.configure)),
            combo("hotkey", "Combinaison", [(v, t) for v, t, _ in CHOICES], icon="hello-keyboard-symbolic",
                  subtitle="Sur Plasma, Hello la reprend à l'action qui l'utilisait"),
            description="Sans raccourci, « hello --toggle » peut être associé à une touche dans les réglages du "
                        "système."))
        login = Adw.SwitchRow(title="Lancer Hello à l'ouverture de session")
        login.set_active(os.path.exists(self.c.autostart_path))
        login.connect("notify::active", lambda r, _p: self.c.toggle_autostart()
                      if r.get_active() != os.path.exists(self.c.autostart_path) else None)
        page.add(group("Démarrage", with_icon(login, "hello-login-symbolic"),
                       switch("showTrayIcon", "Icône dans la zone de notification",
                              "Clic : ouvrir Hello · clic droit : le menu", icon="hello-apps-symbolic")))
        page.add(self._updates())

        from .ui import layer_shell_supported
        ydotool = desktop.can_paste()
        page.add(group(
            "État du système",
            status_row("Panneau flottant (gtk4-layer-shell)", layer_shell_supported(),
                       "Le panneau passe au-dessus de tout" if layer_shell_supported()
                       else "Indisponible : fenêtre ordinaire (installe gtk4-layer-shell)"),
            status_row("Presse-papiers (wl-clipboard)", shutil.which("wl-paste") is not None,
                       "Historique actif" if shutil.which("wl-paste") else "Installe wl-clipboard"),
            status_row("Collage direct (ydotool)", ydotool,
                       "↵ colle dans l'app active" if ydotool else
                       "Sans lui, Hello copie seulement. « systemctl --user enable --now ydotool » "
                       "(et l'accès à /dev/uinput)"),
            status_row("IA", Hermes.available(),
                       ", ".join(engines.TITLES[e] for e in engines.ENGINES if engines.installed(e))
                       or "Aucun fournisseur installé"),
            description="Ce dont Hello a besoin sur ce bureau."))
        return page

    def _updates(self):
        self.update_status = Adw.ActionRow(title=f"Hello {__version__}", use_markup=False)
        with_icon(self.update_status, "hello-update-symbolic")
        self.update_button = Gtk.Button(valign=Gtk.Align.CENTER)
        self.update_button.connect("clicked", lambda *_: Updater.install() if Updater.pending else Updater.check())
        self.update_status.add_suffix(self.update_button)
        notes = Gtk.Button(label="Nouveautés", valign=Gtk.Align.CENTER)
        notes.add_css_class("flat")
        notes.connect("clicked", lambda *_: Updater.pending and desktop.open_uri(Updater.pending["page"]))
        self.update_notes = notes
        self.update_status.add_suffix(notes)
        self._update_status()
        return group("Mises à jour", self.update_status,
                     switch("autoUpdateCheck", "Vérifier toutes les 6 heures"),
                     switch("autoUpdateInstall", "Installer automatiquement",
                            "Quand le panneau est fermé ; Hello se relance en arrière-plan et te prévient"),
                     switch("updatePrereleases", "Proposer aussi les préversions (alpha, bêta)"),
                     description=f"Depuis les releases GitHub de {updater.REPO}. Hello vérifie l'archive "
                                 "avant de l'installer.")

    def _update_status(self):
        if not hasattr(self, "update_status"):
            return
        release = Updater.pending
        text = {
            "checking": "Recherche…",
            "up_to_date": "À jour",
            "available": f"La version {release['version']} est disponible" if release else "",
            "downloading": f"Téléchargement… {int(Updater.progress * 100)} %",
            "installing": "Installation… Hello va se relancer",
            "failed": f"Échec : {Updater.error}",
        }.get(Updater.state, "Version installée")
        self.update_status.set_subtitle(text)
        self.update_button.set_label(f"Installer {release['version']}" if release else "Rechercher")
        (self.update_button.add_css_class if release else self.update_button.remove_css_class)("suggested-action")
        self.update_button.set_sensitive(not Updater.busy())
        self.update_notes.set_visible(release is not None)

    # Apparence

    def _appearance(self):
        page = Adw.PreferencesPage()
        style = settings.panelStyle if settings.panelStyle in STYLES else "kde"
        info = STYLES[style]

        cards = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.SINGLE, homogeneous=True, max_children_per_line=4,
                            min_children_per_line=2, column_spacing=6, row_spacing=6)
        for key, value in STYLES.items():
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=6, margin_bottom=6,
                          margin_start=6, margin_end=6)
            box.append(StylePreview(key))
            name = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
            name.append(Gtk.Image.new_from_icon_name(value["icon"]))
            name.append(Gtk.Label(label=value["title"]))
            box.append(name)
            child = Gtk.FlowBoxChild(child=box)
            child.style = key
            child.set_tooltip_text(value["detail"])
            cards.append(child)
            if key == style:
                cards.select_child(child)

        def chosen(_box, child):
            if child.style != settings.panelStyle:
                settings.panelStyle = child.style
                self._later("appearance", "motion")
        cards.connect("child-activated", chosen)
        style_group = group("Style", description=f"{info['title']} : {info['detail']}")
        style_group.add(cards)
        page.add(style_group)

        options = self._style_options(style)
        if options:
            page.add(group(f"Couleurs · {info['title']}", *options))
        if style == "glyph":
            hours = [(h, f"{h} h") for h in range(24)]
            page.add(group(
                "Nuit",
                switch("glyphAutoNight", "Passer en Nuit aux heures choisies", icon="hello-night-symbolic"),
                combo("glyphNightStart", "À partir de", hours),
                combo("glyphNightEnd", "Jusqu'à", hours),
                spin("glyphNightLevel", "Luminosité du rouge", 0.4, 1, 0.05, 2),
                description="Rouge sur noir, pour la nuit. Rempli : sélectionné ; au trait : disponible."))

        page.add(group(
            "Panneau",
            combo("panelSize", "Taille", [(k, v[0]) for k, v in PANEL_SIZES.items()]),
            combo("panelPosition", "Position", [("upper", "Tiers supérieur de l'écran"), ("center", "Centre de l'écran")]),
            combo("rowDensity", "Densité des lignes", [(k, v[0]) for k, v in ROW_DENSITY.items()],
                  icon="hello-density-symbolic"),
            slider("textScale", "Taille du texte", 0.85, 1.3, [(0.85, "Petit"), (1.0, "Normal"), (1.3, "Grand")],
                   icon="hello-text-size-symbolic"),
        ))
        page.add(group(
            "Contenu des lignes",
            switch("showSubtitles", "Sous-titres", "La description sous chaque titre"),
            switch("showAccessories", "Étiquettes à droite", "Ouverte, Dossier, branche git…"),
            switch("showHints", "Touches dans le pied de page", "↵ Ouvrir, Ctrl ↵…"),
            switch("focusMode", "Mode focus", "À l'ouverture, seulement la barre de recherche",
                   icon="hello-focus-symbolic"),
        ))

        def reset():
            settings.reset_appearance()
            self._later("appearance", "motion")
        page.add(group(None, button_row("Rétablir l'apparence d'origine", reset)))
        return page

    def _style_options(self, style):
        """Les réglages propres au style choisi."""
        if style == "kde":
            row = Adw.ActionRow(title="Couleurs, accent et police de Plasma",
                                subtitle="Hello suit le thème choisi dans la Configuration du système")
            if shutil.which("systemsettings"):
                button = Gtk.Button(label="Ouvrir", valign=Gtk.Align.CENTER)
                button.connect("clicked", lambda *_: desktop.spawn(["systemsettings", "kcm_colors"]))
                row.add_suffix(button)
            return [with_icon(row, "hello-palette-symbolic")]
        if style == "glass":
            return [color("glassTintHex", "Teinte du verre"),
                    slider("glassTintAmount", "Intensité de la teinte", 0, 1, [(0, "Aucune"), (1, "Forte")]),
                    color("highlightHex", "Couleur de la sélection"),
                    slider("highlightAmount", "Intensité de la sélection", 0.04, 0.6, [(0.04, "Discrète"), (0.6, "Forte")]),
                    slider("cornerRadius", "Arrondi des coins", 12, 32, [(12, "Carré"), (32, "Rond")]),
                    switch("glassBorder", "Bordure plus marquée")]
        if style == "atelier":
            return [combo("atelierPalette", "Couleurs", [(k, v[0]) for k, v in PALETTES.items()]),
                    switch("atelierSwap", "Inverser les deux couleurs"),
                    combo("atelierAppearance", "Apparence", list(APPEARANCES.items())),
                    switch("atelierColoredSelection", "Sélection en couleur", "En apparence claire")]
        if style == "glyph":
            return [combo("glyphAccent", "Accent", [(k, v[0]) for k, v in GLYPH_ACCENTS.items()],
                          subtitle="Une seule couleur : la touche ↵, le logo et l'élément choisi"),
                    combo("glyphAppearance", "Apparence", list(GLYPH_APPEARANCES.items()))]
        if style == "phosphor":
            return [combo("phosphorColor", "Couleur du phosphore", [(k, v[0]) for k, v in PHOSPHOR.items()])]
        if style == "paper":
            return [combo("paperTone", "Papier", list(PAPER.items()))]
        if style == "brutal":
            return [combo("brutalColor", "Couleur", [(k, v[0]) for k, v in BRUTAL.items()])]
        return []

    # Animations

    def _motion(self):
        page = Adw.PreferencesPage()
        style = settings.panelStyle if settings.panelStyle in STYLES else "kde"
        info = STYLES[style]
        master = switch("animations", "Animer Hello",
                        "Coupé aussi quand le bureau demande moins d'animations", icon="hello-motion-symbolic")
        page.add(group(None, master))

        try_it = Gtk.Button(label="Essayer", valign=Gtk.Align.CENTER)
        try_it.add_css_class("suggested-action")
        try_it.connect("clicked", lambda *_: self.c.show())
        opening = group(f"À l'ouverture · {info['title']}", description=info["reveal"], suffix=try_it)
        opening.add(switch("haloSweep", "Dessin d'ouverture", FLOURISH[style]))
        if style == "glyph":
            opening.add(switch("asciiDecode", "Décodage ASCII", "Textes et icônes, aussi en tapant et à chaque sélection"))
        page.add(opening)

        rhythm = group(
            "Rythme",
            combo("motionIntensity", "Amplitude", [("subtle", "Subtile"), ("normal", "Normale"),
                                                   ("expressive", "Expressive")],
                  subtitle="Distance des mouvements et force des rebonds"),
            slider("animationSpeed", "Vitesse", 0.5, 2, [(0.5, "Lente"), (1, "Normale"), (2, "Rapide")],
                   icon="hello-speed-symbolic"))
        page.add(rhythm)
        others = group("Ailleurs", switch("launchEffects", "Fondu en ouvrant une app"))
        page.add(others)
        for g in (opening, rhythm, others):
            master.bind_property("active", g, "sensitive", GObject.BindingFlags.SYNC_CREATE)
        return page

    # Recherche

    def _search(self):
        page = Adw.PreferencesPage()
        terminals = [("", "Automatique")] + [(t[0], t[1]) for t in desktop.installed_terminals()]
        editors = [("", "Automatique")] + [(e[0], e[1]) for e in desktop.installed_editors()] + [("none", "Aucun")]
        page.add(group(
            "Classement des résultats",
            switch("frecencyRanking", "Frécence", "Les apps ouvertes souvent et récemment passent devant"),
            switch("learnQueries", "Apprendre ce que je tape", "« f » finit par donner Firefox"),
            switch("showRecents", "Récents à l'ouverture", "Avant même de taper"),
        ))
        page.add(group(
            "Terminal",
            switch("shellCommands", "Commandes shell", "Dossiers, processus, ports (> commande, cd, kill, :3000…)",
                   icon="hello-terminal-symbolic"),
            combo("terminal", "Application de terminal", terminals),
            combo("editor", "Éditeur de code", editors),
            switch("shellHistory", "Historique du shell", "zsh et bash"),
            switch("useZoxide", "Dossiers fréquents de zoxide"),
            switch("shellInteractive", "Shell interactif", "Alias et fonctions de ~/.zshrc"),
        ))
        page.add(self._custom_commands())
        return page

    def _custom_commands(self):
        add = Gtk.Button(label="Ajouter", valign=Gtk.Align.CENTER)
        add.add_css_class("flat")
        g = group("Commandes personnalisées", suffix=add,
                  description="Un mot-clé lance une commande ; « {} » est remplacé par ce qui suit "
                              "(ex. « gh owner/repo »).")

        def save():
            settings.customCommands = [dict(c) for c in commands]

        commands = [dict(c) for c in settings.customCommands]

        def build(cmd):
            row = Adw.ExpanderRow(title=cmd["name"], subtitle=cmd["command"], use_markup=False)
            for key, title in (("name", "Nom"), ("keyword", "Mot-clé"), ("command", "Commande")):
                e = Adw.EntryRow(title=title)
                e.set_text(cmd[key])

                def changed(r, key=key):
                    cmd[key] = r.get_text()
                    row.set_title(cmd["name"] or "Sans nom")
                    row.set_subtitle(cmd["command"])
                    save()
                e.connect("changed", changed)
                row.add_row(e)
            modes = [("app", "Dans Hello"), ("terminal", "Dans le terminal"), ("silent", "En silence")]
            mode = Adw.ComboRow(title="Exécution", model=Gtk.StringList.new([t for _, t in modes]))
            mode.set_selected([m for m, _ in modes].index(cmd.get("mode", "app")))

            def mode_changed(r, _p):
                cmd["mode"] = modes[r.get_selected()][0]
                save()
            mode.connect("notify::selected", mode_changed)
            row.add_row(mode)
            delete = Gtk.Button.new_from_icon_name("hello-trash-symbolic")
            delete.set_tooltip_text("Supprimer")
            delete.add_css_class("flat")
            delete.set_valign(Gtk.Align.CENTER)

            def remove(*_):
                commands.remove(cmd)
                g.remove(row)
                save()
            delete.connect("clicked", remove)
            row.add_suffix(delete)
            g.add(row)
            return row

        for cmd in commands:
            build(cmd)

        def added(*_):
            cmd = {"id": str(uuid.uuid4()), "name": "Nouvelle commande", "keyword": "", "command": "echo {}",
                   "mode": "app"}
            commands.append(cmd)
            save()
            build(cmd).set_expanded(True)
        add.connect("clicked", added)
        return g

    # Presse-papiers

    def _clipboard(self):
        page = Adw.PreferencesPage()
        page.add(group(
            "Historique",
            switch("clipboardEnabled", "Garder l'historique du presse-papiers",
                   "Les copies des gestionnaires de mots de passe sont ignorées", icon="hello-clipboard-symbolic"),
            switch("clipboardImages", "Garder aussi les images", icon="hello-image-symbolic"),
            spin("clipboardLimit", "Nombre d'éléments gardés", 20, 2000, 10),
            spin("clipboardRetentionDays", "Durée de conservation", 0, 365, 1, subtitle="En jours ; 0 : sans limite"),
        ))
        page.add(group(
            "Coller",
            switch("pasteOnEnter", "↵ colle dans l'app active",
                   "Avec ydotool ; sinon, Hello copie et tu colles toi-même"),
        ))
        page.add(group(None, button_row("Vider l'historique", lambda: self.c.clipboard.clear(), destructive=True)))
        return page

    # IA

    def _agent(self):
        page = Adw.PreferencesPage()
        page.add(group(
            "Assistant",
            switch("agentEnabled", "Proposer l'IA dans les résultats", icon="hello-sparkle-symbolic"),
            combo("agentStrategy", "Niveau", [("auto", "Auto : selon la demande"),
                                              ("act", "Toujours Recherche & Action"),
                                              ("delegate", "Toujours Code")]),
            description="Tape « ? » puis ta demande ; « ?? » force Recherche & Action, « ??? » Code. "
                        "Ctrl O joint un fichier, Ctrl ⇧ S une capture d'écran, Ctrl W masque Hello pendant que "
                        "l'IA travaille."))

        levels = group("Les trois niveaux", description="Chaque niveau a son fournisseur et son modèle.")
        for level, detail in ((1, "Répond tout de suite, ou choisit le niveau"),
                              (2, "Cherche sur le web et agit sur l'ordinateur"),
                              (3, f"Session de code dans {desktop.terminal()[1]}")):
            levels.add(self._level(level, detail))
        page.add(levels)

        recheck = Gtk.Button(label="Revérifier", valign=Gtk.Align.CENTER)
        recheck.add_css_class("flat")

        def again(*_):
            Hermes.locate()
            engines.EngineStatus.locate()
            GLib.timeout_add(1500, lambda: (self._rebuild("agent", "general"), False)[1])
        recheck.connect("clicked", again)
        providers = group("Fournisseurs", suffix=recheck)
        for engine in engines.ENGINES:
            path = engines.binary(engine)
            detail = path or "Non installé"
            if engine == "hermes" and path and Hermes.providers:
                detail += " · " + ", ".join(Hermes.provider_name(p) for p in Hermes.providers)
            providers.add(status_row(engines.TITLES[engine], path is not None, detail,
                                     None if path else ("Installer…", lambda e=engine: desktop.run_in_terminal(
                                         engines.INSTALL[e]))))
        page.add(providers)

        count = len(ChatStore.conversations)

        def wipe():
            ChatStore.clear()
            self._later("agent")
        memory = group("Conversations",
                       switch("agentHistory", "Garder les conversations", "Pour les reprendre avec « /resume »",
                              icon="hello-chats-symbolic"),
                       description="Sous une réponse, une question de suite reçoit les échanges précédents.")
        if count:
            memory.add(button_row(f"Effacer les {count} conversations", wipe, destructive=True))
        page.add(memory)
        return page

    def _level(self, level, detail):
        """Fournisseur, modèle et raisonnement d'un niveau, dans une ligne dépliable. Changer de fournisseur reprend
        le réglage proposé pour lui."""
        config = engines.LevelConfig.of(level)
        keys = engines.LEVEL_KEYS[level]
        title, icon, _tint = LEVELS[level]
        row = Adw.ExpanderRow(title=f"{level} · {title}", subtitle=f"{detail} · {config.label}", use_markup=False)
        image = Gtk.Image.new_from_icon_name(icon)
        image.set_pixel_size(20)
        image.add_css_class(f"hello-level-{level}")
        row.add_prefix(image)
        row.set_expanded(level in self._expanded)
        row.connect("notify::expanded", lambda r, _p: (self._expanded.add if r.get_expanded()
                                                       else self._expanded.discard)(level))

        provider = Adw.ComboRow(title="Fournisseur")
        names = [engines.TITLES[e] + ("" if engines.installed(e) else " (non installé)") for e in engines.ENGINES]
        provider.set_model(Gtk.StringList.new(names))
        provider.set_selected(engines.ENGINES.index(config.engine))

        def engine_changed(r, _p):
            chosen = engines.ENGINES[r.get_selected()]
            if chosen != engines.LevelConfig.of(level).engine:
                engines.set_engine(level, chosen)
                self._later("agent")
        provider.connect("notify::selected", engine_changed)
        row.add_row(provider)

        # Modèle : pour Hermes, le compte va avec (« compte|modèle »).
        if config.engine == "hermes":
            options = [("|", "Défaut de Hermes")] + [(f"{p}|{m}", f"{m} ({Hermes.provider_name(p)})")
                                                   for p, m in Hermes.models]
            current = f"{config.provider}|{config.model}" if config.model else "|"
        else:
            options = [("", f"Défaut de {config.title}")] + list(engines.models(config.engine))
            current = config.model
        if current not in [v for v, _ in options]:
            options.append((current, current.split("|")[-1]))
        model = Adw.ComboRow(title="Modèle")
        model.set_model(Gtk.StringList.new([t for _, t in options]))
        model.set_selected([v for v, _ in options].index(current))

        def model_changed(r, _p):
            value = options[r.get_selected()][0]
            if config.engine == "hermes":
                p, m = value.split("|", 1)
                setattr(settings, keys[1], p)
                setattr(settings, keys[2], m)
            else:
                setattr(settings, keys[2], value)
            row.set_subtitle(f"{detail} · {engines.LevelConfig.of(level).label}")
        model.connect("notify::selected", model_changed)
        row.add_row(model)

        levels = [""] + engines.REASONING[config.engine]
        if config.reasoning not in levels:
            levels.append(config.reasoning)
        row.add_row(combo(keys[3], "Raisonnement", [(v, v or "Défaut") for v in levels],
                          subtitle="Plus élevé : plus réfléchi, mais plus lent"))
        if level == 3:
            row.add_row(entry("agentWorkdir", "Dossier de travail"))
        return row
