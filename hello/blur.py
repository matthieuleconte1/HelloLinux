"""Flou de l'arrière-plan sous Wayland, sans dépendance compilée.

- Protocole standard ext_background_effect_v1 (KWin 6.5+…) : GTK 4.22+ s'en sert lui-même pour la propriété CSS
  `backdrop-filter`. Hello vérifie seulement sa présence (créer un second effet sur la surface serait une erreur
  de protocole) et laisse faire la feuille de style.
- Sinon org_kde_kwin_blur (KWin plus ancien), piloté ici directement.

GTK ne propose pas ce protocole : on parle directement à libwayland-client (ctypes), sur la connexion de GTK
mais avec notre propre file d'événements pour ne pas déranger la sienne. On demande à KWin de flouter
uniquement la zone du panneau (coins arrondis compris) ; le reste de la surface plein écran reste net.
Sans l'un des deux (GNOME, X11…), `available` est faux et le Verre reste presque opaque."""
import ctypes
import math
from ctypes import CFUNCTYPE, POINTER, Structure, c_char_p, c_int, c_uint32, c_void_p

_lib = None
_gtk = None


class wl_interface(Structure):
    pass


class wl_message(Structure):
    _fields_ = [("name", c_char_p), ("signature", c_char_p), ("types", POINTER(POINTER(wl_interface)))]


wl_interface._fields_ = [("name", c_char_p), ("version", c_int), ("method_count", c_int),
                         ("methods", POINTER(wl_message)), ("event_count", c_int), ("events", POINTER(wl_message))]

GLOBAL = CFUNCTYPE(None, c_void_p, c_void_p, c_uint32, c_char_p, c_uint32)
GLOBAL_REMOVE = CFUNCTYPE(None, c_void_p, c_void_p, c_uint32)


class _Listener(Structure):
    _fields_ = [("glob", GLOBAL), ("remove", GLOBAL_REMOVE)]


def _gpointer(obj):
    """Adresse C d'un objet GObject de PyGObject."""
    get = ctypes.pythonapi.PyCapsule_GetPointer
    get.restype = c_void_p
    get.argtypes = [ctypes.py_object, c_char_p]
    return get(obj.__gpointer__, None)


def _types(*interfaces):
    arr = (POINTER(wl_interface) * max(1, len(interfaces)))()
    for i, iface in enumerate(interfaces):
        arr[i] = ctypes.pointer(iface) if iface is not None else None
    return arr


class KWinBlur:
    """Un flou par surface (ext_background_effect_v1 ou org_kde_kwin_blur) ; `set_rect` place la zone floutée (coordonnées de la surface)."""

    def __init__(self, display, surface):
        global _lib, _gtk
        self.available = False
        self._blur = None
        self._last = None
        self.native = False
        try:
            _lib = _lib or ctypes.CDLL("libwayland-client.so.0")
            _gtk = _gtk or ctypes.CDLL("libgtk-4.so.1")
        except OSError:
            return
        _gtk.gdk_wayland_display_get_wl_display.restype = c_void_p
        _gtk.gdk_wayland_display_get_wl_display.argtypes = [c_void_p]
        _gtk.gdk_wayland_surface_get_wl_surface.restype = c_void_p
        _gtk.gdk_wayland_surface_get_wl_surface.argtypes = [c_void_p]
        try:
            self.wl_display = _gtk.gdk_wayland_display_get_wl_display(_gpointer(display))
            self.wl_surface = _gtk.gdk_wayland_surface_get_wl_surface(_gpointer(surface))
        except (AttributeError, TypeError):
            return
        if not self.wl_display or not self.wl_surface:
            return
        self._define_interfaces()
        self._bind_globals()
        if not self.compositor:
            return
        if self.ext_manager:
            # GTK applique `backdrop-filter` avec ce protocole : rien à créer ici.
            self.native = True
            self.available = True
            return
        if self.manager:
            # org_kde_kwin_blur_manager.create (opcode 0)
            self._blur = self._marshal(self.manager, 0, self.blur_iface, 1, 0, None, c_void_p(self.wl_surface))
            self.standard = False
        self.available = bool(self._blur)

    def _define_interfaces(self):
        L = _lib
        L.wl_proxy_marshal_flags.restype = c_void_p
        L.wl_proxy_get_version.restype = c_uint32
        L.wl_proxy_get_version.argtypes = [c_void_p]
        L.wl_proxy_create_wrapper.restype = c_void_p
        L.wl_proxy_create_wrapper.argtypes = [c_void_p]
        L.wl_display_create_queue.restype = c_void_p
        L.wl_display_create_queue.argtypes = [c_void_p]
        L.wl_proxy_set_queue.argtypes = [c_void_p, c_void_p]
        L.wl_display_roundtrip_queue.argtypes = [c_void_p, c_void_p]
        L.wl_proxy_add_listener.argtypes = [c_void_p, c_void_p, c_void_p]
        L.wl_display_flush.argtypes = [c_void_p]
        self.surface_iface = wl_interface.in_dll(L, "wl_surface_interface")
        self.region_iface = wl_interface.in_dll(L, "wl_region_interface")
        self.registry_iface = wl_interface.in_dll(L, "wl_registry_interface")
        self.compositor_iface = wl_interface.in_dll(L, "wl_compositor_interface")

        self.blur_iface = wl_interface()
        self._blur_types = _types(self.region_iface)
        self._blur_methods = (wl_message * 3)(
            wl_message(b"commit", b"", None),
            wl_message(b"set_region", b"?o", self._blur_types),
            wl_message(b"release", b"", None),
        )
        self.blur_iface.name = b"org_kde_kwin_blur"
        self.blur_iface.version = 1
        self.blur_iface.method_count = 3
        self.blur_iface.methods = self._blur_methods

        self.manager_iface = wl_interface()
        self._create_types = _types(self.blur_iface, self.surface_iface)
        self._unset_types = _types(self.surface_iface)
        self._manager_methods = (wl_message * 2)(
            wl_message(b"create", b"no", self._create_types),
            wl_message(b"unset", b"o", self._unset_types),
        )
        self.manager_iface.name = b"org_kde_kwin_blur_manager"
        self.manager_iface.version = 1
        self.manager_iface.method_count = 2
        self.manager_iface.methods = self._manager_methods

    def _marshal(self, proxy, opcode, iface, version, flags, *args):
        return _lib.wl_proxy_marshal_flags(c_void_p(proxy), c_uint32(opcode),
                                           ctypes.byref(iface) if iface is not None else None,
                                           c_uint32(version), c_uint32(flags), *args)

    def _bind_globals(self):
        self.manager = self.ext_manager = self.compositor = None
        found = {}

        def on_global(_data, _registry, name, interface, version):
            found[interface.decode()] = (name, version)

        self._listener = _Listener(GLOBAL(on_global), GLOBAL_REMOVE(lambda *_: None))
        queue = _lib.wl_display_create_queue(self.wl_display)
        wrapper = _lib.wl_proxy_create_wrapper(self.wl_display)
        _lib.wl_proxy_set_queue(wrapper, queue)
        # wl_display.get_registry (opcode 1)
        registry = self._marshal(wrapper, 1, self.registry_iface, _lib.wl_proxy_get_version(wrapper), 0, None)
        if not registry:
            return
        _lib.wl_proxy_add_listener(registry, ctypes.addressof(self._listener), None)
        _lib.wl_display_roundtrip_queue(self.wl_display, queue)

        def bind(iface, wanted):
            if iface.name.decode() not in found:
                return None
            name, version = found[iface.name.decode()]
            version = min(version, wanted)
            # wl_registry.bind (opcode 0) : nom, interface, version, nouvel objet
            return self._marshal(registry, 0, iface, version, 0, c_uint32(name), c_char_p(iface.name),
                                 c_uint32(version), None)

        # Le protocole standard est déjà utilisé par GTK : sa présence suffit.
        self.ext_manager = "ext_background_effect_manager_v1" in found
        if not self.ext_manager:
            self.manager = bind(self.manager_iface, 1)
        self.compositor = bind(self.compositor_iface, 4)

    def set_rect(self, x, y, w, h, radius):
        """Floute le rectangle arrondi (x, y, w, h). Prend effet au prochain rendu de la surface."""
        if not self.available or self.native:
            return
        key = (int(x), int(y), int(w), int(h), int(radius))
        if key == self._last:
            return
        self._last = key
        x, y, w, h, r = key
        r = max(0, min(r, w // 2, h // 2))
        # wl_compositor.create_region (opcode 1)
        region = self._marshal(self.compositor, 1, self.region_iface, _lib.wl_proxy_get_version(
            c_void_p(self.compositor)), 0, None)
        if not region:
            return

        def add(rx, ry, rw, rh):
            if rw > 0 and rh > 0:
                self._marshal(region, 1, None, 0, 0, c_int(rx), c_int(ry), c_int(rw), c_int(rh))

        add(x, y + r, w, h - 2 * r)
        step = 2
        for dy in range(0, r, step):
            # Coins arrondis approchés par des bandes de 2 px.
            inset = round(r - math.sqrt(max(0, r * r - (r - dy - step / 2) ** 2)))
            band = min(step, r - dy)
            add(x + inset, y + dy, w - 2 * inset, band)
            add(x + inset, y + h - dy - band, w - 2 * inset, band)
        self._marshal(self._blur, 1, None, 0, 0, c_void_p(region))   # org_kde_kwin_blur.set_region
        self._marshal(self._blur, 0, None, 0, 0)                       # org_kde_kwin_blur.commit
        self._marshal(region, 0, None, 0, 1)                           # wl_region.destroy
        _lib.wl_display_flush(self.wl_display)


def for_window(window):
    """Flou KWin pour une fenêtre GTK déjà réalisée, ou None."""
    try:
        from gi.repository import Gdk
        display = Gdk.Display.get_default()
        if display.__gtype__.name != "GdkWaylandDisplay" or window.get_surface() is None:
            return None
        blur = KWinBlur(display, window.get_surface())
        return blur if blur.available else None
    except Exception:
        return None
