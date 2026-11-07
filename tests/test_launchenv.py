"""Environnement transmis aux apps lancées : python3 -m unittest discover -s tests"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hello.launchenv import RENDERER, choose_renderer, cleaned  # noqa: E402

LIB = "/usr/lib/libgtk4-layer-shell.so"


class LaunchEnvTests(unittest.TestCase):
    def test_retire_layer_shell_empile(self):
        env = cleaned({"LD_PRELOAD": ":".join([LIB] * 4), "HOME": "/home/x"})
        self.assertNotIn("LD_PRELOAD", env)
        self.assertEqual(env["HOME"], "/home/x")

    def test_garde_les_prechargements_de_l_utilisateur(self):
        env = cleaned({"LD_PRELOAD": f"{LIB}:/usr/lib/libmimalloc.so /opt/x/libfoo.so.0"})
        self.assertEqual(env["LD_PRELOAD"], "/usr/lib/libmimalloc.so:/opt/x/libfoo.so.0")

    def test_variante_versionnee(self):
        self.assertNotIn("LD_PRELOAD", cleaned({"LD_PRELOAD": "/usr/lib/x86_64-linux-gnu/libgtk4-layer-shell.so.0"}))

    def test_retire_les_dossiers_de_hello_du_pythonpath(self):
        with tempfile.TemporaryDirectory() as old, tempfile.TemporaryDirectory() as user:
            os.makedirs(os.path.join(old, "hello"))
            os.makedirs(os.path.join(old, "bin"))
            open(os.path.join(old, "hello", "__init__.py"), "w").close()
            open(os.path.join(old, "bin", "hello"), "w").close()
            env = cleaned({"PYTHONPATH": os.pathsep.join([ROOT, old, user])})
            self.assertEqual(env["PYTHONPATH"], user)
            self.assertNotIn("PYTHONPATH", cleaned({"PYTHONPATH": f"{ROOT}{os.pathsep}{old}"}))

    def test_moteur_gl_par_defaut(self):
        env = {}
        self.assertTrue(choose_renderer(env))
        self.assertEqual(env["GSK_RENDERER"], RENDERER)

    def test_moteur_de_l_utilisateur_respecte(self):
        env = {"GSK_RENDERER": "vulkan"}
        self.assertFalse(choose_renderer(env))
        self.assertEqual(env["GSK_RENDERER"], "vulkan")


if __name__ == "__main__":
    unittest.main()
