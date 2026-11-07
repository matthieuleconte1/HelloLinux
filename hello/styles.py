"""Les peaux (Styles.swift) : jetons de style et feuille CSS GTK générée selon les réglages.
Le style KDE, propre à Linux, suit le thème de couleurs de Plasma (kdeglobals)."""
import configparser
import os

from .motion import Spring, clamp01, keyframes, smooth, snappy
from .settings import ROW_DENSITY, glyph_appearance, motion_enabled, motion_speed, settings

# Flou KWin disponible pour le panneau (renseigné par la fenêtre une fois affichée) : le Verre et le style KDE
# deviennent alors translucides.
BLUR = {"available": False}

STYLES = {
    "kde": {"title": "KDE", "icon": "hello-style-kde-symbolic",
            "reveal": "Le panneau glisse comme un menu de Plasma, les lignes suivent, un filet d'accent se trace sous la recherche.",
            "detail": "Suit Plasma : thème de couleurs, couleur d'accentuation et police du système, "
                      "avec le flou de KWin."},
    "glass": {"title": "Verre", "icon": "hello-style-glass-symbolic",
              "reveal": "Le verre passe du flou au net, un reflet balaie la vitre et un liseré multicolore fait le tour du bord.",
              "detail": "Verre transparent ou dépoli, teinte réglable."},
    "atelier": {"title": "Atelier Expressif", "icon": "hello-style-atelier-symbolic",
                "reveal": "Le panneau se déploie depuis la recherche avec un ressort, un anneau de focus s'ouvre autour d'elle.",
                "detail": "Recherche en pilule, listes segmentées et deux accents."},
    "glyph": {"title": "Atelier Glyphe", "icon": "hello-style-glyph-symbolic",
              "reveal": "Une onde de points part du logo, textes et icônes se décodent en ASCII.",
              "detail": "Cadre noir, accent unique et sélection inversée."},
    "phosphor": {"title": "Phosphore", "icon": "hello-style-phosphor-symbolic",
                 "reveal": "Le tube s'allume, puis un faisceau balaie l'écran et fait apparaître les lignes une à une.",
                 "detail": "Écran cathodique et caractères en chasse fixe."},
    "paper": {"title": "Papier", "icon": "hello-style-paper-symbolic",
              "reveal": "La feuille se déplie en perspective, un trait d'encre se trace sous la recherche.",
              "detail": "Papier, titres à empattements et filets fins."},
    "brutal": {"title": "Néo-brutal", "icon": "hello-style-brutal-symbolic",
               "reveal": "Le panneau tombe, s'écrase sur son ombre et rebondit, avec des traits d'impact.",
               "detail": "Contours noirs, ombres pleines et couleurs franches."},
}

# Thèmes d'Atelier : deux couleurs signal sur une base neutre.
PALETTES = {
    "lime": ("Lime / Lavande", "#D4F54A", "#B7AEF7"),
    "orange": ("Orange / Ciel", "#FF6A2B", "#8FD3FF"),
    "pink": ("Rose / Menthe", "#FF5FA2", "#7FF0C4"),
    "yellow": ("Jaune / Outremer", "#FFD23F", "#7D95FF"),
    "red": ("Rouge / Sable", "#FF4F3A", "#EFE2C4"),
}
PHOSPHOR = {"green": ("Vert P1", "#4BFF88", "#040A06"), "amber": ("Ambre P3", "#FFB43A", "#0B0702"),
            "white": ("Blanc P4", "#E6EEFF", "#05070B"), "cyan": ("Cyan", "#3BE8FF", "#02090C")}
PAPER = {"cream": "Crème", "ivory": "Ivoire", "night": "Nuit"}
BRUTAL = {"pink": ("Rose", "#FF8AD8"), "yellow": ("Jaune", "#FFD84D"), "blue": ("Bleu", "#7CB8FF"),
          "green": ("Vert", "#7BE495")}
APPEARANCES = {"auto": "Auto", "light": "Clair", "dark": "Sombre"}
GLYPH_APPEARANCES = {"auto": "Auto", "light": "Clair", "dark": "Sombre", "night": "Nuit"}
# Accent unique d'Atelier Glyphe (les six de l'artifact) : accent et texte posé dessus ; None pour Mono (il dépend de
# l'apparence). Il ne décore jamais : il marque l'action principale (touche ↵), le logo et l'élément choisi.
GLYPH_ACCENTS = {"orange": ("Orange", "#ED6A0C", "#FFFFFF"), "amber": ("Ambre", "#EFB85C", "#111111"),
                 "green": ("Vert", "#78DD8B", "#111111"), "coral": ("Corail", "#FF6C67", "#111111"),
                 "violet": ("Violet", "#A25BFF", "#FFFFFF"), "mono": ("Mono", None, None)}
GLYPH_FONT = "'Red Hat Display', 'Inter', 'Noto Sans', sans-serif"
GLYPH_DISPLAY = "'Zalando Sans Expanded', 'Red Hat Display', 'Inter', 'Noto Sans', sans-serif"

# Mouvement de la sélection (StyleTokens.motion de la version Mac) ; None : saut net (Phosphore, un terminal).
# Le style KDE, propre à Linux, prend la vivacité des menus de Plasma.
SELECTION_SPRINGS = {"kde": snappy(0.16), "glass": snappy(0.18), "atelier": Spring(0.32, 0.8), "glyph": Spring(0.36, 0.78),
                     "phosphor": None, "paper": smooth(0.2), "brutal": Spring(0.24, 0.55)}
# Défilement de la liste jusqu'à la sélection.
SCROLL_SPRING = smooth(0.3)
# Hauteur ajustée aux résultats, et passage à la grille d'applications (Controller.swift).
FIT_SPRING = Spring(0.3, 0.88)
MORPH_SPRING = Spring(0.44, 0.84)


def selection_spring(t=None):
    t = t or tokens()
    return SELECTION_SPRINGS.get(t["style"])


# Dégradé du logo et du reflet du Verre.
GLASS_COLORS = ["#5B4CFA", "#ED5CBF", "#FFA866", "#FFE9CF"]


def rgb(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgba(hex_color, alpha=1.0):
    r, g, b = rgb(hex_color)
    return f"rgba({r},{g},{b},{alpha:.3f})"


def mix(a, b, t):
    ra, rb = rgb(a), rgb(b)
    return "#%02X%02X%02X" % tuple(round(x + (y - x) * t) for x, y in zip(ra, rb))


def system_is_dark():
    try:
        from gi.repository import Adw
        return Adw.StyleManager.get_default().get_dark()
    except Exception:
        return True


KDEGLOBALS = os.path.join(os.path.expanduser("~"), ".config", "kdeglobals")
_kde_cache = {"mtime": None, "colors": None}


def kde_colors():
    """Couleurs du thème Plasma (Breeze par défaut si kdeglobals est absent), lues une fois par modification."""
    try:
        mtime = os.path.getmtime(KDEGLOBALS)
    except OSError:
        mtime = None
    if _kde_cache["colors"] is not None and _kde_cache["mtime"] == mtime:
        return _kde_cache["colors"]
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    try:
        parser.read(KDEGLOBALS, encoding="utf-8")
    except (configparser.Error, UnicodeDecodeError):
        pass
    dark_default = system_is_dark()
    breeze = {  # Breeze sombre / clair
        ("Colors:Window", "BackgroundNormal"): "32,35,38" if dark_default else "239,240,241",
        ("Colors:Window", "ForegroundNormal"): "252,252,252" if dark_default else "35,38,41",
        ("Colors:View", "BackgroundNormal"): "20,22,24" if dark_default else "255,255,255",
        ("Colors:View", "ForegroundNormal"): "252,252,252" if dark_default else "35,38,41",
        ("Colors:View", "ForegroundInactive"): "161,169,177" if dark_default else "112,125,138",
        ("Colors:Selection", "BackgroundNormal"): "61,174,233",
        ("Colors:Selection", "ForegroundNormal"): "252,252,252",
        ("Colors:Button", "BackgroundNormal"): "41,44,48" if dark_default else "252,252,252",
        ("Colors:View", "ForegroundPositive"): "39,174,96",
    }

    def get(section, key):
        raw = parser.get(section, key, fallback=None) or breeze.get((section, key), "128,128,128")
        try:
            r, g, b = (int(v) for v in raw.split(",")[:3])
        except ValueError:
            r, g, b = (int(v) for v in breeze.get((section, key), "128,128,128").split(","))
        return "#%02X%02X%02X" % (r, g, b)

    accent_raw = parser.get("General", "AccentColor", fallback=None)
    font = (parser.get("General", "font", fallback="") or "").split(",")[0].strip()
    colors = {
        "window": get("Colors:Window", "BackgroundNormal"), "window_fg": get("Colors:Window", "ForegroundNormal"),
        "view": get("Colors:View", "BackgroundNormal"), "fg": get("Colors:View", "ForegroundNormal"),
        "inactive": get("Colors:View", "ForegroundInactive"), "button": get("Colors:Button", "BackgroundNormal"),
        "selection": get("Colors:Selection", "BackgroundNormal"),
        "selection_fg": get("Colors:Selection", "ForegroundNormal"),
        "positive": get("Colors:View", "ForegroundPositive"),
        "font": font,
    }
    if accent_raw:
        try:
            colors["accent"] = "#%02X%02X%02X" % tuple(int(v) for v in accent_raw.split(",")[:3])
        except ValueError:
            colors["accent"] = colors["selection"]
    else:
        colors["accent"] = colors["selection"]
    _kde_cache.update(mtime=mtime, colors=colors)
    return colors


def luminance(hex_color):
    r, g, b = (v / 255 for v in rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def glyph_tokens(choice, appearance):
    """Valeurs de l'artifact « Atelier Glyphe » : cadre noir chaud (identique dans tous les thèmes), panneau en
    retrait clair ou sombre, gris superposés, sélection inversée comme l'élément coché d'un menu."""
    if appearance == "night":
        return glyph_night(float(settings.glyphNightLevel))
    dark = appearance == "dark" or (appearance == "auto" and system_is_dark())
    frame, on_frame = "#050403", "#FFFFFF"
    ink = on_frame if dark else "#111111"
    # Sombre : le panneau se détache du cadre d'un cran (assez pour lire la profondeur, sans griser le noir),
    # sélection en blanc cassé chaud plutôt qu'un blanc pur qui éblouit dans le noir.
    selection, selection_ink = ("#ECE9E4", "#111111") if dark else ("#080604", "#FFFFFF")
    _, accent, on_accent = GLYPH_ACCENTS.get(choice, GLYPH_ACCENTS["orange"])
    # Mono : l'accent se confond avec la sélection, la pastille choisie s'inverse plutôt.
    mono = accent is None
    if mono:
        accent, on_accent = ink, ("#111111" if dark else "#FFFFFF")
    # Logo et touche ↵ sont posés sur le cadre noir : Mono y passe en blanc.
    frame_accent = on_frame if mono else accent
    return dict(
        style="glyph", dark=dark, surface=frame, pane="#100E0C" if dark else "#EFEEEC", card=None, ink=ink,
        chrome_ink=on_frame, accent=accent, accent2=accent, toast=on_frame, selection=selection,
        selection_ink=selection_ink, radius=22, row_radius=12, cell_radius=14, border=None, hard_shadow=None,
        divider="transparent", font=GLYPH_FONT, display_font=GLYPH_DISPLAY, title_font=None, title_weight=600,
        header="label", key_fill=rgba("#FFFFFF", 0.07), key_ink=rgba("#FFFFFF", 0.62),
        key_border=rgba("#FFFFFF", 0.14), primary_key=(frame_accent, "#050403" if mono else on_accent),
        mono_keys=True, pane_border=rgba("#FFFFFF", 0.08) if dark else None, strong_meta=dark,
        tile=("glyph", "#262421" if dark else "#E7E5E2", ink, selection_ink if mono else accent,
              selection if mono else on_accent, None),
        mark=("glyph", on_frame, frame_accent), search_bar=False, mono=False, ascii=True)


def glyph_night(level):
    """La Nuit de l'artifact : une seule teinte, alors la forme prend le relais de la couleur.
    Rempli = choisi · trait plein = disponible · pointillé = secondaire · décalage du trait = hauteur.
    Pas de lueur ni d'ombre floue : la seule lumière est ce rouge, à la luminosité réglée.
    La ligne choisie est cernée (un bloc rouge plein éblouit dans le noir) ; ce qu'elle contient se remplit :
    pastille rouge, icône en couleur pleine aux traits gravés. Les icônes d'apps sont dessinées au trait
    (icontrace.py) sur leur couleur atténuée."""
    level = min(max(level, 0.4), 1.0)
    red = "#%02X%02X%02X" % (round(255 * level), round(80 * level), round(60 * level))
    line = "rgba(255,60,40,0.58)"
    outline = bool(settings.glyphNightOutline)
    opacity = min(max(float(settings.glyphNightIconOpacity), 0.0), 1.0)
    return dict(
        style="glyph", night=True, dark=True, surface="#000000", pane="#000000", card=None, ink=red, chrome_ink=red,
        accent=red, accent2=red, toast=red, selection="rgba(255,60,40,0.10)", selection_ink=None,
        selection_extra=f"box-shadow: inset 0 0 0 1.5px {red};", radius=22, row_radius=12,
        cell_radius=14, border=(line, 1), hard_shadow=6, hard_shadow_color="rgba(255,60,40,0.36)",
        divider="transparent", font=GLYPH_FONT, display_font=GLYPH_DISPLAY, title_font=None, title_weight=500,
        header="label", key_fill="transparent", key_ink=red, key_border=line, primary_key=(red, "#000000"),
        mono_keys=True, pane_border=line, chrome_caps=True, section_rule="rgba(255,60,40,0.32)", launch_tint=red,
        tile=("glyph", "transparent", red, red, "#000000", line), strong_meta=True,
        icon_filter=None if settings.glyphNightIconColors else "red",
        # Sans contour, une icône à 0 % disparaîtrait.
        icon_opacity=opacity if outline else max(opacity, 0.1), icon_outline=outline,
        icon_edges=float(settings.glyphNightEdgeDetail) if settings.glyphNightEdges else None,
        monochrome=red, mark=("glyph", red, red), search_bar=False, mono=False, ascii=True)


def tokens(style=None):
    """Tout ce qu'un style décide, selon les réglages courants (un autre style que le choisi : pour son aperçu)."""
    style = style or settings.panelStyle
    style = style if style in STYLES else "kde"
    if style == "glyph":
        return glyph_tokens(settings.glyphAccent, glyph_appearance())
    if style == "kde":
        k = kde_colors()
        ink, accent = k["window_fg"], k["accent"]
        font = f"'{k['font']}', 'Noto Sans', sans-serif" if k["font"] else None
        return dict(
            style=style, dark=luminance(k["window"]) < 0.5, blur=True,
            surface=rgba(k["window"], 0.80 if BLUR["available"] else 1.0), pane=None, card=None,
            ink=ink, chrome_ink=ink, accent=accent, accent2=accent, toast=k["positive"],
            # Sélection de Plasma 6 : accent léger, filet d'accent.
            selection=rgba(accent, 0.22), selection_ink=None,
            selection_extra=f"box-shadow: inset 0 0 0 1px {rgba(accent, 0.75)};",
            radius=12, row_radius=5, cell_radius=8, border=(rgba(ink, 0.14), 1), hard_shadow=None,
            divider=rgba(ink, 0.10), font=font, title_font=None, title_weight=500, header="plain",
            key_fill=rgba(k["button"], 0.9), key_ink=rgba(ink, 0.75), key_border=rgba(ink, 0.22),
            primary_key=(accent, k["selection_fg"]), mark=("paper", ink, accent), search_bar=False, mono=False)
    if style == "atelier":
        dark = {"auto": system_is_dark(), "light": False, "dark": True}[settings.atelierAppearance]
        _, primary, secondary = PALETTES.get(settings.atelierPalette, PALETTES["lime"])
        if settings.atelierSwap:
            primary, secondary = secondary, primary
        ink = "#F4F4F0" if dark else "#111112"
        colored = dark or settings.atelierColoredSelection
        return dict(
            style=style, dark=dark, frame="#000000" if dark else "#111112",
            surface="#000000" if dark else "#111112", pane="#1C1C1F" if dark else "#E3E3DC",
            card="#2C2C31" if dark else "#FFFFFF", ink=ink, chrome_ink="#F4F4F0", accent=primary, accent2=secondary,
            toast=primary, selection=primary if colored else "#111112",
            selection_ink="#111112" if colored else "#F4F4F0", radius=30, row_radius=22, cell_radius=28,
            border=None, hard_shadow=None, divider="transparent", font="'Google Sans Flex', 'Google Sans', "
            "'Roboto Flex', 'Inter', sans-serif", title_font=None, title_weight=600, header="emphasized",
            key_fill="#2C2C2F", key_ink=rgba("#F4F4F0", 0.85), key_border=None, primary_key=(primary, "#111112"),
            mark=("atelier", ink, secondary), search_bar=True, mono=False)
    if style == "phosphor":
        _, green, screen = PHOSPHOR.get(settings.phosphorColor, PHOSPHOR["green"])
        return dict(
            style=style, dark=True, surface=screen, pane=None, card=None, ink=green, chrome_ink=green, accent=green,
            accent2=green, toast=green, selection=green, selection_ink=screen, radius=10, row_radius=3,
            cell_radius=6, border=(rgba(green, 0.35), 1), hard_shadow=None, divider=rgba(green, 0.22),
            font="'JetBrains Mono', 'Fira Code', 'DejaVu Sans Mono', monospace", title_font=None, title_weight=400,
            header="comment", key_fill="transparent", key_ink=rgba(green, 0.75), key_border=rgba(green, 0.4),
            primary_key=(green, screen), mark=("phosphor", green, green), search_bar=False, mono=True,
            icon_filter="phosphor")
    if style == "paper":
        tone = settings.paperTone
        night = tone == "night"
        ink = "#EDE6D8" if night else "#211C17"
        vermilion = "#FF7A45" if night else "#D9480F"
        sheet = {"cream": "#F4EFE6", "ivory": "#FBFAF5"}.get(tone, "#1E1B17")
        selection = {"cream": "#E8DFCE", "ivory": "#EFECE2"}.get(tone, "#2E2923")
        return dict(
            style=style, dark=night, surface=sheet, pane=None, card=None, ink=ink, chrome_ink=ink, accent=vermilion,
            accent2=vermilion, toast=vermilion, selection=selection, selection_ink=None, selection_bar=vermilion,
            radius=18, row_radius=6, cell_radius=14, border=(rgba(ink, 0.14), 1), hard_shadow=None,
            divider=rgba(ink, 0.14), font=None, title_font="'Source Serif 4', 'Noto Serif', 'DejaVu Serif', serif",
            title_weight=600, header="serif", key_fill="transparent", key_ink=rgba(ink, 0.6),
            key_border=rgba(ink, 0.25), primary_key=(vermilion, "#FFFFFF"), mark=("paper", ink, vermilion),
            search_bar=False, mono=False)
    if style == "brutal":
        _, color = BRUTAL.get(settings.brutalColor, BRUTAL["pink"])
        other = BRUTAL["pink"][1] if settings.brutalColor == "yellow" else BRUTAL["yellow"][1]
        return dict(
            style=style, dark=False, surface="#FFF4D6", pane=None, card=None, ink="#000000", chrome_ink="#000000",
            accent="#3D6BFF", accent2=color, toast="#3D6BFF", selection=color, selection_ink=None,
            selection_border="#000000", radius=16, row_radius=10, cell_radius=16, border=("#000000", 3),
            hard_shadow=8, divider="#000000", font=None, title_font=None, title_weight=700, header="kicker",
            key_fill="#FFFFFF", key_ink="#000000", key_border="#000000", primary_key=(other, "#000000"),
            mark=("brutal", color, "#FFD84D"), search_bar=False, mono=False)
    # Verre : fumé translucide, teinte et surlignage réglables.
    tint = settings.glassTintHex
    amount = float(settings.glassTintAmount)
    base = mix("#1C1C21", tint, min(amount, 1.0))
    # Avec le flou de KWin, le verre laisse voir le bureau ; sans lui, il reste presque opaque pour rester lisible.
    alpha = 0.50 + 0.40 * amount if BLUR["available"] else 0.985 + 0.015 * amount
    return dict(
        style="glass", dark=True, blur=True, surface=rgba(base, alpha), pane=None, card=None, ink="#F5F5F7",
        chrome_ink="#F5F5F7", accent="#8F7CFF", accent2="#ED5CBF", toast="#57E389",
        selection=rgba(settings.highlightHex, float(settings.highlightAmount)), selection_ink=None,
        radius=int(min(max(float(settings.cornerRadius), 12), 32)), row_radius=11, cell_radius=18,
        border=(rgba("#FFFFFF", 0.16 if settings.glassBorder else 0.07), 1), hard_shadow=None,
        divider=rgba("#FFFFFF", 0.08), font=None, title_font=None, title_weight=500, header="plain",
        key_fill=rgba("#FFFFFF", 0.08), key_ink=rgba("#FFFFFF", 0.55), key_border=None, primary_key=None,
        mark=("glass", None, None), search_bar=False, mono=False)


def section_title(text, t):
    header = t["header"]
    if header in ("kicker", "label"):
        return text.upper()
    if header == "comment":
        return "// " + text.lower()
    return text


def css():
    t = tokens()
    scale = float(settings.textScale)
    ink, chrome = t["ink"], t["chrome_ink"]
    soft = rgba(ink, 0.62)
    faint = rgba(ink, 0.42)
    font = f"font-family: {t['font']};" if t["font"] else ""
    title_font = f"font-family: {t['title_font']};" if t["title_font"] else ""
    border = f"border: {t['border'][1]}px solid {t['border'][0]};" if t["border"] else "border: none;"
    # Flou de l'arrière-plan : GTK le confie au compositeur (ext_background_effect_v1).
    backdrop = "backdrop-filter: blur(24px);" if t.get("blur") and BLUR["available"] else ""
    if t["hard_shadow"]:
        shadow = f"box-shadow: {t['hard_shadow']}px {t['hard_shadow']}px 0 0 {t.get('hard_shadow_color', '#000')};"
    else:
        shadow = "box-shadow: 0 22px 60px rgba(0,0,0,0.45), 0 4px 14px rgba(0,0,0,0.25);"
    density = ROW_DENSITY.get(settings.rowDensity, ROW_DENSITY["standard"])
    row_h = density[1]
    sel_ink = f"color: {t['selection_ink']};" if t.get("selection_ink") else ""
    # Changement de sélection : la couleur du texte (et, sans glissement, le fond et l'arrondi) suit le ressort du
    # style, comme SwiftUI interpole foregroundStyle avec matchedGeometryEffect.
    spring = selection_spring(t)
    if spring is None or not motion_enabled():
        select_transition = "none"
    else:
        settle = round(spring.scaled().settling() * 1000 * 0.6)
        select_transition = (f"color {settle}ms ease-out, background-color {settle}ms ease-out, "
                             f"border-radius {settle}ms ease-out")
    sel_extra = ""
    if t.get("selection_bar"):
        sel_extra = f"box-shadow: inset 3px 0 0 {t['selection_bar']};"
    if t.get("selection_border"):
        sel_extra = f"border: 2px solid {t['selection_border']}; box-shadow: 3px 3px 0 0 #000;"
    if t.get("selection_extra"):
        sel_extra = t["selection_extra"]
    scan = ""
    if t["style"] == "phosphor":
        scan = ("background-image: repeating-linear-gradient(to bottom, transparent 0px, transparent 2px, "
                "rgba(0,0,0,0.28) 2px, rgba(0,0,0,0.28) 3px);")
    header = {
        "plain": "font-size: 11px; font-weight: 600;",
        "kicker": "font-size: 10px; font-weight: 900; letter-spacing: 1.2px;",
        "comment": "font-size: 11px; font-family: monospace;",
        "serif": "font-size: 12.5px; font-style: italic; font-family: 'Source Serif 4', 'Noto Serif', serif;",
        "emphasized": "font-size: 12.5px; font-weight: 700;",
        "label": "font-size: 10.5px; font-weight: 500; font-family: monospace; letter-spacing: 0.7px;",
    }[t["header"]]
    if t.get("section_rule"):
        header += f" border-bottom: 1px dashed {t['section_rule']}; padding-bottom: 4px;"
    key_border = f"border: 1px solid {t['key_border']};" if t["key_border"] else "border: none;"
    key_shadow = "box-shadow: 2px 2px 0 0 #000;" if t["style"] == "brutal" else ""
    key_font = "font-family: monospace;" if t.get("mono_keys") else ""
    pk = t["primary_key"]
    primary_key = f".hello-key.primary {{ background: {pk[0]}; color: {pk[1]}; }}" if pk else ""
    pane = ""
    if t["pane"]:
        pane_border = f"border: 1px solid {t['pane_border']};" if t.get("pane_border") else ""
        pane = (f".hello-content {{ background: {t['pane']}; border-radius: {max(t['radius'] - 8, 8)}px; "
                f"margin: 0 8px; color: {ink}; {pane_border} }}")
    display = f"font-family: {t['display_font']}; font-stretch: expanded;" if t.get("display_font") else ""
    tile = ""
    if t.get("tile"):
        _, rest, tile_ink, chosen, chosen_ink, stroke = t["tile"]
        tile = (f".hello-gtile {{ background: {rest}; color: {tile_ink}; border-radius: 5px; "
                f"border: {'1px solid ' + stroke if stroke else 'none'}; "
                "transition: all 220ms cubic-bezier(0.3, 1.4, 0.5, 1); }"
                f".hello-list row.selected .hello-gtile, .hello-cell.selected .hello-gtile {{ background: {chosen}; "
                f"color: {chosen_ink}; border-radius: 9px; border-color: transparent; transform: scale(1.06); }}")
    icon_filter = ""
    if t.get("icon_filter") == "red":
        icon_filter = (".hello-appicon { filter: grayscale(1) sepia(1) saturate(6) hue-rotate(-38deg) "
                       f"brightness({0.55 + 0.45 * float(settings.glyphNightLevel):.2f}); }}")
    elif t.get("icon_filter") == "phosphor":
        hue = {"green": 95, "amber": 5, "cyan": 150}.get(settings.phosphorColor)
        icon_filter = (f".hello-appicon {{ filter: grayscale(1) sepia(1) saturate(5) hue-rotate({hue}deg); }}" if hue
                       else ".hello-appicon { filter: grayscale(1) brightness(1.15); }")
    # La Nuit : icônes atténuées au repos, pleines sur l'élément choisi ; leur dessin au trait à l'encre, gravé en
    # noir dans l'icône choisie quand elle est teinte en rouge.
    icon_rest = ""
    if t.get("icon_opacity", 1.0) < 1.0:
        o = t["icon_opacity"]
        icon_rest = (f".hello-appicon, .hello-tile {{ opacity: {o:.2f}; transition: opacity 150ms ease-out; }}"
                     ".hello-list row.selected .hello-appicon, .hello-cell.selected .hello-appicon, "
                     ".hello-cell:hover .hello-appicon, .hello-list row.selected .hello-tile { opacity: 1; }")
    engraved = "rgba(0,0,0,0.85)" if t.get("icon_filter") else ink
    icon_rest += (f".hello-outline {{ color: {ink}; }}"
                  f".hello-list row.selected .hello-outline, .hello-cell.selected .hello-outline, "
                  f".hello-cell:hover .hello-outline {{ color: {engraved}; }}"
                  f".hello-asciifade {{ color: {ink}; }}"
                  f".hello-cell.selected .hello-asciifade, gridview.hello-glyphs > child:selected .hello-asciifade "
                  f"{{ color: {t.get('selection_ink') or ink}; }}")
    search_bar = ""
    if t["search_bar"]:
        search_bar = (f".hello-header {{ background: {t['card']}; border-radius: 999px; margin: 7px 8px; "
                      f"padding: 0 6px 0 14px; min-height: 46px; color: {ink}; }}"
                      f".hello-header entry, .hello-header text {{ color: {ink}; }}"
                      f".hello-appsbutton {{ background: {t['accent']}; color: #111112; border-radius: 999px; "
                      f"min-width: 34px; min-height: 34px; }}")
    cards = ""
    if t["style"] == "atelier":
        # Listes segmentées ; la carte choisie prend la couleur et l'arrondi de la sélection (SegmentCard).
        cards = (f".hello-list row.hello-row {{ background: {t['card']}; border-radius: 5px; margin-bottom: 2px; }}"
                 f".hello-list row.hello-row.first {{ border-top-left-radius: 20px; border-top-right-radius: 20px; }}"
                 f".hello-list row.hello-row.last {{ border-bottom-left-radius: 20px; "
                 f"border-bottom-right-radius: 20px; }}"
                 f".hello-list row.hello-row.selected {{ border-radius: {t['row_radius']}px; }}")
    mono_title = "font-family: monospace;" if t["mono"] else ""
    return f"""
window.hello-window, window.hello-window > * {{ background: transparent; box-shadow: none; }}
.hello-panel {{
  background-color: {t['surface']}; {scan}
  border-radius: {t['radius']}px; {border} {shadow} {backdrop}
  color: {chrome}; {font}
}}
.hello-panel label, .hello-panel entry, .hello-panel text {{ {font} }}
.hello-header {{ min-height: 60px; padding: 0 18px; color: {chrome}; }}
{search_bar}
.hello-search, .hello-search > text {{
  background: none; border: none; box-shadow: none; outline: none; padding: 0;
  font-size: {round(21 * scale)}px; color: inherit; caret-color: {t['accent']};
  font-weight: {800 if t['style'] == 'brutal' else 500 if display else 400}; {mono_title} {display}
}}
.hello-search > text > placeholder {{ color: {rgba(chrome if not t['search_bar'] else ink, 0.45)}; }}
.hello-search > text > selection {{ background-color: {rgba(t['accent'], 0.4)}; }}
.hello-back {{ background: {rgba(chrome, 0.1)}; border-radius: 999px; padding: 4px 10px; font-size: 12px;
  color: inherit; border: none; box-shadow: none; min-height: 0; }}
.hello-back:hover {{ background: {rgba(chrome, 0.18)}; }}
.hello-appsbutton {{ background: none; border: none; box-shadow: none; color: {rgba(chrome, 0.6)};
  min-width: 30px; min-height: 30px; padding: 0; border-radius: 999px; }}
.hello-divider {{ background: {t['divider']}; min-height: 1px; min-width: 1px; }}
.hello-content {{ color: {ink}; }}
{pane}
.hello-list {{ background: transparent; color: {ink}; padding: 8px 8px; }}
.hello-list row {{ background: transparent; padding: 0; border-radius: {t['row_radius']}px; outline: none;
  transition: {select_transition}; }}
.hello-list row.hello-row {{ min-height: {row_h}px; margin-bottom: 2px; }}
{cards}
.hello-list row.hello-row:hover {{ background-color: {rgba(ink, 0.05)}; }}
.hello-list row.selected, .hello-list row.selected:hover, .hello-cell.selected, .hello-glyph.selected {{
  background-color: {t['selection']}; {sel_ink} {sel_extra}
}}
.hello-list row.selected .hello-subtitle, .hello-list row.selected .hello-accessory {{ {sel_ink} }}
.hello-glide {{ background-color: {t['selection']}; border-radius: {t['row_radius']}px; {sel_extra} }}
.hello-glide.cell {{ border-radius: {t['cell_radius']}px; }}
.hello-glided row.selected, .hello-glided row.selected:hover, .hello-glided .hello-cell.selected,
.hello-glided .hello-cell.selected:hover {{ background-color: transparent; box-shadow: none; border-color: transparent; }}
.hello-list row.hello-section {{ padding: 10px 12px 2px 12px; min-height: 0; }}
.hello-list row.hello-section.first {{ padding-top: 2px; }}
.hello-section-label {{ {header} color: {faint}; }}
.hello-title {{ font-size: {13.5 * scale:.1f}px; font-weight: {t['title_weight']}; {title_font} }}
.hello-subtitle {{ font-size: {11.5 * scale:.1f}px; color: {soft}; }}
.hello-accessory {{ font-size: 11px; color: {soft if t['style'] in ('brutal', 'atelier') or t.get('strong_meta') else faint};
  {'font-weight: 500;' if t.get('strong_meta') else ''} }}
.hello-check {{ color: {t['accent']}; }}
.hello-tile {{ border-radius: 7px; background: {rgba(ink, 0.08)}; }}
.hello-footer {{ min-height: 40px; padding: 0 16px; font-size: 12px; color: {chrome}; }}
.hello-hint {{ color: {rgba(chrome, 0.6)}; }}
.hello-hint.primary {{ color: {chrome}; }}
.hello-toast {{ color: {t['toast']}; font-weight: 600; }}
.hello-key {{ background: {t['key_fill']}; color: {t['key_ink']}; {key_border} {key_shadow}
  border-radius: 5px; padding: 1px 6px; font-size: 11px; font-weight: 600; min-width: 12px; {key_font} }}
{primary_key}
{icon_filter}
{icon_rest}
{tile}
.hello-empty {{ color: {faint}; font-size: 13px; }}
.hello-cell {{ border-radius: {t['cell_radius']}px; padding: 10px 4px 8px 4px; transition: {select_transition}; }}
.hello-cell:hover {{ background-color: {rgba(ink, 0.05)}; }}
.hello-cell-label {{ font-size: 12px; }}
.hello-glyph {{ border-radius: {t['cell_radius'] // 2}px; font-size: 26px; min-height: 52px; min-width: 52px; }}
.hello-glyph:hover {{ background-color: {rgba(ink, 0.06)}; }}
gridview.hello-glyphs, gridview.hello-glyphs > child {{ background: transparent; color: {ink}; padding: 0; }}
gridview.hello-glyphs > child:selected {{ background-color: {t['selection']}; border-radius: {t['cell_radius'] // 2}px; {sel_ink}
  {t.get('selection_extra', '')} }}
.hello-filter button {{ font-size: 11px; padding: 2px 9px; min-height: 22px; min-width: 0; border-radius: 999px; border: none;
  background: {rgba(chrome, 0.08)}; color: {rgba(chrome, 0.75)}; box-shadow: none; }}
.hello-filter button:checked {{ background: {t['accent']}; color: {'#111' if t['style'] != 'glass' else '#fff'}; }}
.hello-preview {{ padding: 16px; }}
.hello-preview-title {{ font-size: 15px; font-weight: 600; {title_font} }}
.hello-preview-text {{ font-size: 12px; font-family: monospace; color: {ink}; }}
.hello-meta-key {{ color: {faint}; font-size: 11.5px; }}
.hello-meta-value {{ font-size: 11.5px; }}
.hello-output, .hello-output text {{ background: transparent; color: {ink}; font-family: monospace; font-size: 12px; }}
.hello-agent {{ font-size: 13.5px; }}
.hello-agent-stage {{ color: {soft}; font-size: 12px; }}
.hello-dots {{ padding: 4px; }}
.hello-step {{ font-size: 12px; color: {soft}; }}
.hello-step.current {{ color: {ink}; }}
.hello-step.command {{ font-family: monospace; font-size: 11.5px; }}
.hello-step-mark {{ font-size: 9px; font-weight: 700; color: {faint}; }}
.hello-step-mark.current {{ color: {t['accent']}; }}
.hello-request {{ font-size: 14.5px; font-weight: 600; }}
.hello-past {{ opacity: 0.8; }}
.hello-past-level {{ font-size: 10.5px; font-weight: 600; }}
.hello-rule {{ background: {rgba(ink, 0.12)}; min-height: 1px; margin: 4px 0; }}
.hello-attachment {{ border-radius: 7px; border: 1px solid {rgba(ink if t['search_bar'] else chrome, 0.15)}; }}
.hello-detach {{ min-width: 16px; min-height: 16px; padding: 0; border-radius: 99px; background: rgba(0,0,0,0.65);
  color: white; border: none; box-shadow: none; -gtk-icon-size: 10px; }}
.hello-panel.drop {{ box-shadow: inset 0 0 0 2px {t['accent']}; }}
.hello-drop-label {{ background: {rgba('#000000', 0.6)}; color: white; border-radius: 99px; padding: 6px 12px;
  font-size: 12px; font-weight: 600; margin-bottom: 52px; }}
.hello-dot {{ min-width: 7px; min-height: 7px; border-radius: 99px; background: {rgba(ink, 0.25)}; }}
.hello-dot.active {{ background: {ink}; }}
scrollbar {{ background: transparent; border: none; }}
scrollbar slider {{ background: {rgba(ink, 0.25)}; min-width: 4px; }}
{markdown_css(t)}"""


def markdown_css(t):
    """Réponses de l'IA (ui_markdown.py) : titres, listes, citations, code, tableaux, formules, liens."""
    ink = t["ink"]
    soft, faint = rgba(ink, 0.62), rgba(ink, 0.42)
    # Liens en cyan comme sur Mac ; la Nuit n'a qu'une couleur.
    link = t.get("monochrome") or ("#5AC8FA" if t["dark"] else "#0A6FA8")
    return f"""
.hello-md {{ font-size: 13.5px; }}
.hello-md-h1 {{ font-size: 17px; font-weight: 700; }}
.hello-md-h2 {{ font-size: 15px; font-weight: 700; }}
.hello-md-h3 {{ font-size: 14px; font-weight: 700; }}
.hello-md-marker {{ color: {soft}; font-feature-settings: "tnum"; }}
.hello-md-done {{ color: {soft}; }}
.hello-md-quote {{ border-left: 2px solid {rgba(ink, 0.28)}; padding-left: 10px; }}
.hello-md-quotetext {{ color: {soft}; }}
.hello-md-code {{ background: {rgba(ink, 0.06)}; border-radius: 8px; padding: 10px; }}
.hello-md-codetext {{ font-family: monospace; font-size: 12px; }}
.hello-md-lang {{ font-family: monospace; font-size: 9.5px; font-weight: 500; color: {faint}; margin: 6px 8px; }}
.hello-md-table {{ border: 1px solid {rgba(ink, 0.14)}; border-radius: 8px; }}
.hello-md-cell {{ padding: 6px 10px; border-top: 1px solid {rgba(ink, 0.06)}; font-size: 12.5px; }}
.hello-md-cell.head {{ background: {rgba(ink, 0.05)}; border-top: none; }}
.hello-md-cell.first {{ border-top: 1px solid {rgba(ink, 0.2)}; }}
.hello-md-rule {{ min-height: 1px; background: {rgba(ink, 0.12)}; margin: 4px 0; }}
.hello-md-formula {{ margin: 4px 0; }}
.hello-md link, .hello-md link:visited, .hello-md link:hover {{ color: {link}; }}
.hello-md selection, .hello-md label > selection {{ background-color: {rgba(t['accent'], 0.35)}; }}
"""


# Cascade des lignes à l'ouverture : départ et écart entre deux lignes (ms), par style (RevealStyle.row de la
# version Mac). Glyphe a la sienne (décodage).
ARRIVALS = {"kde": (40, 18), "glass": (40, 18), "atelier": (80, 35), "phosphor": (200, 45), "paper": (100, 30),
            "brutal": (140, 30)}
ARRIVAL_ROWS = 14


def _amplitude():
    return {"subtle": 0.45, "normal": 1.0, "expressive": 1.6}.get(settings.motionIntensity, 1.0)


def reveal_css():
    """Signature de mouvement de chaque style (Motion.swift), en animations CSS GTK aux ressorts de la version Mac :
    l'ouverture du panneau, l'arrivée des lignes en cascade (classes arrive-N posées par la fenêtre) et du pied de
    page, le changement d'écran (enter-forward / enter-back) et l'effacement quand on lance une app (closing).
    Les ressorts sont échantillonnés en images clés (motion.keyframes) ; les dessins (reflet, onde, tube, encre…)
    sont dans mark.py.

    Pas d'échelle animée à l'ouverture (panneau et lignes), contrairement au Mac : à chaque nouvelle échelle, GSK
    re-rastérise tous les glyphes du panneau, soit 5 à 12 ms de plus par image (le Verre passait de 5,7 à 17,8 ms en
    GL). Les ouvertures tombaient à 40-80 images par seconde sur un écran à 240 Hz ; elles bougent donc en
    translation, rotation et fondu, que le GPU compose sans rien redessiner."""
    t = tokens()
    style = t["style"]
    speed = motion_speed()
    k = _amplitude()

    def ms(v):
        return f"{int(v / speed)}ms"

    # Chaque animation : (bloc @keyframes, durée CSS déjà mise à la vitesse réglée, courbe).
    def eased(name, frames, duration, easing):
        return f"@keyframes {name} {{ {frames} }}", ms(duration), easing

    def sprung(name, spring, frame, at_least=0.0):
        block, duration = keyframes(name, spring, frame, at_least=at_least / speed)
        return block, f"{duration}ms", "linear"

    def fade(p):
        return f"opacity: {clamp01(p):.3f};"

    # Ouverture du panneau (RevealStyle.open et PanelReveal).
    if style == "glass":
        # Le verre descend en se posant avec le ressort ; il doit être visible tout de suite, d'où un fondu à part,
        # bien plus court.
        opening = sprung("hello-reveal", Spring(0.46, 0.7), lambda p, s: (
            f"opacity: {clamp01(s * speed / 0.1):.3f}; transform: translateY({-14 * k * (1 - p):.2f}px); "
            f"filter: blur({max(0.0, 8 * k * (1 - p)):.2f}px);"))
        origin = "50% 7%"
    elif style == "atelier":
        # Le déploiement d'Atelier est un ressort de hauteur (ui.py) ; ici la descente et le fondu.
        opening = sprung("hello-reveal", Spring(0.44, 0.72), lambda p, s: (
            f"{fade(p)} transform: translateY({-10 * k * (1 - p):.2f}px);"))
        origin = "50% 0"
    elif style == "phosphor":
        # Le Phosphore s'allume sous le dessin du tube (mark.py) : le panneau est là tout de suite.
        opening = eased("hello-reveal", "from { opacity: 0; } to { opacity: 1; }", 70, "linear")
        origin = "50% 50%"
    elif style == "paper":
        opening = sprung("hello-reveal", Spring(0.48, 0.84), lambda p, s: (
            f"{fade(p)} transform: perspective(900px) rotateX({-24 * k * (1 - p):.2f}deg) "
            f"translateY({-6 * k * (1 - p):.2f}px);"))
        origin = "50% 0"
    elif style == "glyph":
        opening = sprung("hello-reveal", Spring(0.46, 0.8), lambda p, s: (
            f"{fade(p)} transform: translateY({8 * k * (1 - p):.2f}px);"))
        origin = "50% 0"
    elif style == "brutal":
        # Il tombe de haut, s'écrase sur son ombre pleine (qui rentre presque toute au rebond), puis se pose.
        o, c = t["hard_shadow"] or 8, t.get("hard_shadow_color", "#000")

        def slam(p, s):
            shadow = o * (1 + 1.6 * (1 - p)) if p < 1 else o * max(0.2, 1 - 4 * (p - 1))
            return (f"{fade(p)} transform: translateY({-48 * k * (1 - p):.2f}px) "
                    f"rotate({-1.5 * k * (1 - p):.3f}deg); box-shadow: {shadow:.1f}px {shadow:.1f}px 0 0 {c};")
        opening = sprung("hello-reveal", Spring(0.36, 0.5), slam)
        origin = "50% 50%"
    else:   # KDE : comme un menu de Plasma, vif et sans rebond.
        opening = sprung("hello-reveal", Spring(0.38, 0.86), lambda p, s: (
            f"{fade(p)} transform: translateY({-10 * k * (1 - p):.2f}px);"))
        origin = "50% 0"
    block, length, easing = opening
    out = [twin(block, "hello-reveal"), f".hello-panel.reveal {{ animation: hello-reveal {length} {easing} both; "
                                        f"transform-origin: {origin}; }}",
           ".hello-panel.reveal.again { animation-name: hello-reveal-b; }"]
    # Réouverture rapide (le Verre) : un petit ressort vif.
    block, length, _ = sprung("hello-reveal-light", snappy(0.14), lambda p, s: (
        f"{fade(p * 1.4)} transform: translateY({-3 * (1 - p):.2f}px);"))
    out += [twin(block, "hello-reveal-light"), f".hello-panel.reveal-light {{ animation: hello-reveal-light {length} linear both; }}",
            ".hello-panel.reveal-light.again { animation-name: hello-reveal-light-b; }"]

    # Arrivée des lignes (RevealStyle.row et RevealItem).
    rows = None
    if style == "kde":
        rows = sprung("hello-arrive", Spring(0.3, 0.88), lambda p, s: (
            f"{fade(p)} transform: translateY({-4 * k * (1 - p):.2f}px);"))
    elif style == "glass":
        rows = sprung("hello-arrive", Spring(0.28, 0.8), lambda p, s: (
            f"{fade(p)} transform: translateY({10 * k * (1 - p):.2f}px);"))
    elif style == "atelier":
        rows = sprung("hello-arrive", Spring(0.5, 0.72), lambda p, s: (
            f"{fade(p)} transform: translateY({18 * k * (1 - p):.2f}px);"))
    elif style == "phosphor":
        # Une ligne après l'autre, sans fondu : comme un terminal qui affiche sa sortie.
        rows = eased("hello-arrive", "0% { opacity: 0; } 99% { opacity: 0; } 100% { opacity: 1; }", 30, "linear")
    elif style == "paper":
        rows = eased("hello-arrive", f"from {{ opacity: 0; transform: translateX({-10 * k:.1f}px); }} "
                                     "to { opacity: 1; transform: translateX(0); }", 340, "ease-out")
    elif style == "brutal":
        rows = sprung("hello-arrive", Spring(0.32, 0.5), lambda p, s: (
            f"{fade(p)} transform: translateY({16 * k * (1 - p):.2f}px);"))
    if rows:
        block, length, easing = rows
        first, step = ARRIVALS[style]
        out += [twin(block, "hello-arrive"), f".hello-row.arrive, .hello-section.arrive, .hello-footer.arrive "
                                             f"{{ animation: hello-arrive {length} {easing} both; transform-origin: 50% 0; }}",
                ".hello-footer.arrive.again { animation-name: hello-arrive-b; }"]
        out += [f".arrive-{i} {{ animation-delay: {ms(first + i * step)}; }}" for i in range(ARRIVAL_ROWS)]
        out.append(f".hello-footer.arrive {{ animation-delay: {ms(first + 6 * step)}; }}")

    # Changement d'écran (RevealStyle.navigation et modeTransition) : le nouvel écran arrive du côté où l'on va.
    for side, sign in (("forward", 1), ("back", -1)):
        name = f"hello-enter-{side}"
        if style == "glass":
            entry = sprung(name, snappy(0.24), lambda p, s, d=sign: (
                f"{fade(p)} transform: translateX({36 * k * d * (1 - p):.2f}px);"))
        elif style == "atelier":
            entry = sprung(name, Spring(0.38, 0.86), lambda p, s, d=sign: (
                f"{fade(p)} transform: translateX({30 * k * d * (1 - p):.2f}px) scale({1 - 0.02 * (1 - p):.4f});"))
        elif style == "glyph":
            entry = sprung(name, Spring(0.36, 0.82), lambda p, s, d=sign: (
                f"{fade(p)} transform: translateX({22 * k * d * (1 - p):.2f}px);"))
        elif style == "phosphor":
            entry = eased(name, "from { opacity: 0; } to { opacity: 1; }", 60, "linear")
        elif style == "paper":
            entry = eased(name, f"from {{ opacity: 0; transform: translateY({8 * k:.1f}px); }} "
                                "to { opacity: 1; transform: translateY(0); }", 260, "ease-in-out")
        elif style == "brutal":
            entry = sprung(name, Spring(0.3, 0.62), lambda p, s, d=sign: (
                f"{fade(p)} transform: translateX({60 * k * d * (1 - p):.2f}px);"))
        else:
            entry = sprung(name, Spring(0.3, 0.9), lambda p, s, d=sign: (
                f"{fade(p)} transform: translateX({24 * k * d * (1 - p):.2f}px);"))
        block, length, easing = entry
        out += [twin(block, name), f".hello-screen.enter-{side} {{ animation: {name} {length} {easing} both; }}",
                f".hello-screen.enter-{side}.again {{ animation-name: {name}-b; }}"]

    # Effacement quand on lance une app (RevealStyle.close) ; le panneau s'efface en même temps (0,22 s, easeIn).
    fade_out = 0.22
    if style == "glass" or style == "kde":
        closing = eased("hello-close", "from { transform: scale(1); } to { transform: scale(0.985); }", 220, "ease-out")
    elif style == "atelier":
        closing = sprung("hello-close", Spring(0.24, 0.6), lambda p, s: f"transform: scale({1 + 0.02 * k * p:.4f});",
                         at_least=fade_out)
    elif style == "glyph":
        closing = sprung("hello-close", Spring(0.2, 0.9), lambda p, s: f"transform: scale({1 - 0.025 * k * p:.4f});",
                         at_least=fade_out)
    elif style == "phosphor":
        # L'écran s'écrase en trait lumineux.
        closing = eased("hello-close", "from { transform: scale(1, 1); filter: brightness(1); } "
                                       "to { transform: scale(0.6, 0.006); filter: brightness(1.7); }", 160, "ease-in")
    elif style == "paper":
        closing = eased("hello-close", "from { transform: perspective(900px) rotateX(0deg) translateY(0); } "
                                       f"to {{ transform: perspective(900px) rotateX({10 * k:.1f}deg) "
                                       f"translateY({-8 * k:.1f}px); }}", 200, "ease-in")
    else:   # Néo-brutal : il s'enfonce sur son ombre pleine, comme un bouton qu'on presse.
        o, c = t["hard_shadow"] or 8, t.get("hard_shadow_color", "#000")
        closing = sprung("hello-close", Spring(0.16, 0.7), lambda p, s: (
            f"transform: translate({6 * p:.2f}px, {6 * p:.2f}px); box-shadow: {o - 6 * p:.1f}px {o - 6 * p:.1f}px 0 0 {c};"),
            at_least=fade_out)
    block, length, easing = closing
    out += [block, f".hello-panel.closing {{ animation: hello-close {length} {easing} both; transform-origin: 50% 50%; }}",
            "@keyframes hello-fade-out { from { opacity: 1; } to { opacity: 0; } }",
            f".hello-fading {{ animation: hello-fade-out {ms(fade_out * 1000)} ease-in both; }}"]
    return "\n".join(out) + "\n"


def twin(block, name):
    """Les images clés `name`, et leur jumelle `name-b` : passer de l'une à l'autre (classe again) relance une
    animation CSS dans la même image, sans attendre un tour de boucle (qui laisserait passer une image figée)."""
    return block + "\n" + block.replace(f"@keyframes {name} ", f"@keyframes {name}-b ", 1)


def replay(widget, name, others=()):
    """Pose la classe d'animation `name` sur `widget` et la (re)lance tout de suite (voir twin)."""
    for other in others:
        widget.remove_css_class(other)
    if widget.has_css_class(name):
        (widget.remove_css_class if widget.has_css_class("again") else widget.add_css_class)("again")
    else:
        widget.add_css_class(name)


def close_duration():
    """Durée de l'effacement au lancement (ms) : le panneau est masqué ensuite."""
    return round(220 / motion_speed())
