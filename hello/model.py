"""Les modes, la recherche, le clavier et les actions (LauncherModel.swift), indépendants de l'interface.

L'interface (ui.py) affiche `items` / `glyphs` et appelle `set_query`, `key` et `activate` ;
le modèle la prévient par `on_change()` et pilote la fenêtre par `self.c` (le contrôleur)."""
import datetime as dt
import os
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from urllib.parse import unquote, urlparse

from gi.repository import Gdk, GLib

from . import apps as appsmod
from . import colors as colormod
from . import context as attachmod
from . import desktop, engines, hotkey, shell, uninstall, usage
from .agent import LEVELS, AgentRun, Hermes, level_detail, level_model_label
from .chats import ChatStore
from .confirm import EscapeConfirmation
from .fuzzy import fold, score, words_match
from .glyphs import GlyphIndex, Recents, filter_title, next_filter
from .settings import HOME, grid_columns, row_height, settings
from .styles import GLYPH_ACCENTS, PALETTES, STYLES
from . import __version__, updater
from .updater import Updater

MODES = {
    # mode : (titre, icône, texte d'invite)
    "root": ("Hello", "hello-sparkle-symbolic", "Rechercher une app ou une commande…"),
    "apps": ("Applications", "hello-apps-symbolic", "Rechercher une application…"),
    "emoji": ("Emoji & Symboles", "hello-emoji-symbolic", "Rechercher un emoji ou un symbole…"),
    "clipboard": ("Presse-papiers", "hello-clipboard-symbolic", "Rechercher dans l'historique…"),
    "colors": ("Couleurs", "hello-eyedropper-symbolic", "Rechercher une couleur…"),
    "panel": ("Panneau", "hello-panel-symbolic", "Visibilité du panneau Plasma…"),
    "hotkey": ("Raccourci", "hello-keyboard-symbolic", "Raccourci pour ouvrir Hello…"),
    "output": ("Terminal", "hello-terminal-symbolic", ""),
    "uninstall": ("Désinstaller", "hello-trash-symbolic", "Quelle application désinstaller ?"),
    "uninstallFiles": ("Désinstaller", "hello-trash-symbolic", "Filtrer les fichiers…"),
    "stats": ("Statistiques", "hello-stats-symbolic", "Rechercher une app…"),
    "agent": ("IA", "hello-sparkle-symbolic", "Poser une autre question…"),
    "chats": ("Conversations", "hello-chats-symbolic", "Rechercher dans les conversations avec l'IA…"),
}

EMPTY_TEXT = {"clipboard": "Copiez un élément pour le retrouver ici", "emoji": "Aucun caractère trouvé",
              "chats": "Aucune conversation avec l'IA pour l'instant"}


def mode_title(mode):
    return engines.assistant()[2] if mode == "agent" else MODES[mode][0]


@dataclass
class Action:
    title: str
    run: Callable[[], None]


@dataclass
class Item:
    id: str
    title: str
    icon: tuple
    primary: Action
    subtitle: Optional[str] = None
    section: Optional[str] = None
    accessory: Optional[str] = None
    secondary: Optional[Action] = None
    tertiary: Optional[Action] = None
    remove: Optional[Action] = None
    completion: Optional[str] = None
    preview: Optional[tuple] = None
    checked: Optional[bool] = None
    copy_text: Optional[str] = None


@dataclass
class Command:
    id: str
    title: str
    subtitle: str
    keywords: str
    icon: tuple
    action: Callable[[], None]
    suggested: bool = False
    action_title: str = "Ouvrir"
    secondary: Optional[Action] = None
    folded: Any = field(default=None, repr=False)


def sym(name, color="#8E8E93"):
    return ("symbol", name, color)


def relative(timestamp):
    """« il y a 5 min », à la RelativeDateTimeFormatter."""
    seconds = max(0, time.time() - timestamp)
    if seconds < 60:
        return "à l'instant"
    if seconds < 3600:
        return f"il y a {int(seconds // 60)} min"
    if seconds < 86400:
        return f"il y a {int(seconds // 3600)} h"
    days = int(seconds // 86400)
    if days < 7:
        return "hier" if days == 1 else f"il y a {days} j"
    if days < 31:
        return f"il y a {days // 7} sem."
    return dt.date.fromtimestamp(timestamp).strftime("%d/%m/%Y")


def file_url_path(text):
    """Chemin d'un lien file:// (collé depuis un terminal, un navigateur…), None sinon."""
    link = text.strip().strip("'\"<>").strip()
    if not link.lower().startswith("file://"):
        return None
    path = unquote(urlparse(link).path)
    return os.path.normpath(path) if path else None


class LauncherModel:
    def __init__(self, controller):
        self.c = controller
        self.on_change = lambda: None
        self.query = ""
        self.mode = "root"
        self.items = []
        self.glyphs = []
        self.selection = 0
        self.glyph_filter = "all"
        self.toast = None
        self.run = None
        self.agent = None
        self.presented = False
        self.forward = True
        self._root_query = ""
        self._toast_source = None
        self._commands = None
        self._running = None
        self._can_paste = None
        # Désinstallation en cours
        self._plan = None
        self._checked = set()
        self._sizes = {}
        self._uninstall_return = "root"
        self._uninstalling = False
        # Fichiers et captures joints à la prochaine demande à l'IA.
        self.attachments = []
        self.escape_confirmation = EscapeConfirmation()
        # L'IA a fini pendant que Hello était fermé : la prochaine ouverture montre sa réponse.
        self._unseen_agent_result = False
        shell.FolderJump.on_loaded = self.refresh
        shell.Ports.on_loaded = self.refresh

    # MARK: - Navigation

    def changed(self):
        self.on_change()

    @property
    def agent_in_background(self):
        """Une conversation à retrouver à la réouverture : l'IA y travaille encore, ou a fini sans qu'on l'ait vu."""
        return self.mode == "agent" and self.agent is not None and (self.agent.is_thinking or self._unseen_agent_result)

    def mark_agent_seen(self):
        self._unseen_agent_result = False

    @property
    def placeholder(self):
        if self.mode == "root" and self.attachments:
            name = engines.assistant()[0]
            return (f"Que doit faire {name} avec ce fichier ?" if len(self.attachments) == 1
                    else f"Que doit faire {name} avec ces fichiers ?")
        return MODES[self.mode][2]

    def reset(self, mode="root"):
        self.escape_confirmation.reset()
        self.mode = mode
        self._root_query = ""
        self._invalidate()
        self.glyph_filter = "all"
        self.run = None
        self._plan = None
        self.attachments = []
        self.set_query("")

    def resume(self):
        """Réaffiche l'état laissé tel quel en rafraîchissant les données."""
        self._invalidate()
        kept = self.selection
        if self.mode != "output":
            self._update()
        count = len(self.glyphs) if self.mode == "emoji" else len(self.items)
        self.selection = 0 if count == 0 else min(kept, count - 1)
        self.changed()

    def set_query(self, q, notify=True):
        if q != self.query:
            self.escape_confirmation.reset()
        self.query = q
        self.selection = 0
        self._update()
        if notify:
            self.changed()

    def enter(self, mode):
        if self.mode == "root":
            self._root_query = self.query
        self.forward = True
        self.mode = mode
        if mode == "apps":
            self.c.morph(True)
        self.set_query("")
        self.c.query_changed()

    def back(self):
        self.escape_confirmation.reset()
        if self.run:
            self.run.cancel()
        self.run = None
        if self.agent:
            self.agent.cancel()
        self.agent = None
        self.forward = False
        if self.mode == "uninstallFiles" and self._uninstall_return == "uninstall":
            self._plan = None
            self.mode = "uninstall"
            self.set_query("")
            self.c.query_changed()
            return
        self._plan = None
        leaving_apps = self.mode == "apps"
        self.mode = "root"
        self.set_query(self._root_query)
        if leaving_apps:
            self.c.morph(False)
        self.c.query_changed()

    def refresh(self):
        self._invalidate()
        self._update()
        self.changed()

    def _invalidate(self):
        self._commands = None
        self._running = None
        self._can_paste = None

    @property
    def can_paste(self):
        if self._can_paste is None:
            self._can_paste = desktop.can_paste()
        return self._can_paste

    def _update(self):
        builders = {
            "root": self._root_items, "apps": self._grid_app_items, "clipboard": self._clipboard_items,
            "colors": self._color_items, "panel": self._panel_items, "hotkey": self._hotkey_items,
            "uninstall": self._uninstall_picker_items, "uninstallFiles": self._uninstall_file_items,
            "stats": self._stats_items, "chats": self.chat_items,
            # Champ de question de suite : « / » liste les commandes de l'agent.
            "agent": lambda: self.slash_items(self.query.strip()),
        }
        if self.mode == "emoji":
            self.glyphs = GlyphIndex.search(self.query, self.glyph_filter)
        elif self.mode in builders:
            self.items = builders[self.mode]()
        else:
            self.items = []
        count = len(self.glyphs) if self.mode == "emoji" else len(self.items)
        self.selection = 0 if count == 0 else min(max(self.selection, 0), count - 1)

    def apps_did_change(self):
        if self.mode in ("root", "apps", "uninstall"):
            self.refresh()

    def clipboard_did_change(self):
        self._commands = None
        if self.mode == "clipboard":
            self.refresh()

    @property
    def selected_item(self):
        return self.items[self.selection] if 0 <= self.selection < len(self.items) else None

    @property
    def selected_glyph(self):
        return self.glyphs[self.selection] if 0 <= self.selection < len(self.glyphs) else None

    @property
    def collapsed(self):
        """Mode focus : seulement la barre de recherche, tant que rien n'est tapé."""
        return (settings.focusMode and self.mode == "root" and self.toast is None and not self.attachments
                and not self.query.strip())

    def flash(self, text):
        self.toast = text
        if self._toast_source:
            GLib.source_remove(self._toast_source)

        def clear():
            self._toast_source = None
            self.toast = None
            self.changed()
            return False

        self._toast_source = GLib.timeout_add(2200, clear)
        self.changed()

    # MARK: - Clavier

    def key(self, keyval, state, repeat=False):
        """Touche reçue par le panneau. True : traitée (le champ de recherche ne la reçoit pas)."""
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        alt = bool(state & Gdk.ModifierType.ALT_MASK)
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        grid = self.mode in ("emoji", "apps")
        k = Gdk.keyval_name(keyval) or ""
        cols = self.app_columns if self.mode == "apps" else grid_columns()
        if k != "Escape":
            self.escape_confirmation.reset()

        if k == "Escape":
            if not repeat:
                self._escape()
            return True
        if self.mode == "apps" and k in ("Page_Up", "Page_Down"):
            self.turn_page(-1 if k == "Page_Up" else 1)
            return True
        if self.mode == "apps" and ctrl and k in ("Left", "Right"):
            self.turn_page(-1 if k == "Left" else 1)
            return True
        if k == "Down":
            self._move(cols if grid else 1)
            return True
        if k == "Up":
            self._move(-cols if grid else -1)
            return True
        if grid and k in ("Left", "Right"):
            self._move(-1 if k == "Left" else 1)
            return True
        if k in ("Return", "KP_Enter", "ISO_Enter"):
            item = self.selected_item
            if shift and item and item.copy_text and self.mode != "agent":
                desktop.copy(item.copy_text)
                self.c.hide()
                return True
            self.activate("secondary" if ctrl else "tertiary" if alt else "primary")
            return True
        if k in ("Tab", "ISO_Left_Tab"):
            self._tab()
            return True
        if k == "Delete" and shift and self.selected_item and self.selected_item.remove:
            self.selected_item.remove.run()
            return True
        if k == "BackSpace" and not self.query and self.mode == "root" and not ctrl and self.attachments:
            self.detach(self.attachments[-1])
            return True
        if k == "BackSpace" and self.mode == "agent" and self.agent and self.agent.is_thinking:
            return True
        if k == "BackSpace" and not self.query and self.mode != "root":
            self.back()
            return True
        if self.mode == "output":
            if ctrl and k.lower() == "c" and self.run and self.run.running:
                self.run.cancel()
                return True
            if ctrl and k.lower() == "r" and self.run and not self.run.running:
                self.start_run(self.run.command)
                return True
        if ctrl and k.lower() == "w":
            self.c.hide()
            return True
        if ctrl and k == "comma":
            self.c.hide()
            self.c.open_settings()
            return True
        if ctrl and k.lower() == "o" and self.mode == "root" and Hermes.available():
            self.pick_files_for_agent()
            return True
        if ctrl and shift and k.lower() == "s" and self.mode == "root" and Hermes.available():
            self.capture_for_agent()
            return True
        if ctrl and k.lower() == "v" and self.mode == "root" and not shift:
            # Fichiers copiés dans le gestionnaire de fichiers ou image copiée : joints à la demande pour l'IA
            # (Ctrl ⇧ V colle le texte).
            if Hermes.available():
                found = attachmod.from_clipboard()
                if found:
                    self.attach(found)
                    return True
            # Lien file:// collé dans Hello vide : le fichier s'ouvre tout de suite avec son app par défaut.
            if not self.query:
                text = shell.capture(["wl-paste", "-n", "-t", "text/plain"], timeout=1)
                path = file_url_path(text) if text else None
                if path and os.path.exists(path):
                    self.c.hide()
                    desktop.open_path(path)
                    return True
        return False

    def _move(self, delta):
        count = len(self.glyphs) if self.mode == "emoji" else len(self.items)
        if count:
            self.selection = min(max(self.selection + delta, 0), count - 1)
            self.changed()

    # Grille d'applications
    app_columns = 7
    app_rows = 3

    @property
    def apps_per_page(self):
        return self.app_columns * self.app_rows

    @property
    def app_page_count(self):
        return max(1, -(-len(self.items) // self.apps_per_page))

    @property
    def app_page(self):
        return self.selection // self.apps_per_page

    def turn_page(self, delta):
        page = self.app_page + delta
        if self.items and page >= 0 and page * self.apps_per_page < len(self.items):
            self.selection = page * self.apps_per_page
            self.changed()

    def select(self, index):
        self.selection = index
        self.changed()

    def _escape(self):
        if self.mode == "root":
            self.c.hide() if not self.query else self.set_query("")
        elif self.mode == "output":
            self.run.cancel() if self.run and self.run.running else self.back()
        elif self.mode == "agent":
            # Deux pressions distinctes : arrêter l'IA, ou quitter sa réponse. Une saisie est d'abord effacée.
            if self.agent and self.agent.is_thinking:
                if self.escape_confirmation.press("cancel"):
                    self.agent.cancel()
                else:
                    self.flash("Encore Échap pour arrêter · Ctrl W pour masquer")
            elif self.query:
                self.set_query("")
            elif self.escape_confirmation.press("leave"):
                self.back()
            else:
                self.flash("Encore Échap pour revenir à la recherche")
        else:
            self.back() if not self.query else self.set_query("")
        self.c.query_changed()

    def _tab(self):
        if self.mode == "emoji":
            self.glyph_filter = next_filter(self.glyph_filter)
            self.selection = 0
            self.refresh()
        elif self.mode in ("root", "agent"):
            item = self.selected_item
            if item and item.completion:
                self.set_query(item.completion)
                self.c.query_changed()
        elif self.mode == "uninstallFiles" and self._plan:
            every = {f.path for f in self._plan.files}
            self._checked = set() if self._checked == every else every
            self.refresh()

    def set_glyph_filter(self, flt):
        self.glyph_filter = flt
        self.selection = 0
        self.refresh()

    def activate(self, kind="primary"):
        if self.mode == "emoji":
            g = self.selected_glyph
            if not g:
                return
            Recents.add(g.char)
            self.c.hide()
            if kind == "primary":
                desktop.insert(g.char)
            else:
                desktop.copy(g.char)
            return
        if self.mode == "agent":
            self._activate_agent(kind)
            return
        if self.mode == "output":
            if not self.run:
                return
            if kind == "secondary":
                self.c.hide()
                desktop.run_in_terminal(self.run.command)
            else:
                desktop.copy(self.run.output)
                self.flash("Sortie copiée")
            return
        item = self.selected_item
        if not item:
            return
        action = {"primary": item.primary, "secondary": item.secondary, "tertiary": item.tertiary}[kind]
        if action:
            action.run()

    def _activate_agent(self, kind):
        a = self.agent
        if not a:
            return
        if self.query.startswith("/"):
            if kind == "primary" and self.selected_item:
                self.selected_item.primary.run()
            return
        # Question de suite tapée sous la réponse : ↵ Auto, Ctrl ↵ Recherche & Action, Alt ↵ Code.
        follow = self.query.strip()
        if follow and not a.is_thinking:
            self.follow_up(follow, 2 if kind == "secondary" else 3 if kind == "tertiary" else 1)
            return
        if a.phase in ("answer", "done") and kind == "secondary" and a.level == 2:
            a.continue_in_terminal()  # continuer la même conversation dans le terminal
            self.c.hide()
        elif a.phase == "answer" and kind == "secondary":
            self.start_agent(a.request, 2)
        elif a.phase == "answer":
            desktop.copy(a.text)
            self.c.hide()
        elif a.phase in ("done", "delegated", "failed"):
            self.c.hide()

    @property
    def hints(self):
        if self.mode == "emoji":
            if not self.selected_glyph:
                return []
            return [("Coller" if self.can_paste else "Copier", "↵"), ("Copier", "Ctrl ↵"),
                    (filter_title(next_filter(self.glyph_filter)), "⇥")]
        if self.mode == "agent" and self.query.startswith("/"):
            return self._item_hints()
        if self.mode == "agent":
            phase = self.agent.phase if self.agent else None
            if phase in ("thinking", "streaming"):
                return [("Arrière-plan", "Ctrl W"), ("Annuler", "Échap Échap")]
            if self.query.strip():
                return [("Demander", "↵"), ("Recherche & Action", "Ctrl ↵"), ("Code", "Alt ↵")]
            if phase == "answer":
                return [("Copier", "↵"),
                        ("Continuer dans le terminal" if self.agent.level == 2 else "Recherche & Action", "Ctrl ↵"),
                        ("Retour", "Échap Échap")]
            return [("Fermer", "↵"), ("Retour", "Échap Échap")]
        if self.mode == "output":
            running = self.run and self.run.running
            return [("Copier la sortie", "↵"), ("Arrêter", "Ctrl C") if running else ("Relancer", "Ctrl R"),
                    ("Dans le terminal", "Ctrl ↵")]
        return self._item_hints()

    def _item_hints(self):
        item = self.selected_item
        if not item:
            return []
        out = [(item.primary.title, "↵")]
        if item.secondary:
            out.append((item.secondary.title, "Ctrl ↵"))
        if item.tertiary:
            out.append((item.tertiary.title, "Alt ↵"))
        if item.remove:
            out.append((item.remove.title, "⇧ Suppr"))
        if item.copy_text and len(out) < 3:
            out.append(("Copier", "⇧ ↵"))
        if item.completion:
            out.append(("Compléter", "⇥"))
        if self.mode == "uninstallFiles":
            out.append(("Tout", "⇥"))
        return out[:4]

    # MARK: - Racine

    def _root_items(self):
        q = self.query.strip()
        # Avec des pièces jointes, la demande est pour l'IA (« ?? » et « ??? » forcent toujours le niveau).
        if self.attachments and Hermes.available():
            return self.agent_items(q, explicit=q.startswith("?"))
        if not q:
            return [] if settings.focusMode else self._suggestions()
        if q.startswith("?"):
            return self.agent_items(q, explicit=True)
        # « /resume », « /code … » : commandes de l'agent, avant les chemins qui commencent par « / ».
        if q.startswith("/"):
            slash = self.slash_items(q)
            if slash:
                return slash + self._terminal_items(q)
        files = self._file_url_items(q)
        if files is not None:
            return files
        out = self._terminal_items(q)
        folded = fold(q)
        running = self.running
        scored = []  # on classe d'abord, et on ne construit les lignes que pour les 40 premières
        for app in self.c.apps.apps:
            s = app.score(folded)
            if s is not None:
                scored.append((s + usage.boost(app.id, folded),
                               lambda app=app: self._app_item(app, app.desktop_id in running, q)))
        for cmd in self.commands:
            title, keys = cmd.folded
            s = score(folded, title)
            if s is None and words_match(folded, keys):
                s = 520
            if s is not None:
                scored.append((s + usage.boost(cmd.id, folded), lambda cmd=cmd: self._command_item(cmd, q)))
        for s, item in self._custom_command_items(q, folded):
            scored.append((s, lambda item=item: item))
        scored.sort(key=lambda x: -x[0])
        out += [build() for _, build in scored[:40]]

        if not any(i.id.startswith(("run:", "proc:", "port")) for i in out):
            out += self._history_fallback(q)
        # Rien de pertinent (ou une vraie phrase) : Hermes passe en tête, sinon il reste en dernier recours.
        agent = self.agent_items(q, explicit=False)
        sentence = len(q.split()) >= 4 and not q.startswith((">", "$"))
        return agent + out if (not out or sentence) else out + agent

    def _suggestions(self):
        update = self.update_item()
        out = [update] if update else []
        by_app = {a.id: a for a in self.c.apps.apps}
        commands = self.commands
        by_cmd = {c.id: c for c in commands}
        running = self.running
        if settings.showRecents:
            for item_id in usage.top(12):
                if len(out) >= 6:
                    break
                if item_id in by_app:
                    app = by_app[item_id]
                    item = self._app_item(app, app.desktop_id in running)
                elif item_id in by_cmd:
                    item = self._command_item(by_cmd[item_id])
                elif item_id.startswith("path:") and shell.is_folder(item_id[5:]):
                    item = self.path_item(item_id[5:], None)
                else:
                    continue
                item.section = "Récents"
                out.append(item)
        for cmd in commands:
            if cmd.suggested and all(i.id != cmd.id for i in out):
                item = self._command_item(cmd)
                item.section = "Commandes"
                out.append(item)
        # Astuce du terminal : seulement tant qu'il y a peu de récents (elle ne sert qu'à découvrir).
        if sum(1 for i in out if i.section == "Récents") < 3:
            out.append(Item(
                id="hint.shell", section="Terminal", title="cd ~/dossier   ·   > commande shell",
                subtitle=f"« cd ./code » ouvre ~/code dans {desktop.file_manager_name()} · "
                         f"Ctrl ↵ l'ouvre dans {desktop.terminal()[1]}",
                icon=sym("hello-terminal-symbolic"),
                primary=Action("Essayer", lambda: (self.set_query("cd ~/"), self.c.query_changed()))))
        return out

    def _grid_app_items(self):
        q = fold(self.query.strip())
        running = self.running
        found = self.c.apps.apps
        if q:
            scored = [(app.score(q), i, app) for i, app in enumerate(found)]
            found = [app for s, i, app in sorted((x for x in scored if x[0] is not None), key=lambda x: (-x[0], x[1]))]
        return [self._app_item(app, app.desktop_id in running, self.query) for app in found]

    def _app_item(self, app, is_running, query=""):
        pids = self.running.get(app.desktop_id, [])

        def quit_app():
            appsmod.quit_app(pids)
            self.flash(f"{app.name} quittée")
            GLib.timeout_add(600, lambda: (self.refresh(), False)[1])

        return Item(
            id=app.id, title=app.name, subtitle=app.detail, icon=("gicon", app.icon),
            accessory="Ouverte" if is_running else None,
            primary=Action("Ouvrir", lambda: self._launch(app, query)),
            secondary=Action("Afficher le lanceur", lambda: (self.c.hide(), desktop.reveal([app.path]))),
            tertiary=Action("Quitter l'app", quit_app) if is_running else None,
            remove=Action("Désinstaller", lambda: self._start_uninstall(app, "root")))

    def _launch(self, app, query):
        """Ouvre l'app tout de suite ; Hello prend sa couleur pendant qu'il s'efface."""
        usage.record(app.id, query)
        self.c.hide(tint=settings.animations and settings.launchEffects)
        if not self.c.apps.launch(app):
            self.c.show()
            self.flash(f"Impossible d'ouvrir {app.name}")

    def _command_item(self, cmd, query=""):
        def run():
            usage.record(cmd.id, query)
            cmd.action()
        return Item(id=cmd.id, title=cmd.title, subtitle=cmd.subtitle, icon=cmd.icon, accessory="Commande",
                    primary=Action(cmd.action_title, run), secondary=cmd.secondary)

    @property
    def running(self):
        if self._running is None:
            self._running = appsmod.running(self.c.apps.apps)
        return self._running

    @property
    def commands(self):
        if self._commands is None:
            self._commands = self._build_commands()
            for cmd in self._commands:
                title = fold(cmd.title)
                cmd.folded = (title, title + " " + fold(cmd.keywords))
        return self._commands

    def _build_commands(self):
        c = self.c
        login = os.path.exists(c.autostart_path)
        out = [
            Command("cmd.apps", "Toutes les applications", "Grille de grandes icônes, page par page",
                    "applications apps launchpad grille toutes icones", sym("hello-apps-symbolic", "#9141AC"),
                    lambda: self.enter("apps"), suggested=True),
            Command("cmd.emoji", "Emoji & Symboles", "Chercher et insérer emoji et caractères Unicode",
                    "emoji smiley unicode caractere symbole glyphe", sym("hello-emoji-symbolic", "#FF7800"),
                    lambda: self.enter("emoji"), suggested=True),
            Command("cmd.clipboard", "Historique du presse-papiers", f"{len(c.clipboard.entries)} élément(s)",
                    "clipboard presse papiers copier coller historique", sym("hello-clipboard-symbolic", "#3584E4"),
                    lambda: self.enter("clipboard"), suggested=True),
            Command("cmd.pick", "Pipette de couleur", "Capturer une couleur n'importe où à l'écran",
                    "color picker couleur pipette eyedropper hex rgb", sym("hello-eyedropper-symbolic", "#E01B7A"),
                    self.pick_color, suggested=True, action_title="Choisir",
                    secondary=Action("Historique des couleurs", lambda: self.enter("colors"))),
            Command("cmd.colors", "Historique des couleurs", f"{len(c.colors.items)} couleur(s)",
                    "color couleur historique hex palette", sym("hello-palette-symbolic", "#E01B7A"),
                    lambda: self.enter("colors")),
        ]
        if colormod.plasma_available():
            current = c.panel_mode_cached
            title = next((t for v, t, _, _ in colormod.PANEL_MODES if v == current), "?")
            out.append(Command("cmd.panel", "Panneau Plasma", f"Visibilité : {title}",
                               "panneau barre des taches menu bar masquer afficher autohide cacher",
                               sym("hello-panel-symbolic", "#613583"), lambda: self.enter("panel"), suggested=True))
            for value, title, detail, icon in colormod.PANEL_MODES:
                out.append(Command(f"cmd.panel.{value}", f"Panneau : {title}", detail,
                                   "panneau barre taches masquer autohide", sym(icon, "#613583"),
                                   lambda v=value, t=title: self._apply_panel(v, t), action_title="Appliquer"))
        focus = settings.focusMode

        def toggle_focus():
            settings.focusMode = not settings.focusMode
            self.set_query("")
            self.c.query_changed()
            self.flash("Mode focus activé" if settings.focusMode else "Mode focus désactivé")

        out.append(Command("cmd.focus", "Désactiver le mode focus" if focus else "Activer le mode focus",
                           "À l'ouverture, seulement la barre de recherche",
                           "focus minimal epure barre recherche seule spotlight", sym("hello-focus-symbolic", "#2190A4"),
                           toggle_focus, action_title="Désactiver" if focus else "Activer"))
        for key, style in STYLES.items():
            out.append(Command(f"cmd.style.{key}", f"Style : {style['title']}", style["detail"],
                               "style theme apparence design da look visuel", sym(style["icon"], "#2190A4"),
                               lambda k=key: self._apply_style(k), action_title="Appliquer"))
        for key, palette in PALETTES.items():
            out.append(Command(f"cmd.palette.{key}", f"Couleurs : {palette[0]}",
                               "Thème de couleurs du style Atelier Expressif",
                               "couleurs theme palette accent atelier material", sym("hello-palette-symbolic",
                                                                                      "#2190A4"),
                               lambda k=key: self._apply_palette(k), action_title="Appliquer"))
        for key, accent in GLYPH_ACCENTS.items():
            out.append(Command(f"cmd.glyph.{key}", f"Accent : {accent[0]}", "Couleur unique du style Atelier Glyphe",
                               "couleurs accent glyphe glyph theme", sym("hello-style-glyph-symbolic", "#2190A4"),
                               lambda k=key: self._apply_glyph_accent(k), action_title="Appliquer"))

        def toggle_login():
            on = c.toggle_autostart()
            self.flash("Hello se lancera à l'ouverture de session" if on else "Désactivé")
            self.refresh()

        out += [
            Command("cmd.hotkey", "Raccourci global de Hello", f"Actuel : {c.hotkey.description}",
                    "raccourci hotkey shortcut clavier", sym("hello-keyboard-symbolic"), lambda: self.enter("hotkey")),
            Command("cmd.login", "Ne plus lancer Hello à l'ouverture de session" if login
                    else "Lancer Hello à l'ouverture de session",
                    "Actuellement activé" if login else "Actuellement désactivé",
                    "login demarrage startup ouverture session autostart", sym("hello-login-symbolic", "#26A269"),
                    toggle_login, action_title="Désactiver" if login else "Activer"),
            Command("cmd.uninstall", "Désinstaller une application", "Supprime l'app et les fichiers de votre choix",
                    "uninstall desinstaller supprimer app cleaner corbeille", sym("hello-trash-symbolic", "#E01B24"),
                    lambda: self.enter("uninstall"), suggested=True),
            Command("cmd.settings", "Réglages de Hello", "Apparence, recherche, presse-papiers… (Ctrl ,)",
                    "reglages parametres preferences settings options configuration",
                    sym("hello-settings-symbolic"), lambda: (c.hide(), c.open_settings()), suggested=True),
            Command("cmd.update", "Rechercher les mises à jour de Hello",
                    f"Version {__version__} · releases GitHub de {updater.REPO}",
                    "mise a jour update version github release nouvelle", sym("hello-update-symbolic",
                                                                               "#26A269"),
                    self._check_updates),
            Command("cmd.chats", "Conversations avec l'IA",
                    f"{len(ChatStore.conversations)} conversation(s) · reprendre ou poser une question de suite",
                    "hermes claude codex ia ai agent chat conversations historique memoire discussions",
                    sym("hello-chats-symbolic", "#9141AC"), lambda: self.enter("chats")),
            Command("cmd.stats", "Statistiques d'utilisation", "Apps les plus utilisées, historique et raccourcis appris",
                    "stats statistiques usage frequent utilisation historique",
                    sym("hello-stats-symbolic", "#2190A4"), lambda: self.enter("stats")),
            Command("cmd.resetstats", "Réinitialiser les statistiques d'utilisation",
                    "Oublie la fréquence et les raccourcis appris",
                    "reset reinitialiser stats statistiques usage oublier", sym("hello-reset-symbolic", "#E01B24"),
                    lambda: (usage.reset(), self.flash("Statistiques réinitialisées"), self.refresh()),
                    action_title="Réinitialiser"),
            Command("cmd.clearclip", "Vider l'historique du presse-papiers", "Supprime tous les éléments",
                    "clear effacer vider clipboard presse papiers", sym("hello-trash-symbolic", "#E01B24"),
                    lambda: (c.clipboard.clear(), self.flash("Historique vidé"), self.refresh()), action_title="Vider"),
            Command("cmd.reload", "Recharger les applications", "Relancer l'indexation",
                    "reload refresh index apps", sym("hello-refresh-symbolic"),
                    lambda: (c.apps.refresh(), self.flash("Applications rechargées"))),
            Command("cmd.quit", "Quitter Hello", "Ferme complètement le lanceur", "quit exit quitter fermer",
                    sym("hello-close-symbolic"), c.quit, action_title="Quitter"),
        ]
        return out

    def _apply_style(self, key):
        settings.panelStyle = key
        self.refresh()
        self.flash(f"Style : {STYLES[key]['title']}")

    def _apply_palette(self, key):
        settings.atelierPalette = key
        settings.panelStyle = "atelier"
        self.refresh()
        self.flash(f"Couleurs : {PALETTES[key][0]}")

    def _apply_glyph_accent(self, key):
        settings.glyphAccent = key
        settings.panelStyle = "glyph"
        self.refresh()
        self.flash(f"Accent : {GLYPH_ACCENTS[key][0]}")

    def _check_updates(self):
        if Updater.pending:
            Updater.install()
        else:
            self.flash("Recherche de mises à jour…")
            Updater.check()

    def update_item(self):
        """En tête des suggestions quand une mise à jour attend (puis pendant son téléchargement)."""
        release = Updater.pending
        if not release:
            return None
        subtitle = {
            "downloading": f"Téléchargement… {int(Updater.progress * 100)} %",
            "installing": "Installation… Hello va se relancer",
            "failed": f"Échec : {Updater.error} · ↵ pour réessayer",
        }.get(Updater.state, f"Tu as la {__version__} · ↵ installe et relance Hello")

        def notes():
            self.c.hide()
            desktop.open_uri(release["page"])

        return Item(id="update", section="Mise à jour", title=f"Hello {release['version']} est disponible",
                    subtitle=subtitle, icon=sym("hello-update-symbolic", "#26A269"),
                    primary=Action("Installer", Updater.install), secondary=Action("Notes de version", notes))

    def _apply_panel(self, value, title):
        if colormod.apply_panel_mode(value):
            self.c.panel_mode_cached = value
            self.flash(f"Panneau : {title}")
        else:
            self.flash("Plasma n'a pas répondu")
        self.refresh()

    # MARK: - Terminal

    def start_run(self, command):
        shell.ShellHistory.record(command)
        columns = max(60, int((self.c.panel_width - 40) / 7.6))
        run = shell.ShellRun(command, columns)
        if self.mode != "output":
            self.enter("output")
        self.run = run
        run.on_update = self.changed
        run.start()
        self.changed()

    _silent = []

    def run_silently(self, command, name):
        shell.ShellHistory.record(command)
        run = shell.ShellRun(command)
        self._silent.append(run)

        def finished(status):
            self._silent.remove(run)
            self.flash(f"✓ {name} terminé" if status == 0 else f"✗ {name} : code {status}")

        run.on_finish = finished
        run.start()
        self.flash(f"{name}…")

    def _terminal_items(self, q):
        """Résultats « terminal » prioritaires (affichés avant les apps)."""
        if not settings.shellCommands:
            return []
        word, rest = shell.split_first(q)
        if q.startswith((">", "$")):
            command = q[1:].strip()
            out = [self.run_item(command)] if command else []
            for i, past in enumerate(shell.ShellHistory.search(command, 10)):
                if past == command:
                    continue
                item = self.run_item(past, history=True)
                item.section = "Historique" if i == 0 or len(out) <= 1 else None
                out.append(item)
            return out
        w = word.lower()
        if w in ("kill", "killall", "pkill"):
            return self._process_items(rest)
        if w in ("port", "ports"):
            return self._port_items(rest)
        if w == "ip" and not rest:
            return self._ip_items()
        if w == "z":
            return [self.path_item(p, "cd " + shell.abbreviate(p) + "/", learn=rest)
                    for p in shell.FolderJump.candidates(rest, 8)]
        if q.startswith(":") and q[1:].isdigit():
            return self._port_items(q[1:])
        if shell.has_operators(q):
            return []
        if word == "cd":
            out = self.path_items(rest or "~", "cd ", True, rest)
            # « cd proj » : on propose aussi les dossiers fréquents, où qu'ils soient.
            if rest and "/" not in rest and not rest.startswith(("~", ".")):
                known = {i.id for i in out}
                for path in shell.FolderJump.candidates(rest, 6):
                    if "path:" + path not in known:
                        item = self.path_item(path, "cd " + shell.abbreviate(path) + "/", learn=rest)
                        item.section = "Dossiers fréquents"
                        out.append(item)
            return out
        if word in ("open", "xdg-open") and rest and not rest.startswith("-"):
            return self.path_items(rest, word + " ", False, rest)
        if q.startswith(("~", "/", "./", "../")):
            return self.path_items(q, "", False, q)
        return []

    def _custom_command_items(self, q, folded):
        out = []
        for custom in settings.customCommands:
            keyword = custom.get("keyword", "").lower()
            if "{}" in custom["command"] and keyword and q.lower().startswith(keyword + " "):
                out.append((1200, self._custom_item(custom, q[len(keyword) + 1:])))
                continue
            name = fold(custom["name"])
            s = 950 if keyword and folded and keyword.startswith(folded) else score(folded, name)
            if s is not None:
                out.append((s + usage.boost("custom:" + custom["id"], folded), self._custom_item(custom, None)))
        return out

    def _history_fallback(self, q):
        """Historique shell proposé après les résultats quand on tape une commande sans « > »."""
        if not settings.shellCommands or not shell.is_command(shell.split_first(q)[0]):
            return []
        out = [self.run_item(q)]
        for past in shell.ShellHistory.search(q, 4):
            if past != q:
                out.append(self.run_item(past, history=True))
        return out

    def path_items(self, raw, prefix, folders_only, learn):
        path = shell.expand(raw)
        out = []
        folder = shell.is_folder(path)
        if os.path.exists(path) and (not folders_only or folder):
            completion = prefix + shell.abbreviate(path) + ("/" if folder and path != "/" else "")
            out.append(self.path_item(path, completion, learn))
        for candidate in shell.completions(raw, folders_only):
            if candidate.lower() != path.lower():
                completion = prefix + shell.abbreviate(candidate) + ("/" if shell.is_folder(candidate) else "")
                out.append(self.path_item(candidate, completion, learn))
        return out

    def _file_url_items(self, q):
        """Lien file:// tapé ou collé : le fichier, ↵ l'ouvre avec l'app par défaut."""
        path = file_url_path(q)
        if path is None:
            return None
        if os.path.exists(path):
            item = self.path_item(path, None)
            item.section = "Lien vers un fichier"
            return [item]
        folder = os.path.dirname(path)

        def open_folder():
            if not shell.is_folder(folder):
                return self.flash("Le dossier n'existe pas non plus")
            self.c.hide()
            desktop.open_path(folder)

        return [Item(id="missing:" + path, title="Fichier introuvable", subtitle=shell.abbreviate(path),
                     icon=sym("hello-folder-symbolic"), primary=Action("Ouvrir le dossier", open_folder))]

    def path_item(self, path, completion, learn=""):
        folder = shell.is_folder(path)
        name = "Dossier personnel" if path == HOME else (os.path.basename(path) or path)
        branch = shell.git_branch(path) if folder else None
        term_name = desktop.terminal()[1]
        editor = desktop.editor()

        def remember():
            if folder:
                usage.record("path:" + path, learn)

        def primary():
            remember()
            self.c.hide()
            desktop.open_path(path)

        def in_terminal():
            remember()
            self.c.hide()
            desktop.run_in_terminal(None, path)

        def in_editor():
            remember()
            self.c.hide()
            desktop.open_with_editor(path)

        return Item(
            id="path:" + path, title=name, subtitle=shell.abbreviate(path), icon=("file", path),
            accessory=f"⎇ {branch}" if branch else ("Dossier" if folder else "Fichier"),
            primary=Action(f"Ouvrir dans {desktop.file_manager_name()}" if folder else "Ouvrir", primary),
            secondary=Action(f"Ouvrir dans {term_name}", in_terminal) if folder
            else Action("Afficher dans le dossier", lambda: (self.c.hide(), desktop.reveal([path]))),
            tertiary=Action(f"Ouvrir dans {editor[1]}", in_editor) if editor else None,
            completion=completion, copy_text=path)

    def run_item(self, command, history=False):
        def in_terminal():
            shell.ShellHistory.record(command)
            self.c.hide()
            desktop.run_in_terminal(command)

        sh = os.path.basename(desktop.user_shell())
        return Item(
            id=("hist:" if history else "run:") + command, title=command,
            subtitle=None if history else f"Exécuter dans {sh} depuis ~",
            icon=sym("hello-history-symbolic" if history else "hello-terminal-symbolic", "#5E5C64"),
            accessory="Historique" if history else "Shell",
            primary=Action("Exécuter", lambda: self.start_run(command)),
            secondary=Action("Dans le terminal", in_terminal),
            completion="> " + command, copy_text=command)

    def _custom_item(self, custom, argument):
        command = custom["command"].replace("{}", argument) if argument is not None else custom["command"]
        needs_argument = argument is None and "{}" in custom["command"]
        usage_id = "custom:" + custom["id"]
        modes = {"app": "Dans Hello", "terminal": "Dans le terminal", "silent": "En silence"}

        def run():
            if needs_argument:
                self.set_query(custom["keyword"] + " ")
                self.c.query_changed()
                return
            usage.record(usage_id, self.query)
            if custom["mode"] == "app":
                self.start_run(command)
            elif custom["mode"] == "terminal":
                self.c.hide()
                desktop.run_in_terminal(command)
            else:
                self.run_silently(command, custom["name"])

        return Item(
            id=f"custom:{custom['id']}{argument or ''}",
            title=f"{custom['name']} : {argument}" if argument is not None else custom["name"],
            subtitle=f"Tape « {custom['keyword']} … » · {custom['command']}" if needs_argument else command,
            icon=sym("hello-terminal-symbolic", "#2190A4"), accessory=modes.get(custom["mode"]),
            primary=Action("Compléter" if needs_argument else "Exécuter", run),
            secondary=None if needs_argument else Action(
                "Dans le terminal", lambda: (self.c.hide(), desktop.run_in_terminal(command))),
            completion=custom["keyword"] + " " if needs_argument else None, copy_text=command)

    def _process_items(self, query):
        out = []
        for p in shell.Processes.search(query):
            def kill(p=p, force=False):
                ok = shell.Processes.kill(p["pid"], force)
                verb = "tué" if force else "terminé"
                self.flash(f"{p['name']} {verb}" if ok else f"Impossible d'arrêter {p['name']}")
                GLib.timeout_add(500, lambda: (self.refresh(), False)[1])
            out.append(Item(
                id=f"proc:{p['pid']}", title=p["name"], subtitle=f"PID {p['pid']} · {shell.abbreviate(p['path'])}",
                icon=sym("hello-process-symbolic"), accessory="Processus",
                primary=Action("Terminer", kill), secondary=Action("Forcer", lambda p=p: kill(p, True)),
                copy_text=str(p["pid"])))
        return out

    def _port_items(self, flt):
        ports = shell.Ports.listening()
        if ports is None:
            return [Item(id="ports.loading", title="Recherche des ports ouverts…",
                         icon=sym("hello-ports-symbolic", "#3584E4"), primary=Action("Patienter", lambda: None))]
        wanted = int(flt) if flt.strip().isdigit() else None
        found = [p for p in ports if wanted is None or p["port"] == wanted]
        if not found:
            title = f"Rien n'écoute sur le port {wanted}" if wanted else "Aucun port en écoute"
            return [Item(id="ports.none", title=title, icon=sym("hello-ports-none-symbolic"),
                         primary=Action("OK", lambda: None))]
        out = []
        for e in found:
            def stop(e=e, force=False):
                ok = e["pid"] and shell.Processes.kill(e["pid"], force)
                if not force:
                    self.flash(f"Port {e['port']} libéré" if ok else f"Impossible d'arrêter {e['command']}")
                shell.Ports.invalidate()
                GLib.timeout_add(600, lambda: (self.refresh(), False)[1])
            out.append(Item(
                id=f"port:{e['pid']}:{e['port']}", title=f":{e['port']}  ·  {e['command']}",
                subtitle=f"PID {e['pid'] or '?'} · {e['address']}", icon=sym("hello-port-symbolic", "#3584E4"),
                accessory="Port",
                primary=Action("Ouvrir localhost", lambda e=e: (self.c.hide(),
                                                                  desktop.open_uri(f"http://localhost:{e['port']}"))),
                secondary=Action("Arrêter le processus", stop),
                tertiary=Action("Forcer", lambda e=e: stop(e, True)),
                copy_text=f"http://localhost:{e['port']}"))
        return out

    def _ip_items(self):
        def copy(value):
            desktop.copy(value)
            self.c.hide()
        out = [Item(id="ip:" + iface, title=addr, subtitle=f"Adresse locale · {iface}",
                    icon=sym("hello-network-symbolic", "#3584E4"), accessory="IP",
                    primary=Action("Copier", lambda a=addr: copy(a))) for iface, addr in shell.addresses()]
        host = socket.gethostname()
        out.append(Item(id="ip.host", title=host, subtitle="Nom d'hôte", icon=sym("hello-computer-symbolic"),
                        primary=Action("Copier", lambda: copy(host))))
        return out

    # MARK: - Agent

    def agent_items(self, q, explicit):
        """« ? » Auto, « ?? » Recherche & Action, « ??? » Code (le niveau choisi passe en tête)."""
        if not Hermes.available():
            return []
        name = engines.assistant()[0]
        marks = len(q) - len(q.lstrip("?")) if explicit else 0
        request = q[marks:].strip() if explicit else q
        if not request and self.attachments:
            n = len(self.attachments)
            what = (f"ces {n} fichiers" if n > 1 else "cette capture" if self.attachments[0].screenshot
                    else f"« {self.attachments[0].name} »")
            ask = "Qu'est-ce que c'est ? Décris et analyse " + ("les pièces jointes." if n > 1 else "la pièce jointe.")
            return [Item(id="agent.attachments", section="Agent", title=f"Demander à {name} d'analyser {what}",
                         subtitle="Ou écris ce qu'il doit en faire · ⌫ retire le dernier fichier",
                         icon=sym("hello-attach-symbolic", "#9141AC"),
                         primary=Action("Analyser", lambda: self.start_agent(ask, 1)),
                         secondary=Action("Recherche & Action", lambda: self.start_agent(ask, 2)))]
        if not request:
            # « ? » seul : l'invite, puis les dernières conversations à reprendre.
            out = [Item(id="agent.hint", section="Agent", title=f"Demande n'importe quoi à {name}",
                        subtitle="Auto : le niveau 1 choisit · « ?? » Recherche & Action · « ??? » Code · "
                                 "Ctrl O fichier · Ctrl ⇧ S capture",
                        icon=sym("hello-sparkle-symbolic", "#9141AC"), primary=Action("OK", lambda: None))]
            out += [self.chat_item(c, "Conversations récentes") for c in ChatStore.conversations[:4]]
            if len(ChatStore.conversations) > 4:
                out.append(Item(id="agent.chats", section="Conversations récentes", title="Toutes les conversations",
                                subtitle=f"{len(ChatStore.conversations)} conversations avec l'IA",
                                icon=sym("hello-chats-symbolic", "#9141AC"),
                                primary=Action("Ouvrir", lambda: self.enter("chats"))))
            return out
        # Par défaut le niveau 1 décide ; « ?? » et « ??? » forcent un niveau.
        level = min(max(marks, 1), 3)
        title, icon, tint = LEVELS[level]
        return [Item(
            id=f"agent{level}:{request}", section="Agent",
            title=f"Demander à {name} : {request}" if level == 1 else f"{title} : {request}",
            subtitle=f"{level_detail(level)} · {level_model_label(level)}", icon=sym(icon, tint),
            accessory=f"Niveau {level}",
            primary=Action("Demander" if level == 1 else title, lambda: self.start_agent(request, level)),
            secondary=Action("Recherche & Action", lambda: self.start_agent(request, 2)) if level == 1 else None,
            tertiary=Action("Code", lambda: self.start_agent(request, 3)) if level == 1 else None,
            copy_text=request)]

    def start_agent(self, request, level):
        run = AgentRun(request, level, self.attachments)
        self.enter("agent")
        self.attach_agent(run)
        run.start()
        self.changed()

    def attach_agent(self, run):
        self.agent = run
        self.escape_confirmation.reset()

        def changed():
            if run is not self.agent:
                return
            if run.phase == "delegated":
                # Le terminal passe devant : on referme le panneau.
                GLib.timeout_add(800, lambda: (self.c.hide(), False)[1])
            self.changed()

        def finished(run):
            # Fermer Hello ne l'arrête pas : s'il finit pendant ce temps, une notification prévient.
            if run is not self.agent:
                return
            self.escape_confirmation.reset()
            if run.phase in ("answer", "done", "delegated"):
                # La barre de recherche revient, pour une question de suite.
                GLib.idle_add(lambda: (self.c.query_changed(), False)[1])
            if not self.presented and run.phase != "delegated":
                self._unseen_agent_result = True
                self.c.notify_agent(run)

        run.on_change = changed
        run.on_finish = finished

    # Conversations

    def chat_item(self, conversation, section=None):
        """Ligne d'une conversation passée (mode Conversations, et sous « ? » vide)."""
        last = conversation.turns[-1] if conversation.turns else {}
        level = last.get("level") if last.get("level") in LEVELS else 1
        _, icon, tint = LEVELS[level]
        exchanges = f" · {len(conversation.turns)} échanges" if len(conversation.turns) > 1 else ""
        snippet = (last.get("answer") or "").replace("\n", " ")[:90]

        def resume_terminal():
            AgentRun.restoring(conversation).continue_in_terminal()
            self.c.hide()

        def delete():
            ChatStore.delete(conversation.id)
            self.refresh()

        return Item(
            id="chat:" + conversation.id, section=section, title=conversation.title,
            subtitle=f"{relative(conversation.updated)}{exchanges} · {snippet}", icon=sym(icon, tint),
            primary=Action("Reprendre", lambda: self.open_conversation(conversation)),
            secondary=Action("Continuer dans le terminal", resume_terminal) if last.get("sessionID") else None,
            remove=Action("Supprimer", delete), copy_text=last.get("answer"))

    def chat_items(self):
        return [self.chat_item(c) for c in ChatStore.search(self.query)[:80]]

    def open_conversation(self, conversation):
        """Rouvre une conversation dans la vue de l'agent, prête pour une question de suite."""
        if not conversation.turns:
            return
        run = AgentRun.restoring(conversation)
        self.enter("agent")
        self.attach_agent(run)
        self.changed()

    def follow_up(self, text, level):
        """Question de suite : même conversation, l'IA reçoit les échanges précédents."""
        previous = self.agent
        if not previous:
            return
        run = AgentRun(text, level, conversation=previous.conversation)
        self.attach_agent(run)
        self.set_query("")
        self.c.query_changed()
        run.start()
        self.changed()

    # Commandes « / »

    SLASH = [
        # (nom, alias, argument, argument obligatoire, titre, résumé, icône, action(model, args))
        ("resume", ("history", "conversations"), "<recherche>", False, "Reprendre",
         "Reprendre une conversation passée", "hello-chats-symbolic",
         lambda m, a: (m.enter("chats"), m.set_query(a), m.c.query_changed())),
        ("new", ("clear",), "<demande>", False, "Nouvelle", "Nouvelle conversation, sans les échanges précédents",
         "hello-new-symbolic", lambda m, a: m.new_conversation(a)),
        ("fast", (), "<demande>", True, "Demander", "Niveau 1 · Fast : répond tout de suite",
         LEVELS[1][1], lambda m, a: m.ask(a, 1)),
        ("work", ("recherche", "search"), "<demande>", True, "Recherche & Action",
         "Niveau 2 · cherche sur le web et agit sur l'ordinateur", LEVELS[2][1], lambda m, a: m.ask(a, 2)),
        ("code", (), "<demande>", True, "Code", "Niveau 3 · session de code dans le terminal",
         LEVELS[3][1], lambda m, a: m.ask(a, 3)),
        ("retry", ("again",), None, False, "Relancer", "Reposer la dernière demande, au même niveau",
         "hello-refresh-symbolic", lambda m, a: m.retry_last()),
        ("terminal", ("continue",), None, False, "Continuer dans le terminal",
         "Reprendre la conversation dans une session interactive, dans le terminal", "hello-terminal-symbolic",
         lambda m, a: m.continue_last_in_terminal()),
        ("copy", (), None, False, "Copier", "Copier la dernière réponse", "hello-copy-symbolic",
         lambda m, a: m.copy_last_answer()),
        ("delete", ("forget",), None, False, "Supprimer", "Supprimer la conversation de l'historique",
         "hello-trash-symbolic", lambda m, a: m.delete_current_conversation()),
        ("memory", (), None, False, "Mémoire", "Ce que Hermes a retenu de toi (~/.hermes/memories)",
         "hello-help-symbolic", lambda m, a: m.open_hermes_memory()),
        ("model", ("models", "settings"), None, False, "Modèles",
         "Choisir les modèles de chaque niveau (Réglages › Agent)", "hello-models-symbolic",
         lambda m, a: (m.c.hide(), m.c.open_settings("agent"))),
        ("help", (), None, False, "Aide", "Toutes les commandes « / »", "hello-help-symbolic",
         lambda m, a: (m.set_query("/"), m.c.query_changed())),
    ]

    def slash_items(self, text):
        """Commandes « / » correspondant au texte : « /re » propose /resume et /retry, « /code ma demande » la seule
        /code. Un argument tapé : on ne garde que la commande exacte (sinon c'est un chemin, « /home/… »)."""
        if not Hermes.available() or not text.startswith("/"):
            return []
        first, args = shell.split_first(text[1:])
        word = first.lower()
        out = []
        for name, aliases, argument, required, title, summary, icon, run in self.SLASH:
            names = (name,) + aliases
            if args and word not in names:
                continue
            if not args and word and not any(n.startswith(word) for n in names):
                continue
            usage_line = f"/{name}" + (f" {argument}" if argument else "")
            missing = required and not args

            def go(name=name, run=run, missing=missing, args=args):
                if missing:
                    self.set_query(f"/{name} ")
                    self.c.query_changed()
                else:
                    run(self, args)

            out.append(Item(id="slash:" + name, section="Commandes IA",
                            title=f"/{name} {args}" if args else usage_line, subtitle=summary,
                            icon=sym(icon, "#9141AC"), primary=Action(title, go), completion=f"/{name} "))
        return out

    @property
    def current_conversation(self):
        """Conversation visée : celle ouverte dans l'agent, sinon la plus récente de l'historique."""
        if self.mode == "agent" and self.agent and self.agent.conversation.turns:
            return self.agent.conversation
        return ChatStore.conversations[0] if ChatStore.conversations else None

    def ask(self, request, level):
        """Demande à un niveau donné : question de suite dans une conversation ouverte, sinon nouvelle conversation."""
        if self.mode == "agent" and self.agent and not self.agent.is_thinking:
            self.follow_up(request, level)
        else:
            self.start_agent(request, level)

    def new_conversation(self, request):
        if request:
            return self.start_agent(request, 1)
        if self.mode != "root":
            self.back()
        self.set_query("? ")
        self.c.query_changed()

    def retry_last(self):
        conversation = self.current_conversation
        if not conversation or not conversation.turns:
            return self.flash("Aucune demande à relancer")
        from .chats import Conversation
        last = conversation.turns[-1]
        trimmed = Conversation(conversation.turns[:-1], conversation.id)
        run = AgentRun(last["request"], last.get("level") if last.get("level") in LEVELS else 1, conversation=trimmed)
        if self.mode != "agent":
            self.enter("agent")
        self.attach_agent(run)
        self.set_query("")
        self.c.query_changed()
        run.start()
        self.changed()

    def continue_last_in_terminal(self):
        conversation = self.current_conversation
        if not conversation:
            return self.flash("Aucune conversation à continuer")
        if conversation.turns[-1].get("sessionID"):
            AgentRun.restoring(conversation).continue_in_terminal()
        else:
            # Pas de session à reprendre (réponse du niveau 1) : le terminal repart avec les échanges en contexte.
            AgentRun("Reprends cette conversation là où elle s'est arrêtée.", 3, conversation=conversation).start()
        self.c.hide()

    def copy_last_answer(self):
        conversation = self.current_conversation
        if not conversation:
            return self.flash("Aucune réponse à copier")
        desktop.copy(conversation.turns[-1].get("answer") or "")
        self.flash("Réponse copiée")

    def delete_current_conversation(self):
        conversation = self.current_conversation
        if not conversation:
            return self.flash("Aucune conversation à supprimer")
        ChatStore.delete(conversation.id)
        if self.mode == "agent":
            self.back()
        self.flash("Conversation supprimée")

    def open_hermes_memory(self):
        folder = os.path.join(HOME, ".hermes", "memories")
        if not os.path.isdir(folder) or not os.listdir(folder):
            return self.flash("Hermes n'a encore rien retenu")
        self.c.hide()
        desktop.open_path(folder)

    # Pièces jointes

    def attach(self, new):
        fresh = [a for a in new if a not in self.attachments]
        if not fresh:
            return
        self.attachments = self.attachments + fresh
        self.selection = 0
        self.refresh()

    def detach(self, attachment):
        self.attachments = [a for a in self.attachments if a != attachment]
        self.refresh()

    def capture_for_agent(self):
        """Capture d'écran pour l'IA : Hello s'efface le temps de choisir la zone, puis revient tel qu'il était."""
        if Hermes.available():
            self._step_aside(lambda back: GLib.timeout_add(
                200, lambda: (attachmod.capture_screen(lambda a: back([a] if a else [])), False)[1]))

    def pick_files_for_agent(self):
        if Hermes.available():
            name = engines.assistant()[0]
            self._step_aside(lambda back: attachmod.pick_files(back, f"Fichiers à donner à {name}"))

    def drop_files(self, paths):
        """Fichiers glissés sur le panneau."""
        if not Hermes.available() or self.mode != "root":
            return False
        self.attach([attachmod.Attachment(p) for p in paths if os.path.exists(p)])
        return True

    def _step_aside(self, work):
        """Ferme le panneau, laisse `work` faire (capture, sélecteur de fichiers), puis le rouvre avec le texte et les
        pièces jointes d'avant, plus les nouvelles."""
        text, kept = self.query, list(self.attachments)
        self.c.hide()

        def back(added):
            self.c.show()
            self.attachments = kept
            self.attach(added)
            self.set_query(text)
            self.c.query_changed()
        work(back)

    # MARK: - Presse-papiers

    def _clipboard_items(self):
        q = fold(self.query.strip())
        history = self.c.clipboard
        paste_title = "Coller" if self.can_paste else "Copier"
        out = []
        for entry in history.entries:
            if q and q not in history.search_key(entry):
                continue
            icon = ("image", entry.image_path) if entry["kind"] == "image" else \
                ("file", (entry.get("files") or ["/"])[0]) if entry["kind"] == "files" else \
                ("color", entry.hex_color) if entry.hex_color else \
                sym("hello-link-symbolic", "#3584E4") if entry.is_link else sym("hello-text-symbolic")

            def restore(e=entry, paste=True):
                self.c.hide()
                history.restore(e, paste)

            def remove(e=entry):
                history.remove(e)
                self.refresh()

            out.append(Item(
                id=entry["id"], title=entry.title,
                subtitle=" · ".join(x for x in (entry.get("source"), relative(entry["date"])) if x),
                icon=icon, primary=Action(paste_title, restore),
                secondary=Action("Copier", lambda e=entry: restore(e, False)),
                tertiary=Action("Afficher dans le dossier", lambda e=entry: (self.c.hide(),
                                                                             desktop.reveal(e.get("files") or [])))
                if entry["kind"] == "files" else None,
                remove=Action("Supprimer", remove), preview=("clip", entry)))
            if len(out) >= 200:
                break
        return out

    # MARK: - Couleurs

    def pick_color(self):
        self.c.hide()

        def picked(rgb):
            if not rgb:
                return
            stored = self.c.colors.add(*rgb)
            desktop.copy(stored.hex)
            self.c.show("colors")
            self.selection = 1
            self.flash(f"{stored.hex} copié dans le presse-papiers")

        GLib.timeout_add(150, lambda: (colormod.pick_color(picked), False)[1])

    def _copy_and_close(self, value):
        desktop.copy(value)
        self.c.hide()

    def _color_items(self):
        q = fold(self.query.strip())
        out = [Item(id="pick", title="Choisir une couleur à l'écran", subtitle="Ouvre la pipette du bureau",
                    icon=sym("hello-eyedropper-symbolic", "#E01B7A"), primary=Action("Choisir", self.pick_color))]
        for color in self.c.colors.items:
            if q and q not in fold(" ".join(v for _, v in color.formats)):
                continue

            def remove(c=color):
                self.c.colors.remove(c)
                self.refresh()

            out.append(Item(
                id=color["id"], title=color.hex, subtitle=color.rgb, icon=("color", (color["r"], color["g"], color["b"])),
                primary=Action("Copier HEX", lambda c=color: self._copy_and_close(c.hex)),
                secondary=Action("Copier RGB", lambda c=color: self._copy_and_close(c.rgb)),
                tertiary=Action("Copier HSL", lambda c=color: self._copy_and_close(c.hsl)),
                remove=Action("Supprimer", remove), preview=("color", color)))
        return out

    # MARK: - Réglages rapides

    def _panel_items(self):
        current = self.c.panel_mode_cached
        return [Item(id="panel." + v, title=t, subtitle=d, icon=sym(icon, "#613583"),
                     accessory="✓ Actuel" if v == current else None,
                     primary=Action("Appliquer", lambda v=v, t=t: self._apply_panel(v, t)))
                for v, t, d, icon in colormod.PANEL_MODES]

    def _hotkey_items(self):
        hk = self.c.hotkey
        out = [Item(id="hk.configure", title="Changer le raccourci…", subtitle=f"Actuel : {hk.description}",
                    icon=sym("hello-shortcut-symbolic"),
                    primary=Action("Ouvrir", lambda: (self.c.hide(), hk.configure())))]
        for value, title, note in hotkey.CHOICES:
            def use(v=value, t=title):
                settings.hotkey = v
                hk.bind(v, force=True)
                self.flash(f"Raccourci : {t}")
                GLib.timeout_add(1200, lambda: (self.refresh(), False)[1])
            out.append(Item(id="hk." + value, title=title, subtitle=note, icon=sym("hello-keyboard-symbolic"),
                            accessory="✓ Actuel" if value == settings.hotkey else None,
                            primary=Action("Utiliser", use)))
        out.append(Item(id="hk.cli", title="hello --toggle", icon=sym("hello-terminal-symbolic"),
                        subtitle="À associer à n'importe quel raccourci si le portail n'est pas disponible",
                        primary=Action("Copier", lambda: self._copy_and_close("hello --toggle"))))
        return out

    # MARK: - Désinstallation

    def _uninstall_picker_items(self):
        q = fold(self.query.strip())
        found = []
        for app in self.c.apps.apps:
            s = 0 if not q else app.score(q)
            if s is not None:
                found.append((s, app))
        found.sort(key=lambda x: -x[0])
        return [Item(id=app.id, title=app.name, subtitle=app.detail or app.desktop_id, icon=("gicon", app.icon),
                     primary=Action("Choisir", lambda app=app: self._start_uninstall(app, "uninstall")))
                for _, app in found]

    def _start_uninstall(self, app, origin):
        if self.mode == "root":
            self._root_query = self.query
        self._uninstall_return = origin
        self.flash("Recherche des fichiers…")

        def work():
            plan = uninstall.Plan(app)
            GLib.idle_add(self._show_plan, plan)

        threading.Thread(target=work, daemon=True).start()

    def _show_plan(self, plan):
        self._plan = plan
        self._checked = {f.path for f in plan.files}
        self._sizes = {}
        self.toast = None
        self.forward = True
        self.mode = "uninstallFiles"
        self.set_query("")
        self.c.query_changed()

        def sizes():
            for f in plan.files:
                n = uninstall.size(f.path)

                def store(path=f.path, n=n):
                    if self._plan is plan:
                        self._sizes[path] = n
                        if self.mode == "uninstallFiles":
                            self.refresh()
                    return False
                GLib.idle_add(store)

        threading.Thread(target=sizes, daemon=True).start()
        return False

    def _uninstall_file_items(self):
        plan = self._plan
        if not plan:
            return []
        q = fold(self.query.strip())
        checked = [f for f in plan.files if f.path in self._checked]
        total = sum(self._sizes.get(f.path, 0) for f in checked)
        trash_title = f"Désinstaller ({len(checked)} · {uninstall.format_size(total)})"
        out = []
        for f in plan.files:
            if q and q not in fold(f.path + " " + f.kind):
                continue
            is_checked = f.path in self._checked
            is_app = f.kind == "Application"

            def toggle(path=f.path, on=is_checked):
                self._checked.discard(path) if on else self._checked.add(path)
                self.refresh()

            out.append(Item(
                id="rm:" + f.path, section=f"{plan.app.name} · {plan.source}" if is_app else "Fichiers associés",
                title=plan.app.name if is_app else os.path.basename(f.path),
                subtitle=f.kind + " · " + (plan.command or shell.abbreviate(f.path) if is_app
                                           else shell.abbreviate(f.path)),
                icon=("gicon", plan.app.icon) if is_app else ("file", f.path),
                accessory=uninstall.format_size(self._sizes.get(f.path)),
                primary=Action("Garder" if is_checked else "Supprimer", toggle),
                secondary=Action(trash_title, self._perform_uninstall),
                tertiary=Action("Afficher dans le dossier", lambda p=f.path: desktop.reveal([p])),
                checked=is_checked))
        return out

    def _perform_uninstall(self):
        plan = self._plan
        if not plan:
            return
        paths = [f.path for f in plan.files if f.path in self._checked]
        if not paths:
            return self.flash("Rien de coché")
        if self._uninstalling:
            return
        self._uninstalling = True
        remove_app = plan.app.path in paths
        total = sum(self._sizes.get(p, 0) for p in paths)
        app = plan.app

        # L'app tourne : on la ferme d'abord.
        pids = appsmod.running(self.c.apps.apps).get(app.desktop_id, [])
        appsmod.quit_app(pids)

        def work():
            failed = []
            done = 0
            for p in paths:
                if p == app.path and (plan.flatpak or plan.command):
                    continue  # retiré par le gestionnaire de paquets
                if os.path.lexists(p) and not desktop.trash(p):
                    failed.append(p)
                else:
                    done += 1
            ok = True
            if remove_app and plan.flatpak:
                try:
                    import subprocess
                    ok = subprocess.run(["flatpak", "uninstall", "-y", "--noninteractive", plan.flatpak],
                                        capture_output=True, timeout=600).returncode == 0
                except Exception:
                    ok = False
                done += ok

            def finish():
                if remove_app and plan.command:
                    # Paquet du système : le terminal demande le mot de passe et montre ce qui part.
                    self.c.hide()
                    desktop.run_in_terminal(plan.command)
                self.c.apps.refresh()
                self._uninstalling = False
                self._plan = None
                if not self.c.visible and not plan.command:
                    self.c.show()
                self.reset("root")
                if failed or not ok:
                    self.flash(f"{len(failed) + (not ok)} élément(s) n'ont pas pu être supprimés")
                else:
                    self.flash(f"{app.name} désinstallée — {done} élément(s), "
                               f"{uninstall.format_size(total)} à la corbeille")
                return False
            GLib.idle_add(finish)

        threading.Thread(target=work, daemon=True).start()

    # MARK: - Statistiques

    def stats_name(self, item_id):
        if item_id.startswith("path:"):
            path = item_id[5:]
            return (shell.abbreviate(path), ("file", path)) if shell.is_folder(path) else None
        if item_id.startswith("custom:"):
            for custom in settings.customCommands:
                if "custom:" + custom["id"] == item_id:
                    return custom["name"], sym("hello-terminal-symbolic", "#2190A4")
        for app in self.c.apps.apps:
            if app.id == item_id:
                return app.name, ("gicon", app.icon)
        for cmd in self.commands:
            if cmd.id == item_id:
                return cmd.title, cmd.icon
        return None

    def _stats_items(self):
        q = fold(self.query.strip())
        out = []
        rank = 0
        by_app = {a.id: a for a in self.c.apps.apps}
        for item_id in usage.top(200):
            info = self.stats_name(item_id)
            record = usage.records.get(item_id)
            if not info or not record:
                continue
            rank += 1
            if q and q not in fold(info[0]):
                continue
            week = usage.launches(item_id, 7)
            count = record["count"]

            def open_item(item_id=item_id):
                if item_id in by_app:
                    self._launch(by_app[item_id], "")
                elif item_id.startswith("path:"):
                    self.path_item(item_id[5:], None).primary.run()
                else:
                    for cmd in self.commands:
                        if cmd.id == item_id:
                            cmd.action()

            def forget(item_id=item_id):
                usage.forget(item_id)
                self.refresh()

            out.append(Item(
                id="stats:" + item_id, title=f"{rank}. {info[0]}",
                subtitle=f"{count} ouverture{'s' if count > 1 else ''} · {week} cette semaine · "
                         f"{relative(record['last'])}",
                icon=info[1], accessory=" ".join(f"« {s} »" for s in usage.shortcuts(item_id)),
                primary=Action("Ouvrir", open_item), remove=Action("Oublier", forget), preview=("stats", item_id)))
        return out

    # MARK: - Hauteur du panneau

    def preferred_height(self, limit):
        """À l'accueil, juste ce qu'il faut pour les résultats (comme Spotlight), ailleurs la hauteur réglée."""
        if self.collapsed:
            return 60
        if self.mode != "root":
            return limit
        chrome = 60 + 1 + 1 + 40
        if not self.items:
            return min(limit, chrome + 150)
        total = 16
        for i, item in enumerate(self.items):
            if i:
                total += 2
            if item.section and (i == 0 or self.items[i - 1].section != item.section):
                total += 30
            total += row_height()
            if chrome + total >= limit:
                return limit
        return min(limit, chrome + total)

