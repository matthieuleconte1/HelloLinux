"""Tout ce qui touche au « mode terminal » : chemins, complétion, exécution dans un PTY,
historique, dossiers fréquents, git, processus, ports, réseau. (Shell.swift, Terminal.swift)"""
import json
import os
import pty
import shutil
import signal
import struct
import subprocess
import termios
import fcntl
import threading
import time

from gi.repository import GLib

from . import usage
from .desktop import user_shell
from .fuzzy import fold, score
from .settings import DATA_DIR, HOME, load_json, save_json, settings
from .term import TerminalBuffer

BUILTINS = {"cd", "echo", "export", "source", "alias", "which", "type", "print", "eval", "exec",
            "kill", "time", "for", "while", "if", "pushd", "popd", "history", "unset", "set"}
OPERATORS = ["&&", "||", ";", "|", ">", "<", "`", "$("]

_path_dirs = os.environ.get("PATH", "/usr/bin:/bin").split(":") + [os.path.join(HOME, ".local/bin")]
_command_cache = {}


def load_user_path():
    """Récupère le PATH du shell de connexion une seule fois au lancement."""
    def work():
        try:
            out = subprocess.run([user_shell(), "-l", "-c", 'printf "%s" "$PATH"'], capture_output=True,
                                 text=True, timeout=5).stdout
        except (OSError, subprocess.SubprocessError):
            return
        line = out.strip().split("\n")[-1]
        if "/" in line:
            def apply():
                global _path_dirs
                _path_dirs = line.split(":")
                _command_cache.clear()
            GLib.idle_add(apply)
    threading.Thread(target=work, daemon=True).start()


def user_path():
    return ":".join(_path_dirs)


def split_first(s):
    if " " not in s:
        return s, ""
    word, rest = s.split(" ", 1)
    return word, rest.strip()


def has_operators(s):
    return any(op in s for op in OPERATORS)


def is_command(word):
    if not word:
        return False
    if word in BUILTINS:
        return True
    if word in _command_cache:
        return _command_cache[word]
    if "/" in word:
        found = os.access(expand(word), os.X_OK) and os.path.isfile(expand(word))
    else:
        found = any(os.access(os.path.join(d, word), os.X_OK) for d in _path_dirs if d)
    _command_cache[word] = found
    return found


def expand(raw):
    """`./code`, `code`, `~/code` → /home/…/code (le dossier courant est le dossier personnel)."""
    s = raw.strip()
    if len(s) >= 2 and s[0] in "\"'" and s[-1] == s[0]:
        s = s[1:-1]
    s = s.replace("\\ ", " ")
    if not s or s == "~":
        return HOME
    if s.startswith("~/"):
        s = HOME + s[1:]
    elif not s.startswith("/"):
        s = os.path.join(HOME, s)
    return os.path.normpath(s)


def abbreviate(path):
    if path == HOME:
        return "~"
    if path.startswith(HOME + "/"):
        return "~" + path[len(HOME):]
    return path


def is_folder(path):
    return os.path.isdir(path)


def completions(raw, folders_only, limit=8):
    """Complétion façon Tab : liste les entrées du dossier parent qui correspondent."""
    trimmed = raw.strip()
    full = expand(trimmed)
    listing = not trimmed or trimmed == "~" or trimmed.endswith("/")
    directory = full if listing else os.path.dirname(full)
    partial = "" if listing else fold(os.path.basename(full))
    try:
        names = os.listdir(directory)
    except OSError:
        return []
    matches = []
    for name in names:
        if name.startswith(".") and not partial.startswith("."):
            continue
        folded = fold(name)
        if not partial:
            rank = 0
        elif folded.startswith(partial):
            rank = 2
        elif partial in folded:
            rank = 1
        else:
            continue
        path = os.path.join(directory, name)
        if folders_only and not is_folder(path):
            continue
        matches.append((-rank, folded, path))
    matches.sort()
    return [m[2] for m in matches[:limit]]


def capture(argv, timeout=5):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def capture_shell(command):
    """Sortie d'une commande passée par le shell de connexion (PATH utilisateur)."""
    return capture([user_shell(), "-l", "-c", command])


# MARK: - Exécution dans un PTY

class ShellRun:
    """Commande exécutée dans le shell, dans un pseudo-terminal : les outils se croient dans un vrai
    terminal et gardent leurs couleurs, affichées en direct dans Hello."""
    MAX_OUTPUT = 2_000_000

    def __init__(self, command, columns=100):
        self.command = command
        self.columns = columns
        self.buffer = TerminalBuffer()
        self.running = False
        self.status = None
        self.started_at = time.time()
        self.finished_at = None
        self.on_update = None
        self.on_finish = None
        self._pid = None
        self._fd = None
        self._received = 0
        self._render_scheduled = False
        self._decoder = None

    @property
    def output(self):
        return self.buffer.plain_text

    @property
    def elapsed(self):
        seconds = (self.finished_at or time.time()) - self.started_at
        if seconds < 60:
            return f"{seconds:.1f} s".replace(".", ",")
        return f"{int(seconds) // 60} min {int(seconds) % 60:02d} s"

    def start(self):
        import codecs
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        sh = user_shell()
        args = [sh, "-l", "-i", "-c", self.command] if settings.shellInteractive else [sh, "-l", "-c", self.command]
        env = dict(os.environ)
        env.pop("NO_COLOR", None)
        env.update(TERM="xterm-256color", COLORTERM="truecolor", CLICOLOR="1", FORCE_COLOR="1",
                   COLUMNS=str(self.columns), PAGER="cat", GIT_PAGER="cat", PATH=user_path())
        try:
            pid, fd = pty.fork()
        except OSError as e:
            self.buffer.feed(str(e))
            self.status = -1
            return
        if pid == 0:  # enfant
            try:
                os.chdir(HOME)
                os.execvpe(args[0], args, env)
            finally:
                os._exit(127)
        self._pid, self._fd = pid, fd
        try:
            fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, self.columns, 0, 0))
        except OSError:
            pass
        self.running = True
        self.started_at = time.time()
        GLib.io_add_watch(fd, GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, self._readable)

    def _readable(self, fd, condition):
        try:
            data = os.read(fd, 65536)
        except OSError:
            data = b""
        if data:
            if self._received < self.MAX_OUTPUT:
                self._received += len(data)
                # Caractère UTF-8 coupé entre deux lectures : gardé par le décodeur pour la suivante.
                self.buffer.feed(self._decoder.decode(data))
                self._schedule_render()
            return True
        self.buffer.feed(self._decoder.decode(b"", final=True))
        try:
            os.close(fd)
        except OSError:
            pass
        GLib.child_watch_add(GLib.PRIORITY_DEFAULT, self._pid, self._exited)
        return False

    def _exited(self, pid, status):
        self.running = False
        self.finished_at = time.time()
        try:
            self.status = os.waitstatus_to_exitcode(status)
        except ValueError:
            self.status = status
        if self.on_update:
            self.on_update()
        if self.on_finish:
            self.on_finish(self.status)

    def _schedule_render(self):
        # Rendu regroupé (~20 fois par seconde au plus) pour rester léger sur les grosses sorties.
        if self._render_scheduled:
            return
        self._render_scheduled = True

        def render():
            self._render_scheduled = False
            if self.on_update:
                self.on_update()
            return False

        GLib.timeout_add(50, render)

    def cancel(self):
        if not self.running or not self._pid:
            return
        try:
            os.killpg(os.getpgid(self._pid), signal.SIGINT)
        except OSError:
            pass

        def force():
            if self.running:
                try:
                    os.killpg(os.getpgid(self._pid), signal.SIGTERM)
                except OSError:
                    pass
            return False

        GLib.timeout_add(800, force)


# MARK: - Historique des commandes

class ShellHistory:
    """Commandes lancées depuis Hello + historique du shell (~/.zsh_history ou ~/.bash_history)."""
    _path = os.path.join(DATA_DIR, "shell_history.json")
    own = load_json(_path, [])
    _shell = None

    @classmethod
    def record(cls, command):
        cls.own = [command] + [c for c in cls.own if c != command][:299]
        save_json(cls._path, cls.own, private=True)

    @classmethod
    def clear(cls):
        cls.own = []
        save_json(cls._path, cls.own, private=True)

    @classmethod
    def search(cls, query, limit):
        q = fold(query.strip())
        seen = set()
        out = []
        for command, folded in [(c, None) for c in cls.own] + cls._shell_history():
            if command in seen:
                continue
            if q and q not in (folded if folded is not None else fold(command)):
                continue
            seen.add(command)
            out.append(command)
            if len(out) >= limit:
                break
        return out

    @classmethod
    def _shell_history(cls):
        """Lu (et normalisé pour la recherche) une seule fois, à la première utilisation."""
        if not settings.shellHistory:
            return []
        if cls._shell is not None:
            return cls._shell
        lines = []
        for name in (".zsh_history", ".bash_history"):
            try:
                with open(os.path.join(HOME, name), "rb") as f:
                    lines += f.read().decode("utf-8", "replace").split("\n")[-4000:]
            except OSError:
                pass
        seen = set()
        result = []
        for line in reversed(lines):
            command = line
            if command.startswith(": ") and ";" in command:
                command = command.split(";", 1)[1]
            command = command.strip()
            if len(command) <= 1 or command.endswith("\\") or command in seen:
                continue
            seen.add(command)
            result.append((command, fold(command)))
            if len(result) >= 1500:
                break
        cls._shell = result
        return result


# MARK: - Dossiers fréquents (à la zoxide)

class FolderJump:
    _zoxide = None
    _loading = False
    on_loaded = None

    @classmethod
    def candidates(cls, query, limit):
        """Dossiers déjà ouverts via Hello (et ceux de zoxide s'il est installé) dont le nom correspond."""
        q = fold(query.strip())
        if not q:
            return []
        scored = {}
        for item_id in list(usage.records):
            if not item_id.startswith("path:"):
                continue
            path = item_id[5:]
            s = score(q, fold(os.path.basename(path)))
            if s is not None:
                scored[path] = max(scored.get(path, 0), s + usage.boost(item_id, q))
        for path, z in cls._zoxide_entries():
            s = score(q, fold(os.path.basename(path)))
            if s is not None:
                scored[path] = max(scored.get(path, 0), s + min(200, int(z * 2)))
        ordered = sorted(scored, key=lambda p: -scored[p])
        return [p for p in ordered if is_folder(p)][:limit]

    @classmethod
    def _zoxide_entries(cls):
        if cls._zoxide is not None:
            return cls._zoxide
        if cls._loading or not settings.useZoxide or not shutil.which("zoxide"):
            return []
        cls._loading = True

        def work():
            entries = []
            for line in capture(["zoxide", "query", "--list", "--score"]).split("\n"):
                parts = line.strip().split(" ", 1)
                if len(parts) == 2:
                    try:
                        entries.append((parts[1], float(parts[0])))
                    except ValueError:
                        pass

            def done():
                cls._zoxide = entries
                if cls.on_loaded:
                    cls.on_loaded()
            GLib.idle_add(done)

        threading.Thread(target=work, daemon=True).start()
        return []


# MARK: - Git

def git_branch(path):
    """Branche courante en lisant .git/HEAD (aucun processus lancé)."""
    git_dir = os.path.join(path, ".git")
    if not os.path.exists(git_dir):
        return None
    if os.path.isfile(git_dir):
        try:
            with open(git_dir) as f:
                content = f.read()
        except OSError:
            return None
        if "gitdir: " not in content:
            return None
        git_dir = content.split("gitdir: ", 1)[1].strip()
        if not git_dir.startswith("/"):
            git_dir = os.path.join(path, git_dir)
    try:
        with open(os.path.join(git_dir, "HEAD")) as f:
            head = f.read().strip()
    except OSError:
        return None
    if head.startswith("ref: refs/heads/"):
        return head[16:]
    return head[:7]


# MARK: - Processus et ports

class Processes:
    _cache = None

    @classmethod
    def list(cls):
        """Processus de l'utilisateur (/proc). Mis en cache 3 s."""
        if cls._cache and time.time() - cls._cache[0] < 3:
            return cls._cache[1]
        me = os.getpid()
        uid = os.getuid()
        out = []
        for name in os.listdir("/proc"):
            if not name.isdigit() or int(name) == me:
                continue
            try:
                if os.stat(f"/proc/{name}").st_uid != uid:
                    continue
                with open(f"/proc/{name}/comm") as f:
                    comm = f.read().strip()
            except OSError:
                continue
            try:
                path = os.readlink(f"/proc/{name}/exe")
            except OSError:
                path = comm
            out.append({"pid": int(name), "name": comm, "path": path})
        cls._cache = (time.time(), out)
        return out

    @classmethod
    def search(cls, query):
        q = fold(query)
        found = [p for p in cls.list() if not q or q in fold(p["name"])]
        found.sort(key=lambda p: (len(p["name"]), p["name"]))
        return found[:20]

    @classmethod
    def kill(cls, pid, force):
        cls._cache = None
        try:
            os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)
            return True
        except OSError:
            return False


class Ports:
    _cache = None
    _loading = False
    on_loaded = None

    @classmethod
    def listening(cls):
        """Ports TCP en écoute (ss, en arrière-plan). None pendant le premier chargement."""
        if cls._cache and time.time() - cls._cache[0] < 4:
            return cls._cache[1]
        if not cls._loading:
            cls._loading = True
            threading.Thread(target=cls._load, daemon=True).start()
        return cls._cache[1] if cls._cache else None

    @classmethod
    def _load(cls):
        import re
        entries = []
        seen = set()
        for line in capture(["ss", "-ltnpH"]).split("\n"):
            parts = line.split()
            if len(parts) < 4:
                continue
            local = parts[3]
            address, _, port = local.rpartition(":")
            if not port.isdigit():
                continue
            m = re.search(r'\("([^"]+)",pid=(\d+)', line)
            command, pid = (m.group(1), int(m.group(2))) if m else ("?", 0)
            key = (pid, int(port))
            if key in seen:
                continue
            seen.add(key)
            entries.append({"port": int(port), "pid": pid, "command": command, "address": address.strip("[]")})
        entries.sort(key=lambda e: e["port"])

        def done():
            cls._cache = (time.time(), entries)
            cls._loading = False
            if cls.on_loaded:
                cls.on_loaded()
        GLib.idle_add(done)

    @classmethod
    def invalidate(cls):
        cls._cache = None


def addresses():
    """Adresses IPv4 locales (hors boucle locale)."""
    try:
        data = json.loads(capture(["ip", "-j", "-4", "addr"]) or "[]")
    except ValueError:
        return []
    out = []
    for iface in data:
        if "LOOPBACK" in iface.get("flags", []) or "UP" not in iface.get("flags", []):
            continue
        for addr in iface.get("addr_info", []):
            out.append((iface.get("ifname", "?"), addr.get("local", "")))
    return out
