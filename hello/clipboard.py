"""Historique du presse-papiers (Clipboard.swift).

Sous Wayland, une app sans focus ne peut pas lire le presse-papiers : on s'appuie sur `wl-paste --watch`
(protocole data-control, géré par KWin, wlroots…), qui ne réveille Hello qu'à chaque copie.
Les copies marquées secrètes par les gestionnaires de mots de passe (KeePassXC, Bitwarden…) sont ignorées."""
import os
import re
import shutil
import subprocess
import threading
import time
import uuid

from gi.repository import GLib

from . import desktop
from .fuzzy import fold
from .settings import CLIP_DIR, DATA_DIR, Debounced, load_json, save_json, settings

# Types posés par les gestionnaires de mots de passe (équivalents de org.nspasteboard.ConcealedType).
IGNORED_TYPES = {"x-kde-passwordManagerHint", "x-kde-passwordmanagerhint"}
_HEX = re.compile(r"^#?[0-9a-fA-F]{6}$")


class ClipEntry(dict):
    """id, kind (text | image | files), text, files, image, size, date, source."""

    @property
    def title(self):
        kind = self["kind"]
        if kind == "text":
            for line in (self.get("text") or "").splitlines():
                if line.strip():
                    return line.strip()[:140]
            return ""
        if kind == "image":
            return "Image" + (f" {self['size']}" if self.get("size") else "")
        files = self.get("files") or []
        return os.path.basename(files[0]) if len(files) == 1 else f"{len(files)} fichiers"

    @property
    def detail(self):
        kind = self["kind"]
        if kind == "text":
            t = self.get("text") or ""
            lines = max(len(t.splitlines()), 1)
            return f"{len(t)} caractères · {lines} ligne{'s' if lines > 1 else ''}"
        if kind == "image":
            return "Image PNG" + (f" · {self['size']} px" if self.get("size") else "")
        return f"{len(self.get('files') or [])} élément(s)"

    @property
    def image_path(self):
        return os.path.join(CLIP_DIR, self["image"]) if self.get("image") else None

    @property
    def trimmed(self):
        return (self.get("text") or "").strip()

    @property
    def hex_color(self):
        t = self.trimmed
        if len(t) <= 7 and _HEX.match(t):
            v = int(t.lstrip("#"), 16)
            return ((v >> 16) & 255) / 255, ((v >> 8) & 255) / 255, (v & 255) / 255
        return None

    @property
    def is_link(self):
        t = self.trimmed
        return t.startswith(("http://", "https://")) and not any(c.isspace() for c in t)

    @property
    def looks_like_code(self):
        t = self.get("text") or ""
        return "{" in t or "\t" in t or ";\n" in t or "=>" in t or t.startswith("  ")

    def same_content(self, other):
        return (self["kind"] == other["kind"] and self["kind"] != "image"
                and self.get("text") == other.get("text") and self.get("files") == other.get("files"))


class ClipboardHistory:
    _index = os.path.join(DATA_DIR, "clipboard.json")

    def __init__(self):
        self.entries = [ClipEntry(e) for e in load_json(self._index, [])]
        self.on_change = None
        self._keys = {}
        self._process = None
        self._skip_until = 0
        self._save = Debounced(1.5, self._write)
        desktop._on_own_copy.append(self.skip_current)

    @property
    def available(self):
        return shutil.which("wl-paste") is not None

    def start(self):
        self.prune()
        self.update_monitoring()

    def update_monitoring(self):
        """Démarre / arrête la surveillance selon les réglages (aucun processus si désactivé)."""
        if self._process:
            self._process.terminate()
            self._process = None
        if not settings.clipboardEnabled or not self.available:
            return
        try:
            # Le contenu arrive sur l'entrée de `sh`, qu'on jette : seule compte la notification (une ligne).
            self._process = subprocess.Popen(
                ["wl-paste", "--watch", "sh", "-c", "cat >/dev/null; echo"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        except OSError:
            return
        channel = GLib.IOChannel.unix_new(self._process.stdout.fileno())
        GLib.io_add_watch(channel, GLib.PRIORITY_DEFAULT_IDLE, GLib.IO_IN | GLib.IO_HUP, self._changed, self._process)

    def stop(self):
        if self._process:
            self._process.terminate()
            self._process = None

    def _changed(self, channel, condition, process):
        if process is not self._process:
            return False
        line = process.stdout.readline()
        if not line:
            return False
        if time.time() < self._skip_until:
            return True
        threading.Thread(target=self._read, daemon=True).start()
        return True

    def skip_current(self):
        """À appeler après avoir écrit nous-mêmes dans le presse-papiers."""
        self._skip_until = time.time() + 0.6

    def _read(self):
        try:
            types = subprocess.run(["wl-paste", "--list-types"], capture_output=True, text=True,
                                   timeout=2).stdout.split("\n")
        except (OSError, subprocess.SubprocessError):
            return
        types = [t.strip() for t in types if t.strip()]
        if not types or any(t in IGNORED_TYPES for t in types):
            return

        def get(mime, binary=False):
            try:
                out = subprocess.run(["wl-paste", "-n", "-t", mime], capture_output=True, timeout=3).stdout
            except (OSError, subprocess.SubprocessError):
                return None
            return out if binary else out.decode("utf-8", "replace")

        entry = None
        if "text/uri-list" in types:
            uris = [u.strip() for u in (get("text/uri-list") or "").splitlines() if u.startswith("file://")]
            if uris:
                files = [GLib.filename_from_uri(u)[0] for u in uris]
                entry = ClipEntry(kind="files", files=files)
        if entry is None:
            text_type = next((t for t in ("text/plain;charset=utf-8", "UTF8_STRING", "text/plain", "TEXT", "STRING")
                              if t in types), None)
            if text_type:
                text = get(text_type)
                if text and text.strip():
                    entry = ClipEntry(kind="text", text=text)
        if entry is None and settings.clipboardImages and "image/png" in types:
            data = get("image/png", binary=True)
            if data:
                entry = self._store_image(data)
        if entry is not None:
            entry.update(id=str(uuid.uuid4()), date=time.time())
            GLib.idle_add(self._insert, entry)

    @staticmethod
    def _store_image(data):
        name = str(uuid.uuid4()) + ".png"
        path = os.path.join(CLIP_DIR, name)
        try:
            with open(path, "wb") as f:
                f.write(data)
            os.chmod(path, 0o600)
        except OSError:
            return None
        size = None
        if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) > 24:
            size = f"{int.from_bytes(data[16:20], 'big')}×{int.from_bytes(data[20:24], 'big')}"
        return ClipEntry(kind="image", image=name, size=size)

    def _insert(self, entry):
        for i, e in enumerate(self.entries):
            if e.same_content(entry):
                self._keys.pop(e["id"], None)
                del self.entries[i]
                break
        self.entries.insert(0, entry)
        self._changed_list()
        self.prune()
        return False

    def prune(self):
        """Applique la limite de taille et la durée de conservation."""
        removed = False
        if settings.clipboardRetentionDays > 0:
            limit = time.time() - settings.clipboardRetentionDays * 86400
            for e in [e for e in self.entries if e["date"] < limit]:
                self._discard(e)
                self.entries.remove(e)
                removed = True
        while len(self.entries) > settings.clipboardLimit:
            self._discard(self.entries.pop())
            removed = True
        if removed:
            self._changed_list()

    def search_key(self, e):
        k = self._keys.get(e["id"])
        if k is None:
            if e["kind"] == "text":
                base = (e.get("text") or "")[:4000]
            elif e["kind"] == "files":
                base = " ".join(e.get("files") or [])
            else:
                base = "image " + (e.get("size") or "")
            k = fold(base + " " + (e.get("source") or ""))
            self._keys[e["id"]] = k
        return k

    def restore(self, e, paste):
        """Remet l'élément dans le presse-papiers (et le colle dans l'app active si demandé)."""
        if e["kind"] == "text":
            desktop.copy(e.get("text") or "")
        elif e["kind"] == "image" and e.image_path:
            desktop.copy_image(e.image_path)
        else:
            desktop.copy_files(e.get("files") or [])
        for i, x in enumerate(self.entries):
            if x["id"] == e["id"]:
                moved = self.entries.pop(i)
                moved["date"] = time.time()
                self.entries.insert(0, moved)
                self._changed_list()
                break
        if paste:
            desktop.paste_frontmost()

    def remove(self, e):
        for i, x in enumerate(self.entries):
            if x["id"] == e["id"]:
                self._discard(self.entries.pop(i))
                self._changed_list()
                return

    def clear(self):
        for e in self.entries:
            self._discard(e)
        self.entries = []
        self._changed_list()

    def _discard(self, e):
        self._keys.pop(e["id"], None)
        if e.image_path:
            try:
                os.remove(e.image_path)
            except OSError:
                pass

    def _changed_list(self):
        if self.on_change:
            self.on_change()
        self._save()

    def _write(self):
        save_json(self._index, [dict(e) for e in self.entries], private=True)
