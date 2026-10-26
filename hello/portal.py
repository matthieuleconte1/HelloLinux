"""Appels aux portails XDG (raccourci global, pipette), sans dépendance : Gio D-Bus.

Chaque méthode de portail renvoie un objet « Request » ; la réponse arrive par le signal Response.
On s'abonne au chemin prévu avant l'appel pour ne jamais rater une réponse rapide."""
import uuid

from gi.repository import Gio, GLib

from .settings import APP_ID

BUS = "org.freedesktop.portal.Desktop"
PATH = "/org/freedesktop/portal/desktop"

_bus = None
_registered = False


def bus():
    global _bus
    if _bus is None:
        _bus = Gio.bus_get_sync(Gio.BusType.SESSION)
    return _bus


def register_app():
    """Annonce l'identifiant de Hello au portail (app non sandboxée, portail ≥ 1.19).
    Sans cela, KDE ne sait pas à quelle app rattacher le raccourci. Sans effet sur les portails plus anciens."""
    global _registered
    if _registered:
        return
    _registered = True
    try:
        bus().call_sync(BUS, PATH, "org.freedesktop.host.portal.Registry", "Register",
                        GLib.Variant("(sa{sv})", (APP_ID, {})), None, Gio.DBusCallFlags.NONE, 2000)
    except GLib.Error:
        pass


def _token():
    return "hello_" + uuid.uuid4().hex[:12]


def request(interface, method, build_args, on_response):
    """Appelle `method` ; `build_args(token)` renvoie le GLib.Variant des arguments (avec handle_token = token).
    `on_response(code, results)` : code 0 = succès, 1 = annulé, 2 = autre erreur."""
    token = _token()
    sender = bus().get_unique_name()[1:].replace(".", "_")
    handle = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
    sub = None

    def received(_conn, _sender, _path, _iface, _signal, params):
        bus().signal_unsubscribe(sub)
        code, results = params.unpack()
        on_response(code, results)

    sub = bus().signal_subscribe(BUS, "org.freedesktop.portal.Request", "Response", handle, None,
                                 Gio.DBusSignalFlags.NO_MATCH_RULE, received)

    def called(conn, result):
        try:
            conn.call_finish(result)
        except GLib.Error as e:
            bus().signal_unsubscribe(sub)
            on_response(2, {"error": e.message})

    bus().call(BUS, PATH, interface, method, build_args(token), None, Gio.DBusCallFlags.NONE, -1, None, called)


def version(interface):
    try:
        v = bus().call_sync(BUS, PATH, "org.freedesktop.DBus.Properties", "Get",
                            GLib.Variant("(ss)", (interface, "version")), None, Gio.DBusCallFlags.NONE, 1000)
        return v.unpack()[0]
    except GLib.Error:
        return 0
