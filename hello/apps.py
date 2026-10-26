"""Index des applications : les fichiers .desktop (Gio), relus au plus une fois par minute,
seulement à l'ouverture du panneau. Aucune surveillance en tâche de fond."""
import os
import re
import signal
import threading
import time

from gi.repository import Gio, GLib

from .fuzzy import fold, score
from .settings import APP_ID, HOME


class AppEntry:
    __slots__ = ("id", "desktop_id", "name", "path", "key", "alt_key", "detail", "info", "icon",
                 "exec_name", "keywords")

    def __init__(self, info):
        self.info = info
        self.desktop_id = info.get_id() or ""
        self.id = "app:" + self.desktop_id
        self.name = info.get_display_name() or info.get_name() or self.desktop_id
        self.path = info.get_filename() or ""
        self.key = fold(self.name)
        stem = self.desktop_id[:-8] if self.desktop_id.endswith(".desktop") else self.desktop_id
        # Nom anglais / générique, ou dernier segment de l'identifiant (org.kde.dolphin → dolphin).
        generic = info.get_generic_name() or ""
        self.alt_key = fold(generic or stem.split(".")[-1])
        self.keywords = fold(" ".join(info.get_keywords() or []))
        self.detail = None
        self.icon = info.get_icon()
        executable = info.get_executable() or ""
        self.exec_name = os.path.basename(executable)

    def score(self, query):
        a = score(query, self.key)
        b = score(query, self.alt_key)
        best = max((s for s in (a, b - 5 if b is not None else None) if s is not None), default=None)
        if best is None and len(query) >= 3 and query in self.keywords:
            best = 500
        return best

    @property
    def flatpak_id(self):
        if "/flatpak/exports/" in self.path:
            return self.desktop_id[:-8]
        return None

    @property
    def is_user_local(self):
        return self.path.startswith(os.path.join(HOME, ".local/share/applications"))


class AppIndex:
    def __init__(self, on_change):
        self.apps = []
        self.on_change = on_change
        self.last_scan = 0
        self.scanning = False
        self._monitor = Gio.AppInfoMonitor.get()
        # Le système prévient quand un paquet ajoute ou retire une app : on relira à la prochaine ouverture.
        self._monitor.connect("changed", lambda *_: setattr(self, "last_scan", 0))

    def refresh(self):
        if self.scanning:
            return
        self.scanning = True

        def work():
            result = self._scan()
            GLib.idle_add(self._done, result)

        threading.Thread(target=work, daemon=True).start()

    def _done(self, result):
        self.apps = result
        self.last_scan = time.time()
        self.scanning = False
        self.on_change()
        return False

    def refresh_if_stale(self):
        if time.time() - self.last_scan > 60:
            self.refresh()

    @staticmethod
    def _scan():
        out = []
        seen = set()
        for info in Gio.AppInfo.get_all():
            if not isinstance(info, Gio.DesktopAppInfo) or not info.should_show():
                continue
            entry = AppEntry(info)
            if entry.desktop_id.startswith(APP_ID) or entry.desktop_id in seen:
                continue
            seen.add(entry.desktop_id)
            out.append(entry)
        # Plusieurs apps du même nom (ex. deux Firefox) : on affiche l'origine de chacune.
        counts = {}
        for a in out:
            counts[a.key] = counts.get(a.key, 0) + 1
        for a in out:
            if counts[a.key] > 1:
                origin = "Flatpak" if a.flatpak_id else ("Local" if a.is_user_local else "Système")
                a.detail = f"{origin} · {a.desktop_id}"
        out.sort(key=lambda a: a.key)
        return out

    def launch(self, app):
        ctx = None
        try:
            from gi.repository import Gdk
            ctx = Gdk.Display.get_default().get_app_launch_context()
        except Exception:
            pass
        try:
            return app.info.launch([], ctx)
        except GLib.Error:
            return False


# MARK: - Apps ouvertes

_ESCAPE = re.compile(r"\\x([0-9a-fA-F]{2})")
_running_cache = (0.0, {})


def _units():
    """pid → nom d'unité systemd de l'app (Plasma, GNOME et la plupart des lanceurs placent chaque app
    dans une unité « app-<lanceur>-<id>@….service » ou « app-…-<id>-<hasard>.scope »)."""
    out = {}
    uid = os.getuid()
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            if os.stat(f"/proc/{name}").st_uid != uid:
                continue
            with open(f"/proc/{name}/cgroup") as f:
                cg = f.read()
        except OSError:
            continue
        unit = cg.strip().rsplit("/", 1)[-1]
        if unit.startswith("app-"):
            out[int(name)] = _ESCAPE.sub(lambda m: chr(int(m.group(1), 16)), unit)
    return out


def running(apps):
    """desktop_id → pids des apps ouvertes. Mis en cache 3 s."""
    global _running_cache
    now = time.time()
    if now - _running_cache[0] < 3:
        return _running_cache[1]
    units = _units()
    result = {}
    for app in apps:
        stem = app.desktop_id[:-8]
        if not stem:
            continue
        for pid, unit in units.items():
            if f"-{stem}@" in unit or f"-{stem}-" in unit or unit.endswith(f"-{stem}.scope") \
                    or unit.endswith(f"-{stem}.service"):
                result.setdefault(app.desktop_id, []).append(pid)
    _running_cache = (now, result)
    return result


def invalidate_running():
    global _running_cache
    _running_cache = (0.0, {})


def quit_app(pids):
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    invalidate_running()
