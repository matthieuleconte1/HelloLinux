"""Tests de la logique sans interface : python3 -m unittest discover -s tests"""
import os
import sys
import tempfile
import time
import unittest

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

# Réglages et données dans un dossier jetable (avant tout import de Hello).
_tmp = tempfile.mkdtemp(prefix="hello-tests-")
os.environ["XDG_CONFIG_HOME"] = os.path.join(_tmp, "config")
os.environ["XDG_DATA_HOME"] = os.path.join(_tmp, "data")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hello import fuzzy, shell, usage  # noqa: E402
from hello.clipboard import ClipEntry  # noqa: E402
from hello.colors import StoredColor  # noqa: E402
from hello.glyphs import GlyphIndex  # noqa: E402
from hello.term import TerminalBuffer, TermStyle  # noqa: E402


class FuzzyTests(unittest.TestCase):
    def test_fold(self):
        self.assertEqual(fuzzy.fold("Éditeur Été"), "editeur ete")

    def test_scores_rank_like_macos(self):
        s = fuzzy.score
        self.assertEqual(s("firefox", "firefox"), 1000)
        self.assertEqual(s("fir", "firefox"), 900 - 4)
        self.assertEqual(s("code", "visual studio code"), 800 - 18)
        self.assertEqual(s("vsc", "visual studio code"), 750)
        self.assertEqual(s("fox", "firefox"), 600 - 7)
        self.assertIsNone(s("zz", "firefox"))
        self.assertGreater(s("ffx", "firefox"), 0)

    def test_words_match(self):
        self.assertTrue(fuzzy.words_match("pre pap", "historique du presse papiers"))
        self.assertFalse(fuzzy.words_match("pre xyz", "presse papiers"))


class UsageTests(unittest.TestCase):
    def setUp(self):
        usage.reset()

    def test_learns_prefixes(self):
        usage.record("app:firefox.desktop", "fir")
        self.assertEqual(usage.records["app:firefox.desktop"]["queries"], {"f": 1, "fi": 1, "fir": 1})
        self.assertGreater(usage.boost("app:firefox.desktop", "f"), usage.boost("app:other", "f"))

    def test_frecency_prefers_recent(self):
        now = time.time()
        usage.records["old"] = {"count": 3, "first": 0, "last": 0, "recent": [now - 200 * 86400] * 3, "queries": {}}
        usage.records["new"] = {"count": 3, "first": 0, "last": 0, "recent": [now - 60] * 3, "queries": {}}
        self.assertEqual(usage.top(1), ["new"])
        self.assertEqual(usage.daily("new", 3), [0, 0, 3])


class ShellTests(unittest.TestCase):
    def test_expand_and_abbreviate(self):
        home = os.path.expanduser("~")
        self.assertEqual(shell.expand("~/code"), home + "/code")
        self.assertEqual(shell.expand("code"), home + "/code")
        self.assertEqual(shell.expand("'/tmp/a b'"), "/tmp/a b")
        self.assertEqual(shell.abbreviate(home + "/x"), "~/x")

    def test_split_and_operators(self):
        self.assertEqual(shell.split_first("cd  ~/code"), ("cd", "~/code"))
        self.assertTrue(shell.has_operators("ls | wc"))
        self.assertTrue(shell.is_command("ls"))
        self.assertFalse(shell.is_command("cette-commande-n-existe-pas"))

    def test_completions(self):
        root = tempfile.mkdtemp()
        os.mkdir(os.path.join(root, "Projets"))
        os.mkdir(os.path.join(root, "photos"))
        open(os.path.join(root, "pomme.txt"), "w").close()
        found = shell.completions(root + "/p", folders_only=True)
        self.assertEqual([os.path.basename(p) for p in found], ["photos", "Projets"])

    def test_git_branch(self):
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, ".git"))
        with open(os.path.join(root, ".git", "HEAD"), "w") as f:
            f.write("ref: refs/heads/linux\n")
        self.assertEqual(shell.git_branch(root), "linux")

    def test_shell_run_in_pty(self):
        from gi.repository import GLib
        run = shell.ShellRun("printf '\\033[31mrouge\\033[0m ok'")
        loop = GLib.MainLoop()
        run.on_finish = lambda status: loop.quit()
        run.start()
        GLib.timeout_add_seconds(10, loop.quit)
        loop.run()
        self.assertEqual(run.status, 0)
        self.assertEqual(run.output.strip(), "rouge ok")
        self.assertEqual(run.buffer.lines[0][0][1].fg, 1)


class TerminalTests(unittest.TestCase):
    def test_colors_and_progress(self):
        b = TerminalBuffer()
        b.feed("\x1b[1;32mvert\x1b[0m normal\n10%\r50%\r100%\n")
        self.assertEqual(b.plain_text, "vert normal\n100%\n")
        self.assertEqual(b.lines[0][0][1], TermStyle(fg=2, bold=True))

    def test_split_escape(self):
        b = TerminalBuffer()
        b.feed("a\x1b[3")
        b.feed("8;2;255;0;0mb")
        self.assertEqual(b.plain_text, "ab")
        self.assertEqual(b.lines[0][1][1].fg, (1.0, 0.0, 0.0))


class HotkeyTests(unittest.TestCase):
    def test_qt_key_codes(self):
        from hello.hotkey import key_label, qt_key
        self.assertEqual(qt_key("ALT+space"), 0x08000020)
        self.assertEqual(qt_key("LOGO+r"), 0x10000052)
        self.assertEqual(key_label(qt_key("CTRL+ALT+space")), "Ctrl Alt Espace")
        self.assertIsNone(qt_key("ALT+F13"))


class LinuxTests(unittest.TestCase):
    def test_kde_colors_from_kdeglobals(self):
        from hello import styles
        path = os.path.join(_tmp, "kdeglobals")
        with open(path, "w") as f:
            f.write("[General]\nAccentColor=233,61,88\nfont=SF Pro Text,10,-1,5,400\n"
                    "[Colors:Window]\nBackgroundNormal=11,11,14\nForegroundNormal=252,253,253\n")
        old = styles.KDEGLOBALS
        styles.KDEGLOBALS = path
        styles._kde_cache["colors"] = None
        try:
            k = styles.kde_colors()
            self.assertEqual((k["accent"], k["window"], k["font"]), ("#E93D58", "#0B0B0E", "SF Pro Text"))
            self.assertIn("#E93D58", styles.css())   # style KDE par défaut
        finally:
            styles.KDEGLOBALS = old
            styles._kde_cache["colors"] = None

    def test_tray_pixmaps_are_argb_network_order(self):
        from hello.tray import icon_pixmaps
        pixmaps = icon_pixmaps("#FFFFFF", "#FF0000")
        self.assertEqual([p[0] for p in pixmaps], [16, 22, 24, 32, 48, 64])
        size, _, data = pixmaps[-1]
        self.assertEqual(len(data), size * size * 4)
        opaque = [data[i:i + 4] for i in range(0, len(data), 4) if data[i] == 255]
        self.assertTrue(any(px[1:] == b"\xff\x00\x00" for px in opaque))  # le point, rouge

    def test_settings_save_only_changes(self):
        from hello.settings import settings
        self.assertEqual(settings.panelStyle, "kde")
        settings.panelStyle = "paper"
        self.assertEqual(settings._changed().get("panelStyle"), "paper")
        settings.panelStyle = "kde"
        self.assertNotIn("panelStyle", settings._changed())


class DataTests(unittest.TestCase):
    def test_colors(self):
        c = StoredColor(id="x", r=1.0, g=0.5, b=0.0, date=0)
        self.assertEqual(c.hex, "#FF8000")
        self.assertEqual(c.rgb, "rgb(255, 128, 0)")
        self.assertEqual(c.hsl, "hsl(30, 100%, 50%)")

    def test_clip_entry(self):
        e = ClipEntry(kind="text", text="\n  #FF0000 \n", id="1", date=0)
        self.assertEqual(e.title, "#FF0000")
        self.assertEqual(e.hex_color, (1.0, 0.0, 0.0))
        self.assertTrue(ClipEntry(kind="text", text="https://kde.org").is_link)

    def test_file_url(self):
        from hello.model import file_url_path
        self.assertEqual(file_url_path("'file:///tmp/a%20b.txt'"), "/tmp/a b.txt")
        self.assertIsNone(file_url_path("/tmp/x"))

    def test_glyph_search_french(self):
        results = GlyphIndex.search("coeur", "emoji")
        self.assertTrue(results)
        self.assertTrue(any("heart" in g.key for g in results[:5]))
        flags = GlyphIndex.search("allemagne", "emoji")
        self.assertEqual(flags[0].char, "🇩🇪")
        self.assertEqual(GlyphIndex.search("→", "all")[0].char, "→")


if __name__ == "__main__":
    unittest.main()
