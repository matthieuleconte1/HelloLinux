"""Intégration au bureau Linux : ouvrir, afficher dans le gestionnaire de fichiers, corbeille,
presse-papiers (wl-copy), collage dans l'app active (ydotool), terminal et éditeur."""
import os
import shlex
import shutil
import subprocess

from gi.repository import Gio, GLib

from .settings import HOME, settings


def spawn(argv, cwd=None, env=None):
    """Lance un programme détaché (il survit à Hello)."""
    try:
        subprocess.Popen(argv, cwd=cwd or HOME, env=env, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return True
    except OSError:
        return False


def open_path(path):
    try:
        Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(path).get_uri(), None)
    except GLib.Error:
        spawn(["xdg-open", path])


def open_uri(uri):
    try:
        Gio.AppInfo.launch_default_for_uri(uri, None)
    except GLib.Error:
        spawn(["xdg-open", uri])


def reveal(paths):
    """Afficher dans le gestionnaire de fichiers (Dolphin, Nautilus…), fichiers sélectionnés."""
    uris = [Gio.File.new_for_path(p).get_uri() for p in paths]
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        bus.call_sync("org.freedesktop.FileManager1", "/org/freedesktop/FileManager1",
                      "org.freedesktop.FileManager1", "ShowItems", GLib.Variant("(ass)", (uris, "")),
                      None, Gio.DBusCallFlags.NONE, 2000)
    except GLib.Error:
        if paths:
            open_path(os.path.dirname(paths[0]))


def trash(path):
    try:
        return Gio.File.new_for_path(path).trash(None)
    except GLib.Error:
        return False


def file_manager_name():
    info = Gio.AppInfo.get_default_for_type("inode/directory", False)
    return info.get_display_name() if info else "le gestionnaire de fichiers"


# MARK: - Presse-papiers

_on_own_copy = []  # prévenu quand Hello écrit lui-même dans le presse-papiers


def _wl_copy(data, mime=None):
    if not shutil.which("wl-copy"):
        return False
    argv = ["wl-copy"] + (["-t", mime] if mime else [])
    try:
        subprocess.run(argv, input=data, timeout=3, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return False
    for callback in _on_own_copy:
        callback()
    return True


def copy(text):
    if not _wl_copy(text.encode()):
        from gi.repository import Gdk
        Gdk.Display.get_default().get_clipboard().set(text)


def copy_files(paths):
    uris = "\r\n".join(Gio.File.new_for_path(p).get_uri() for p in paths)
    _wl_copy(uris.encode(), "text/uri-list")


def copy_image(path):
    try:
        with open(path, "rb") as f:
            _wl_copy(f.read(), "image/png")
    except OSError:
        pass


def _ydotool_socket():
    for candidate in (os.environ.get("YDOTOOL_SOCKET"), f"/run/user/{os.getuid()}/.ydotool_socket",
                      "/tmp/.ydotool_socket"):
        if candidate and os.path.exists(candidate):
            return candidate
    return None


def can_paste():
    """Collage direct possible : réglage activé + ydotool (démon ydotoold lancé)."""
    return bool(settings.pasteOnEnter and shutil.which("ydotool") and _ydotool_socket())


def paste_frontmost(delay_ms=180):
    """Ctrl+V dans l'app qui reprend le focus une fois Hello masqué."""
    if not can_paste():
        return False

    def press():
        env = dict(os.environ, YDOTOOL_SOCKET=_ydotool_socket())
        # 29 = Ctrl gauche, 47 = V (codes evdev)
        spawn(["ydotool", "key", "29:1", "47:1", "47:0", "29:0"], env=env)
        return False

    GLib.timeout_add(delay_ms, press)
    return True


def insert(text):
    """Tape un texte dans l'app active (via Ctrl+V). Sans ydotool : se contente de copier."""
    copy(text)
    return paste_frontmost()


# MARK: - Terminal et éditeur

TERMINALS = [
    # (commande, nom, gabarit : {dir} et {argv} remplacés)
    ("ghostty", "Ghostty", ["ghostty", "--working-directory={dir}", "-e", "{argv}"]),
    ("kitty", "kitty", ["kitty", "--directory", "{dir}", "{argv}"]),
    ("wezterm", "WezTerm", ["wezterm", "start", "--cwd", "{dir}", "--", "{argv}"]),
    ("alacritty", "Alacritty", ["alacritty", "--working-directory", "{dir}", "-e", "{argv}"]),
    ("foot", "foot", ["foot", "-D", "{dir}", "{argv}"]),
    ("konsole", "Konsole", ["konsole", "--workdir", "{dir}", "-e", "{argv}"]),
    ("gnome-terminal", "Terminal GNOME", ["gnome-terminal", "--working-directory={dir}", "--", "{argv}"]),
    ("ptyxis", "Ptyxis", ["ptyxis", "--new-window", "--working-directory={dir}", "--", "{argv}"]),
    ("xfce4-terminal", "Terminal Xfce", ["xfce4-terminal", "--working-directory={dir}", "-x", "{argv}"]),
    ("xterm", "XTerm", ["xterm", "-e", "{argv}"]),
]

EDITORS = [
    ("cursor", "Cursor"), ("code", "Visual Studio Code"), ("codium", "VSCodium"), ("zed", "Zed"),
    ("zeditor", "Zed"), ("subl", "Sublime Text"), ("kate", "Kate"), ("gnome-text-editor", "Éditeur de texte"),
    ("idea", "IntelliJ IDEA"),
]


def installed_terminals():
    return [t for t in TERMINALS if shutil.which(t[0])]


def installed_editors():
    return [e for e in EDITORS if shutil.which(e[0])]


def terminal():
    """Terminal choisi dans les réglages (ou le premier installé)."""
    found = installed_terminals()
    for t in found:
        if t[0] == settings.terminal:
            return t
    return found[0] if found else TERMINALS[-1]


def editor():
    """Éditeur choisi dans les réglages ("none" : désactivé)."""
    if settings.editor == "none":
        return None
    found = installed_editors()
    for e in found:
        if e[0] == settings.editor:
            return e
    return found[0] if found else None


def user_shell():
    return os.environ.get("SHELL") or shutil.which("zsh") or "/bin/bash"


def run_in_terminal(command=None, directory=HOME):
    """Lance la commande dans le terminal choisi, dans `directory`, puis laisse un shell ouvert."""
    sh = user_shell()
    if command:
        argv = [sh, "-lic", f"{command}; exec {shlex.quote(sh)} -l"]
    else:
        argv = [sh, "-l"]
    _, _, template = terminal()
    out = []
    for part in template:
        if part == "{argv}":
            out += argv
        else:
            out.append(part.replace("{dir}", directory))
    if not spawn(out, cwd=directory):
        # Dernier recours : xdg-terminal-exec (standard en cours d'adoption).
        spawn(["xdg-terminal-exec"] + argv, cwd=directory)


def open_with_editor(path):
    e = editor()
    if e:
        spawn([e[0], path])


def notify(title, body=""):
    spawn(["notify-send", "-a", "Hello", "-i", "io.github.matthieuleconte1.Hello", title, body])
