"""Désinstallation « propre » (Uninstaller.swift), version Linux :
- l'app elle-même : Flatpak (flatpak uninstall), paquet du système (pacman, apt, dnf… dans le terminal,
  qui demande le mot de passe) ou app locale (.desktop et AppImage dans le dossier personnel, à la corbeille) ;
- ses fichiers dans ~/.config, ~/.local/share, ~/.local/state, ~/.cache et ~/.var/app,
  retrouvés par identifiant et par nom. Tout part à la corbeille (récupérable)."""
import os
import shlex
import shutil
import subprocess

from .fuzzy import fold
from .settings import HOME

PLACES = [
    (os.path.join(HOME, ".config"), "Réglages"),
    (os.path.join(HOME, ".local/share"), "Données"),
    (os.path.join(HOME, ".local/state"), "État"),
    (os.path.join(HOME, ".cache"), "Cache"),
    (os.path.join(HOME, ".var/app"), "Données Flatpak"),
    (os.path.join(HOME, ".config/autostart"), "Lancement au démarrage"),
    (os.path.join(HOME, ".local/share/applications"), "Raccourci de lancement"),
]
# Dossiers partagés par tout le système : jamais proposés en bloc.
PROTECTED = {"applications", "icons", "fonts", "themes", "mime", "trash", "flatpak", "systemd", "autostart",
             "kservices6", "kxmlgui5", "recently-used.xbel", "user-places.xbel", "keyrings", "gnupg"}


class Leftover:
    __slots__ = ("path", "kind")

    def __init__(self, path, kind):
        self.path, self.kind = path, kind


def package_owner(path):
    """(gestionnaire, paquet) qui possède le fichier, ou None."""
    checks = [
        ("pacman", ["pacman", "-Qqo", path]),
        ("dpkg", ["dpkg", "-S", path]),
        ("rpm", ["rpm", "-qf", "--qf", "%{NAME}", path]),
    ]
    for manager, argv in checks:
        if not shutil.which(argv[0]):
            continue
        try:
            out = subprocess.run(argv, capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            continue
        if out.returncode == 0 and out.stdout.strip():
            name = out.stdout.strip().split("\n")[0]
            if manager == "dpkg":
                name = name.split(":")[0]
            return manager, name
    return None


def remove_command(manager, package):
    return {
        "pacman": f"sudo pacman -Rns {shlex.quote(package)}",
        "dpkg": f"sudo apt remove {shlex.quote(package)}",
        "rpm": f"sudo dnf remove {shlex.quote(package)}" if shutil.which("dnf")
        else f"sudo zypper remove {shlex.quote(package)}",
    }[manager]


class Plan:
    """Ce qu'il faut faire pour retirer l'app : `files` (à la corbeille) et `command` (gestionnaire de paquets)."""

    def __init__(self, app):
        self.app = app
        self.command = None          # commande à lancer dans le terminal (paquet système)
        self.flatpak = app.flatpak_id
        self.package = None
        self.files = [Leftover(app.path, "Application")]
        if app.is_user_local:
            # App locale : son lanceur, et l'AppImage / l'exécutable s'il est dans le dossier personnel.
            target = shutil.which(app.exec_name) if app.exec_name else None
            executable = app.info.get_executable() or ""
            for candidate in (executable, target):
                if candidate and os.path.isabs(candidate) and candidate.startswith(HOME + "/") \
                        and os.path.isfile(candidate):
                    self.files.append(Leftover(candidate, "Programme"))
                    break
        elif not self.flatpak:
            owner = package_owner(app.path)
            if owner:
                self.package = owner[1]
                self.command = remove_command(*owner)
        self.files += find_leftovers(app)

    @property
    def source(self):
        if self.flatpak:
            return f"Flatpak · {self.flatpak}"
        if self.package:
            return f"Paquet · {self.package}"
        if self.app.is_user_local:
            return "App locale"
        return "Origine inconnue"


def find_leftovers(app):
    stem = app.desktop_id[:-8] if app.desktop_id.endswith(".desktop") else app.desktop_id
    ids = {stem.lower()}
    names = set()
    for name in (app.name, stem.split(".")[-1], app.exec_name):
        folded = fold(name or "")
        for variant in (folded, folded.replace(" ", ""), folded.replace(" ", "-")):
            if len(variant) >= 3:
                names.add(variant)
    seen = {app.path}
    out = []
    for directory, kind in PLACES:
        try:
            entries = os.listdir(directory)
        except OSError:
            continue
        for entry in entries:
            lower = entry.lower()
            if lower in PROTECTED:
                continue
            base = lower
            for ext in (".desktop", ".conf", "rc", ".json", ".ini", ".toml"):
                if base.endswith(ext) and len(base) > len(ext):
                    base = base[: -len(ext)]
                    break
            by_id = any(base == i or base.startswith(i + ".") for i in ids)
            by_name = fold(base) in names
            path = os.path.join(directory, entry)
            if (by_id or by_name) and path not in seen:
                seen.add(path)
                out.append(Leftover(path, kind))
    return out


def size(path):
    try:
        if os.path.islink(path) or os.path.isfile(path):
            return os.lstat(path).st_blocks * 512
    except OSError:
        return 0
    total = 0
    for root, _dirs, files in os.walk(path, onerror=lambda e: None):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_blocks * 512
            except OSError:
                pass
    return total


def format_size(n):
    if n is None:
        return "…"
    for unit in ("octets", "Ko", "Mo", "Go", "To"):
        if n < 1000 or unit == "To":
            return f"{n:.0f} {unit}" if unit == "octets" else f"{n:.1f} {unit}".replace(".", ",")
        n /= 1000
    return ""
