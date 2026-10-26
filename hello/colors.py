"""Pipette et historique des couleurs (Colors.swift), et réglage du panneau Plasma
(l'équivalent Linux de « Masquer automatiquement la barre des menus »)."""
import os
import time
import uuid

from gi.repository import Gio, GLib

from . import portal
from .settings import DATA_DIR, load_json, save_json


class StoredColor(dict):
    """id, r, g, b (0-1), date."""

    @property
    def bytes(self):
        return tuple(round(self[k] * 255) for k in ("r", "g", "b"))

    @property
    def hex(self):
        return "#%02X%02X%02X" % self.bytes

    @property
    def rgb(self):
        return "rgb(%d, %d, %d)" % self.bytes

    @property
    def hsl(self):
        r, g, b = self["r"], self["g"], self["b"]
        mx, mn = max(r, g, b), min(r, g, b)
        lum, d = (mx + mn) / 2, mx - mn
        h = s = 0.0
        if d > 0:
            s = d / (2 - mx - mn) if lum > 0.5 else d / (mx + mn)
            if mx == r:
                h = (g - b) / d + (6 if g < b else 0)
            elif mx == g:
                h = (b - r) / d + 2
            else:
                h = (r - g) / d + 4
            h *= 60
        return "hsl(%d, %d%%, %d%%)" % (round(h), round(s * 100), round(lum * 100))

    @property
    def formats(self):
        r, g, b = self["r"], self["g"], self["b"]
        return [
            ("HEX", self.hex),
            ("RGB", self.rgb),
            ("HSL", self.hsl),
            ("GdkRGBA", "Gdk.RGBA(red=%.3f, green=%.3f, blue=%.3f)" % (r, g, b)),
            ("Qt", "QColor(%d, %d, %d)" % self.bytes),
            ("Tailwind", f"[{self.hex}]"),
        ]


class ColorStore:
    _path = os.path.join(DATA_DIR, "colors.json")

    def __init__(self):
        self.items = [StoredColor(c) for c in load_json(self._path, [])]

    def add(self, r, g, b):
        stored = StoredColor(id=str(uuid.uuid4()), r=r, g=g, b=b, date=time.time())
        self.items = [stored] + [c for c in self.items if c.hex != stored.hex][:39]
        self._save()
        return stored

    def remove(self, color):
        self.items = [c for c in self.items if c["id"] != color["id"]]
        self._save()

    def _save(self):
        save_json(self._path, [dict(c) for c in self.items])


def pick_color(done):
    """Pipette du système (portail Screenshot.PickColor) : aucune capture d'écran n'est gardée.
    `done((r, g, b))`, ou `done(None)` si annulé / indisponible."""
    def response(code, results):
        color = results.get("color") if code == 0 else None
        done(tuple(color) if color else None)

    portal.request("org.freedesktop.portal.Screenshot", "PickColor",
                   lambda token: GLib.Variant("(sa{sv})", ("", {"handle_token": GLib.Variant("s", token)})),
                   response)


# MARK: - Panneau Plasma

PANEL_MODES = [
    # (valeur de plasmashell, titre, détail, icône)
    ("none", "Toujours visible", "Le panneau reste affiché, les fenêtres s'arrêtent à son bord",
     "hello-panel-symbolic"),
    ("autohide", "Masquage automatique", "Masqué, il apparaît quand la souris touche le bord de l'écran",
     "hello-panel-autohide-symbolic"),
    ("dodgewindows", "Esquiver les fenêtres", "Masqué seulement quand une fenêtre le recouvre",
     "hello-panel-dodge-symbolic"),
    ("windowsgobelow", "Fenêtres par-dessus", "Toujours visible, les fenêtres peuvent passer dessous",
     "hello-panel-below-symbolic"),
]


def _plasma_script(script):
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        out = bus.call_sync("org.kde.plasmashell", "/PlasmaShell", "org.kde.PlasmaShell", "evaluateScript",
                            GLib.Variant("(s)", (script,)), GLib.VariantType("(s)"), Gio.DBusCallFlags.NONE, 3000)
        return out.unpack()[0]
    except GLib.Error:
        return None


def plasma_available():
    return "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "")


def panel_mode():
    out = _plasma_script("print(panels().length ? panels()[0].hiding : '')")
    return (out or "").strip() or None


def apply_panel_mode(mode):
    """Applique le mode à tous les panneaux Plasma (comme Configurer le panneau › Visibilité)."""
    return _plasma_script(f"panels().forEach(function (p) {{ p.hiding = '{mode}'; }})") is not None
