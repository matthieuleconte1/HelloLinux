"""Mises à jour depuis les releases GitHub de HelloLinux (Updater.swift).

L'étiquette d'une release est `v<version>`, avec l'archive `Hello-linux-<version>.tar.gz` (`./install.sh release`).
Hello la télécharge, vérifie que c'est bien lui, la décompresse dans ~/.local/share/hello/app/<version> et lance
son install.sh, qui remplace le lanceur et relance Hello en arrière-plan. Par défaut, tout se fait seul : Hello
vérifie toutes les 6 heures et installe dès que le panneau est fermé et que l'IA ne travaille pas."""
import json
import os
import re
import shutil
import tarfile
import tempfile
import threading
import time
import urllib.request

from gi.repository import GLib

from . import __version__, desktop
from .settings import DATA_DIR, settings

REPO = "matthieuleconte1/HelloLinux"
APP_DIR = os.path.join(DATA_DIR, "app")
# Laissé par la version qui s'installe, lu au démarrage de la nouvelle : elle prévient qu'elle est arrivée.
MARKER = os.path.join(DATA_DIR, "updated.json")
CHECK_EVERY = 6 * 3600
RETRY = 10 * 60


def asset_name(version):
    return f"Hello-linux-{version}.tar.gz"


def compare(a, b):
    """Comparaison façon semver : 2.0.0 > 2.0.0-alpha.2 > 2.0.0-alpha.1 > 1.9."""
    def split(v):
        # Étiquette vide ou réduite à un suffixe (« v », « -beta ») : pas de numéro, pas de plantage.
        head, _, pre = v.partition("-")
        numbers = [int(x) if x.isdigit() else 0 for x in head.split(".")] if head else []
        return numbers, (pre.split(".") if pre else [])

    (na, pa), (nb, pb) = split(a), split(b)
    for i in range(max(len(na), len(nb))):
        x = na[i] if i < len(na) else 0
        y = nb[i] if i < len(nb) else 0
        if x != y:
            return -1 if x < y else 1
    # Sans suffixe, c'est la version finale : elle passe devant ses préversions.
    if not pa or not pb:
        return 0 if bool(pa) == bool(pb) else (1 if not pa else -1)
    for i in range(max(len(pa), len(pb))):
        if i >= len(pa):
            return -1
        if i >= len(pb):
            return 1
        if pa[i] == pb[i]:
            continue
        if pa[i].isdigit() and pb[i].isdigit():
            return -1 if int(pa[i]) < int(pb[i]) else 1
        return -1 if pa[i] < pb[i] else 1
    return 0


def newest(releases, prereleases):
    """Release publiée la plus récente (préversions comprises si demandé) qui contient la version Linux."""
    for release in releases if isinstance(releases, list) else []:
        if not isinstance(release, dict) or release.get("draft") or (release.get("prerelease") and not prereleases):
            continue
        tag, page = release.get("tag_name"), release.get("html_url")
        if not tag or not page:
            continue
        version = tag[1:] if tag.startswith("v") else tag
        url = next((a.get("browser_download_url") for a in release.get("assets") or []
                    if isinstance(a, dict) and a.get("name") == asset_name(version)), None)
        if url:
            return {"version": version, "notes": release.get("body") or "", "asset": url, "page": page}
    return None


class Updater:
    """state : idle | checking | up_to_date | available | downloading | installing | failed."""
    state = "idle"
    progress = 0.0
    error = ""
    pending = None
    on_change = None
    # Installation automatique possible maintenant ? (panneau fermé, IA au repos ; renseigné par l'app)
    ready = None
    _last_check = 0
    _waiting = False

    @classmethod
    def _set(cls, state, error=""):
        changed = state != cls.state or error != cls.error
        cls.state, cls.error = state, error
        if changed and cls.on_change:
            cls.on_change()

    @classmethod
    def busy(cls):
        return cls.state in ("checking", "downloading", "installing")

    @classmethod
    def check_if_due(cls):
        """Vérification automatique : au lancement puis toutes les 6 heures (minuteur de l'app et ouverture du
        panneau)."""
        if not settings.autoUpdateCheck or time.time() - cls._last_check < CHECK_EVERY:
            return
        if cls.busy() or cls.state == "available":
            return
        cls.check()

    @classmethod
    def check(cls):
        cls._last_check = time.time()
        cls._set("checking")
        prereleases = settings.updatePrereleases

        def work():
            request = urllib.request.Request(f"https://api.github.com/repos/{REPO}/releases?per_page=15",
                                             headers={"Accept": "application/vnd.github+json",
                                                      "User-Agent": f"Hello/{__version__}"})
            try:
                with urllib.request.urlopen(request, timeout=20) as response:
                    release = newest(json.loads(response.read()), prereleases)
                error = None
            except (OSError, ValueError) as e:
                release, error = None, getattr(e, "reason", None) or str(e)

            def done():
                if error:
                    cls._set("failed", str(error))
                elif release and compare(release["version"], __version__) > 0:
                    cls.pending = release
                    cls._set("available")
                    cls._install_when_ready()
                else:
                    cls._set("up_to_date")
                return False
            GLib.idle_add(done)

        threading.Thread(target=work, daemon=True).start()

    @classmethod
    def _install_when_ready(cls):
        """Installation automatique : tout de suite si Hello est au repos, sinon un peu plus tard."""
        if not settings.autoUpdateInstall or cls._waiting or cls.state != "available":
            return
        if cls.ready is None or cls.ready():
            cls.install()
            return
        cls._waiting = True

        def again():
            cls._waiting = False
            cls._install_when_ready()
            return False
        GLib.timeout_add_seconds(RETRY, again)

    @classmethod
    def install(cls):
        """Télécharge la release, vérifie que c'est bien Hello, l'installe puis relance Hello."""
        release = cls.pending
        if cls.busy() or not release:
            return
        cls.progress = 0.0
        cls._set("downloading")

        def report(value):
            cls.progress = value
            if cls.on_change:
                cls.on_change()
            return False

        def work():
            work_dir = tempfile.mkdtemp(prefix="hello-update-")
            archive = os.path.join(work_dir, asset_name(release["version"]))
            try:
                request = urllib.request.Request(release["asset"], headers={"User-Agent": f"Hello/{__version__}"})
                with urllib.request.urlopen(request, timeout=30) as response, open(archive, "wb") as out:
                    total = int(response.headers.get("Content-Length") or 0)
                    done, last = 0, 0.0
                    while chunk := response.read(65536):
                        out.write(chunk)
                        done += len(chunk)
                        if total and time.time() - last > 0.2:
                            last = time.time()
                            GLib.idle_add(report, done / total)
                GLib.idle_add(lambda: (cls._set("installing"), False)[1])
                folder = stage(archive, work_dir, release["version"])
            except (OSError, ValueError, tarfile.TarError) as e:
                shutil.rmtree(work_dir, ignore_errors=True)
                message = getattr(e, "message", None) or getattr(e, "reason", None) or str(e)
                GLib.idle_add(lambda: (cls._set("failed", str(message)), False)[1])
                return
            shutil.rmtree(work_dir, ignore_errors=True)
            GLib.idle_add(lambda: (swap(folder, release) or cls._set("failed", "Impossible de lancer l'installation."),
                                   False)[1])

        threading.Thread(target=work, daemon=True).start()


class UpdateError(ValueError):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


def stage(archive, work_dir, version):
    """Décompresse l'archive et vérifie son contenu : un dossier Hello pour Linux, à la version attendue.
    Renvoie le dossier installé dans ~/.local/share/hello/app/<version>."""
    out = os.path.join(work_dir, "staged")
    os.makedirs(out)
    with tarfile.open(archive) as tar:
        tar.extractall(out, filter="data")
    entries = os.listdir(out)
    root = os.path.join(out, entries[0]) if len(entries) == 1 and os.path.isdir(os.path.join(out, entries[0])) else out
    init = os.path.join(root, "hello", "__init__.py")
    try:
        with open(init, encoding="utf-8") as f:
            found = re.search(r'__version__\s*=\s*"([^"]+)"', f.read())
    except OSError:
        found = None
    if not found or not os.path.isfile(os.path.join(root, "install.sh")):
        raise UpdateError("L'archive ne contient pas Hello.")
    if found.group(1) != version:
        raise UpdateError(f"L'archive contient la version {found.group(1)}, pas la {version}.")
    target = os.path.join(APP_DIR, version)
    shutil.rmtree(target, ignore_errors=True)
    os.makedirs(APP_DIR, mode=0o700, exist_ok=True)
    shutil.move(root, target)
    for script in ("install.sh", os.path.join("bin", "hello")):
        path = os.path.join(target, script)
        if os.path.exists(path):
            os.chmod(path, 0o755)
    return target


def swap(folder, release):
    """L'install.sh de la nouvelle version remplace le lanceur, quitte Hello et relance la nouvelle version en
    arrière-plan ; elle préviendra qu'elle est installée (voir arrived)."""
    try:
        with open(MARKER, "w", encoding="utf-8") as f:
            json.dump({"from": __version__, "to": release["version"], "page": release["page"]}, f)
    except OSError:
        pass
    return desktop.spawn(["bash", os.path.join(folder, "install.sh"), "--update"], cwd=folder)


def arrived():
    """Au démarrage : la mise à jour qui vient d'être installée ({from, to, page}), ou None. Lu une seule fois."""
    try:
        with open(MARKER, encoding="utf-8") as f:
            info = json.load(f)
        os.remove(MARKER)
    except (OSError, ValueError):
        return None
    return info if isinstance(info, dict) and info.get("to") == __version__ else None
