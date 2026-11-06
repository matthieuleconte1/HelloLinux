"""Tests de la 2.1 : Markdown des réponses de l'IA et formules LaTeX (MarkdownTests.swift)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hello import latex, markdown  # noqa: E402


class MarkdownTests(unittest.TestCase):
    def test_dollar_amounts_are_not_math(self):
        self.assertEqual(markdown.split("De $5 à $10 par mois"), [("markdown", "De $5 à $10 par mois")])
        self.assertEqual(markdown.split("Entre $5-$10"), [("markdown", "Entre $5-$10")])

    def test_inline_and_display_math_are_split_out(self):
        self.assertEqual(markdown.split("Soit $x^2$ et \\(y\\)."),
                         [("markdown", "Soit "), ("math", "x^2", False), ("markdown", " et "), ("math", "y", False),
                          ("markdown", ".")])
        self.assertEqual(markdown.split("`$PATH` vaut $$a$$"), [("markdown", "`$PATH` vaut "), ("math", "a", True)])

    def test_table_cells_keep_pipes_inside_math_and_escapes(self):
        self.assertEqual(markdown.Table.cells("| $|x|$ | a \\| b | `c|d` |"), ["$|x|$", "a | b", "`c|d`"])
        self.assertTrue(markdown.Table.is_separator("|:--|:-:|--:|"))
        self.assertFalse(markdown.Table.is_separator("---"))

    def test_blocks(self):
        blocks = markdown.parse("| A | B |\n|---|--:|\n| 1 | 2 |\n\n$$\n\\frac{1}{2}\n$$\n- [x] fait\n"
                                "  - sous-point\n---")
        self.assertEqual(len(blocks), 5, blocks)
        self.assertEqual(blocks[0][0], "table")
        table = blocks[0][1]
        self.assertEqual(table.header, ["A", "B"])
        self.assertEqual(table.rows, [["1", "2"]])
        self.assertEqual(table.align, ["leading", "trailing"])
        self.assertEqual(blocks[1][0], "math")
        self.assertEqual(blocks[1][1].strip(), "\\frac{1}{2}")
        self.assertEqual(blocks[2], ("task", 0, True, "fait"))
        self.assertEqual(blocks[3][:2], ("bullet", 1))
        self.assertEqual(blocks[3][3], "sous-point")
        self.assertEqual(blocks[4], ("rule",))

    def test_unclosed_display_math_is_shown_as_code_while_streaming(self):
        self.assertEqual(markdown.parse("$$\n\\frac{1}"), [("code", "$$\n\n\\frac{1}", "")])

    def test_inline_markup(self):
        self.assertEqual(markdown.inline_markup("**gras** et *ita* `a*b*c` [lien](https://x.fr) <b>"),
                         "<b>gras</b> et <i>ita</i> <tt>a*b*c</tt> <a href=\"https://x.fr\">lien</a> &lt;b&gt;")
        self.assertEqual(markdown.inline_markup("un\\_mot et 5 \\$"), "un_mot et 5 $")

    def test_simple_math_is_written_in_unicode(self):
        self.assertEqual(latex.plain("x^2 + y_1 \\leq \\alpha"), "𝑥² + 𝑦₁ ≤ 𝛼")
        self.assertEqual(latex.plain("\\mathbb{R}^n"), "ℝⁿ")
        self.assertIsNone(latex.plain("\\frac{a}{b}"))
        self.assertIsNone(latex.plain("\\sum_{i=1}^n i"))

    def test_every_formula_lays_out(self):
        for formula in ["\\frac{a}{b}", "\\sqrt[3]{x+1}", "\\begin{pmatrix} 1 & 2 \\\\ 3 & 4 \\end{pmatrix}",
                        "\\left( \\frac{1}{2} \\right", "}{x", "x^", "\\unknown{x}", "a \\\\ b & c",
                        "\\begin{cases} x & x > 0 \\\\ -x & \\text{sinon} \\end{cases}",
                        "\\int_0^1 f(x)\\,dx", "\\vec{v} + \\hat{x} + \\widetilde{abc}", "\\binom{n}{k}"]:
            self.assertIsNotNone(latex.render(formula, 16, True), formula)

    def test_formula_draws(self):
        import cairo
        box = latex.render("\\sum_{i=1}^n \\frac{1}{i^2} = \\frac{\\pi^2}{6}", 16, True)
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, int(box.width) + 4, int(box.ascent + box.descent) + 4)
        ctx = cairo.Context(surface)
        ctx.set_source_rgb(0, 0, 0)
        box.draw(ctx, 2, 2 + box.ascent)
        surface.flush()
        self.assertTrue(any(surface.get_data()[3::4]), "rien n'a été dessiné")
        # Une fraction en display est plus haute qu'une ligne de texte.
        self.assertGreater(box.ascent + box.descent, 16 * 1.5)


if __name__ == "__main__":
    unittest.main()
