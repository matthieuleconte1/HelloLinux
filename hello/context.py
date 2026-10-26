"""Pièces jointes et contexte donnés à l'IA (AgentContext.swift) : fichiers, images collées, captures d'écran,
et ce que l'IA sait de la situation au moment de la demande."""
import os
import platform
import shutil
import subprocess
import time
from urllib.parse import unquote, urlparse

from gi.repository import Gio, GLib

from . import portal, shell
from .settings import HOME

# Captures et images collées. Vidé au lancement de Hello : une session du terminal peut encore s'en servir.
FOLDER = os.path.join(GLib.get_tmp_dir(), f"hello-attachments-{os.getuid()}")


class Attachment:
    def __init__(self, path, screenshot=False):
        self.path = path
        self.screenshot = screenshot

    def __eq__(self, other):
        return isinstance(other, Attachment) and other.path == self.path

    def __hash__(self):
        return hash(self.path)

    @property
    def name(self):
        return "Capture d'écran" if self.screenshot else os.path.basename(self.path) or self.path

    @property
    def is_image(self):
        mime, _ = Gio.content_type_guess(self.path, None)
        return bool(mime) and Gio.content_type_is_mime_type(mime, "image/*")

    @property
    def is_folder(self):
        return os.path.isdir(self.path)


def clean_up():
    shutil.rmtree(FOLDER, ignore_errors=True)


def _new_file(prefix, ext="png"):
    os.makedirs(FOLDER, mode=0o700, exist_ok=True)
    return os.path.join(FOLDER, f"{prefix}-{int(time.time() * 1000)}.{ext}")


def _paste(mime):
    try:
        return subprocess.run(["wl-paste", "-n", "-t", mime], capture_output=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return b""


def from_clipboard():
    """Fichiers copiés dans le gestionnaire de fichiers, ou image sans fichier (capture copiée, image d'une page
    web). None s'il n'y a ni l'un ni l'autre (Ctrl V colle alors le texte, comme d'habitude)."""
    if not shutil.which("wl-paste"):
        return None
    types = shell.capture(["wl-paste", "--list-types"], timeout=2).split()
    if "text/uri-list" in types or "x-special/gnome-copied-files" in types:
        raw = _paste("text/uri-list").decode("utf-8", "replace")
        paths = []
        for line in raw.replace("\r", "").split("\n"):
            if line.startswith("file://"):
                path = unquote(urlparse(line).path)
                if os.path.exists(path):
                    paths.append(path)
        if paths:
            return [Attachment(p) for p in paths]
    image = next((t for t in ("image/png", "image/jpeg", "image/webp") if t in types), None)
    if image and not any(t.startswith("text/plain") or t in ("UTF8_STRING", "TEXT", "STRING") for t in types):
        data = _paste(image)
        if data:
            path = _new_file("Image", image.split("/")[1])
            try:
                with open(path, "wb") as f:
                    f.write(data)
                return [Attachment(path)]
            except OSError:
                return None
    return None


def capture_screen(done):
    """Capture interactive du bureau (portail Screenshot : zone, fenêtre ou écran). `done(Attachment | None)`."""
    def response(code, results):
        uri = results.get("uri") if code == 0 else None
        source = unquote(urlparse(uri).path) if uri else None
        if not source or not os.path.exists(source):
            return done(None)
        target = _new_file("Capture", os.path.splitext(source)[1].lstrip(".") or "png")
        try:
            shutil.move(source, target)
        except OSError:
            target = source
        done(Attachment(target, screenshot=True))

    portal.request("org.freedesktop.portal.Screenshot", "Screenshot",
                   lambda token: GLib.Variant("(sa{sv})", ("", {"handle_token": GLib.Variant("s", token),
                                                               "interactive": GLib.Variant("b", True),
                                                               "modal": GLib.Variant("b", True)})),
                   response)


def pick_files(done, title):
    """Sélecteur de fichiers du bureau (portail FileChooser). `done([Attachment])`."""
    from gi.repository import Gtk
    dialog = Gtk.FileDialog(title=title, accept_label="Joindre", modal=True)

    def finished(d, result):
        try:
            files = d.open_multiple_finish(result)
        except GLib.Error:
            return done([])
        done([Attachment(f.get_path()) for f in files if f.get_path()])

    dialog.open_multiple(None, None, finished)


def _distribution():
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return "Linux"


class Context:
    """Ce que l'IA sait de la situation au moment de la demande."""

    def __init__(self, attachments=(), history=""):
        self.attachments = list(attachments)
        self.history = history

    @property
    def first_image(self):
        return next((a for a in self.attachments if a.is_image), None)

    @property
    def block(self):
        desktop = os.environ.get("XDG_CURRENT_DESKTOP", "") or "?"
        session = os.environ.get("XDG_SESSION_TYPE", "") or "?"
        lines = [f"- {_distribution()} (kernel {platform.release()}), desktop {desktop} on {session}, user home: {HOME}"]
        if self.attachments:
            lines.append("- Files attached by the user (local paths; look at images with vision_analyze, "
                         "read others with read_file):")
            for a in self.attachments:
                kind = ("screenshot of the user's screen" if a.screenshot else "image" if a.is_image
                        else "folder" if a.is_folder else "file")
                lines.append(f"  - {a.path} ({kind})")
        block = "Context from Hello:\n" + "\n".join(lines)
        if self.history:
            block += "\n\nThis is a follow-up. Earlier in this conversation (oldest first):\n" + self.history
        return block

    @property
    def router_note(self):
        """Pour le routeur, qui n'a aucun outil et ne voit pas les fichiers."""
        if not self.attachments:
            return self.block
        return self.block + "\nYou cannot see the attachments: if the request depends on their content, never use ANSWER."
