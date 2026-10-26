"""Interprète la sortie d'un terminal (séquences ANSI) en segments stylés :
couleurs 16 / 256 / truecolor, gras, atténué, italique, souligné, inverse,
retour chariot (barres de progression) et effacement de ligne. (TerminalRender.swift)"""
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class TermStyle:
    fg: object = None   # int (index) ou (r, g, b) en 0-1
    bg: object = None
    bold: bool = False
    dim: bool = False
    italic: bool = False
    underline: bool = False
    inverse: bool = False


# Palette pensée pour le fond sombre du panneau (le noir ANSI reste lisible).
PALETTE = [
    (0.36, 0.38, 0.44), (1.00, 0.37, 0.43), (0.35, 0.97, 0.56), (0.95, 0.98, 0.62),
    (0.34, 0.78, 1.00), (1.00, 0.42, 0.76), (0.60, 0.93, 1.00), (0.82, 0.82, 0.86),
    (0.48, 0.50, 0.55), (1.00, 0.54, 0.54), (0.49, 1.00, 0.66), (1.00, 0.96, 0.54),
    (0.49, 0.83, 1.00), (1.00, 0.57, 0.87), (0.72, 0.96, 1.00), (1.00, 1.00, 1.00),
]


def color(tint):
    if isinstance(tint, tuple):
        return tint
    n = max(0, min(int(tint), 255))
    if n < 16:
        return PALETTE[n]
    if n < 232:
        steps = [0, 95, 135, 175, 215, 255]
        v = n - 16
        return (steps[v // 36] / 255, steps[(v // 6) % 6] / 255, steps[v % 6] / 255)
    level = (8 + (n - 232) * 10) / 255
    return (level, level, level)


def hex_color(tint):
    r, g, b = color(tint)
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


class TerminalBuffer:
    MAX_LINES = 4000

    def __init__(self):
        self.lines = [[]]          # chaque ligne : liste de [texte, style]
        self.style = TermStyle()
        self.pending = ""          # séquence d'échappement coupée entre deux lectures
        self.carriage_return = False
        self.version = 0

    @property
    def is_empty(self):
        return len(self.lines) == 1 and not self.lines[0]

    @property
    def plain_text(self):
        return "\n".join("".join(seg[0] for seg in line) for line in self.lines)

    def _flush(self, text):
        if not text:
            return
        if self.carriage_return:
            self.lines[-1] = []
            self.carriage_return = False
        line = self.lines[-1]
        if line and line[-1][1] == self.style:
            line[-1][0] += text
        else:
            line.append([text, self.style])

    def feed(self, chunk):
        data = self.pending + chunk
        self.pending = ""
        text = []
        i = 0
        n = len(data)
        while i < n:
            ch = data[i]
            if ch == "\x1b":
                self._flush("".join(text))
                text = []
                end = self._escape_end(data, i)
                if end is None:
                    self.pending = data[i:]
                    break
                seq = data[i:end]
                if seq.startswith("\x1b[") and len(seq) >= 3:
                    final, params = seq[-1], seq[2:-1]
                    if final == "m":
                        self._sgr(params)
                    elif final == "K":
                        self._erase_line(params)
                    elif final == "J" and "2" in params:
                        self.lines = [[]]
                i = end
                continue
            if ch == "\n":
                self._flush("".join(text))
                text = []
                self.carriage_return = False
                self.lines.append([])
                if len(self.lines) > self.MAX_LINES:
                    del self.lines[: len(self.lines) - self.MAX_LINES]
            elif ch == "\r":
                self._flush("".join(text))
                text = []
                # « \r\n » : simple fin de ligne
                if i + 1 < n and data[i + 1] == "\n":
                    pass
                else:
                    self.carriage_return = True
            elif ch in "\x07\x08\x0e\x0f":
                pass
            else:
                text.append(ch)
            i += 1
        self._flush("".join(text))
        self.version += 1

    @staticmethod
    def _escape_end(s, start):
        """Fin d'une séquence CSI (ESC [ … lettre) ou OSC (ESC ] … BEL / ESC \\), None si incomplète."""
        i = start + 1
        if i >= len(s):
            return None
        if s[i] == "[":
            i += 1
            while i < len(s):
                if 0x40 <= ord(s[i]) <= 0x7E:
                    return i + 1
                i += 1
            return None
        if s[i] == "]":
            while i < len(s):
                if s[i] == "\x07":
                    return i + 1
                if s[i] == "\x1b" and i + 1 < len(s) and s[i + 1] == "\\":
                    return i + 2
                i += 1
            return None
        return i + 1

    def _erase_line(self, params):
        if params in ("", "0", "2"):
            if self.carriage_return or params == "2":
                self.lines[-1] = []

    def _sgr(self, params):
        codes = [int(c) if c.isdigit() else 0 for c in params.split(";")] if params else [0]
        s = self.style
        i = 0
        while i < len(codes):
            c = codes[i]
            if c == 0:
                s = TermStyle()
            elif c == 1:
                s = replace(s, bold=True)
            elif c == 2:
                s = replace(s, dim=True)
            elif c == 3:
                s = replace(s, italic=True)
            elif c == 4:
                s = replace(s, underline=True)
            elif c == 7:
                s = replace(s, inverse=True)
            elif c == 22:
                s = replace(s, bold=False, dim=False)
            elif c == 23:
                s = replace(s, italic=False)
            elif c == 24:
                s = replace(s, underline=False)
            elif c == 27:
                s = replace(s, inverse=False)
            elif 30 <= c <= 37:
                s = replace(s, fg=c - 30)
            elif 90 <= c <= 97:
                s = replace(s, fg=c - 90 + 8)
            elif c == 39:
                s = replace(s, fg=None)
            elif 40 <= c <= 47:
                s = replace(s, bg=c - 40)
            elif 100 <= c <= 107:
                s = replace(s, bg=c - 100 + 8)
            elif c == 49:
                s = replace(s, bg=None)
            elif c in (38, 48):
                tint = None
                if i + 2 < len(codes) and codes[i + 1] == 5:
                    tint = codes[i + 2]
                    i += 2
                elif i + 4 < len(codes) and codes[i + 1] == 2:
                    tint = (codes[i + 2] / 255, codes[i + 3] / 255, codes[i + 4] / 255)
                    i += 4
                s = replace(s, fg=tint) if c == 38 else replace(s, bg=tint)
            i += 1
        self.style = s
