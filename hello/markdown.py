"""Markdown des réponses de l'IA (Markdown.swift) : titres, listes (imbriquées, à cocher), citations, blocs de code,
tableaux, filets, liens et styles en ligne, et formules LaTeX — `$…$` ou `\\(…\\)` dans le texte, `$$…$$`, `\\[…\\]`
ou `\\begin{…}` sur leurs propres lignes. Ici, seulement la lecture : le dessin est dans ui_markdown.py.

Blocs : (\"heading\", niveau, texte), (\"bullet\", retrait, marque, texte), (\"task\", retrait, fait, texte),
(\"quote\", texte), (\"code\", texte, langage), (\"math\", latex), (\"table\", Table), (\"rule\",), (\"paragraph\", texte).
Morceaux en ligne : (\"markdown\", texte) ou (\"math\", latex, display)."""
import re
from html import escape

MATH_LANGUAGES = {"math", "latex", "tex", "katex"}


class Table:
    __slots__ = ("header", "align", "rows")

    def __init__(self, header, align, rows):
        self.header = header
        self.align = align   # \"leading\", \"center\" ou \"trailing\" par colonne
        self.rows = rows

    def __repr__(self):
        return f"Table({self.header!r}, {self.align!r}, {self.rows!r})"

    def __eq__(self, other):
        return isinstance(other, Table) and (self.header, self.align, self.rows) == (other.header, other.align,
                                                                                     other.rows)

    __hash__ = None

    @staticmethod
    def is_separator(line):
        """Ligne de séparation sous l'en-tête : des tirets, des deux-points pour l'alignement, des barres."""
        trimmed = line.strip(" \t")
        return "-" in trimmed and "|" in trimmed and all(c in "|:- \t" for c in trimmed)

    @staticmethod
    def alignment(cell):
        start, end = cell.startswith(":"), cell.endswith(":")
        if start and end:
            return "center"
        if end:
            return "trailing"
        return "leading"

    @staticmethod
    def cells(line):
        """Cellules d'une ligne : séparées par `|`, sauf dans le code, dans une formule ou échappé (`\\|`)."""
        chars = line.strip(" \t")
        if chars.startswith("|"):
            chars = chars[1:]
        if chars.endswith("|") and not chars[:-1].endswith("\\"):
            chars = chars[:-1]
        cells = []
        cell = []
        code = False
        i = 0
        while i < len(chars):
            c = chars[i]
            if c == "`":
                code = not code
            if not code and c == "\\" and i + 1 < len(chars) and chars[i + 1] == "|":
                cell.append("|")
                i += 2
                continue
            if not code and c == "$":
                end = dollar_end(chars, i)
                if end is not None:
                    cell.append(chars[i:end + 1])
                    i = end + 1
                    continue
            if not code and c == "|":
                cells.append("".join(cell).strip(" \t"))
                cell = []
            else:
                cell.append(c)
            i += 1
        cells.append("".join(cell).strip(" \t"))
        return cells


def _indent(raw):
    """Retrait des listes imbriquées : deux espaces (ou une tabulation) par niveau."""
    width = 0
    for c in raw:
        if c == " ":
            width += 1
        elif c == "\t":
            width += 4
        else:
            break
    return min(width // 2, 4)


_ORDERED = re.compile(r"^(\d{1,3})[.)] (.*)$")


def parse(text):
    lines = text.split("\n")
    out = []
    index = 0
    while index < len(lines):
        raw = lines[index]
        line = raw.strip(" \t")
        index += 1
        if not line:
            continue

        # Bloc de code (« ```math » : une formule).
        if line.startswith("```") or line.startswith("~~~"):
            fence = line[:3]
            language = line[3:].strip()
            body = []
            while index < len(lines) and not lines[index].strip(" \t").startswith(fence):
                body.append(lines[index])
                index += 1
            index += 1
            content = "\n".join(body)
            out.append(("math", content) if language.lower() in MATH_LANGUAGES else ("code", content, language))
            continue

        # Formule à part : `$$…$$`, `\[…\]`, ou un environnement LaTeX (`\begin{align}`…).
        fence = next(((o, c) for o, c in (("$$", "$$"), ("\\[", "\\]")) if line.startswith(o)), None)
        if fence:
            opening, closing = fence
            rest = line[len(opening):]
            end = rest.find(closing)
            if end >= 0:
                out.append(("math", rest[:end]))
                tail = rest[end + len(closing):].strip(" \t")
                if tail:
                    out.append(("paragraph", tail))
                continue
            body = [rest]
            closed = False
            while index < len(lines):
                nxt = lines[index]
                index += 1
                end = nxt.find(closing)
                if end >= 0:
                    body.append(nxt[:end])
                    closed = True
                    break
                body.append(nxt)
            # Formule pas encore refermée (réponse en cours) : montrée telle quelle en attendant.
            out.append(("math", "\n".join(body)) if closed else ("code", "\n".join([opening] + body), ""))
            continue
        if line.startswith("\\begin{"):
            name = line[7:].split("}", 1)[0]
            if name:
                end = "\\end{" + name + "}"
                body = [line]
                while end not in body[-1] and index < len(lines):
                    body.append(lines[index])
                    index += 1
                out.append(("math", "\n".join(body)))
                continue

        # Tableau : une ligne d'en-tête, puis la ligne de séparation (`|---|:--:|`).
        if "|" in line and index < len(lines) and Table.is_separator(lines[index]):
            header = Table.cells(line)
            align = [Table.alignment(c) for c in Table.cells(lines[index])]
            index += 1
            rows = []
            while index < len(lines):
                nxt = lines[index].strip(" \t")
                if "|" not in nxt:
                    break
                rows.append(Table.cells(nxt))
                index += 1
            out.append(("table", Table(header, align, rows)))
            continue

        if len(line) >= 3 and line[0] in "-*_" and all(c == line[0] or c == " " for c in line):
            out.append(("rule",))
            continue
        if line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            out.append(("heading", level, line[level:].strip(" \t")))
            continue
        indent = _indent(raw)
        if line[:2] in ("- ", "* ", "+ ", "• "):
            content = line[2:]
            if content[:4] in ("[ ] ", "[x] ", "[X] "):
                out.append(("task", indent, not content.startswith("[ ]"), content[4:]))
            else:
                out.append(("bullet", indent, "•" if indent % 2 == 0 else "◦", content))
            continue
        ordered = _ORDERED.match(line)
        if ordered:
            out.append(("bullet", indent, ordered.group(1) + ".", ordered.group(2).strip(" \t")))
        elif line.startswith(">"):
            out.append(("quote", line[1:].strip(" \t")))
        else:
            out.append(("paragraph", line))
    return out


# MARK: - Texte en ligne

def dollar_end(chars, start):
    """Fin d'une formule `$…$` ouverte en `start` : collée à son contenu des deux côtés, et pas suivie d'un chiffre."""
    if start + 1 >= len(chars) or chars[start + 1].isspace() or chars[start + 1] == "$":
        return None
    j = start + 2
    while j < len(chars):
        if chars[j] == "$" and chars[j - 1] != "\\":
            if chars[j - 1].isspace() or (j + 1 < len(chars) and chars[j + 1].isdigit()):
                return None
            return j
        j += 1
    return None


def split(string):
    """Découpe le texte en Markdown et en formules ; rien n'est pris pour une formule dans le code (`…`),
    ni un prix (« 5 $ et 10 $ », « $5 à $10 »)."""
    chars = string
    pieces = []
    buffer = []
    code = False
    i = 0

    def flush():
        if buffer:
            pieces.append(("markdown", "".join(buffer)))
            buffer.clear()

    while i < len(chars):
        c = chars[i]
        if c == "`":
            code = not code
        elif not code and c == "\\" and i + 1 < len(chars):
            nxt = chars[i + 1]
            if nxt in "([":
                end = chars.find("\\)" if nxt == "(" else "\\]", i + 2)
                if end >= 0:
                    flush()
                    pieces.append(("math", chars[i + 2:end], nxt == "["))
                    i = end + 2
                    continue
            if nxt == "$":
                buffer.append("\\$")
                i += 2
                continue
        elif not code and c == "$":
            if i + 1 < len(chars) and chars[i + 1] == "$":
                end = chars.find("$$", i + 2)
                if end >= 0:
                    flush()
                    pieces.append(("math", chars[i + 2:end], True))
                    i = end + 2
                    continue
            end = dollar_end(chars, i)
            if end is not None:
                flush()
                pieces.append(("math", chars[i + 1:end], False))
                i = end + 1
                continue
        buffer.append(c)
        i += 1
    flush()
    return pieces


_CODE = re.compile(r"`([^`]+)`")
_LINK = re.compile(r"\[([^\]]+)\]\(((?:https?|mailto|file):[^)\s]+)\)")
_AUTOLINK = re.compile(r"<((?:https?|mailto):[^>\s]+)>")
_BOLD = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")
_ITALIC = re.compile(r"(?<![*\w])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![*\w])|(?<![_\w])_(?=\S)([^_\n]+?)(?<=\S)_(?![_\w])")
_STRIKE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~")


def inline_markup(text):
    """Markdown en ligne → balisage Pango : code, liens, gras, italique, barré, `\\$` échappé."""
    # Le code d'abord, mis de côté : rien de ce qu'il contient n'est interprété.
    codes = []

    def keep_code(m):
        codes.append(m.group(1))
        return f"\x00{len(codes) - 1}\x00"
    text = _CODE.sub(keep_code, text)
    links = []

    def keep_link(m):
        links.append((m.group(1), m.group(2)))
        return f"\x01{len(links) - 1}\x01"
    text = _LINK.sub(keep_link, text)
    text = _AUTOLINK.sub(lambda m: (links.append((m.group(1), m.group(1))), f"\x01{len(links) - 1}\x01")[1], text)
    text = text.replace("\\$", "$").replace("\\*", "\x02").replace("\\_", "\x03")
    s = escape(text, quote=False)
    s = _BOLD.sub(r"<b>\2</b>", s)
    s = _ITALIC.sub(lambda m: f"<i>{m.group(1) or m.group(2)}</i>", s)
    s = _STRIKE.sub(r"<s>\1</s>", s)
    s = s.replace("\x02", "*").replace("\x03", "_")

    def link(m):
        title, url = links[int(m.group(1))]
        inner = inline_markup(title) if "\x01" not in title else escape(title)
        return f'<a href="{escape(url)}">{inner}</a>'
    s = re.sub(r"\x01(\d+)\x01", link, s)
    s = re.sub(r"\x00(\d+)\x00", lambda m: f"<tt>{escape(codes[int(m.group(1))], quote=False)}</tt>", s)
    return s


def plain_text(markdown_text):
    """Le texte sans balises (pour copier une réponse ou l'afficher à défaut)."""
    return re.sub(r"<[^>]+>", "", inline_markup(markdown_text)).replace("&lt;", "<").replace("&gt;", ">") \
        .replace("&amp;", "&")
