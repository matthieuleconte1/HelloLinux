"""Icône dans la zone de notification (StatusMenu.swift), via les protocoles D-Bus StatusNotifierItem
et com.canonical.dbusmenu : Plasma, et GNOME avec l'extension AppIndicator. Aucune dépendance.

Clic : ouvre ou ferme le panneau. Clic droit : le menu (reconstruit à chaque ouverture, comme sur Mac)."""
import os

import cairo
from gi.repository import Gio, GLib

from . import colors as colormod
from .mark import draw_mark

ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/MenuBar"

ITEM_XML = """<node><interface name="org.kde.StatusNotifierItem">
  <property name="Category" type="s" access="read"/>
  <property name="Id" type="s" access="read"/>
  <property name="Title" type="s" access="read"/>
  <property name="Status" type="s" access="read"/>
  <property name="WindowId" type="i" access="read"/>
  <property name="IconName" type="s" access="read"/>
  <property name="IconPixmap" type="a(iiay)" access="read"/>
  <property name="OverlayIconName" type="s" access="read"/>
  <property name="AttentionIconName" type="s" access="read"/>
  <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
  <property name="ItemIsMenu" type="b" access="read"/>
  <property name="Menu" type="o" access="read"/>
  <method name="ContextMenu"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
  <method name="Activate"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
  <method name="SecondaryActivate"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
  <method name="Scroll"><arg name="delta" type="i" direction="in"/><arg name="orientation" type="s" direction="in"/></method>
  <signal name="NewIcon"/><signal name="NewToolTip"/><signal name="NewTitle"/>
  <signal name="NewStatus"><arg name="status" type="s"/></signal>
</interface></node>"""

MENU_XML = """<node><interface name="com.canonical.dbusmenu">
  <property name="Version" type="u" access="read"/>
  <property name="TextDirection" type="s" access="read"/>
  <property name="Status" type="s" access="read"/>
  <property name="IconThemePath" type="as" access="read"/>
  <method name="GetLayout">
    <arg name="parentId" type="i" direction="in"/><arg name="recursionDepth" type="i" direction="in"/>
    <arg name="propertyNames" type="as" direction="in"/>
    <arg name="revision" type="u" direction="out"/><arg name="layout" type="(ia{sv}av)" direction="out"/>
  </method>
  <method name="GetGroupProperties">
    <arg name="ids" type="ai" direction="in"/><arg name="propertyNames" type="as" direction="in"/>
    <arg name="properties" type="a(ia{sv})" direction="out"/>
  </method>
  <method name="GetProperty">
    <arg name="id" type="i" direction="in"/><arg name="name" type="s" direction="in"/>
    <arg name="value" type="v" direction="out"/>
  </method>
  <method name="Event">
    <arg name="id" type="i" direction="in"/><arg name="eventId" type="s" direction="in"/>
    <arg name="data" type="v" direction="in"/><arg name="timestamp" type="u" direction="in"/>
  </method>
  <method name="EventGroup">
    <arg name="events" type="a(isvu)" direction="in"/><arg name="idErrors" type="ai" direction="out"/>
  </method>
  <method name="AboutToShow">
    <arg name="id" type="i" direction="in"/><arg name="needUpdate" type="b" direction="out"/>
  </method>
  <method name="AboutToShowGroup">
    <arg name="ids" type="ai" direction="in"/>
    <arg name="updatesNeeded" type="ai" direction="out"/><arg name="idErrors" type="ai" direction="out"/>
  </method>
  <signal name="ItemsPropertiesUpdated">
    <arg name="updatedProps" type="a(ia{sv})"/><arg name="removedProps" type="a(ias)"/>
  </signal>
  <signal name="LayoutUpdated"><arg name="revision" type="u"/><arg name="parent" type="i"/></signal>
</interface></node>"""


def icon_pixmaps(ring, dot):
    """Le logo (anneau ouvert et point) aux tailles usuelles, en ARGB32 « ordre réseau » (spécification SNI)."""
    out = []
    for size in (16, 22, 24, 32, 48, 64):
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
        ctx = cairo.Context(surface)
        # Un peu de marge : le logo occupe la même place que les icônes voisines.
        draw_mark(ctx, size * 1.15, ("paper", ring, dot), ox=-size * 0.075, oy=-size * 0.075)
        surface.flush()
        data = bytes(surface.get_data())  # BGRA (petit-boutiste, prémultiplié)
        argb = bytearray(len(data))
        argb[0::4], argb[1::4], argb[2::4], argb[3::4] = data[3::4], data[2::4], data[1::4], data[0::4]
        out.append((size, size, bytes(argb)))
    return out


class TrayIcon:
    def __init__(self, controller):
        self.c = controller
        self.bus = None
        self.ids = []
        self.owner = 0
        self.revision = 1
        self.actions = {}
        self.running = False

    # MARK: Cycle de vie

    def start(self):
        if self.running:
            return
        self.running = True
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        item = Gio.DBusNodeInfo.new_for_xml(ITEM_XML).interfaces[0]
        menu = Gio.DBusNodeInfo.new_for_xml(MENU_XML).interfaces[0]
        self.ids = [
            self.bus.register_object(ITEM_PATH, item, self._item_call, self._item_property, None),
            self.bus.register_object(MENU_PATH, menu, self._menu_call, self._menu_property, None),
        ]
        name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        self.owner = Gio.bus_own_name_on_connection(self.bus, name, Gio.BusNameOwnerFlags.NONE, None, None)
        self._register(name)
        # La zone de notification redémarre (plasmashell relancé) : on se réinscrit.
        self._watch = Gio.bus_watch_name_on_connection(
            self.bus, "org.kde.StatusNotifierWatcher", Gio.BusNameWatcherFlags.NONE,
            lambda *_: self._register(name), None)

    def stop(self):
        if not self.running:
            return
        self.running = False
        for i in self.ids:
            self.bus.unregister_object(i)
        self.ids = []
        if self.owner:
            Gio.bus_unown_name(self.owner)
            self.owner = 0
        Gio.bus_unwatch_name(self._watch)

    def _register(self, name):
        self.bus.call("org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher", "org.kde.StatusNotifierWatcher",
                      "RegisterStatusNotifierItem", GLib.Variant("(s)", (name,)), None,
                      Gio.DBusCallFlags.NONE, -1, None, None)

    def refresh(self):
        """Thème ou raccourci changé : nouvelle icône, nouvelle bulle."""
        if not self.running:
            return
        for signal in ("NewIcon", "NewToolTip"):
            self.bus.emit_signal(None, ITEM_PATH, "org.kde.StatusNotifierItem", signal, None)

    # MARK: StatusNotifierItem

    def _item_property(self, _conn, _sender, _path, _iface, name):
        from .styles import kde_colors
        if name == "IconPixmap":
            k = kde_colors()
            return GLib.Variant("a(iiay)", icon_pixmaps(k["window_fg"], k["accent"]))
        values = {
            "Category": GLib.Variant("s", "ApplicationStatus"),
            "Id": GLib.Variant("s", "hello"),
            "Title": GLib.Variant("s", "Hello"),
            "Status": GLib.Variant("s", "Active"),
            "WindowId": GLib.Variant("i", 0),
            "IconName": GLib.Variant("s", ""),
            "OverlayIconName": GLib.Variant("s", ""),
            "AttentionIconName": GLib.Variant("s", ""),
            "ToolTip": GLib.Variant("(sa(iiay)ss)", ("", [], "Hello",
                                                      f"Raccourci : {self.c.hotkey.description}")),
            "ItemIsMenu": GLib.Variant("b", False),
            "Menu": GLib.Variant("o", MENU_PATH),
        }
        return values.get(name)

    def _item_call(self, _conn, _sender, _path, _iface, method, _params, invocation):
        if method in ("Activate", "SecondaryActivate"):
            GLib.idle_add(lambda: (self.c.toggle(), False)[1])
        invocation.return_value(None)

    # MARK: Menu (dbusmenu)

    def _menu_property(self, _conn, _sender, _path, _iface, name):
        return {
            "Version": GLib.Variant("u", 3),
            "TextDirection": GLib.Variant("s", "ltr"),
            "Status": GLib.Variant("s", "normal"),
            "IconThemePath": GLib.Variant("as", []),
        }.get(name)

    def _entries(self):
        """(id, propriétés, action, enfants) ; reconstruit à chaque ouverture du menu."""
        c = self.c
        m = c.model
        entries = [
            (1, {"label": "Ouvrir Hello", "icon-name": "io.github.matthieuleconte1.Hello"}, c.show, None),
        ]
        if not c.hotkey.active:
            entries.append((2, {"label": f"⚠ Raccourci : {c.hotkey.description}", "enabled": False}, None, None))
        entries += [
            (3, {"type": "separator"}, None, None),
            (4, {"label": "Emoji & Symboles", "icon-name": "face-smile-symbolic"}, lambda: c.show("emoji"), None),
            (5, {"label": "Presse-papiers", "icon-name": "edit-paste-symbolic"}, lambda: c.show("clipboard"), None),
            (6, {"label": "Pipette de couleur", "icon-name": "color-select-symbolic"}, m.pick_color, None),
        ]
        if colormod.plasma_available():
            current = c.panel_mode_cached
            children = []
            for i, (value, title, _detail, _icon) in enumerate(colormod.PANEL_MODES):
                children.append((70 + i, {"label": title, "toggle-type": "radio",
                                          "toggle-state": 1 if value == current else 0},
                                 lambda v=value, t=title: m._apply_panel(v, t), None))
            entries.append((7, {"label": "Panneau Plasma", "icon-name": "view-restore-symbolic",
                                "children-display": "submenu"}, None, children))
        login = os.path.exists(c.autostart_path)
        entries += [
            (8, {"type": "separator"}, None, None),
            (9, {"label": "Statistiques d'utilisation", "icon-name": "power-profile-performance-symbolic"},
             lambda: c.show("stats"), None),
            (10, {"label": "Réglages…", "icon-name": "preferences-system-symbolic"}, c.open_settings, None),
            (11, {"label": "Lancer à l'ouverture de session", "toggle-type": "checkmark",
                  "toggle-state": 1 if login else 0}, c.toggle_autostart, None),
            (12, {"label": "Quitter Hello", "icon-name": "application-exit-symbolic"}, c.quit, None),
        ]
        return entries

    @staticmethod
    def _props(props):
        out = {}
        for key, value in props.items():
            if isinstance(value, bool):
                out[key] = GLib.Variant("b", value)
            elif isinstance(value, int):
                out[key] = GLib.Variant("i", value)
            else:
                out[key] = GLib.Variant("s", value)
        return out

    def _layout(self):
        """Reconstruit l'arbre ; chaque nœud (id, propriétés, enfants) est aussi gardé par identifiant."""
        self.actions = {}
        self.nodes = {}

        def node(entry):
            item_id, props, action, children = entry
            if action:
                self.actions[item_id] = action
            kids = [GLib.Variant("(ia{sv}av)", node(child)) for child in (children or [])]
            self.nodes[item_id] = (item_id, self._props(props), kids)
            return self.nodes[item_id]

        root = [GLib.Variant("(ia{sv}av)", node(e)) for e in self._entries()]
        self.nodes[0] = (0, {"children-display": GLib.Variant("s", "submenu")}, root)
        return self.nodes[0]

    def _find(self, item_id):
        if not getattr(self, "nodes", None):
            self._layout()
        return self.nodes.get(item_id)

    def _menu_call(self, _conn, _sender, _path, _iface, method, params, invocation):
        args = params.unpack()
        if method == "GetLayout":
            self._layout()
            layout = self._find(args[0]) or (args[0], {}, [])
            invocation.return_value(GLib.Variant("(u(ia{sv}av))", (self.revision, layout)))
        elif method == "GetGroupProperties":
            out = []
            for item_id in args[0]:
                found = self._find(item_id)
                if found:
                    out.append((item_id, found[1]))
            invocation.return_value(GLib.Variant("(a(ia{sv}))", (out,)))
        elif method == "GetProperty":
            found = self._find(args[0])
            value = found[1].get(args[1]) if found else None
            invocation.return_value(GLib.Variant("(v)", (value or GLib.Variant("s", ""),)))
        elif method == "Event":
            self._event(args[0], args[1])
            invocation.return_value(None)
        elif method == "EventGroup":
            for item_id, event_id, _data, _ts in args[0]:
                self._event(item_id, event_id)
            invocation.return_value(GLib.Variant("(ai)", ([],)))
        elif method == "AboutToShow":
            # Menu reconstruit à chaque ouverture : l'état (panneau, démarrage, raccourci) est toujours juste.
            self.revision += 1
            self._layout()
            invocation.return_value(GLib.Variant("(b)", (args[0] == 0,)))
        elif method == "AboutToShowGroup":
            self.revision += 1
            self._layout()
            invocation.return_value(GLib.Variant("(aiai)", ([0] if 0 in args[0] else [], [])))
        else:
            invocation.return_value(None)

    def _event(self, item_id, event_id):
        if event_id != "clicked":
            return
        if not self.actions:
            self._layout()
        action = self.actions.get(item_id)
        if action:
            GLib.idle_add(lambda: (action(), False)[1])
