"""Tests de la 2.0.0 : agent multi-fournisseurs, conversations, commandes « / », Échap en deux temps,
mises à jour et Atelier Glyphe. python3 -m unittest discover -s tests"""
import json
import os
import sys
import tempfile
import unittest

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")

# Réglages et données dans un dossier jetable (avant tout import de Hello).
if "hello" not in sys.modules:
    _tmp = tempfile.mkdtemp(prefix="hello-tests-")
    os.environ.setdefault("XDG_CONFIG_HOME", os.path.join(_tmp, "config"))
    os.environ.setdefault("XDG_DATA_HOME", os.path.join(_tmp, "data"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hello import decode, engines, updater  # noqa: E402
from hello.chats import ChatStore, Conversation, new_turn  # noqa: E402
from hello.confirm import EscapeConfirmation  # noqa: E402
from hello.settings import glyph_appearance, settings  # noqa: E402


class EscapeConfirmationTests(unittest.TestCase):
    def test_second_press_in_window_confirms(self):
        c = EscapeConfirmation()
        self.assertFalse(c.press("cancel", now=10))
        self.assertTrue(c.press("cancel", now=11))
        # Confirmé : on repart de zéro.
        self.assertFalse(c.press("cancel", now=11.5))

    def test_window_expires(self):
        c = EscapeConfirmation()
        self.assertFalse(c.press("leave", now=0))
        self.assertFalse(c.press("leave", now=2.6))
        self.assertTrue(c.press("leave", now=3))

    def test_other_action_or_reset_starts_over(self):
        c = EscapeConfirmation()
        c.press("cancel", now=0)
        self.assertFalse(c.press("leave", now=0.5))
        c.reset()
        self.assertFalse(c.press("leave", now=1))


class UpdaterTests(unittest.TestCase):
    def test_compare_like_semver(self):
        cmp = updater.compare
        self.assertEqual(cmp("2.0.0", "2.0.0-alpha.2"), 1)
        self.assertEqual(cmp("2.0.0-alpha.2", "2.0.0-alpha.1"), 1)
        self.assertEqual(cmp("2.0.0-alpha.10", "2.0.0-alpha.9"), 1)
        self.assertEqual(cmp("1.9", "2.0.0-alpha.1"), -1)
        self.assertEqual(cmp("2.0", "2.0.0"), 0)
        self.assertEqual(cmp("2.0.0-beta", "2.0.0-alpha"), 1)
        # Étiquettes mal formées : pas de plantage.
        self.assertEqual(cmp("", "v"), 0)
        self.assertEqual(cmp("-beta", "0"), -1)

    def test_newest_takes_linux_asset_and_skips_drafts(self):
        def release(tag, linux=True, **kw):
            assets = [{"name": f"Hello-{tag[1:]}.zip", "browser_download_url": "https://x/mac.zip"}]
            if linux:
                assets.append({"name": updater.asset_name(tag[1:]), "browser_download_url": f"https://x/{tag}.tar.gz"})
            return dict(tag_name=tag, html_url=f"https://x/{tag}", assets=assets, **kw)

        releases = [release("v2.2.0", draft=True), release("v2.1.0-beta.1", prerelease=True),
                    release("v2.0.2", linux=False), release("v2.0.1")]
        self.assertEqual(updater.newest(releases, prereleases=True)["version"], "2.1.0-beta.1")
        found = updater.newest(releases, prereleases=False)
        self.assertEqual((found["version"], found["asset"]), ("2.0.1", "https://x/v2.0.1.tar.gz"))
        self.assertIsNone(updater.newest([release("v3.0.0", linux=False)], True))
        self.assertIsNone(updater.newest({"message": "rate limited"}, True))

    def test_stage_checks_the_archive(self):
        import tarfile
        work = tempfile.mkdtemp()
        source = os.path.join(work, "src", "Hello-linux-9.9.9")
        os.makedirs(os.path.join(source, "hello"))
        with open(os.path.join(source, "hello", "__init__.py"), "w") as f:
            f.write('__version__ = "9.9.9"\n')
        open(os.path.join(source, "install.sh"), "w").close()
        archive = os.path.join(work, "a.tar.gz")
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(source, arcname="Hello-linux-9.9.9")
        old = updater.APP_DIR
        updater.APP_DIR = os.path.join(work, "app")
        try:
            target = updater.stage(archive, tempfile.mkdtemp(), "9.9.9")
            self.assertTrue(os.access(os.path.join(target, "install.sh"), os.X_OK))
            with self.assertRaises(updater.UpdateError):
                updater.stage(archive, tempfile.mkdtemp(), "9.9.8")
        finally:
            updater.APP_DIR = old


class AutoUpdateTests(unittest.TestCase):
    def setUp(self):
        from hello import __version__
        self.version = __version__
        self.Updater = updater.Updater
        self.installed = []
        self.old = (self.Updater.install, self.Updater.ready, self.Updater.state, self.Updater._waiting)
        self.Updater.install = classmethod(lambda cls: self.installed.append(True))
        self.Updater.state = "available"
        self.Updater._waiting = False

    def tearDown(self):
        (install, self.Updater.ready, self.Updater.state, self.Updater._waiting) = self.old
        self.Updater.install = install
        settings.autoUpdateInstall = True

    def test_installs_when_idle_and_waits_otherwise(self):
        self.Updater.ready = lambda: False
        self.Updater._install_when_ready()
        self.assertEqual((self.installed, self.Updater._waiting), ([], True))
        self.Updater._waiting = False
        self.Updater.ready = lambda: True
        self.Updater._install_when_ready()
        self.assertEqual(self.installed, [True])
        settings.autoUpdateInstall = False
        self.Updater._install_when_ready()
        self.assertEqual(self.installed, [True])

    def test_marker_announces_the_new_version_once(self):
        self.assertEqual(updater.REPO, "matthieuleconte1/HelloLinux")
        os.makedirs(os.path.dirname(updater.MARKER), exist_ok=True)
        with open(updater.MARKER, "w") as f:
            json.dump({"from": "1.0.0", "to": self.version, "page": "https://x"}, f)
        self.assertEqual(updater.arrived()["from"], "1.0.0")
        self.assertIsNone(updater.arrived())
        with open(updater.MARKER, "w") as f:
            json.dump({"from": "1.0.0", "to": "0.0.1"}, f)
        self.assertIsNone(updater.arrived())


class DecodeTests(unittest.TestCase):
    def test_finished_frame_preserves_accents_spaces_and_emoji(self):
        for title in ["Réglages Système", "Émoji 🫧", "", "Firefox"]:
            self.assertEqual(decode.frame(title, 1), title)
            self.assertEqual(decode.frame(title, 2), title)

    def test_frame_keeps_length_and_spaces(self):
        text = "Toutes les applications"
        for p in (0, 0.3, 0.6, 0.9):
            f = decode.frame(text, p)
            self.assertEqual(len(f), len(text))
            self.assertEqual([i for i, c in enumerate(f) if c == " " and text[i] == " "],
                             [i for i, c in enumerate(text) if c == " "])
        self.assertNotEqual(decode.frame(text, 0.5), text)

    def test_noise_is_deterministic_and_bounded(self):
        values = [decode.noise(a, b, t) for a in range(-3, 9) for b in range(5) for t in range(4)]
        self.assertTrue(all(0 <= v < 1 for v in values))
        self.assertEqual(decode.noise(3, 4, 5), decode.noise(3, 4, 5))
        self.assertGreater(len(set(values)), len(values) // 2)

    def test_durations(self):
        self.assertAlmostEqual(decode.duration("ab"), 0.324)
        self.assertEqual(decode.duration("x" * 200), 0.6)
        self.assertEqual(decode.duration("x" * 200, quick=True), 0.3)


class EventParserTests(unittest.TestCase):
    def feed(self, engine, events):
        parser = engines.EventParser(engine)
        out = []
        for event in events:
            out += parser.feed(json.dumps(event))
        return out

    def test_hermes(self):
        out = self.feed("hermes", [
            {"type": "tool_use", "name": "terminal", "input": {"command": "ls\npwd"}, "session_id": "s1"},
            {"type": "text", "text": "Bon"}, {"type": "result", "text": " Bonjour "}])
        self.assertEqual(out, [("session", "s1"), ("step", "$ ls ⏎ pwd"), ("text", "Bon"), ("final", "Bonjour")])
        self.assertEqual(self.feed("hermes", [{"type": "result", "text": "", "error": "quota"}]), [("failure", "quota")])

    def test_claude(self):
        out = self.feed("claude", [
            {"type": "system", "subtype": "init", "session_id": "c1"},
            {"type": "stream_event", "event": {"type": "content_block_delta",
                                               "delta": {"type": "text_delta", "text": "Sa"}}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Read", "input": {"file_path": "/etc/hostname"}},
                {"type": "text", "text": "x"}]}},
            {"type": "result", "result": "Salut"}])
        self.assertEqual(out, [("session", "c1"), ("text", "Sa"), ("step", "Lit hostname"), ("final", "Salut")])
        self.assertEqual(self.feed("claude", [{"type": "result", "result": "", "is_error": True}]),
                         [("failure", "Aucune réponse.")])

    def test_codex(self):
        out = self.feed("codex", [
            {"type": "thread.started", "thread_id": "t1"},
            {"type": "item.started", "item": {"type": "command_execution", "command": "/usr/bin/bash -lc \"ls -a\""}},
            {"type": "item.started", "item": {"type": "web_search", "query": "météo"}},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "Fini"}},
            {"type": "turn.completed"}])
        self.assertEqual(out, [("session", "t1"), ("step", "$ ls -a"), ("step", "Cherche « météo »"),
                               ("text", "Fini\n\n"), ("final", "Fini")])
        failed = self.feed("codex", [{"type": "error", "message": "réseau"}, {"type": "turn.completed"}])
        self.assertEqual(failed, [("failure", "réseau")])

    def test_garbage_is_ignored(self):
        parser = engines.EventParser("claude")
        self.assertEqual(parser.feed("pas du json"), [])
        self.assertEqual(parser.feed("[1, 2]"), [])

    def test_unwrap_shell(self):
        self.assertEqual(engines.unwrap_shell("bash -lc date"), "date")
        self.assertEqual(engines.unwrap_shell("/bin/zsh -c 'echo \\\"a\\\"'"), 'echo "a"')
        self.assertEqual(engines.unwrap_shell("ls -la"), "ls -la")


class LevelConfigTests(unittest.TestCase):
    def tearDown(self):
        for level in (1, 2, 3):
            engines.set_engine(level, "hermes")

    def test_arguments_per_engine(self):
        c = engines.LevelConfig("claude", "", "sonnet", "high")
        self.assertEqual(c.model_args(), ["--model", "sonnet", "--effort", "high"])
        self.assertEqual(c.router_args("p")[:2], ["-p", "p"])
        self.assertIn("--no-session-persistence", c.router_args("p"))
        self.assertEqual(c.terminal_command("fais ça"), "claude 'fais ça' --model sonnet --effort high")
        x = engines.LevelConfig("codex", "", "gpt-6-luna", "low")
        self.assertEqual(x.model_args(), ["-m", "gpt-6-luna", "-c", 'model_reasoning_effort="low"'])
        self.assertTrue(x.streams_router and x.needs_timeout)
        self.assertEqual(x.resume_command("abc"), "codex resume abc")
        h = engines.LevelConfig("hermes", "anthropic", "claude-sonnet-5-5", "medium")
        self.assertEqual(h.model_args(), ["-m", "claude-sonnet-5-5", "--provider", "anthropic", "--reasoning", "medium"])
        self.assertFalse(h.needs_timeout)

    def test_set_engine_takes_its_defaults(self):
        engines.set_engine(2, "claude")
        self.assertEqual((settings.agentResearchEngine, settings.agentResearchModel, settings.agentResearchReasoning),
                         ("claude", "sonnet", "medium"))
        self.assertEqual(engines.LevelConfig.of(2).label, "Sonnet 5.5 · Claude Code")
        self.assertEqual(engines.assistant()[0], "l'IA")
        for level in (1, 3):
            engines.set_engine(level, "claude")
        self.assertEqual(engines.assistant()[0], "Claude Code")

    def test_codex_models_cache(self):
        home = tempfile.mkdtemp()
        os.makedirs(os.path.join(home, ".codex"))
        with open(os.path.join(home, ".codex", "models_cache.json"), "w") as f:
            json.dump({"models": [{"slug": "gpt-6-luna", "display_name": "Luna"}, {"slug": "hidden", "visibility": "hide"},
                                  {"slug": "gpt-6.1-sol"}]}, f)
        old = engines.HOME
        engines.HOME = home
        try:
            self.assertEqual(engines.codex_model_list(), [("gpt-6-luna", "Luna"), ("gpt-6.1-sol", "gpt-6.1-sol")])
        finally:
            engines.HOME = old


class ChatTests(unittest.TestCase):
    def setUp(self):
        ChatStore.clear()

    def test_transcript_keeps_recent_turns_and_abridges(self):
        c = Conversation([new_turn(1, f"q{i}", "r" * 2000 if i == 9 else f"a{i}", "answer") for i in range(10)])
        transcript = c.transcript
        self.assertNotIn("q1\n", transcript)
        self.assertIn("User: q2\nAssistant (answered): a2", transcript)
        self.assertIn("r" * 1500 + "…", transcript)
        code = Conversation([new_turn(3, "app", "prompt", "code", attachments=["/tmp/a.png"])])
        self.assertIn("(attached: /tmp/a.png)\nAssistant (sent to a coding session in the terminal)", code.transcript)

    def test_store_moves_updated_conversation_first_and_searches(self):
        a = Conversation([new_turn(1, "météo", "Il pleut", "answer")])
        b = Conversation([new_turn(2, "pommes", "Golden", "answer")])
        ChatStore.save(a)
        ChatStore.save(b)
        a.turns.append(new_turn(1, "et demain ?", "Soleil", "answer"))
        ChatStore.save(a)
        self.assertEqual([c.id for c in ChatStore.conversations], [a.id, b.id])
        self.assertEqual([c.id for c in ChatStore.search("soleil")], [a.id])
        ChatStore.delete(a.id)
        self.assertEqual([c.title for c in ChatStore.conversations], ["pommes"])
        self.assertEqual(Conversation.load(b.dump()).turns, b.turns)


class FakeController:
    """Le strict nécessaire pour faire tourner le modèle sans fenêtre."""

    class Apps:
        apps = []

    class Store:
        entries = []
        items = []

    class Hotkey:
        description = "Alt Espace"

    autostart_path = "/nonexistent/hello.desktop"
    panel_mode_cached = "compact"
    panel_width = 680
    visible = True

    def __init__(self):
        self.apps = self.Apps()
        self.clipboard = self.colors = self.Store()
        self.hotkey = self.Hotkey()
        self.hidden = 0

    def hide(self, **_):
        self.hidden += 1

    def query_changed(self):
        pass

    def morph(self, _apps):
        pass

    def __getattr__(self, name):
        # Les autres actions (quit, show, toggle_autostart…) : sans effet ici.
        return lambda *a, **k: None


class SlashTests(unittest.TestCase):
    def setUp(self):
        from hello.model import LauncherModel
        self.model = LauncherModel(FakeController())
        self.old = dict(engines.EngineStatus.paths)
        engines.EngineStatus.paths = {"claude": "/usr/bin/true"}

    def tearDown(self):
        engines.EngineStatus.paths = self.old

    def titles(self, text):
        return [i.title for i in self.model.slash_items(text)]

    def test_prefix_lists_matching_commands(self):
        # « /re » : resume, retry, et work par son alias « recherche » (comme sur Mac).
        self.assertEqual(self.titles("/re"), ["/resume <recherche>", "/work <demande>", "/retry"])
        self.assertIn("/help", self.titles("/"))
        # Alias : « /search » mène à /work.
        self.assertEqual(self.titles("/sea"), ["/work <demande>"])

    def test_argument_keeps_only_exact_command(self):
        self.assertEqual(self.titles("/code un script"), ["/code un script"])
        # Un chemin n'est pas une commande.
        self.assertEqual(self.titles("/home/moi truc"), [])

    def test_missing_argument_completes_instead_of_running(self):
        item = self.model.slash_items("/work")[0]
        item.primary.run()
        self.assertEqual(self.model.query, "/work ")

    def test_root_shows_slash_before_paths(self):
        self.model.set_query("/new")
        self.assertEqual(self.model.items[0].id, "slash:new")

    def test_escape_twice_leaves_answer(self):
        from hello.agent import AgentRun
        run = AgentRun.restoring(Conversation([new_turn(1, "q", "r", "answer")]))
        self.model.enter("agent")
        self.model.attach_agent(run)
        self.model.set_query("question de suite")
        self.model._escape()
        self.assertEqual((self.model.mode, self.model.query), ("agent", ""))
        self.model._escape()
        self.assertEqual(self.model.mode, "agent")
        self.assertEqual(self.model.toast, "Encore Échap pour revenir à la recherche")
        self.model._escape()
        self.assertEqual(self.model.mode, "root")


class RouteTests(unittest.TestCase):
    def route(self, text):
        from hello.agent import AgentRun
        run = AgentRun("q", 1)
        run.work = lambda content: setattr(run, "routed", ("work", content))
        run.send = lambda content: setattr(run, "routed", ("code", content))
        run._route(text)
        return getattr(run, "routed", None) or (run.phase, run.text)

    def test_strips_copied_level_hint(self):
        self.assertEqual(self.route("ANSWER: 51 — level 1, fast"), ("answer", "51"))
        self.assertEqual(self.route("ANSWER: 51 - level 1"), ("answer", "51"))
        self.assertEqual(self.route("Bien sûr. WORK: ouvre Dolphin — level 2, research and action"),
                         ("work", "ouvre Dolphin"))
        self.assertEqual(self.route("CODE: script de sauvegarde"), ("code", "script de sauvegarde"))
        self.assertEqual(self.route("ANSWER: le niveau 1 — level 1 est le plus bas, puis level 2"),
                         ("answer", "le niveau 1 — level 1 est le plus bas, puis level 2"))
        self.assertEqual(self.route("Juste du texte"), ("answer", "Juste du texte"))


class GlyphTests(unittest.TestCase):
    def tearDown(self):
        settings.panelStyle = "kde"
        settings.glyphAutoNight = False
        settings.glyphAppearance = "auto"
        settings.glyphAccent = "orange"

    def test_auto_night_window(self):
        import datetime
        settings.glyphAppearance = "dark"
        settings.glyphAutoNight = True
        hour = datetime.datetime.now().hour
        settings.glyphNightStart, settings.glyphNightEnd = hour, (hour + 1) % 24
        self.assertEqual(glyph_appearance(), "night")
        settings.glyphNightStart, settings.glyphNightEnd = (hour + 1) % 24, (hour + 2) % 24
        self.assertEqual(glyph_appearance(), "dark")
        settings.glyphNightStart = settings.glyphNightEnd
        self.assertEqual(glyph_appearance(), "dark")
        settings.glyphNightStart, settings.glyphNightEnd = 22, 7

    def test_tokens_and_css(self):
        from hello import styles
        settings.panelStyle = "glyph"
        settings.glyphAppearance = "dark"
        t = styles.tokens()
        self.assertEqual((t["style"], t["surface"], t["selection"], t["primary_key"]),
                         ("glyph", "#050403", "#F1F1F1", ("#ED6A0C", "#FFFFFF")))
        settings.glyphAccent = "mono"
        self.assertEqual(styles.tokens()["primary_key"], ("#FFFFFF", "#050403"))
        settings.glyphAppearance = "night"
        night = styles.tokens()
        self.assertTrue(night["chrome_caps"])
        self.assertEqual(night["mark"][0], "glyph")
        css = styles.css() + styles.reveal_css()
        self.assertIn("dashed", css)
        self.assertIn(".hello-panel.reveal {", css)
        # Glyphe décode ses lignes ; les autres styles les font arriver en cascade (arrive-0…13).
        self.assertNotIn("arrive-0", css)
        for style in ("kde", "glass", "atelier", "phosphor", "paper", "brutal"):
            settings.panelStyle = style
            self.assertIn(f".arrive-{styles.ARRIVAL_ROWS - 1} ", styles.reveal_css())


if __name__ == "__main__":
    unittest.main()
