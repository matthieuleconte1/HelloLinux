"""L'application : une seule instance (D-Bus), le raccourci global, l'ouverture et la fermeture
du panneau (Controller.swift, AppDelegate.swift)."""
import os
import sys
import threading
import time

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from . import colors as colormod
from . import context, engines
from .agent import Hermes
from .apps import AppIndex
from .clipboard import ClipboardHistory
from .colors import ColorStore
from .glyphs import GlyphIndex
from .hotkey import GlobalHotkey
from .model import LauncherModel
from .settings import APP_ID, settings
from . import shell
from .styles import css, reveal_css
from . import updater
from .updater import Updater

AUTOSTART = os.path.join(GLib.get_user_config_dir(), "autostart", APP_ID + ".desktop")
# Icônes de Hello (Phosphor, licence MIT) : hello-<nom>-symbolic, recolorées par GTK comme celles du thème.
ICONS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "icons")


class HelloApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.add_main_option("toggle", ord("t"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             "Ouvre ou ferme le panneau", None)
        self.add_main_option("show", ord("s"), GLib.OptionFlags.NONE, GLib.OptionArg.STRING,
                             "Ouvre le panneau dans un mode (apps, emoji, clipboard, colors, chats…)", "MODE")
        self.add_main_option("query", 0, GLib.OptionFlags.NONE, GLib.OptionArg.STRING,
                             "Ouvre le panneau avec ce texte déjà tapé", "TEXTE")
        self.add_main_option("background", ord("b"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
                             "Démarre sans ouvrir le panneau (ouverture de session)", None)
        self.add_main_option("settings", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE, "Ouvre les réglages", None)
        self.add_main_option("quit", ord("q"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE, "Quitte Hello", None)
        self.window = None
        self.started = False
        self.visible = False
        self.resume_until = 0
        self.last_reveal = 0
        self.panel_mode_cached = None
        self.autostart_path = AUTOSTART
        self.model = LauncherModel(self)
        self.apps = AppIndex(self.model.apps_did_change)
        self.clipboard = ClipboardHistory()
        self.clipboard.on_change = self.model.clipboard_did_change
        self.colors = ColorStore()
        self.hotkey = GlobalHotkey(self.toggle)
        self.hotkey.on_state = self._hotkey_state
        from .tray import TrayIcon
        self.tray = TrayIcon(self)
        self._css = Gtk.CssProvider()
        self._settings_window = None

    # MARK: Démarrage

    def do_startup(self):
        Adw.Application.do_startup(self)
        self.hold()  # pas de fenêtre visible la plupart du temps : l'app reste en vie
        # Clic sur la notification de l'IA : Hello rouvre la conversation.
        show = Gio.SimpleAction.new("show-agent", None)
        show.connect("activate", lambda *_: self.show())
        self.add_action(show)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), self._css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_USER)
        Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).add_search_path(ICONS)
        Adw.StyleManager.get_default().connect("notify::dark", lambda *_: self.apply_style())
        settings.connect(self._setting_changed)

    def _start(self):
        if self.started:
            return
        self.started = True
        from .ui import LauncherWindow
        self.window = LauncherWindow(self, self)
        self.apply_style()
        shell.load_user_path()
        self.apps.refresh()
        self.clipboard.start()
        refresh = lambda: self.model.refresh() if self.visible else None  # noqa: E731
        Hermes.on_change = refresh
        engines.EngineStatus.on_change = refresh
        Updater.on_change = refresh
        Hermes.locate()
        engines.EngineStatus.locate()
        context.clean_up()
        # Mises à jour : installées seules quand le panneau est fermé et que l'IA ne travaille pas.
        Updater.ready = lambda: not self.visible and not (self.model.agent and self.model.agent.is_thinking)
        GLib.timeout_add_seconds(8, lambda: (Updater.check_if_due(), False)[1])
        GLib.timeout_add_seconds(3600, lambda: (Updater.check_if_due(), True)[1])
        update = updater.arrived()
        if update:
            GLib.timeout_add_seconds(2, lambda: (self._updated(update), False)[1])
        self.hotkey.start()
        if settings.showTrayIcon:
            self.tray.start()
        if colormod.plasma_available():
            threading.Thread(target=self._read_panel_mode, daemon=True).start()
        # Changement de thème Plasma : le style KDE (et l'icône de la zone de notification) suivent.
        from .styles import KDEGLOBALS
        self._kde_monitor = Gio.File.new_for_path(KDEGLOBALS).monitor_file(Gio.FileMonitorFlags.NONE, None)
        self._kde_monitor.connect("changed", lambda *_: self._theme_changed())
        # Index des emoji construit en arrière-plan, pour que la première recherche soit instantanée.
        GLib.timeout_add_seconds(3, lambda: (threading.Thread(target=GlyphIndex.warm, daemon=True).start(), False)[1])

    def _hotkey_state(self):
        self.tray.refresh()
        if self.visible:
            self.model.refresh()

    def _read_panel_mode(self):
        mode = colormod.panel_mode()
        GLib.idle_add(lambda: (setattr(self, "panel_mode_cached", mode), False)[1])

    def do_command_line(self, command_line):
        options = command_line.get_options_dict().end().unpack()
        if options.get("quit"):
            self.quit()
            return 0
        first = not self.started
        self._start()
        if options.get("settings"):
            self.open_settings()
        elif options.get("toggle"):
            self.toggle()
        elif options.get("show"):
            self.show(options["show"])
        elif options.get("query") is not None:
            self.show()
            self.model.set_query(options["query"])
            self.query_changed()
        elif not options.get("background"):
            self.show()
        if first and not settings.onboarded:
            settings.onboarded = True
            GLib.timeout_add_seconds(2, self._welcome)
        return 0

    def _updated(self, update):
        from .desktop import notify
        notify(f"Hello est passé à la version {update['to']}", f"Mis à jour depuis la {update['from']}.")
        return False

    def _welcome(self):
        from .desktop import notify
        notify("Hello est prêt", f"Raccourci : {self.hotkey.description}. Ctrl , pour les réglages.")
        return False

    # MARK: Style

    def apply_style(self):
        self._css.load_from_string(css() + reveal_css())
        if self.window:
            self.window.invalidate()
            if self.visible:
                self.model.refresh()

    def _theme_changed(self):
        if getattr(self, "_theme_pending", False):
            return
        self._theme_pending = True

        def apply():
            self._theme_pending = False
            self.apply_style()
            self.tray.refresh()
            return False
        GLib.timeout_add(300, apply)

    def _setting_changed(self, name):
        visual = {"panelStyle", "atelierPalette", "atelierSwap", "atelierAppearance", "atelierColoredSelection",
                  "glyphAccent", "glyphAppearance", "glyphAutoNight", "glyphNightStart", "glyphNightEnd",
                  "glyphNightLevel", "asciiDecode", "phosphorColor", "paperTone", "brutalColor", "glassTintHex", "glassTintAmount", "glassBorder",
                  "highlightHex", "highlightAmount", "cornerRadius", "rowDensity", "textScale", "animationSpeed",
                  "motionIntensity", "showSubtitles", "showAccessories", "showHints", "panelSize"}
        if name in visual:
            self.apply_style()
        elif name == "hotkey" and self.started:
            # Choix fait dans les réglages (le mode Raccourci du panneau appelle bind lui-même).
            if self._settings_window is not None:
                self.hotkey.bind(settings.hotkey, force=True)
        elif name == "showTrayIcon":
            self.tray.start() if settings.showTrayIcon else self.tray.stop()
        elif name in ("clipboardEnabled",):
            self.clipboard.update_monitoring()
        elif name in ("clipboardLimit", "clipboardRetentionDays"):
            self.clipboard.prune()
        elif name in ("focusMode", "showRecents", "agentEnabled", "shellCommands") or name.startswith("agent"):
            self.model.refresh()

    # MARK: Panneau

    @property
    def panel_width(self):
        return self.window._panel_w if self.window else 760

    def toggle(self):
        self.hide() if self.visible else self.show()

    def show(self, mode="root"):
        self._start()
        if mode not in ("root", "apps", "emoji", "clipboard", "colors", "stats", "uninstall", "hotkey", "panel", "chats"):
            mode = "root"
        self.apps.refresh_if_stale()
        w = self.window
        # Nuit automatique de Glyphe : l'horaire est vérifié à chaque ouverture.
        if settings.panelStyle == "glyph" and settings.glyphAutoNight:
            self.apply_style()
        # Hello a été fermé par un clic à côté, ou l'IA travaille (ou a fini) en arrière-plan : on reprend où on en était.
        if mode == "root" and (time.time() < self.resume_until or self.model.agent_in_background):
            self.model.resume()
        else:
            w.apps_mode = mode == "apps"
            self.model.reset(mode)
        self.model.mark_agent_seen()
        Updater.check_if_due()
        self.resume_until = 0
        w.place()
        w._set_panel_size(*w.target_size())
        was_visible = self.visible
        self.visible = True
        self.model.presented = True
        # Rouvert aussitôt (aller-retour au raccourci) : version allégée, sans dessin ni cascade.
        light = time.time() - self.last_reveal < 1.5
        if not was_visible and not light:
            w.begin_reveal()  # avant le rendu : les lignes arrivent en cascade
        w.render()
        w.present()
        if w.ensure_blur():
            self.apply_style()  # le Verre et le style KDE deviennent translucides
        if not was_visible:
            self.last_reveal = time.time()
            w.reveal(light)
        w.entry.grab_focus_without_selecting()

    def hide(self, tint=False, away=False):
        if not self.visible or not self.window:
            return
        self.visible = False
        self.model.presented = False
        self.resume_until = time.time() + 90 if away else 0
        if self.model.run and not self.model.run.running and not away:
            self.model.run = None
        w = self.window
        if settings.animations and tint:
            w.panel.add_css_class("closing")
            GLib.timeout_add(170, lambda: (w.set_visible(False), w.panel.remove_css_class("closing"), False)[2])
        else:
            w.set_visible(False)

    def morph(self, apps):
        if self.window:
            self.window.morph(apps)

    def query_changed(self):
        if self.window:
            self.window.sync_entry()
            self.window.entry.grab_focus_without_selecting()

    def open_settings(self, page=None):
        from .prefs import SettingsWindow
        if self._settings_window is None:
            self._settings_window = SettingsWindow(self)
            self._settings_window.connect("close-request", self._settings_closed)
        if page:
            self._settings_window.show_page(page)
        self._settings_window.present()

    def focus_search(self):
        if self.window and self.visible:
            self.window.entry.grab_focus_without_selecting()

    def notify_agent(self, run):
        """L'IA a fini pendant que Hello était fermé : une notification, et un clic rouvre la conversation."""
        title = engines.TITLES.get(run.engine, "L'IA")
        heading = {"answer": f"{title} a répondu", "done": f"{title} a terminé",
                   "failed": f"{title} n'a pas pu répondre"}.get(run.phase)
        if not heading:
            return
        notification = Gio.Notification.new(heading)
        body = (run.request + " — " + run.text.replace("\n", " "))[:200]
        notification.set_body(body)
        notification.set_icon(Gio.ThemedIcon.new(APP_ID))
        notification.set_default_action("app.show-agent")
        self.send_notification("agent", notification)

    def _settings_closed(self, *_):
        self._settings_window = None
        return False

    def toggle_autostart(self):
        """Lancement à l'ouverture de session (~/.config/autostart). Renvoie le nouvel état."""
        if os.path.exists(AUTOSTART):
            os.remove(AUTOSTART)
            self.model.refresh()
            return False
        os.makedirs(os.path.dirname(AUTOSTART), exist_ok=True)
        # Le lanceur de ~/.local/bin suit les mises à jour ; sinon celui du dossier de Hello.
        installed = os.path.join(os.path.expanduser("~"), ".local", "bin", "hello")
        launcher = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "hello")
        executable = installed if os.path.exists(installed) else launcher if os.path.exists(launcher) else "hello"
        with open(AUTOSTART, "w") as f:
            f.write("[Desktop Entry]\nType=Application\nName=Hello\nComment=Lanceur\n"
                    f"Exec={executable} --background\nIcon={APP_ID}\nX-GNOME-Autostart-enabled=true\n"
                    "NoDisplay=true\n")
        return True

    def quit(self):
        self.clipboard.stop()
        self.tray.stop()
        self.hotkey.stop()
        if self.model.agent:
            self.model.agent.cancel()
        if self.model.run:
            self.model.run.cancel()
        Gio.Application.quit(self)


def main():
    # Avant GTK : libadwaita interroge le portail (thème) dès le démarrage, et le portail n'accepte
    # l'identifiant de l'app que s'il est annoncé avant tout autre appel.
    from . import portal
    portal.register_app()
    GLib.set_application_name("Hello")
    GLib.set_prgname(APP_ID)
    return HelloApp().run(sys.argv)
