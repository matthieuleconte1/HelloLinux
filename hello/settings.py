"""Réglages et emplacements des données (équivalent de Settings.swift / UserDefaults).

Réglages : ~/.config/hello/settings.json
Données  : ~/.local/share/hello/ (statistiques, presse-papiers, couleurs, historique) en 0700 / 0600.
"""
import json
import os
import threading

from gi.repository import GLib

APP_ID = "io.github.matthieuleconte1.Hello"

CONFIG_DIR = os.path.join(GLib.get_user_config_dir(), "hello")
DATA_DIR = os.path.join(GLib.get_user_data_dir(), "hello")
CLIP_DIR = os.path.join(DATA_DIR, "clipboard")
HOME = os.path.expanduser("~")

for _d in (CONFIG_DIR, DATA_DIR, CLIP_DIR):
    os.makedirs(_d, mode=0o700, exist_ok=True)


def load_json(path, fallback):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return fallback


def save_json(path, value, private=False):
    """Écriture atomique (fichier temporaire puis renommage)."""
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=1)
        if private:
            os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except OSError:
        pass


class Debounced:
    """Sauvegarde regroupée : au plus une écriture toutes les `delay` secondes."""

    def __init__(self, delay, write):
        self.delay = delay
        self.write = write
        self.scheduled = False

    def __call__(self):
        if self.scheduled:
            return
        self.scheduled = True

        def run():
            self.scheduled = False
            threading.Thread(target=self.write, daemon=True).start()
            return False

        GLib.timeout_add(int(self.delay * 1000), run)


EXAMPLE_COMMANDS = [
    {"id": "ex-update", "name": "Mettre à jour le système", "keyword": "maj",
     "command": "sudo pacman -Syu", "mode": "terminal"},
    {"id": "ex-gh", "name": "Ouvrir un dépôt GitHub", "keyword": "gh",
     "command": "xdg-open https://github.com/{}", "mode": "silent"},
    {"id": "ex-du", "name": "Taille des dossiers ici", "keyword": "du",
     "command": "du -sh ~/{}/* | sort -h", "mode": "app"},
]

DEFAULTS = {
    # Général
    "hotkey": "ALT+space",
    "onboarded": False,
    "showTrayIcon": True,
    # Apparence
    "panelSize": "standard",
    "panelPosition": "upper",
    "panelStyle": "kde",
    "motionIntensity": "normal",
    "animationSpeed": 1.0,
    "launchEffects": True,
    "asciiDecode": True,
    "rowDensity": "standard",
    "textScale": 1.0,
    "showAccessories": True,
    "showHints": True,
    "showSubtitles": True,
    "focusMode": False,
    "atelierPalette": "lime",
    "atelierSwap": False,
    "atelierAppearance": "auto",
    "atelierColoredSelection": False,
    "glyphAccent": "orange",
    "glyphAppearance": "auto",
    "glyphAutoNight": False,
    "glyphNightStart": 22,
    "glyphNightEnd": 7,
    "glyphNightLevel": 0.85,
    "phosphorColor": "green",
    "paperTone": "cream",
    "brutalColor": "pink",
    "glassTintHex": "#000000",
    "glassTintAmount": 0.0,
    "glassBorder": False,
    "highlightHex": "#FFFFFF",
    "highlightAmount": 0.12,
    "cornerRadius": 26.0,
    "animations": True,
    "haloSweep": True,
    # Recherche
    "frecencyRanking": True,
    "learnQueries": True,
    "showRecents": True,
    "shellCommands": True,
    "terminal": "",
    "editor": "",
    "shellHistory": True,
    "useZoxide": True,
    "shellInteractive": False,
    "customCommands": EXAMPLE_COMMANDS,
    # Agent : fournisseur de chaque niveau (hermes, claude pour Claude Code, codex), compte Hermes, modèle, raisonnement
    "agentEnabled": True,
    "agentRouterEngine": "hermes",
    "agentResearchEngine": "hermes",
    "agentDefaultEngine": "hermes",
    "agentRouterModel": "gpt-6-luna",
    "agentRouterProvider": "openai-codex",
    "agentRouterReasoning": "low",
    "agentDefaultProvider": "",
    "agentDefaultModel": "",
    "agentDefaultReasoning": "",
    "agentStrategy": "auto",
    "agentWorkdir": "~",
    "agentResearchProvider": "anthropic",
    "agentResearchModel": "claude-sonnet-5-5",
    "agentResearchReasoning": "medium",
    "agentHistory": True,
    # Mises à jour (releases GitHub)
    "autoUpdateCheck": True,
    "autoUpdateInstall": True,
    "updatePrereleases": True,
    # Presse-papiers
    "clipboardEnabled": True,
    "clipboardLimit": 300,
    "clipboardRetentionDays": 0,
    "clipboardImages": True,
    "pasteOnEnter": True,
}


class Settings:
    """Réglages persistés ; `settings.x` lit, `settings.x = v` écrit (sauvegarde regroupée)."""

    _path = os.path.join(CONFIG_DIR, "settings.json")

    def __init__(self):
        object.__setattr__(self, "_values", dict(DEFAULTS))
        self._values.update(load_json(self._path, {}))
        object.__setattr__(self, "_listeners", [])
        object.__setattr__(self, "_save", Debounced(0.5, lambda: save_json(self._path, self._changed())))

    def __getattr__(self, name):
        try:
            return self._values[name]
        except KeyError:
            raise AttributeError(name) from None

    def __setattr__(self, name, value):
        if self._values.get(name) == value:
            return
        self._values[name] = value
        self._save()
        for listener in list(self._listeners):
            listener(name)

    def _changed(self):
        """Seulement ce qui diffère des valeurs par défaut : une nouvelle valeur par défaut profite à tous."""
        return {k: v for k, v in self._values.items() if DEFAULTS.get(k, object()) != v}

    def connect(self, listener):
        self._listeners.append(listener)

    def reset_appearance(self):
        for key in ("panelStyle", "glassTintHex", "glassTintAmount", "glassBorder", "highlightHex",
                    "highlightAmount", "cornerRadius", "rowDensity", "textScale", "showSubtitles",
                    "showAccessories", "showHints", "focusMode", "atelierPalette", "atelierSwap",
                    "atelierAppearance", "atelierColoredSelection", "glyphAccent", "glyphAppearance", "glyphAutoNight",
                    "glyphNightStart", "glyphNightEnd", "glyphNightLevel", "phosphorColor", "paperTone", "brutalColor"):
            setattr(self, key, DEFAULTS[key])


settings = Settings()


def motion_enabled():
    """Animations activées dans Hello et dans le bureau (« Réduire les animations » de Plasma ou de GNOME)."""
    if not settings.animations:
        return False
    try:
        from gi.repository import Gtk
        gtk = Gtk.Settings.get_default()
        return gtk is None or bool(gtk.get_property("gtk-enable-animations"))
    except (ImportError, TypeError, ValueError):
        return True


def motion_speed():
    """Vitesse réglée, bornée à 0,5–2."""
    try:
        value = float(settings.animationSpeed)
    except (TypeError, ValueError):
        return 1.0
    return min(max(value, 0.5), 2.0) if value == value else 1.0


def decodes():
    """Atelier Glyphe : textes et icônes qui se décodent en ASCII en apparaissant."""
    return motion_enabled() and settings.asciiDecode and settings.panelStyle == "glyph"


def glyph_appearance():
    """Apparence de Glyphe à cet instant : la Nuit automatique l'emporte pendant sa plage horaire."""
    import datetime
    s = settings
    start, end = int(s.glyphNightStart), int(s.glyphNightEnd)
    if not s.glyphAutoNight or start == end:
        return s.glyphAppearance
    hour = datetime.datetime.now().hour
    # Plage qui passe minuit (22 h → 7 h) ou non (1 h → 5 h).
    night = (hour >= start or hour < end) if start > end else (start <= hour < end)
    return "night" if night else s.glyphAppearance

PANEL_SIZES = {
    "compact": ("Compact", 680, 420, 10),
    "standard": ("Standard", 760, 480, 11),
    "large": ("Grand", 880, 560, 13),
}

ROW_DENSITY = {
    "compact": ("Compacte", 36, 22),
    "standard": ("Standard", 44, 26),
    "comfortable": ("Aérée", 52, 30),
}


def panel_size():
    _, w, h, _ = PANEL_SIZES.get(settings.panelSize, PANEL_SIZES["standard"])
    return w, h


def grid_columns():
    return PANEL_SIZES.get(settings.panelSize, PANEL_SIZES["standard"])[3]


def row_height():
    return ROW_DENSITY.get(settings.rowDensity, ROW_DENSITY["standard"])[1]


def icon_size():
    return ROW_DENSITY.get(settings.rowDensity, ROW_DENSITY["standard"])[2]
