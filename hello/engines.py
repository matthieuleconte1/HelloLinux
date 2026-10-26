"""Fournisseurs d'IA (Engines.swift) : Hermes, Claude Code ou Codex, des outils en ligne de commande déjà
connectés à leur compte. Hello les lance, lit leurs événements et affiche le résultat.

Chaque niveau de l'agent (1 Fast, 2 Recherche & Action, 3 Code) a son fournisseur, son modèle et son
raisonnement (et, pour Hermes, son compte)."""
import json
import os
import re
import shlex
import threading

from gi.repository import GLib

from . import shell
from .settings import HOME, settings

ENGINES = ["hermes", "claude", "codex"]
TITLES = {"hermes": "Hermes", "claude": "Claude Code", "codex": "Codex"}
INSTALL = {
    "hermes": "curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash",
    "claude": "curl -fsSL https://claude.ai/install.sh | bash",
    "codex": "npm install -g @openai/codex",
}
CLAUDE_MODELS = [("opus", "Opus 5.5"), ("sonnet", "Sonnet 5.5"), ("haiku", "Haiku 5.5"), ("fable", "Fable 5.1")]
REASONING = {
    "hermes": ["none", "minimal", "low", "medium", "high", "xhigh"],
    "claude": ["low", "medium", "high", "xhigh", "max"],
    "codex": ["low", "medium", "high", "xhigh", "max"],
}
# Réglage proposé quand on choisit un fournisseur pour un niveau : (compte Hermes, modèle, raisonnement).
DEFAULTS = {
    ("hermes", 1): ("openai-codex", "gpt-6-luna", "low"),
    ("hermes", 2): ("anthropic", "claude-sonnet-5-5", "medium"),
    ("hermes", 3): ("", "", ""),
    ("claude", 1): ("", "haiku", "low"),
    ("claude", 2): ("", "sonnet", "medium"),
    ("claude", 3): ("", "opus", ""),
    ("codex", 1): ("", "gpt-6-luna", "low"),
    ("codex", 2): ("", "gpt-6.1-sol", "medium"),
    ("codex", 3): ("", "", ""),
}
# Clés des réglages de chaque niveau : (fournisseur, compte, modèle, raisonnement).
LEVEL_KEYS = {
    1: ("agentRouterEngine", "agentRouterProvider", "agentRouterModel", "agentRouterReasoning"),
    2: ("agentResearchEngine", "agentResearchProvider", "agentResearchModel", "agentResearchReasoning"),
    3: ("agentDefaultEngine", "agentDefaultProvider", "agentDefaultModel", "agentDefaultReasoning"),
}

# Outils de Hermes au niveau 2. Pas de computer_use : lancé depuis Hello, personne n'est là pour approuver un clic.
HERMES_WORK_TOOLS = "web,file,terminal,vision,browser,memory"


class EngineStatus:
    """Emplacements de `claude` et `codex`, et modèles de Codex (Hermes a son propre état, agent.Hermes)."""
    paths = {}
    codex_models = []
    on_change = None

    @classmethod
    def locate(cls):
        def work():
            places = {
                "claude": [os.path.join(HOME, ".local/bin/claude"), "/usr/bin/claude", "/usr/local/bin/claude",
                           os.path.join(HOME, ".claude/local/claude")],
                "codex": [os.path.join(HOME, ".local/bin/codex"), "/usr/bin/codex", "/usr/local/bin/codex"],
            }
            found = {}
            for engine, candidates in places.items():
                lines = shell.capture_shell(f"command -v {engine}").strip().split("\n")
                found[engine] = next((c for c in [lines[-1]] + candidates
                                      if c.startswith("/") and os.access(c, os.X_OK)), None)
            models = codex_model_list()

            def done():
                cls.paths = {k: v for k, v in found.items() if v}
                cls.codex_models = models
                if cls.on_change:
                    cls.on_change()
                return False
            GLib.idle_add(done)

        threading.Thread(target=work, daemon=True).start()


def codex_model_list():
    """Modèles visibles du cache de Codex (~/.codex/models_cache.json)."""
    try:
        with open(os.path.join(HOME, ".codex", "models_cache.json"), encoding="utf-8") as f:
            cache = json.load(f)
        models = cache.get("models") or []
    except (OSError, ValueError, AttributeError):
        return []
    return [(m["slug"], m.get("display_name") or m["slug"]) for m in models
            if isinstance(m, dict) and m.get("visibility") != "hide" and m.get("slug")]


def binary(engine):
    if engine == "hermes":
        from .agent import Hermes
        return Hermes.binary
    return EngineStatus.paths.get(engine)


def installed(engine):
    return binary(engine) is not None


def models(engine):
    """Modèles proposés : (valeur passée à l'outil, nom affiché)."""
    if engine == "hermes":
        from .agent import Hermes
        return [(m, m) for _, m in Hermes.models]
    if engine == "claude":
        return CLAUDE_MODELS
    return EngineStatus.codex_models


def model_name(engine, model_id):
    return next((name for mid, name in models(engine) if mid == model_id), model_id)


def quote(s):
    return shlex.quote(s)


class LevelConfig:
    """Réglage d'un niveau : fournisseur, compte (Hermes seulement), modèle, raisonnement."""

    def __init__(self, engine, provider, model, reasoning):
        self.engine = engine if engine in ENGINES else "hermes"
        self.provider, self.model, self.reasoning = provider or "", model or "", reasoning or ""

    @classmethod
    def of(cls, level):
        return cls(*(getattr(settings, key) for key in LEVEL_KEYS[level]))

    @property
    def title(self):
        return TITLES[self.engine]

    @property
    def label(self):
        if self.engine == "hermes":
            from .agent import Hermes
            return Hermes.label(self.provider, self.model)
        return (model_name(self.engine, self.model) if self.model else "modèle par défaut") + " · " + self.title

    def model_args(self):
        if self.engine == "hermes":
            from .agent import Hermes
            args = Hermes.model_args(self.provider, self.model)
            return args + (["--reasoning", self.reasoning] if self.reasoning else [])
        if self.engine == "claude":
            return (["--model", self.model] if self.model else []) + (["--effort", self.reasoning] if self.reasoning else [])
        return ((["-m", self.model] if self.model else [])
                + (["-c", f'model_reasoning_effort="{self.reasoning}"'] if self.reasoning else []))

    # Niveau 1 : classement sans aucun outil. Codex répond en JSON (`streams_router`), les autres en texte.
    def router_args(self, prompt):
        if self.engine == "hermes":
            return ["-z", prompt, "-t", "todo"] + self.model_args()
        if self.engine == "claude":
            return ["-p", prompt, "--output-format", "text", "--tools", "", "--no-session-persistence"] + self.model_args()
        return ["exec", prompt, "--json", "--skip-git-repo-check", "--ephemeral", "-s", "read-only"] + self.model_args()

    @property
    def streams_router(self):
        return self.engine == "codex"

    # Niveau 2 : web et actions sur l'ordinateur, en flux d'événements.
    def work_args(self, prompt, context):
        if self.engine == "hermes":
            image = context.first_image
            return (["chat", "-q", prompt, "--format", "stream-json", "--max-turns", "30", "--run-budget", "300",
                     "-t", HERMES_WORK_TOOLS] + (["--image", image.path] if image else []) + self.model_args())
        if self.engine == "claude":
            # Outils permis d'office, rien d'autre (dontAsk refuse ce qui demanderait une confirmation).
            return (["-p", prompt, "--output-format", "stream-json", "--verbose", "--include-partial-messages",
                     "--allowedTools", "Bash,Read,Glob,Grep,WebSearch,WebFetch,TodoWrite",
                     "--disallowedTools", "Bash(rm *),Bash(sudo *),Bash(git push *),Bash(dd *),Bash(mkfs *)",
                     "--permission-mode", "dontAsk"] + self.model_args())
        # Bac à sable : écriture dans le dossier de travail, réseau ouvert ; recherche web native.
        images = [a.path for a in context.attachments if a.is_image]
        return (["--search", "exec", prompt, "--json", "--skip-git-repo-check", "-s", "workspace-write",
                 "-c", "sandbox_workspace_write.network_access=true", "-C", shell.expand(settings.agentWorkdir)]
                + self.model_args() + (["-i"] + images if images else []))

    @property
    def needs_timeout(self):
        """Hermes borne lui-même sa durée ; pour les autres, Hello arrête le processus."""
        return self.engine != "hermes"

    def terminal_command(self, prompt):
        """Niveau 3 : session interactive dans le terminal, amorcée avec le prompt."""
        head = {"hermes": "hermes chat -q", "claude": "claude", "codex": "codex"}[self.engine]
        return " ".join([head, quote(prompt)] + [quote(a) for a in self.model_args()])

    def resume_command(self, session_id):
        if self.engine == "hermes":
            from .agent import Hermes
            return " ".join(["hermes chat --resume", quote(session_id)]
                            + [quote(a) for a in Hermes.model_args(self.provider, self.model)])
        if self.engine == "claude":
            return "claude --resume " + quote(session_id)
        return "codex resume " + quote(session_id)


def set_engine(level, engine):
    """Change le fournisseur du niveau et reprend le réglage proposé pour lui."""
    keys = LEVEL_KEYS[level]
    setattr(settings, keys[0], engine)
    for key, value in zip(keys[1:], DEFAULTS[(engine, level)]):
        setattr(settings, key, value)


def assistant():
    """Nom de l'assistant dans l'interface : celui du fournisseur s'il est le même partout, sinon « l'IA »."""
    engines = {LevelConfig.of(level).engine for level in (1, 2, 3)}
    if len(engines) == 1:
        title = TITLES[engines.pop()]
        return title, title, title
    return "l'IA", "L'IA", "IA"


# MARK: - Événements

class EventParser:
    """Lit le flux JSON d'un fournisseur, ligne par ligne, et le traduit en événements communs :
    (« session », id), (« step », texte), (« text », morceau), (« final », réponse), (« failure », message)."""

    def __init__(self, engine):
        self.engine = engine
        self._last_message = ""
        self._last_error = None

    def feed(self, line):
        try:
            event = json.loads(line)
        except ValueError:
            return []
        if not isinstance(event, dict):
            return []
        return getattr(self, "_" + self.engine)(event)

    @staticmethod
    def _hermes(event):
        out = []
        if event.get("session_id"):
            out.append(("session", event["session_id"]))
        kind = event.get("type")
        if kind == "tool_use":
            out.append(("step", hermes_step(event.get("name") or "", event.get("input"))))
        elif kind == "text":
            out.append(("text", event.get("text") or ""))
        elif kind == "result":
            text = (event.get("text") or "").strip()
            out.append(("final", text) if text else ("failure", event.get("error") or "Aucune réponse."))
        return out

    @staticmethod
    def _claude(event):
        kind = event.get("type")
        if kind == "system":
            if event.get("subtype") == "init" and event.get("session_id"):
                return [("session", event["session_id"])]
        elif kind == "stream_event":
            inner = event.get("event") or {}
            delta = inner.get("delta") or {}
            if inner.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
                return [("text", delta.get("text") or "")]
        elif kind == "assistant":
            content = (event.get("message") or {}).get("content") or []
            return [("step", claude_step(c.get("name") or "", c.get("input")))
                    for c in content if isinstance(c, dict) and c.get("type") == "tool_use"]
        elif kind == "result":
            text = (event.get("result") or "").strip()
            if event.get("is_error") or not text:
                return [("failure", text or "Aucune réponse.")]
            return [("final", text)]
        return []

    def _codex(self, event):
        item = event.get("item") or {}
        kind, item_kind = event.get("type"), item.get("type")
        if kind == "thread.started":
            return [("session", event["thread_id"])] if event.get("thread_id") else []
        if kind == "item.started":
            if item_kind == "command_execution":
                return [("step", "$ " + unwrap_shell(item.get("command") or ""))]
            if item_kind == "web_search":
                return [("step", f"Cherche « {item['query']} »" if item.get("query") else "Cherche sur le web")]
            if item_kind == "file_change":
                return [("step", "Modifie des fichiers")]
            if item_kind == "mcp_tool_call":
                return [("step", item.get("tool") or "Utilise un outil")]
        elif kind == "item.completed" and item_kind == "agent_message":
            text = item.get("text") or ""
            self._last_message = text
            return [("text", text + "\n\n")]
        elif kind == "turn.completed":
            text = self._last_message.strip()
            return [("final", text) if text else ("failure", self._last_error or "Aucune réponse.")]
        elif kind == "turn.failed":
            message = (event.get("error") or {}).get("message")
            return [("failure", message or self._last_error or "Codex a échoué.")]
        elif kind == "error":
            self._last_error = event.get("message")
        return []


def unwrap_shell(command):
    """« /usr/bin/bash -lc "ls && date" » ou « bash -lc date » → la commande elle-même."""
    m = re.match(r"^(?:/\S*/)?\w+ -l?c ", command)
    if not m:
        return command
    inner = command[m.end():]
    if len(inner) >= 2 and inner[0] in "\"'" and inner[-1] == inner[0]:
        inner = inner[1:-1]
    return inner.replace('\\"', '"')


def _text(data, key):
    value = (data or {}).get(key) if isinstance(data, dict) else None
    return value.strip() if isinstance(value, str) else None


def _file(data, key):
    path = _text(data, key)
    return os.path.basename(path) if path else "un fichier"


def hermes_step(name, data):
    """Étape lisible d'après un événement `tool_use` de Hermes."""
    if name == "terminal":
        command = _text(data, "command")
        return "$ " + command.replace("\n", " ⏎ ") if command else "Lance une commande"
    if name == "web_search":
        query = _text(data, "query")
        return f"Cherche « {query} »" if query else "Cherche sur le web"
    labels = {"vision_analyze": "Regarde l'image", "read_file": f"Lit {_file(data, 'path')}",
              "write_file": f"Écrit {_file(data, 'path')}", "patch": f"Écrit {_file(data, 'path')}",
              "search_files": "Cherche des fichiers", "web_extract": "Lit une page web",
              "execute_code": "Exécute du code", "todo_list": "Planifie les étapes"}
    if name in labels:
        return labels[name]
    return "Navigue dans le navigateur" if name.startswith("browser") else name


def claude_step(name, data):
    if name == "Bash":
        command = _text(data, "command")
        return "$ " + command.replace("\n", " ⏎ ") if command else "Lance une commande"
    if name == "WebSearch":
        query = _text(data, "query")
        return f"Cherche « {query} »" if query else "Cherche sur le web"
    if name == "Read":
        return f"Lit {_file(data, 'file_path')}"
    if name in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        return f"Écrit {_file(data, 'file_path')}"
    return {"Glob": "Cherche des fichiers", "Grep": "Cherche des fichiers", "WebFetch": "Lit une page web",
            "TodoWrite": "Planifie les étapes", "Task": "Délègue une sous-tâche",
            "Agent": "Délègue une sous-tâche"}.get(name, name)
