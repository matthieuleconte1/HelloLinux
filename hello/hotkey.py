"""Raccourci global (HotKey.swift) via le portail XDG GlobalShortcuts (Plasma 6, GNOME 48+, Hyprland…).

Wayland interdit d'écouter le clavier des autres apps : c'est le bureau qui détient le raccourci et prévient
Hello. Sur Plasma, Hello parle directement à kglobalaccel, comme une app KDE native : il déclare son action
(sinon KWin ignore la touche) et reprend la combinaison à son propriétaire au premier lancement
(Alt Espace à KRunner, qui garde Alt F2 et la touche Recherche). Ailleurs, portail GlobalShortcuts.
Sans portail, `hello --toggle` reste utilisable depuis n'importe quel gestionnaire de raccourcis."""
import os

from gi.repository import Gio, GLib

from . import portal
from .settings import APP_ID, settings

IFACE = "org.freedesktop.portal.GlobalShortcuts"
SHORTCUT_ID = "toggle"

# Combinaisons proposées au bureau (format du portail : MODIFICATEUR+touche, cf. spécification XDG).
CHOICES = [
    ("ALT+space", "Alt Espace", "Remplace KRunner sur Plasma (qui garde Alt F2)"),
    ("LOGO+space", "Super Espace", "L'équivalent de ⌘ Espace sur Mac"),
    ("CTRL+space", "Ctrl Espace", "Peut entrer en conflit avec certaines méthodes de saisie"),
    ("LOGO+r", "Super R", "Comme « Exécuter » sous Windows"),
    ("CTRL+ALT+space", "Ctrl Alt Espace", "Rarement utilisé ailleurs"),
]


def label(trigger):
    for value, title, _ in CHOICES:
        if value == trigger:
            return title
    return trigger


# MARK: - Plasma (kglobalaccel)

HELLO_ACTION = [APP_ID, SHORTCUT_ID, "Hello", "Ouvrir Hello"]
QT_MODIFIERS = {"SHIFT": 0x02000000, "CTRL": 0x04000000, "ALT": 0x08000000, "LOGO": 0x10000000}
QT_NAMES = [(0x10000000, "Meta"), (0x04000000, "Ctrl"), (0x08000000, "Alt"), (0x02000000, "Maj")]


def is_kde():
    return "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "")


def qt_key(trigger):
    """« ALT+space » → code QKeySequence (modificateurs | touche), None si inconnu."""
    *mods, key = trigger.split("+")
    if key.lower() == "space":
        code = 0x20
    elif len(key) == 1 and key.isalnum():
        code = ord(key.upper())
    else:
        return None
    try:
        return code | sum(QT_MODIFIERS[m.upper()] for m in mods)
    except KeyError:
        return None


def key_label(code):
    names = [name for flag, name in QT_NAMES if code & flag]
    key = code & 0x01FFFFFF
    names.append("Espace" if key == 0x20 else chr(key) if 0x21 <= key < 0x7F else hex(key))
    return " ".join(names)


def _kga(method, signature, args, reply):
    try:
        out = portal.bus().call_sync("org.kde.kglobalaccel", "/kglobalaccel", "org.kde.KGlobalAccel", method,
                                     GLib.Variant(signature, args), GLib.VariantType(reply) if reply else None,
                                     Gio.DBusCallFlags.NONE, 2000)
        return out.unpack()[0] if reply else True
    except GLib.Error:
        return None


def kde_keys(action):
    """Combinaisons d'une action (première touche de chaque séquence)."""
    sequences = _kga("shortcutKeys", "(as)", (action,), "(a(ai))") or []
    return [seq[0][0] for seq in sequences if seq and seq[0] and seq[0][0]]


SET_PRESENT = 2   # KGlobalAccel::SetPresent : l'action est tenue par un programme en cours d'exécution


def kde_register(trigger):
    """Déclare l'action « Ouvrir Hello » auprès de kglobalaccel, comme le fait une app KDE native.
    Sans cela, KDE garde la combinaison mais la considère inactive et KWin ignore la touche.
    Au premier lancement (aucune combinaison), `trigger` est repris à l'action qui l'utilise."""
    if _kga("doRegister", "(as)", (HELLO_ACTION,), None) is None:
        return False
    # Sans NoAutoloading, kglobalaccel garde la combinaison déjà enregistrée (choisie par l'utilisateur).
    _kga("setShortcutKeys", "(asa(ai)u)", (HELLO_ACTION, [], SET_PRESENT), "(a(ai))")
    if not kde_keys(HELLO_ACTION):
        kde_take(trigger)
    return bool(kde_keys(HELLO_ACTION))


def kde_unregister():
    """Hello quitte : la combinaison reste enregistrée mais KWin ne la capte plus."""
    _kga("setInactive", "(as)", (HELLO_ACTION,), None)


def kde_take(trigger):
    """Attribue `trigger` à Hello en le retirant à l'action qui l'utilise. Renvoie le nom de l'ancien
    propriétaire (ou None), False si impossible."""
    code = qt_key(trigger)
    if code is None:
        return False
    owner = _kga("actionList", "((ai))", (([code, 0, 0, 0],),), "(as)") or []
    previous = None
    if len(owner) >= 2 and owner[:2] != HELLO_ACTION[:2]:
        keep = [([k, 0, 0, 0],) for k in kde_keys(owner) if k != code]
        _kga("setForeignShortcutKeys", "(asa(ai))", (owner, keep), None)
        previous = owner[3] if len(owner) > 3 else owner[0]
    ok = _kga("setForeignShortcutKeys", "(asa(ai))", (HELLO_ACTION, [([code, 0, 0, 0],)]), None)
    return previous if ok else False


class GlobalHotkey:
    def __init__(self, on_activate):
        self.on_activate = on_activate
        self.session = None
        self.trigger_description = None
        self.state = "pending"     # pending | bound | unavailable | refused
        self.on_state = None
        self._sub = None
        self.kde = False
        self._last_fire = 0

    @property
    def available(self):
        return portal.version(IFACE) > 0

    def start(self):
        if is_kde() and self._start_kde():
            return
        # L'enregistrement doit précéder tout autre appel au portail sur cette connexion.
        portal.register_app()
        if not self.available:
            self._set("unavailable")
            return
        self._sub = portal.bus().signal_subscribe(portal.BUS, IFACE, "Activated", portal.PATH, None,
                                                  Gio.DBusSignalFlags.NONE, self._activated)

        def created(code, results):
            if code != 0 or "session_handle" not in results:
                self._set("refused")
                return
            self.session = results["session_handle"]
            self.bind()

        portal.request(IFACE, "CreateSession", lambda token: GLib.Variant("(a{sv})", ({
            "handle_token": GLib.Variant("s", token),
            "session_handle_token": GLib.Variant("s", token + "_s"),
        },)), created)

    def _start_kde(self):
        """Plasma : Hello tient lui-même son action dans kglobalaccel et écoute ses appuis (pas de portail)."""
        portal.bus().signal_subscribe("org.kde.kglobalaccel", "org.kde.kglobalaccel.Component",
                                      "globalShortcutPressed", "/component/" + APP_ID.replace(".", "_"), None,
                                      Gio.DBusSignalFlags.NONE, self._kde_pressed)
        self.kde = True
        ok = kde_register(settings.hotkey)
        self._set("bound" if ok else "refused")
        return ok

    def stop(self):
        if getattr(self, "kde", False):
            kde_unregister()

    def bind(self, trigger=None, force=False):
        """Propose la combinaison au bureau. Sur Plasma, Hello la prend lui-même, même si elle est occupée :
        au premier lancement (Hello sans raccourci) ou quand on la choisit (`force`)."""
        if getattr(self, "kde", False):
            if force:
                kde_take(trigger or settings.hotkey)
            self._set("bound" if kde_keys(HELLO_ACTION) else "refused")
            return
        if not self.session:
            return
        shortcuts = [(SHORTCUT_ID, {
            "description": GLib.Variant("s", "Ouvrir Hello"),
            "preferred_trigger": GLib.Variant("s", trigger or settings.hotkey),
        })]

        def bound(code, results):
            if code != 0:
                self._set("refused")
                return
            for sid, data in results.get("shortcuts", []):
                if sid == SHORTCUT_ID:
                    self.trigger_description = data.get("trigger_description") or None
            self._set("bound")

        portal.request(IFACE, "BindShortcuts", lambda token: GLib.Variant("(oa(sa{sv})sa{sv})", (
            self.session, shortcuts, "", {"handle_token": GLib.Variant("s", token)})), bound)

    def configure(self):
        """Ouvre la fenêtre du bureau pour changer le raccourci (portail v2), sinon les réglages de KDE."""
        if self.session and portal.version(IFACE) >= 2:
            try:
                portal.bus().call_sync(portal.BUS, portal.PATH, IFACE, "ConfigureShortcuts",
                                       GLib.Variant("(osa{sv})", (self.session, "", {})), None,
                                       Gio.DBusCallFlags.NONE, 2000)
                return True
            except GLib.Error:
                pass
        from .desktop import spawn
        return spawn(["systemsettings", "kcm_keys"])

    def _activated(self, _conn, _sender, _path, _iface, _signal, params):
        session, shortcut_id = params.unpack()[:2]
        if session == self.session and shortcut_id == SHORTCUT_ID:
            self._fire()

    def _kde_pressed(self, _conn, _sender, _path, _iface, _signal, params):
        component, shortcut_id = params.unpack()[:2]
        if component == APP_ID and shortcut_id == SHORTCUT_ID:
            self._fire()

    def _fire(self):
        # Un même appui peut arriver par les deux chemins (portail et kglobalaccel) : un seul compte.
        now = GLib.get_monotonic_time()
        if now - self._last_fire < 300_000:
            return
        self._last_fire = now
        self.on_activate()

    def _set(self, state):
        self.state = state
        if self.on_state:
            self.on_state()

    @property
    def active(self):
        """Le raccourci ouvre bien Hello (lié par le portail, ou attribué dans kglobalaccel sur Plasma)."""
        return self.state == "bound" or (is_kde() and bool(kde_keys(HELLO_ACTION)))

    @property
    def description(self):
        if is_kde():
            keys = kde_keys(HELLO_ACTION)
            if keys:
                return " ou ".join(key_label(k) for k in keys)
        if self.state == "bound":
            return self.trigger_description or label(settings.hotkey)
        if self.state == "unavailable":
            return "portail indisponible : associe « hello --toggle » à un raccourci"
        if self.state == "refused":
            return "refusé : associe « hello --toggle » à un raccourci"
        return "en attente du bureau…"
