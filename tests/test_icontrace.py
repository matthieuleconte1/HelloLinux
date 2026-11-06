"""Tests de la 2.1 : icônes au trait de la Nuit (IconOutlineTests.swift) et leur version ASCII."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hello import icontrace  # noqa: E402


@unittest.skipUnless(icontrace.available(), "numpy absent")
class IconOutlineTests(unittest.TestCase):
    def icon(self):
        """Un carré opaque gris, un carré blanc au milieu : le filet suit le bord, le trait intérieur le carré blanc."""
        np = icontrace.np
        rgba = np.zeros((128, 128, 4), dtype=np.float32)
        rgba[16:112, 16:112] = (0.3, 0.3, 0.3, 1)
        rgba[48:80, 48:80] = (1, 1, 1, 1)
        return rgba

    def test_ring_only(self):
        ring = icontrace.outline(self.icon(), 4.5)
        self.assertGreater(ring[64, 18] * 255, 200)   # bord de l'icône
        self.assertEqual(ring[64, 48], 0)             # pas de trait intérieur
        self.assertEqual(ring[64, 4], 0)              # dehors

    def test_inner_lines(self):
        drawing = icontrace.outline(self.icon(), 4.5, detail=0.6, line_width=3)
        self.assertGreater(drawing[64, 18] * 255, 200)
        # Le bord du carré blanc est détouré, du côté sombre ; son centre et le gris uni restent vides.
        self.assertGreater(max(drawing[64, x] for x in range(42, 51)) * 255, 128)
        self.assertEqual(drawing[64, 64], 0)
        self.assertEqual(drawing[64, 32], 0)

    def test_specks_are_removed(self):
        np = icontrace.np
        ink = np.zeros((20, 20), dtype=np.float32)
        ink[2, 2] = 1                  # tache isolée
        ink[10:14, 10:14] = 1          # forme gardée
        cleaned = icontrace._remove_specks(ink, 4)
        self.assertEqual(cleaned[2, 2], 0)
        self.assertEqual(cleaned[11, 11], 1)


class AsciiTests(unittest.TestCase):
    def test_density_ramp(self):
        side = icontrace.ASCII_SIDE
        rows = [[(0, 0, 0, 0)] * side for _ in range(side)]
        rows[0][0] = (255, 255, 255, 255)      # blanc opaque : le plus dense
        rows[0][1] = (20, 20, 20, 255)         # noir opaque : peu dense, mais visible
        cells = {(r, c): ch for r, c, ch in icontrace.ascii_cells(rows)}
        self.assertEqual(cells[(0, 0)], "@")
        self.assertIn(cells[(0, 1)], icontrace.RAMP[1:5])
        self.assertNotIn((5, 5), cells)


if __name__ == "__main__":
    unittest.main()
