"""L'agent (Agent.swift) : trois niveaux, chacun confié à Hermes, Claude Code ou Codex.

Niveau 1 · Fast : un modèle rapide répond seul ou choisit le niveau (Auto). Niveau 2 · Recherche & Action :
web et actions sur l'ordinateur, réponse en direct dans Hello. Niveau 3 · Code : session interactive dans le
terminal. Fermer Hello n'arrête pas une demande : une notification prévient quand elle se termine."""
import json
import os
import re
import subprocess
import threading
import time

from gi.repository import GLib

from . import desktop, engines, shell
from .chats import ChatStore, Conversation, new_turn
from .context import Attachment, Context
from .engines import LevelConfig
from .settings import HOME, settings

PROVIDER_ORDER = ["openai-codex", "anthropic", "copilot", "nous", "openrouter"]
QUICK_PREFERENCES = ["gpt-6-luna", "claude-haiku-4-5-20251001", "gpt-5.4-mini", "claude-haiku-4.5", "gpt-5-mini"]
RESEARCH_PREFERENCES = ["claude-sonnet-5-5", "gpt-6.1-sol", "claude-sonnet-5", "gpt-5.4"]


class Hermes:
    """Hermes Agent (Nous Research) : emplacement, comptes connectés et modèles connus."""
    binary = None
    providers = []
    models = []      # (compte, modèle)
    checking = False
    on_change = None

    @classmethod
    def available(cls):
        """L'agent est utilisable dès qu'un des fournisseurs (Hermes, Claude Code, Codex) est installé."""
        return settings.agentEnabled and any(engines.installed(e) for e in engines.ENGINES)

    @classmethod
    def locate(cls):
        """Localise `hermes` et lit ses comptes. Au lancement, puis à la demande (réglages)."""
        if cls.checking:
            return
        cls.checking = True

        def work():
            from_shell = shell.capture_shell("command -v hermes").strip().split("\n")[-1]
            candidates = [from_shell, os.path.join(HOME, ".local/bin/hermes"), "/usr/local/bin/hermes",
                          "/usr/bin/hermes"]
            path = next((c for c in candidates if c.startswith("/") and os.access(c, os.X_OK)), None)
            providers, models = cls._load_accounts()

            def done():
                cls.binary = path
                cls.providers = providers if path else []
                cls.models = models if path else []
                cls.checking = False
                cls.adapt_models()
                if cls.on_change:
                    cls.on_change()
            GLib.idle_add(done)

        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def provider_name(pid):
        return {"openai-codex": "OpenAI (ChatGPT)", "anthropic": "Anthropic", "copilot": "GitHub Copilot",
                "nous": "Nous", "openrouter": "OpenRouter"}.get(pid, pid)

    @classmethod
    def _load_accounts(cls):
        """Comptes connectés (auth.json + provider du config.yaml) et modèles connus (cache de `hermes model`)."""
        home = os.path.join(HOME, ".hermes")
        providers = []
        try:
            with open(os.path.join(home, "auth.json")) as f:
                auth = json.load(f)
            for key in ("providers", "credential_pool"):
                for name in (auth.get(key) or {}):
                    if name not in providers:
                        providers.append(name)
        except (OSError, ValueError, AttributeError):
            pass
        configured = cls._configured_provider(os.path.join(home, "config.yaml"))
        if configured and configured not in providers:
            providers.append(configured)
        providers.sort(key=lambda p: PROVIDER_ORDER.index(p) if p in PROVIDER_ORDER else 99)
        models = []
        try:
            with open(os.path.join(home, "provider_models_cache.json")) as f:
                cache = json.load(f)
            for p in providers:
                for m in (cache.get(p) or {}).get("models", []):
                    models.append((p, m))
        except (OSError, ValueError, AttributeError):
            pass
        return providers, models

    @staticmethod
    def _configured_provider(path):
        """`provider:` de la section `model:` du config.yaml (clé API ou provider local, absent d'auth.json)."""
        try:
            with open(path) as f:
                lines = f.read().split("\n")
        except OSError:
            return None
        in_model = False
        for line in lines:
            if not line.startswith((" ", "\t")):
                in_model = line.startswith("model:")
            trimmed = line.strip()
            if in_model and trimmed.startswith("provider:"):
                value = trimmed[len("provider:"):].strip(" \"'")
                return value or None
        return None

    @classmethod
    def adapt_models(cls):
        """Les réglages par défaut visent ChatGPT (Luna) et Anthropic (Sonnet). Si le compte correspondant n'est
        pas connecté, on bascule sur un modèle d'un compte qui l'est, sinon sur le modèle par défaut de Hermes.
        Seuls les niveaux confiés à Hermes utilisent ses comptes."""
        if not cls.providers:
            return

        def pick(preferences):
            for name in preferences:
                for p, m in cls.models:
                    if m == name:
                        return p, m
            return "", ""

        s = settings
        hermes = {level for level in (1, 2, 3) if LevelConfig.of(level).engine == "hermes"}
        if 1 in hermes and s.agentRouterModel and s.agentRouterProvider not in cls.providers:
            s.agentRouterProvider, s.agentRouterModel = pick(QUICK_PREFERENCES)
        if 2 in hermes and s.agentResearchModel and s.agentResearchProvider not in cls.providers:
            s.agentResearchProvider, s.agentResearchModel = pick(RESEARCH_PREFERENCES)
        if 3 in hermes and s.agentDefaultProvider and s.agentDefaultProvider not in cls.providers:
            s.agentDefaultProvider, s.agentDefaultModel = "", ""

    @classmethod
    def label(cls, provider, model):
        if not model:
            return "modèle par défaut de Hermes"
        return model if not provider else f"{model} ({cls.provider_name(provider)})"

    @staticmethod
    def model_args(provider, model):
        args = []
        if model:
            args += ["-m", model]
        if provider:
            args += ["--provider", provider]
        return args


def router_prompt(request, context):
    """Phase 1 : classement sans outils (rapide, ne peut rien faire lui-même)."""
    if settings.agentStrategy == "delegate":
        forms = ("Reply exactly: CODE: <rewritten, precise, self-contained prompt for a coding agent, in the user's "
                 "language, with useful context: paths, constraints, expected result>")
    else:
        forms = (
            "Decide the level of effort needed and reply with exactly one of these forms and nothing else:\n"
            "ANSWER: <short answer in the user's language> — level 1, fast: a short answer you are sure of is enough "
            "(fact, definition, conversion, which command to use).\n"
            "WORK: <the request rewritten as a precise, self-contained instruction in the user's language> — level 2, "
            "research and action: needs up-to-date information, web search, comparing sources or a thoughtful "
            "explanation, or any action on this computer (open, launch or control apps, change a setting, find, open "
            "or organize files, look at the screen or the attachments).\n"
            "CODE: <rewritten, precise, self-contained prompt for a coding agent, in the user's language, with useful "
            "context: paths, constraints, expected result> — level 3: writing or fixing code, building an app or a "
            "script, long multi-step work in a project.")
    desktop_name = os.environ.get("XDG_CURRENT_DESKTOP", "") or "Linux"
    return (f"You are the fast router of Hello, a launcher on the user's Linux computer ({desktop_name}). "
            "Classify the user's request. You have no tools and must not try to do the task.\n"
            f"{forms}\n\n{context.router_note}\n\nUser request: {request}")


def work_prompt(instruction, context):
    """Niveau 2 : recherche et actions sur l'ordinateur, bornées en tours et en durée."""
    kde = "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "")
    settings_tools = ("`kwriteconfig6` / `kreadconfig6`, `plasma-apply-colorscheme`, `qdbus6` (KWin, Plasma, Dolphin)"
                      if kde else "`gsettings`, `gdbus call`")
    screenshot = ("`spectacle -b -n -f -o /tmp/hello-screen.png`" if kde
                  else "`grim /tmp/hello-screen.png` (or `gnome-screenshot -f /tmp/hello-screen.png`)")
    return f"""{instruction}

{context.block}

You can both research and act.
For a question: research it carefully (use the web when useful) and answer in the user's language, structured \
and concise, with short sections or bullet points when it helps, and cite sources as markdown links.
For an action: do it now on this Linux computer, with as few tool calls as possible. Ways to act, in order of preference:
1. Shell: `xdg-open` (files, folders, URLs), `gtk-launch <app>.desktop` to start an app, `fd` / `find` / `locate` \
to find files, `wl-copy` / `wl-paste`, `notify-send`, `playerctl` (media), `wpctl` / `pactl` (volume), `nmcli`, \
`brightnessctl`, `systemctl --user`.
2. Desktop settings and apps over D-Bus: {settings_tools}.
3. To see the screen: {screenshot}, then vision_analyze.
Never do anything destructive or irreversible (deleting or overwriting data, emptying the trash, sending messages \
or emails, payments, purchases, pushing code, changing passwords or security settings, sudo): prepare it (draft, \
open the right page or window) and leave the last step to the user.
When you performed an action, finish with one line: DONE: <short summary in the user's language>"""


LEVELS = {
    # niveau : (titre, icône, teinte)
    1: ("Fast", "hello-fast-symbolic", "#F5C211"),
    2: ("Recherche & Action", "hello-level-work-symbolic", "#33C7DE"),
    3: ("Code", "hello-code-symbolic", "#C061CB"),
}


def level_detail(level):
    if level == 1:
        return "Auto : répond ou choisit le niveau"
    if level == 2:
        return "Cherche sur le web, agit sur l'ordinateur, répond ici"
    return f"Session de code dans {desktop.terminal()[1]}"


def level_model_label(level):
    return LevelConfig.of(level).label


class AgentRun:
    """phase : thinking | streaming | done | answer | delegated | failed ; `text` porte le contenu."""

    def __init__(self, request, level, attachments=(), conversation=None):
        self.request = request
        self.level = level
        self.engine = LevelConfig.of(level).engine
        self.conversation = conversation or Conversation()
        self.earlier = list(self.conversation.turns)
        self.context = Context(attachments, self.conversation.transcript)
        self.phase = "thinking"
        self.text = ""
        self.stage = "analyse ta demande"
        self.details = ""
        self.steps = []
        self.session_id = None
        self.started_at = time.time()
        self.on_change = None
        self.on_finish = None
        self._finished = False
        self._recorded = False
        self._process = None
        self._timed_out = False

    @classmethod
    def restoring(cls, conversation):
        """Conversation rouverte depuis l'historique : son dernier échange, déjà terminé."""
        last = conversation.turns[-1] if conversation.turns else {}
        run = cls.__new__(cls)
        files = [p for p in last.get("attachments") or [] if os.path.exists(p)]
        run.request = last.get("request") or ""
        run.level = last.get("level") if last.get("level") in LEVELS else 1
        run.engine = last.get("engine") if last.get("engine") in engines.ENGINES else "hermes"
        run.conversation = conversation
        run.earlier = conversation.turns[:-1]
        run.context = Context([Attachment(p) for p in files])
        run.phase = {"done": "done", "code": "delegated"}.get(last.get("kind"), "answer")
        run.text = last.get("answer") or ""
        run.stage, run.details = "", ""
        run.steps = list(last.get("steps") or [])
        run.session_id = last.get("sessionID")
        run.started_at = last.get("date") or time.time()
        run.on_change = run.on_finish = None
        run._finished = run._recorded = True
        run._process = None
        run._timed_out = False
        return run

    @property
    def attachments(self):
        return self.context.attachments

    @property
    def is_thinking(self):
        return self.phase in ("thinking", "streaming")

    @property
    def model_label(self):
        return level_model_label(self.level)

    def _set(self, phase, text=""):
        self.phase, self.text = phase, text
        if not self.is_thinking:
            self._record()
            if not self._finished:
                self._finished = True
                if self.on_finish:
                    self.on_finish(self)
        self._changed()

    def _changed(self):
        if self.on_change:
            self.on_change()

    def _record(self):
        """Ajoute l'échange terminé à la conversation, et à l'historique s'il est activé. Les échecs ne sont pas gardés."""
        kind = {"answer": "answer", "done": "done", "delegated": "code"}.get(self.phase)
        if self._recorded or not kind:
            return
        self._recorded = True
        self.conversation.turns.append(new_turn(self.level, self.request, self.text, kind, self.steps,
                                                [a.path for a in self.attachments], self.session_id, self.engine))
        if settings.agentHistory:
            ChatStore.save(self.conversation)

    def _config(self, level):
        """Le fournisseur du niveau, s'il est installé ; sinon la demande échoue avec un message clair."""
        config = LevelConfig.of(level)
        if not engines.installed(config.engine):
            self._set("failed", f"{config.title} n'est pas installé. Choisis un autre fournisseur dans Réglages › Agent, "
                                f"ou installe-le : {engines.INSTALL[config.engine]}")
            return None
        self.engine = config.engine
        return config

    def start(self):
        self.started_at = time.time()
        if self.level == 3:
            self.send(self.request)
        elif self.level == 2:
            self.work(self.request)
        else:
            self.stage = "choisit le niveau"
            self.work(self.request) if settings.agentStrategy == "act" else self._classify()

    # Niveau 1 — Fast / Auto

    def _classify(self):
        config = self._config(1)
        if not config:
            return
        args = config.router_args(router_prompt(self.request, self.context))
        if config.streams_router:
            self._stream(args, show_text=False, budget=90, finish=self._route)
        else:
            self._launch(args, budget=90 if config.needs_timeout else None, then=self._route)

    def _route(self, text):
        """Le routeur a choisi : niveau 1 (il répond), 2 (recherche & action) ou 3 (code dans le terminal)."""
        found = [(text.find(tag), tag) for tag in ("ANSWER:", "WORK:", "CODE:") if tag in text]
        if not found:
            return self._set("answer", text)
        i, tag = min(found)
        # Le modèle recopie parfois la fin de la consigne : « 51 — level 1, fast ».
        content = re.sub(r"\s*[—–-]\s*level\s*\d(?:\s*[,:][^\n]{0,40})?\s*$", "", text[i + len(tag):],
                         flags=re.I).strip()
        if tag == "WORK:":
            self.work(content)
        elif tag == "CODE:":
            self.level = 3
            self.send(content)
        else:
            self._set("answer", content)

    # Niveau 2 — Recherche & Action (réponse en direct dans Hello)

    def work(self, prompt):
        self.stage = "s'en occupe"
        self.level = 2
        self.started_at = time.time()
        self._set("thinking")
        config = self._config(2)
        if not config:
            return

        def finish(text):
            # Une action se termine par « DONE: résumé » ; une recherche, par la réponse elle-même.
            idx = text.rfind("DONE:")
            if idx >= 0:
                self.details = text[:idx].strip()
                self._set("done", text[idx + 5:].strip())
            else:
                self._set("answer", text)

        self._stream(config.work_args(work_prompt(prompt, self.context), self.context), show_text=True,
                     budget=300 if config.needs_timeout else None, finish=finish)

    # Niveau 3 — Code (terminal)

    def send(self, prompt):
        config = self._config(3)
        if not config:
            return
        desktop.run_in_terminal(config.terminal_command(prompt + "\n\n" + self.context.block),
                                shell.expand(settings.agentWorkdir))
        self._set("delegated", prompt)

    def continue_in_terminal(self):
        """Reprend la session du niveau 2 dans le terminal, avec le fournisseur qui l'a menée."""
        if not self.session_id or not engines.installed(self.engine):
            return self.send(self.request)
        work = LevelConfig.of(2)
        config = work if work.engine == self.engine else LevelConfig(self.engine, "", "", "")
        desktop.run_in_terminal(config.resume_command(self.session_id), shell.expand(settings.agentWorkdir))

    # Processus

    def _stream(self, args, show_text, budget, finish):
        """Fournisseur en flux JSON : étapes et texte au fil de l'eau, puis `finish` avec la réponse finale."""
        self.steps = []
        streamed = []
        parser = engines.EventParser(self.engine)

        def line(raw):
            if not self.is_thinking:
                return
            for kind, value in parser.feed(raw):
                if kind == "session":
                    self.session_id = value
                elif kind == "step":
                    self.steps.append(value)
                    if not show_text:
                        self.stage = "lance une commande" if value.startswith("$ ") else value[:1].lower() + value[1:]
                    self._changed()
                elif kind == "text":
                    streamed.append(value)
                    if show_text:
                        self._set("streaming", "".join(streamed))
                elif kind == "final":
                    finish(value)
                else:
                    self._set("failed", value)
                if not self.is_thinking:
                    return

        def end(_text):
            if self.is_thinking:
                text = "".join(streamed).strip()
                finish(text) if text else self._set("failed", "Aucune réponse.")

        self._launch(args, budget=budget, streaming=line, then=end)

    def _launch(self, args, then, streaming=None, budget=None):
        """Lance le fournisseur. `streaming` reçoit chaque ligne au fil de l'eau (fil principal), `then` la sortie
        complète à la fin (code 0 uniquement). `budget` : arrêt forcé au-delà (en secondes)."""
        path = engines.binary(self.engine)
        if not path:
            return self._set("failed", f"{engines.TITLES[self.engine]} introuvable dans le PATH.")
        env = dict(os.environ, PATH=shell.user_path(), NO_COLOR="1")
        try:
            process = subprocess.Popen([path] + args, cwd=shell.expand(settings.agentWorkdir), env=env,
                                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as e:
            return self._set("failed", str(e))
        self._process = process
        if budget:
            def stop():
                if process.poll() is None:
                    self._timed_out = True
                    process.terminate()
                return False
            GLib.timeout_add_seconds(budget, stop)

        def read():
            collected = []
            errors = []
            # stderr lu à part : un outil bavard ne doit pas bloquer sur un tuyau plein.
            reader = threading.Thread(target=lambda: errors.append(process.stderr.read()), daemon=True)
            reader.start()
            for raw in iter(process.stdout.readline, b""):
                text = raw.decode("utf-8", "replace")
                collected.append(text)
                if streaming:
                    GLib.idle_add(lambda t=text.rstrip("\n"): (streaming(t), False)[1])
            code = process.wait()
            reader.join(2)
            detail = b"".join(errors).decode("utf-8", "replace").strip()

            def finish():
                if not self.is_thinking:
                    return False
                text = "".join(collected).strip()
                if code == 0 and text:
                    then(text)
                elif code < 0:
                    self._set("failed", "Trop long : arrêté." if self._timed_out else "Annulé.")
                else:
                    tail = "\n".join(detail.split("\n")[-4:])
                    self._set("failed", tail or f"{engines.TITLES[self.engine]} a quitté avec le code {code}.")
                return False
            GLib.idle_add(finish)

        threading.Thread(target=read, daemon=True).start()

    def cancel(self):
        if self._process and self._process.poll() is None:
            self._process.terminate()
