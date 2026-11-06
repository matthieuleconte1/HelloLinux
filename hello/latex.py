"""LaTeX des réponses de l'IA, composé sur place, sans dépendance (Math.swift) : un sous-ensemble courant (fractions,
racines, exposants et indices, sommes et intégrales, matrices, `cases`, `aligned`, accents, lettres grecques, ℝ 𝒜 𝐀…)
mis en boîtes comme le fait TeX — une largeur, une hauteur au-dessus de la ligne de base, une profondeur en dessous —
puis dessiné avec Pango et Cairo dans une police mathématique (STIX Two Math si elle est là, sinon Latin Modern Math,
DejaVu Math TeX Gyre ou Noto Sans Math). Le dessin prend la couleur courante du contexte Cairo : l'encre du style.

Les nœuds sont des tuples : (\"atom\", texte, classe), (\"text\", texte), (\"space\", em), (\"row\", [nœuds]),
(\"frac\", num, dén, barre), (\"root\", radicande, indice), (\"scripts\", base, exposant, indice),
(\"op\", nom, symbole, bornes), (\"fenced\", gauche, dedans, droite), (\"accent\", base, genre),
(\"table\", lignes, alignements, gauche, droite, écart).

Repère : y vers le bas (Cairo). Une boîte se dessine depuis son origine posée sur la ligne de base ; les décalages
verticaux des boîtes posées (`place`) comptent vers le haut, comme dans TeX."""

MATH_FAMILY = "STIX Two Math, Latin Modern Math, DejaVu Math TeX Gyre, Noto Sans Math, serif"
TEXT_FAMILY = "STIX Two Text, Latin Modern Roman, DejaVu Serif, serif"

# Classes TeX : ord, op, bin, rel, open, close, punct (None : transparent, une espace).


def node_class(node):
    kind = node[0]
    if kind == "atom":
        return node[2]
    if kind == "space":
        return None
    if kind == "op":
        return "op"
    if kind == "scripts":
        return node_class(node[1]) or "ord"
    return "ord"


# MARK: - Symboles

GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ϵ", "varepsilon": "ε", "zeta": "ζ",
    "eta": "η", "theta": "θ", "vartheta": "ϑ", "iota": "ι", "kappa": "κ", "varkappa": "ϰ", "lambda": "λ",
    "mu": "μ", "nu": "ν", "xi": "ξ", "omicron": "ο", "pi": "π", "varpi": "ϖ", "rho": "ρ", "varrho": "ϱ",
    "sigma": "σ", "varsigma": "ς", "tau": "τ", "upsilon": "υ", "phi": "ϕ", "varphi": "φ", "chi": "χ",
    "psi": "ψ", "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ", "Pi": "Π", "Sigma": "Σ",
    "Upsilon": "Υ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
}

_GREEK_ORDER = "αβγδεζηθικλμνξοπρςστυφχψω"
_GREEK_VARIANTS = {"ϵ": 0x1D716, "ϑ": 0x1D717, "ϰ": 0x1D718, "ϕ": 0x1D719, "ϱ": 0x1D71A, "ϖ": 0x1D71B}


def italic_greek(s):
    """Minuscules grecques en italique mathématique, comme TeX (les capitales restent droites)."""
    if not s:
        return s
    c = s[0]
    index = _GREEK_ORDER.find(c)
    if index >= 0:
        return chr(0x1D6FC + index)
    if c in _GREEK_VARIANTS:
        return chr(_GREEK_VARIANTS[c])
    return s


SYMBOLS = {
    # Opérations
    "pm": ("±", "bin"), "mp": ("∓", "bin"), "times": ("×", "bin"), "div": ("÷", "bin"), "cdot": ("⋅", "bin"),
    "ast": ("∗", "bin"), "star": ("⋆", "bin"), "circ": ("∘", "bin"), "bullet": ("∙", "bin"), "oplus": ("⊕", "bin"),
    "ominus": ("⊖", "bin"), "otimes": ("⊗", "bin"), "odot": ("⊙", "bin"), "cup": ("∪", "bin"), "cap": ("∩", "bin"),
    "setminus": ("∖", "bin"), "wedge": ("∧", "bin"), "land": ("∧", "bin"), "vee": ("∨", "bin"), "lor": ("∨", "bin"),
    "sqcup": ("⊔", "bin"), "sqcap": ("⊓", "bin"), "dagger": ("†", "bin"), "amalg": ("⨿", "bin"),
    # Relations
    "leq": ("≤", "rel"), "le": ("≤", "rel"), "geq": ("≥", "rel"), "ge": ("≥", "rel"), "neq": ("≠", "rel"),
    "ne": ("≠", "rel"), "approx": ("≈", "rel"), "equiv": ("≡", "rel"), "sim": ("∼", "rel"), "simeq": ("≃", "rel"),
    "cong": ("≅", "rel"), "propto": ("∝", "rel"), "ll": ("≪", "rel"), "gg": ("≫", "rel"), "leqslant": ("⩽", "rel"),
    "geqslant": ("⩾", "rel"), "prec": ("≺", "rel"), "succ": ("≻", "rel"), "preceq": ("⪯", "rel"),
    "succeq": ("⪰", "rel"),
    "in": ("∈", "rel"), "notin": ("∉", "rel"), "ni": ("∋", "rel"), "subset": ("⊂", "rel"), "supset": ("⊃", "rel"),
    "subseteq": ("⊆", "rel"), "supseteq": ("⊇", "rel"), "subsetneq": ("⊊", "rel"), "perp": ("⊥", "rel"),
    "parallel": ("∥", "rel"), "mid": ("∣", "rel"), "nmid": ("∤", "rel"), "models": ("⊨", "rel"),
    "vdash": ("⊢", "rel"), "coloneqq": ("≔", "rel"), "doteq": ("≐", "rel"), "asymp": ("≍", "rel"),
    "to": ("→", "rel"), "rightarrow": ("→", "rel"), "leftarrow": ("←", "rel"), "gets": ("←", "rel"),
    "leftrightarrow": ("↔", "rel"), "Rightarrow": ("⇒", "rel"), "Leftarrow": ("⇐", "rel"),
    "Leftrightarrow": ("⇔", "rel"), "implies": ("⟹", "rel"), "impliedby": ("⟸", "rel"), "iff": ("⟺", "rel"),
    "mapsto": ("↦", "rel"), "longrightarrow": ("⟶", "rel"), "longleftarrow": ("⟵", "rel"),
    "longmapsto": ("⟼", "rel"), "Longrightarrow": ("⟹", "rel"), "Longleftrightarrow": ("⟺", "rel"),
    "uparrow": ("↑", "rel"), "downarrow": ("↓", "rel"), "nearrow": ("↗", "rel"), "searrow": ("↘", "rel"),
    "hookrightarrow": ("↪", "rel"), "rightleftharpoons": ("⇌", "rel"), "xrightarrow": ("⟶", "rel"),
    # Symboles
    "infty": ("∞", "ord"), "partial": ("∂", "ord"), "nabla": ("∇", "ord"), "forall": ("∀", "ord"),
    "exists": ("∃", "ord"), "nexists": ("∄", "ord"), "emptyset": ("∅", "ord"), "varnothing": ("∅", "ord"),
    "neg": ("¬", "ord"), "lnot": ("¬", "ord"), "angle": ("∠", "ord"), "triangle": ("△", "ord"),
    "hbar": ("ℏ", "ord"), "ell": ("ℓ", "ord"), "Re": ("ℜ", "ord"), "Im": ("ℑ", "ord"), "aleph": ("ℵ", "ord"),
    "wp": ("℘", "ord"), "prime": ("′", "ord"), "degree": ("°", "ord"), "dots": ("…", "ord"),
    "ldots": ("…", "ord"), "cdots": ("⋯", "ord"), "vdots": ("⋮", "ord"), "ddots": ("⋱", "ord"),
    "therefore": ("∴", "rel"), "because": ("∵", "rel"), "top": ("⊤", "ord"), "bot": ("⊥", "ord"),
    "square": ("□", "ord"), "Box": ("□", "ord"), "checkmark": ("✓", "ord"), "clubsuit": ("♣", "ord"),
    "heartsuit": ("♡", "ord"), "spadesuit": ("♠", "ord"), "diamondsuit": ("♢", "ord"), "imath": ("𝚤", "ord"),
    "jmath": ("𝚥", "ord"), "dag": ("†", "ord"), "S": ("§", "ord"), "P": ("¶", "ord"),
    "langle": ("⟨", "open"), "rangle": ("⟩", "close"), "lfloor": ("⌊", "open"), "rfloor": ("⌋", "close"),
    "lceil": ("⌈", "open"), "rceil": ("⌉", "close"), "lbrace": ("{", "open"), "rbrace": ("}", "close"),
    "vert": ("|", "ord"), "lvert": ("|", "open"), "rvert": ("|", "close"), "Vert": ("‖", "ord"),
    "colon": (":", "punct"), "backslash": ("∖", "ord"),
}

BIG_OPERATORS = {
    "sum": "∑", "prod": "∏", "coprod": "∐", "int": "∫", "iint": "∬", "iiint": "∭", "oint": "∮",
    "bigcup": "⋃", "bigcap": "⋂", "bigoplus": "⨁", "bigotimes": "⨂", "bigodot": "⨀", "bigvee": "⋁",
    "bigwedge": "⋀", "bigsqcup": "⨆",
}
INTEGRALS = "∫∬∭∮"

FUNCTIONS = {
    "sin", "cos", "tan", "cot", "sec", "csc", "arcsin", "arccos", "arctan", "sinh", "cosh", "tanh", "coth",
    "log", "ln", "lg", "exp", "det", "dim", "ker", "deg", "gcd", "arg", "min", "max", "sup", "inf", "lim",
    "liminf", "limsup", "Pr", "hom", "mod", "bmod", "tr", "rank", "sgn", "argmax", "argmin",
}
LIMIT_FUNCTIONS = {"lim", "liminf", "limsup", "max", "min", "sup", "inf", "det", "gcd", "Pr", "argmax", "argmin"}

SPACES = {
    ",": 3 / 18, "thinspace": 3 / 18, ":": 4 / 18, ">": 4 / 18, "medspace": 4 / 18, ";": 5 / 18,
    "thickspace": 5 / 18, "!": -3 / 18, "negthinspace": -3 / 18, " ": 0.25, "enspace": 0.5, "quad": 1, "qquad": 2,
}

_DELIMITERS = {"{": "{", "}": "}", "|": "‖", "lbrace": "{", "rbrace": "}", "langle": "⟨", "rangle": "⟩",
               "vert": "|", "lvert": "|", "rvert": "|", "Vert": "‖", "lVert": "‖", "rVert": "‖",
               "lfloor": "⌊", "rfloor": "⌋", "lceil": "⌈", "rceil": "⌉", "lbrack": "[", "rbrack": "]"}

_FENCES = {"pmatrix": ("(", ")"), "bmatrix": ("[", "]"), "Bmatrix": ("{", "}"), "vmatrix": ("|", "|"),
           "Vmatrix": ("‖", "‖")}

_ALPHABETS = {
    # alphabet : (capitales, minuscules, chiffres, cas particuliers)
    "italic": (0x1D434, 0x1D44E, None, {"h": "ℎ"}),
    "bold": (0x1D400, 0x1D41A, 0x1D7CE, {}),
    "boldItalic": (0x1D468, 0x1D482, None, {}),
    "sans": (0x1D5A0, 0x1D5BA, None, {}),
    "blackboard": (0x1D538, 0x1D552, None, {"C": "ℂ", "H": "ℍ", "N": "ℕ", "P": "ℙ", "Q": "ℚ", "R": "ℝ", "Z": "ℤ"}),
    "script": (0x1D49C, 0x1D4B6, None, {"B": "ℬ", "E": "ℰ", "F": "ℱ", "H": "ℋ", "I": "ℐ", "L": "ℒ", "M": "ℳ",
                                        "R": "ℛ", "e": "ℯ", "g": "ℊ", "o": "ℴ"}),
    "fraktur": (0x1D504, 0x1D51E, None, {"C": "ℭ", "H": "ℌ", "I": "ℑ", "R": "ℜ", "Z": "ℨ"}),
}


def _shift(c, upper, lower, digit=None):
    """Lettre (ou chiffre) latine dans un alphabet mathématique Unicode ; inchangée sinon."""
    o = ord(c)
    if 65 <= o <= 90 and upper is not None:
        return chr(upper + o - 65)
    if 97 <= o <= 122 and lower is not None:
        return chr(lower + o - 97)
    if 48 <= o <= 57 and digit is not None:
        return chr(digit + o - 48)
    return c


# MARK: - Lecture

_STOP_COMMANDS = {"\\", "right", "end"}


class Parser:
    def __init__(self, text):
        self.chars = text
        self.i = 0
        self.alphabet = "italic"

    @classmethod
    def parse(cls, latex):
        p = cls(latex)
        nodes = p.row()
        # Accolade fermante en trop : ignorée.
        while p.peek() == "close":
            p.next()
            nodes += p.row()
        if p.peek() is None:
            return ("row", nodes)
        # Plusieurs lignes (`\\`) ou des colonnes (`&`) hors environnement : alignées comme dans `aligned`.
        p.i = 0
        return p.environment("aligned")

    # Jetons : ("cmd", nom), ("char", c), "open", "close", "sup", "sub", "amp"

    def skip_spaces(self):
        while self.i < len(self.chars) and self.chars[self.i].isspace():
            self.i += 1

    def next(self):
        self.skip_spaces()
        chars = self.chars
        if self.i >= len(chars):
            return None
        c = chars[self.i]
        self.i += 1
        if c == "\\":
            if self.i >= len(chars):
                return ("char", "\\")
            if chars[self.i].isascii() and chars[self.i].isalpha():
                start = self.i
                while self.i < len(chars) and chars[self.i].isascii() and chars[self.i].isalpha():
                    self.i += 1
                name = chars[start:self.i]
                # `\operatorname*` : l'étoile fait partie de la commande.
                if self.i < len(chars) and chars[self.i] == "*" and name == "operatorname":
                    name += "*"
                    self.i += 1
                return ("cmd", name)
            symbol = chars[self.i]
            self.i += 1
            return ("cmd", symbol)
        return {"{": "open", "}": "close", "^": "sup", "_": "sub", "&": "amp"}.get(c, ("char", c))

    def peek(self):
        saved = self.i
        try:
            return self.next()
        finally:
            self.i = saved

    def raw_group(self):
        """Contenu brut entre accolades (`\\text{…}`, `\\begin{…}`), espaces compris."""
        self.skip_spaces()
        chars = self.chars
        if self.i >= len(chars) or chars[self.i] != "{":
            return ""
        self.i += 1
        depth = 1
        out = []
        while self.i < len(chars):
            c = chars[self.i]
            self.i += 1
            if c == "\\" and self.i < len(chars) and chars[self.i] in "{}$%&_#":
                out.append(chars[self.i])
                self.i += 1
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    break
            out.append(c)
        return "".join(out)

    def optional_argument(self):
        """Argument optionnel entre crochets (`\\sqrt[3]{x}`)."""
        self.skip_spaces()
        chars = self.chars
        if self.i >= len(chars) or chars[self.i] != "[":
            return None
        self.i += 1
        start = self.i
        while self.i < len(chars) and chars[self.i] != "]":
            self.i += 1
        out = chars[start:self.i]
        self.i += 1
        return out

    @staticmethod
    def stops(token):
        if token in ("close", "amp"):
            return True
        return isinstance(token, tuple) and token[0] == "cmd" and token[1] in _STOP_COMMANDS

    def row(self):
        """Une suite d'atomes, jusqu'à une fin de groupe, une cellule, `\\right` ou `\\end`."""
        nodes = []
        while True:
            token = self.peek()
            if token is None or self.stops(token):
                break
            self.next()
            if token in ("sup", "sub"):
                argument = self.argument()
                base = nodes.pop() if nodes else ("atom", "", "ord")
                if base[0] == "scripts":
                    _, inner, sup, sub = base
                    if token == "sup":
                        sup = argument
                    else:
                        sub = argument
                    nodes.append(("scripts", inner, sup, sub))
                else:
                    nodes.append(("scripts", base, argument if token == "sup" else None,
                                  argument if token == "sub" else None))
            else:
                node = self.atom(token)
                if node is not None:
                    nodes.append(node)
        # Fin du texte sans `}` fermante : le groupe ouvert est simplement refermé.
        return nodes

    def argument(self):
        """Argument d'une commande ou d'un exposant : un groupe ou un seul atome."""
        token = self.next()
        if token is None:
            return ("row", [])
        return self.atom(token) or ("row", [])

    def group(self):
        nodes = self.row()
        if self.peek() == "close":
            self.next()
        return nodes[0] if len(nodes) == 1 else ("row", nodes)

    def styled(self, alphabet):
        saved = self.alphabet
        self.alphabet = alphabet
        try:
            return self.argument()
        finally:
            self.alphabet = saved

    def atom(self, token):
        if token == "open":
            return self.group()
        if token in ("close", "amp", "sup", "sub"):
            return None
        kind, value = token
        if kind == "char":
            return self.character(value)
        return self.command(value)

    def character(self, c):
        if c.isalpha():
            return ("atom", self.letter(c), "ord")
        if c.isdigit():
            return ("atom", _shift(c, None, None, 0x1D7CE) if self.alphabet == "bold" else c, "ord")
        if c == "+":
            return ("atom", "+", "bin")
        if c == "-":
            return ("atom", "−", "bin")
        if c == "*":
            return ("atom", "∗", "bin")
        if c in "=<>:":
            return ("atom", c, "rel")
        if c in ",;":
            return ("atom", c, "punct")
        if c in "([":
            return ("atom", c, "open")
        if c in ")]!?":
            return ("atom", c, "close")
        if c == "'":
            return ("atom", "′", "ord")
        if c == "~":
            return ("space", 0.33)
        return ("atom", c, "ord")

    def letter(self, c):
        if self.alphabet == "roman":
            return c
        upper, lower, digit, special = _ALPHABETS[self.alphabet]
        return special.get(c) or _shift(c, upper, lower, digit)

    def command(self, name):
        if name in SYMBOLS:
            symbol, cls = SYMBOLS[name]
            return ("atom", symbol, cls)
        if name in GREEK:
            greek = GREEK[name]
            return ("atom", italic_greek(greek) if self.alphabet == "italic" else greek, "ord")
        if name in BIG_OPERATORS:
            symbol = BIG_OPERATORS[name]
            return ("op", symbol, True, symbol not in INTEGRALS)
        if name in FUNCTIONS:
            return ("op", name, False, name in LIMIT_FUNCTIONS)
        if name in SPACES:
            return ("space", SPACES[name])
        if name in ("frac", "dfrac", "tfrac", "cfrac"):
            numerator = self.argument()
            return ("frac", numerator, self.argument(), True)
        if name in ("binom", "dbinom", "tbinom"):
            top = self.argument()
            return ("fenced", "(", ("frac", top, self.argument(), False), ")")
        if name == "sqrt":
            index = self.optional_argument()
            index = Parser.parse(index) if index is not None else None
            return ("root", self.argument(), index)
        if name == "left":
            opening = self.delimiter()
            inner = self.row()
            if self.peek() == ("cmd", "right"):
                self.next()
            return ("fenced", opening, ("row", inner), self.delimiter())
        if name == "right":
            return None
        if name in ("middle", "big", "Big", "bigg", "Bigg", "bigl", "bigr", "Bigl", "Bigr", "biggl", "biggr"):
            d = self.delimiter()
            return ("atom", d, "open" if name.endswith("l") else "close" if name.endswith("r") else "ord")
        if name == "begin":
            return self.environment(self.raw_group())
        if name in ("text", "textrm", "textup", "mbox", "hbox", "textnormal", "textit", "textbf", "textsf", "texttt"):
            return ("text", self.raw_group())
        if name == "operatorname":
            return ("op", self.raw_group(), False, False)
        if name == "operatorname*":
            return ("op", self.raw_group(), False, True)
        styles = {"mathrm": "roman", "rm": "roman", "mathup": "roman", "mathit": "italic", "mathbf": "bold",
                  "bf": "bold", "bold": "bold", "boldsymbol": "boldItalic", "bm": "boldItalic",
                  "mathbb": "blackboard", "Bbb": "blackboard", "mathcal": "script", "mathscr": "script",
                  "mathfrak": "fraktur", "mathsf": "sans"}
        if name in styles:
            return self.styled(styles[name])
        if name in ("hat", "widehat", "bar", "overline", "vec", "overrightarrow", "tilde", "widetilde", "dot", "ddot",
                    "underline", "check", "breve", "acute", "grave"):
            return ("accent", self.argument(), name)
        if name == "not":
            token = self.next()
            node = self.atom(token) if token is not None else None
            if node is None:
                return ("atom", "/", "ord")
            if node[0] == "atom":
                return ("atom", node[1] + "\u0338", node[2])
            return node
        if name == "color":
            self.raw_group()
            return None
        if name in ("textcolor", "colorbox"):
            self.raw_group()
            return self.argument()
        if name in ("label", "tag"):
            self.raw_group()
            return None
        if name in ("displaystyle", "textstyle", "scriptstyle", "limits", "nolimits", "nonumber", "notag"):
            return None
        if name in ("overbrace", "underbrace", "boxed", "phantom", "mathop", "mathrel", "mathbin", "mathord"):
            return self.argument()
        if name in ("{", "}", "%", "$", "#", "&", "_"):
            return ("atom", name, "open" if name == "{" else "close" if name == "}" else "ord")
        if name == "|":
            return ("atom", "‖", "ord")
        if name == "\\":
            return None
        return ("text", "\\" + name)

    def delimiter(self):
        """Délimiteur après `\\left`, `\\right`, `\\big`… : un caractère ou une commande ; « . » : aucun."""
        token = self.next()
        if not isinstance(token, tuple):
            return ""
        kind, value = token
        if kind == "char":
            return {".": "", "<": "⟨", ">": "⟩"}.get(value, value)
        return _DELIMITERS.get(value, "")

    def environment(self, name):
        env = name.replace("*", "")
        columns = None
        if env == "array":
            columns = [{"l": "left", "c": "center", "r": "right"}[c] for c in self.raw_group() if c in "lcr"]
        elif env == "alignat":
            self.raw_group()
        rows = [[]]
        while True:
            cell = self.row()
            rows[-1].append(cell[0] if len(cell) == 1 else ("row", cell))
            token = self.next()
            if token is None:
                break
            if token == "amp":
                continue
            if token == ("cmd", "\\"):
                self.optional_argument()
                rows.append([])
            elif token == ("cmd", "end"):
                self.raw_group()
                break
            else:
                break
        # `\\` final : pas de ligne vide en bas.
        if len(rows) > 1 and len(rows[-1]) == 1 and rows[-1][0] == ("row", []):
            rows.pop()
        count = max((len(r) for r in rows), default=1)
        if env in ("equation", "displaymath", "math"):
            return rows[0][0] if rows and rows[0] else ("row", [])
        if env in ("aligned", "align", "alignat", "split", "eqnarray", "flalign"):
            align = ["center"] if count == 1 else ["right" if c % 2 == 0 else "left" for c in range(count)]
            return ("table", rows, align, "", "", 0)
        if env in ("gathered", "gather", "multline"):
            return ("table", rows, ["center"], "", "", 0)
        if env in ("cases", "dcases"):
            return ("table", rows, ["left", "left"], "{", "", 1)
        if env == "rcases":
            return ("table", rows, ["left", "left"], "", "}", 1)
        left, right = _FENCES.get(env, ("", ""))
        return ("table", rows, columns or ["center"], left, right, 0.9)


def parse(latex):
    return Parser.parse(latex)


# MARK: - Composition

class Box:
    """Une boîte à la TeX : largeur, hauteur au-dessus de la ligne de base, profondeur en dessous, et de quoi se
    dessiner depuis son origine (x, ligne de base y ; y vers le bas)."""
    __slots__ = ("width", "ascent", "descent", "draw")

    def __init__(self, width, ascent, descent, draw=None):
        self.width = width
        self.ascent = ascent
        self.descent = descent
        self.draw = draw or (lambda ctx, x, y: None)


def empty():
    return Box(0, 0, 0)


def place(parts, width):
    """Boîtes posées les unes par rapport aux autres : (boîte, décalage horizontal, hauteur de sa ligne de base)."""
    ascent = max((b.ascent + dy for b, _, dy in parts), default=0)
    descent = max((b.descent - dy for b, _, dy in parts), default=0)

    def draw(ctx, x, y):
        for box, dx, dy in parts:
            box.draw(ctx, x + dx, y - dy)
    return Box(width, max(ascent, 0), max(descent, 0), draw)


class Style:
    __slots__ = ("size", "base", "display", "script")

    def __init__(self, size, base, display, script=False):
        self.size = size
        self.base = base
        self.display = display
        # Indices et exposants : ni espace moyen, ni espace large (comme TeX).
        self.script = script

    @property
    def axis(self):
        """Axe mathématique (barre de fraction, centre des délimiteurs)."""
        return self.size * 0.258

    @property
    def rule(self):
        return max(self.size * 0.066, 0.7)

    def script_style(self):
        return Style(max(self.size * 0.7, self.base * 0.5), self.base, False, True)

    def fraction_style(self):
        if self.display:
            return Style(self.size, self.base, False, self.script)
        return Style(max(self.size * 0.8, self.base * 0.5), self.base, False, self.script)

    def text_style(self):
        return Style(self.size, self.base, False, self.script)


# Pango : un seul contexte de mesure, sans crénage ni ajustement à la grille (les mesures valent pour tout dessin).
_pango = {}


def _context():
    if "context" not in _pango:
        import gi
        gi.require_version("Pango", "1.0")
        gi.require_version("PangoCairo", "1.0")
        import cairo
        from gi.repository import Pango, PangoCairo
        context = PangoCairo.FontMap.get_default().create_context()
        options = cairo.FontOptions()
        options.set_hint_metrics(cairo.HINT_METRICS_OFF)
        options.set_hint_style(cairo.HINT_STYLE_NONE)
        options.set_antialias(cairo.ANTIALIAS_GRAY)
        PangoCairo.context_set_font_options(context, options)
        try:
            context.set_round_glyph_positions(False)
        except AttributeError:
            pass
        _pango.update(context=context, Pango=Pango, PangoCairo=PangoCairo)
    return _pango["context"]


def _layout(text, family, size):
    context = _context()
    Pango = _pango["Pango"]
    layout = Pango.Layout.new(context)
    font = Pango.FontDescription.from_string(family)
    font.set_absolute_size(size * Pango.SCALE)
    layout.set_font_description(font)
    layout.set_text(text, -1)
    return layout


_x_heights = {}


def _x_height(family, size):
    key = (family, round(size, 2))
    if key not in _x_heights:
        layout = _layout("x", family, size)
        Pango = _pango["Pango"]
        ink, _ = layout.get_extents()
        baseline = layout.get_baseline() / Pango.SCALE
        _x_heights[key] = max(baseline - ink.y / Pango.SCALE, size * 0.4)
    return _x_heights[key]


def glyph(text, family, size):
    if not text:
        return empty()
    layout = _layout(text, family, size)
    Pango = _pango["Pango"]
    ink, logical = layout.get_extents()
    scale = Pango.SCALE
    baseline = layout.get_baseline() / scale
    width = logical.width / scale
    x_height = _x_height(family, size)
    if ink.width == 0 or ink.height == 0:
        ascent, descent = x_height, 0
    else:
        ascent = max(baseline - ink.y / scale, x_height)
        descent = max((ink.y + ink.height) / scale - baseline, 0)
    show = _pango["PangoCairo"].show_layout

    def draw(ctx, x, y):
        ctx.move_to(x, y - baseline)
        show(ctx, layout)
        ctx.new_path()
    return Box(width, ascent, descent, draw)


def math_glyph(text, size):
    return glyph(text, MATH_FAMILY, size)


def text_glyph(text, size):
    return glyph(text, TEXT_FAMILY, size)


def _centered(text, size, axis):
    """Glyphe centré sur l'axe (grands opérateurs)."""
    box = math_glyph(text, size)
    shift = axis - (box.ascent - box.descent) / 2
    draw = box.draw
    return Box(box.width, box.ascent + shift, box.descent - shift, lambda ctx, x, y: draw(ctx, x, y - shift))


def layout(node, style):
    kind = node[0]
    if kind == "atom":
        return math_glyph(node[1], style.size)
    if kind == "text":
        return text_glyph(node[1], style.size)
    if kind == "space":
        return Box(node[1] * style.size, 0, 0)
    if kind == "row":
        return row(node[1], style)
    if kind == "frac":
        return _fraction(node[1], node[2], node[3], style)
    if kind == "root":
        return _root(node[1], node[2], style)
    if kind == "scripts":
        return _scripts(node[1], node[2], node[3], style)
    if kind == "op":
        _, name, symbol, _limits = node
        if symbol:
            integral = name in INTEGRALS
            scale = (1.75 if integral else 1.45) if style.display else (1.25 if integral else 1.1)
            return _centered(name, style.size * scale, style.axis)
        return text_glyph(name, style.size)
    if kind == "fenced":
        _, left, inner, right = node
        content = layout(inner, style)
        opening = _delimiter_around(left, content, style)
        closing = _delimiter_around(right, content, style)
        gap = style.size * 0.04
        return place([(opening, 0, 0), (content, opening.width + gap, 0),
                      (closing, opening.width + gap * 2 + content.width, 0)],
                     opening.width + content.width + closing.width + gap * 2)
    if kind == "accent":
        return _accent(node[1], node[2], style)
    if kind == "table":
        _, rows, align, left, right, gap = node
        return _table(rows, align, left, right, gap, style)
    return empty()


def _spacing(left, right):
    """Espaces de TeX entre classes, en dix-huitièmes d'em ; négatif : seulement hors indices et exposants."""
    if (left, right) in (("ord", "op"), ("op", "ord"), ("op", "op"), ("close", "op")):
        return 3
    if left == "bin" or right == "bin":
        return -4
    if (left, right) in (("rel", "rel"), ("open", "rel"), ("rel", "close"), ("rel", "punct")):
        return 0
    if left == "rel" or right == "rel":
        return -5
    if left == "punct":
        return -3
    return 0


_BIN_AFTER = {"bin", "op", "rel", "open", "punct"}


def row(nodes, style, after_ord=False):
    """`after_ord` : la ligne continue une cellule précédente (colonne de droite d'un `aligned`, qui commence par =)."""
    # Classes effectives : un « − » en tête ou après une relation est un signe (ord), pas une soustraction.
    classes = []
    previous = "ord" if after_ord else None
    for node in nodes:
        cls = node_class(node)
        if cls is None:
            classes.append(None)
            continue
        if cls == "bin" and (previous is None or previous in _BIN_AFTER):
            cls = "ord"
        classes.append(cls)
        previous = cls
    for index in range(len(classes) - 1, -1, -1):
        if classes[index] is not None:
            if classes[index] == "bin":
                classes[index] = "ord"
            break
    parts = []
    x = 0.0
    previous = "ord" if after_ord else None
    for node, cls in zip(nodes, classes):
        if cls is not None and previous is not None:
            gap = _spacing(previous, cls)
            if gap > 0 or not style.script:
                x += abs(gap) / 18 * style.size
        box = layout(node, style)
        parts.append((box, x, 0))
        x += box.width
        if cls is not None:
            previous = cls
    return place(parts, x)


def _fraction(numerator, denominator, bar, style):
    inner = style.fraction_style()
    top = layout(numerator, inner)
    bottom = layout(denominator, inner)
    rule = style.rule if bar else 0
    gap = style.size * (0.16 if style.display else 0.11) + (0 if bar else style.size * 0.1)
    pad = style.size * 0.12
    width = max(top.width, bottom.width) + pad * 2
    up = style.axis + rule / 2 + gap + top.descent
    down = rule / 2 + gap + bottom.ascent - style.axis

    def draw_bar(ctx, x, y):
        if bar:
            ctx.rectangle(x + pad * 0.5, y - style.axis - rule / 2, width - pad, rule)
            ctx.fill()
    return place([(top, (width - top.width) / 2, up), (Box(width, 0, 0, draw_bar), 0, 0),
                  (bottom, (width - bottom.width) / 2, -down)], width)


def _root(radicand, index, style):
    body = layout(radicand, style)
    rule = style.rule
    s = style.size
    gap = s * (0.16 if style.display else 0.1)
    top = max(body.ascent, s * 0.7) + gap
    bottom = -max(body.descent, s * 0.05) - s * 0.04
    sign = s * 0.6
    # Indice de la racine (∛) : petit, posé dans le creux du signe.
    index_box = layout(index, Style(max(s * 0.5, style.base * 0.45), style.base, False, True)) if index else None
    lead = max((index_box.width if index_box else 0) - sign * 0.45, 0)
    height = top - bottom

    def draw(ctx, ox, oy):
        import cairo
        x = ox + lead

        def p(dx, dy):
            return x + dx, oy - dy
        ctx.set_line_join(cairo.LINE_JOIN_ROUND)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.set_line_width(rule)
        ctx.move_to(*p(s * 0.04, bottom + height * 0.42))
        ctx.line_to(*p(s * 0.16, bottom + height * 0.5))
        ctx.stroke()
        ctx.set_line_width(rule * 1.9)
        ctx.move_to(*p(s * 0.16, bottom + height * 0.5))
        ctx.line_to(*p(sign * 0.5, bottom))
        ctx.stroke()
        ctx.set_line_width(rule)
        ctx.move_to(*p(sign * 0.5, bottom))
        ctx.line_to(*p(sign, top + rule / 2))
        ctx.line_to(*p(sign + body.width + s * 0.1, top + rule / 2))
        ctx.stroke()
    shape = Box(lead + sign + body.width + s * 0.12, top + rule, -bottom, draw)
    parts = [(shape, 0, 0), (body, lead + sign + s * 0.04, 0)]
    if index_box:
        parts.append((index_box, max(lead + sign * 0.45 - index_box.width, 0),
                      bottom + height * 0.56 + index_box.descent))
    return place(parts, shape.width)


def _scripts(base, sup, sub, style):
    small = style.script_style()
    s = style.size
    # Bornes dessus et dessous (∑, lim) en display.
    if base[0] == "op" and base[3] and style.display:
        op = layout(base, style)
        upper = layout(sup, small) if sup else None
        lower = layout(sub, small) if sub else None
        width = max(op.width, upper.width if upper else 0, lower.width if lower else 0)
        parts = [(op, (width - op.width) / 2, 0)]
        if upper:
            parts.append((upper, (width - upper.width) / 2, op.ascent + s * 0.12 + upper.descent))
        if lower:
            parts.append((lower, (width - lower.width) / 2, -(op.descent + s * 0.1 + lower.ascent)))
        return place(parts, width)
    box = layout(base, style)
    upper = layout(sup, small) if sup else None
    lower = layout(sub, small) if sub else None
    up = max(s * 0.36, box.ascent - s * 0.28)
    down = max(s * 0.2, box.descent + s * 0.05 * (1 if box.descent > s * 0.3 else 0))
    if upper:
        up = max(up, upper.descent + s * 0.12)
    if lower:
        down = max(down, lower.ascent - s * 0.4)
    if upper and lower:
        clash = s * 0.18 - ((up - upper.descent) - (lower.ascent - down))
        if clash > 0:
            down += clash
    # Les intégrales penchent : leur exposant part plus loin que leur indice.
    sup_kern = s * 0.12 if base[0] == "op" and base[2] and base[1] in INTEGRALS else 0
    x = box.width + s * 0.04
    parts = [(box, 0, 0)]
    if upper:
        parts.append((upper, x + sup_kern, up))
    if lower:
        parts.append((lower, x - sup_kern * 0.6, -down))
    width = x + max((upper.width if upper else 0) + sup_kern, (lower.width if lower else 0) - sup_kern * 0.6) + s * 0.04
    return place(parts, width)


_MARKS = {"hat": "ˆ", "widehat": "ˆ", "tilde": "˜", "widetilde": "˜", "dot": "˙", "ddot": "¨", "check": "ˇ",
          "breve": "˘", "acute": "´", "grave": "`"}


def _accent(base, kind, style):
    import cairo
    box = layout(base, style)
    s = style.size
    rule = style.rule
    # Les lettres italiques penchent : l'accent se décale un peu vers la droite.
    skew = s * 0.06 if base[0] == "atom" and base[2] == "ord" and len(base[1]) == 1 else 0
    if kind in ("bar", "overline"):
        inset = box.width * 0.08 if kind == "bar" else 0
        y = box.ascent + s * 0.1

        def draw_bar(ctx, ox, oy):
            ctx.rectangle(ox + inset + skew, oy - y - rule, box.width - inset * 2, rule)
            ctx.fill()
        return place([(box, 0, 0), (Box(box.width, y + rule, 0, draw_bar), 0, 0)], box.width)
    if kind == "underline":
        y = -box.descent - s * 0.12

        def draw_under(ctx, ox, oy):
            ctx.rectangle(ox, oy - y, box.width, rule)
            ctx.fill()
        return place([(box, 0, 0), (Box(box.width, 0, -y + rule, draw_under), 0, 0)], box.width)
    if kind in ("vec", "overrightarrow"):
        y = box.ascent + s * 0.16
        width = max(box.width, s * 0.45)

        def draw_arrow(ctx, ox, oy):
            x0 = ox + (box.width - width) / 2 + skew
            x1 = x0 + width
            yy = oy - y
            ctx.set_line_width(rule)
            ctx.set_line_cap(cairo.LINE_CAP_ROUND)
            ctx.set_line_join(cairo.LINE_JOIN_ROUND)
            ctx.move_to(x0, yy)
            ctx.line_to(x1, yy)
            ctx.move_to(x1 - s * 0.12, yy - s * 0.08)
            ctx.line_to(x1, yy)
            ctx.line_to(x1 - s * 0.12, yy + s * 0.08)
            ctx.stroke()
        return place([(box, 0, 0), (Box(width, y + s * 0.1, 0, draw_arrow), 0, 0)], box.width)
    mark_text = _MARKS.get(kind, "ˆ")
    mark = math_glyph(mark_text, s)
    # Encre de la marque : son bas et son haut au-dessus de la ligne de base.
    layout_ = _layout(mark_text, MATH_FAMILY, s)
    Pango = _pango["Pango"]
    ink, _ = layout_.get_extents()
    baseline = layout_.get_baseline() / Pango.SCALE
    ink_w = ink.width / Pango.SCALE
    has_ink = ink.width > 0 and ink.height > 0
    min_y = baseline - (ink.y + ink.height) / Pango.SCALE if has_ink else 0   # bas de l'encre, vers le haut
    max_y = baseline - ink.y / Pango.SCALE if has_ink else 0
    # Accent large sur plusieurs lettres : étiré en largeur.
    stretch = max(box.width * 0.9 / max(ink_w, 1), 1) if kind.startswith("wide") else 1
    dy = box.ascent + s * 0.06 - min_y
    width = mark.width * stretch
    draw_mark = mark.draw

    def draw_accent(ctx, ox, oy):
        ctx.save()
        ctx.translate(ox + (box.width - width) / 2 + skew, oy - dy)
        ctx.scale(stretch, 1)
        draw_mark(ctx, 0, 0)
        ctx.restore()
    return place([(box, 0, 0), (Box(width, dy + max_y, 0, draw_accent), 0, 0)], box.width)


def _delimiter_around(d, content, style):
    """Délimiteur à la hauteur de ce qu'il entoure, centré sur l'axe."""
    return delimiter(d, 2 * max(content.ascent - style.axis, content.descent + style.axis) + style.size * 0.12, style)


def _quad(ctx, cx, cy, x, y):
    """Courbe quadratique (CoreGraphics) en cubique (Cairo), depuis le point courant."""
    x0, y0 = ctx.get_current_point()
    ctx.curve_to(x0 + 2 / 3 * (cx - x0), y0 + 2 / 3 * (cy - y0), x + 2 / 3 * (cx - x), y + 2 / 3 * (cy - y), x, y)


def delimiter(d, height, style):
    """Le glyphe de la police s'il suffit, sinon dessiné à la bonne hauteur."""
    if not d:
        return Box(style.size * 0.06, 0, 0)
    s = style.size
    if height <= s * 1.15:
        return _centered(d, s, style.axis)
    rule = style.rule * 1.1
    width = s * (0.5 if d in "{}" else 0.3 if d in "|‖" else 0.4)
    half = height / 2
    axis = style.axis

    def draw(ctx, x, oy):
        import cairo
        top = oy - axis - half
        bottom = oy - axis + half
        mid = oy - axis
        ctx.save()
        ctx.set_line_width(rule)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.set_line_join(cairo.LINE_JOIN_ROUND)
        # Les délimiteurs de droite sont ceux de gauche en miroir.
        if d in ")]}⟩⌋⌉":
            ctx.translate(x * 2 + width, 0)
            ctx.scale(-1, 1)
        if d in "()":
            right = x + width * 0.82
            outer = x + width * 0.12
            ctx.move_to(right, top)
            _quad(ctx, 2 * outer - right, mid, right, bottom)
            _quad(ctx, 2 * (outer + rule * 1.2) - right, mid, right, top)
            ctx.fill()
        elif d in "[]⌊⌋⌈⌉":
            stem = x + width * 0.3
            ctx.move_to(stem, top)
            ctx.line_to(stem, bottom)
            if d not in "⌈⌉":
                ctx.move_to(stem, bottom)
                ctx.line_to(x + width * 0.85, bottom)
            if d not in "⌊⌋":
                ctx.move_to(stem, top)
                ctx.line_to(x + width * 0.85, top)
            ctx.stroke()
        elif d in "{}":
            right = x + width * 0.85
            stem = x + width * 0.5
            tip = x + width * 0.12
            r = min(s * 0.18, half * 0.3)
            ctx.move_to(right, top)
            _quad(ctx, stem, top, stem, top + r)
            ctx.line_to(stem, mid - r)
            _quad(ctx, stem, mid, tip, mid)
            _quad(ctx, stem, mid, stem, mid + r)
            ctx.line_to(stem, bottom - r)
            _quad(ctx, stem, bottom, right, bottom)
            ctx.stroke()
        elif d in "⟨⟩":
            ctx.move_to(x + width * 0.8, top)
            ctx.line_to(x + width * 0.2, mid)
            ctx.line_to(x + width * 0.8, bottom)
            ctx.stroke()
        elif d == "‖":
            for stem in (x + width * 0.3, x + width * 0.7):
                ctx.move_to(stem, top)
                ctx.line_to(stem, bottom)
            ctx.stroke()
        else:
            ctx.move_to(x + width / 2, top)
            ctx.line_to(x + width / 2, bottom)
            ctx.stroke()
        ctx.restore()
    return Box(width, axis + half, half - axis, draw)


def _table(rows, align, left, right, column_gap, style):
    inner = style.text_style()
    s = style.size
    count = max((len(r) for r in rows), default=0)
    if count == 0:
        return empty()
    aligned = column_gap == 0 and len(align) > 1
    # Colonnes d'un `aligned` qui commencent à droite du « & » : la relation garde ses espaces.
    boxes = []
    for cells in rows:
        line = []
        for column in range(count):
            if column >= len(cells):
                line.append(empty())
                continue
            cell = cells[column]
            if aligned and column % 2 == 1:
                line.append(row(cell[1] if cell[0] == "row" else [cell], inner, after_ord=True))
            else:
                line.append(layout(cell, inner))
        boxes.append(line)
    widths = [max(line[c].width for line in boxes) for c in range(count)]
    ascents = [max(max(b.ascent for b in line), s * 0.72) for line in boxes]
    descents = [max(max(b.descent for b in line), s * 0.28) for line in boxes]
    row_gap = s * (0.4 if aligned or align == ["left", "left"] else 0.32)
    height = sum(a + d for a, d in zip(ascents, descents)) + row_gap * max(len(rows) - 1, 0)
    gaps = [0.0 if c == 0 else (s * 1.6 if c % 2 == 0 else 0) if aligned else column_gap * s for c in range(count)]
    opening = delimiter(left, height + s * 0.2, style)
    closing = delimiter(right, height + s * 0.2, style)
    pad = 0 if not left and not right else s * 0.12
    parts = [(opening, 0, 0)]
    y = style.axis + height / 2
    for index, cells in enumerate(boxes):
        y -= ascents[index]
        x = opening.width + pad
        for column in range(count):
            x += gaps[column]
            box = cells[column]
            mode = align[column] if column < len(align) else (align[-1] if align else "center")
            dx = 0 if mode == "left" else (widths[column] - box.width) / 2 if mode == "center" \
                else widths[column] - box.width
            parts.append((box, x + dx, y))
            x += widths[column]
        y -= descents[index] + row_gap
    content_width = sum(widths) + sum(gaps)
    parts.append((closing, opening.width + pad * 2 + content_width, 0))
    return place(parts, opening.width + pad * 2 + content_width + closing.width)


# MARK: - Rendu

_cache = {}


def render(latex, size, display):
    """La formule composée (une Box), ou None si elle est vide. Gardée en cache : le texte d'une réponse se
    redessine à chaque mot reçu."""
    key = (round(size, 2), display, latex)
    if key in _cache:
        return _cache[key]
    try:
        box = layout(parse(latex), Style(size, size, display))
    except (RecursionError, IndexError, KeyError, ValueError):
        box = None
    if box is not None and box.width <= 0:
        box = None
    if len(_cache) > 400:
        _cache.clear()
    _cache[key] = box
    return box


def plain(latex):
    """Formule simple écrite en caractères Unicode (𝑥² + 𝑦₁ ≤ 𝛼), sélectionnable et copiable dans le texte ;
    None si elle a besoin d'être composée (fraction, racine sur plusieurs signes, matrice…)."""
    try:
        return _plain(parse(latex))
    except (RecursionError, IndexError, KeyError, ValueError):
        return None


def _plain(node):
    kind = node[0]
    if kind in ("atom", "text"):
        return node[1]
    if kind == "space":
        em = node[1]
        return "  " if em >= 0.9 else " " if em > 0.2 else "\u2009" if em > 0 else ""
    if kind == "row":
        out = ""
        previous = None
        for child in node[1]:
            part = _plain(child)
            if part is None:
                return None
            cls = node_class(child)
            if cls == "bin" and (previous is None or previous in _BIN_AFTER):
                cls = "ord"
            if cls in ("bin", "rel"):
                out += " " + part + " "
            elif cls == "punct":
                out += part + " "
            elif cls == "op":
                out += ("" if not out or out.endswith(" ") else " ") + part + "\u2009"
            else:
                out += part
            if cls is not None:
                previous = cls
        return out.strip()
    if kind == "scripts":
        _, base, sup, sub = node
        if base[0] == "op" and base[3]:
            return None
        body = _plain(base)
        if body is None:
            return None
        out = body
        if sub is not None:
            text = _plain(sub)
            text = _map(text, _SUBSCRIPTS) if text is not None else None
            if text is None:
                return None
            out += text
        if sup is not None:
            text = _plain(sup)
            text = _map(text, _SUPERSCRIPTS) if text is not None else None
            if text is None:
                return None
            out += text
        return out
    if kind == "op":
        return node[1]
    if kind == "root":
        _, radicand, index = node
        if index is not None or radicand[0] != "atom":
            return None
        return "√" + radicand[1]
    if kind == "fenced":
        body = _plain(node[2])
        return None if body is None else node[1] + body + node[3]
    if kind == "accent":
        _, base, accent = node
        marks = {"bar": "\u0304", "overline": "\u0305", "hat": "\u0302", "vec": "\u20D7", "tilde": "\u0303",
                 "dot": "\u0307", "ddot": "\u0308", "check": "\u030C"}
        if base[0] != "atom" or len(base[1]) != 1 or accent not in marks:
            return None
        return base[1] + marks[accent]
    return None


def _ascii_letter(c):
    """Lettre italique mathématique (𝑥) ramenée à sa lettre latine (x)."""
    o = ord(c)
    if c == "ℎ":
        return "h"
    if 0x1D44E <= o <= 0x1D467:
        return chr(97 + o - 0x1D44E)
    if 0x1D434 <= o <= 0x1D44D:
        return chr(65 + o - 0x1D434)
    if c == "−":
        return "-"
    return None


def _map(text, table):
    """Exposants et indices Unicode ; None dès qu'un caractère n'en a pas."""
    out = []
    for c in text:
        if c in " \u2009":
            continue
        mapped = table.get(_ascii_letter(c) or c)
        if mapped is None:
            return None
        out.append(mapped)
    return "".join(out)


def _table_of(keys, values):
    table = {}
    for k, v in zip(keys, values):
        table.setdefault(k, v)
    return table


_SUPERSCRIPTS = _table_of("0123456789+-=()abcdefghijklmnoprstuvwxyzABDEGHIJKLMNOPRTUVW′",
                          "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖʳˢᵗᵘᵛʷˣʸᶻᴬᴮᴰᴱᴳᴴᴵᴶᴷᴸᴹᴺᴼᴾᴿᵀᵁⱽᵂ′")
_SUBSCRIPTS = _table_of("0123456789+-=()aehijklmnoprstuvx", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ")
