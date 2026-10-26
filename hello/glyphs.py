"""Emoji et caractères Unicode générés depuis les données Unicode de Python (noms officiels),
construits une seule fois, paresseusement. (Glyphs.swift)"""
import gettext
import os
import unicodedata

from .fuzzy import fold
from .settings import DATA_DIR, load_json, save_json

# Emoji du plan de base (propriété Emoji d'Unicode) ; ceux en présentation emoji par défaut à part.
_BMP_EMOJI = [
    (0x00A9, 0x00A9), (0x00AE, 0x00AE), (0x203C, 0x203C), (0x2049, 0x2049), (0x2122, 0x2122),
    (0x2139, 0x2139), (0x2194, 0x2199), (0x21A9, 0x21AA), (0x231A, 0x231B), (0x2328, 0x2328),
    (0x23CF, 0x23CF), (0x23E9, 0x23F3), (0x23F8, 0x23FA), (0x24C2, 0x24C2), (0x25AA, 0x25AB),
    (0x25B6, 0x25B6), (0x25C0, 0x25C0), (0x25FB, 0x25FE), (0x2600, 0x2604), (0x260E, 0x260E),
    (0x2611, 0x2611), (0x2614, 0x2615), (0x2618, 0x2618), (0x261D, 0x261D), (0x2620, 0x2620),
    (0x2622, 0x2623), (0x2626, 0x2626), (0x262A, 0x262A), (0x262E, 0x262F), (0x2638, 0x263A),
    (0x2640, 0x2640), (0x2642, 0x2642), (0x2648, 0x2653), (0x265F, 0x2660), (0x2663, 0x2663),
    (0x2665, 0x2666), (0x2668, 0x2668), (0x267B, 0x267B), (0x267E, 0x267F), (0x2692, 0x2697),
    (0x2699, 0x2699), (0x269B, 0x269C), (0x26A0, 0x26A1), (0x26A7, 0x26A7), (0x26AA, 0x26AB),
    (0x26B0, 0x26B1), (0x26BD, 0x26BE), (0x26C4, 0x26C5), (0x26C8, 0x26C8), (0x26CE, 0x26CF),
    (0x26D1, 0x26D1), (0x26D3, 0x26D4), (0x26E9, 0x26EA), (0x26F0, 0x26F5), (0x26F7, 0x26FA),
    (0x26FD, 0x26FD), (0x2702, 0x2702), (0x2705, 0x2705), (0x2708, 0x270D), (0x270F, 0x270F),
    (0x2712, 0x2712), (0x2714, 0x2714), (0x2716, 0x2716), (0x271D, 0x271D), (0x2721, 0x2721),
    (0x2728, 0x2728), (0x2733, 0x2734), (0x2744, 0x2744), (0x2747, 0x2747), (0x274C, 0x274C),
    (0x274E, 0x274E), (0x2753, 0x2755), (0x2757, 0x2757), (0x2763, 0x2764), (0x2795, 0x2797),
    (0x27A1, 0x27A1), (0x27B0, 0x27B0), (0x27BF, 0x27BF), (0x2934, 0x2935), (0x2B05, 0x2B07),
    (0x2B1B, 0x2B1C), (0x2B50, 0x2B50), (0x2B55, 0x2B55), (0x3030, 0x3030), (0x303D, 0x303D),
    (0x3297, 0x3297), (0x3299, 0x3299),
]
_BMP_PRESENTATION = {
    0x231A, 0x231B, 0x23E9, 0x23EA, 0x23EB, 0x23EC, 0x23F0, 0x23F3, 0x25FD, 0x25FE, 0x2614, 0x2615,
    *range(0x2648, 0x2654), 0x267F, 0x2693, 0x26A1, 0x26AA, 0x26AB, 0x26BD, 0x26BE, 0x26C4, 0x26C5,
    0x26CE, 0x26D4, 0x26EA, 0x26F2, 0x26F3, 0x26F5, 0x26FA, 0x26FD, 0x2705, 0x270A, 0x270B, 0x2728,
    0x274C, 0x274E, 0x2753, 0x2754, 0x2755, 0x2757, 0x2795, 0x2796, 0x2797, 0x27B0, 0x27BF, 0x2B1B,
    0x2B1C, 0x2B50, 0x2B55,
}
# Blocs d'emoji des plans supplémentaires, ordre choisi : visages d'abord, puis gens, objets, nature…
_SUPP_EMOJI = [
    (0x1F600, 0x1F64F), (0x1F900, 0x1F9FF), (0x1FAE0, 0x1FAFF), (0x1F440, 0x1F4FF), (0x1F300, 0x1F43F),
    (0x1FA70, 0x1FADF), (0x1F500, 0x1F5FF), (0x1F680, 0x1F6FF), (0x1F7E0, 0x1F7F0), (0x1F004, 0x1F004),
    (0x1F0CF, 0x1F0CF), (0x1F170, 0x1F251),
]
# Plans supplémentaires sans présentation emoji par défaut (affichés avec le sélecteur U+FE0F).
_SUPP_TEXT = {0x1F170, 0x1F171, 0x1F17E, 0x1F17F, 0x1F202, 0x1F237, 0x1F321, *range(0x1F324, 0x1F32D), 0x1F336,
              0x1F37D, 0x1F396, 0x1F397, 0x1F399, 0x1F39A, 0x1F39B, 0x1F39E, 0x1F39F, *range(0x1F3CB, 0x1F3CF),
              *range(0x1F3D4, 0x1F3E0), 0x1F3F3, 0x1F3F5, 0x1F3F7, 0x1F43F, 0x1F441, 0x1F4FD, 0x1F549, 0x1F54A,
              0x1F56F, 0x1F570, *range(0x1F573, 0x1F57A), 0x1F587, *range(0x1F58A, 0x1F58E), 0x1F590, 0x1F5A5,
              0x1F5A8, 0x1F5B1, 0x1F5B2, 0x1F5BC, *range(0x1F5C2, 0x1F5C5), *range(0x1F5D1, 0x1F5D4),
              *range(0x1F5DC, 0x1F5DF), 0x1F5E1, 0x1F5E3, 0x1F5E8, 0x1F5EF, 0x1F5F3, 0x1F5FA, 0x1F6CB,
              *range(0x1F6CD, 0x1F6D0), *range(0x1F6E0, 0x1F6E6), 0x1F6E9, 0x1F6F0, 0x1F6F3}
# Zones des plans supplémentaires qui ne sont pas des emoji (ornements, géométrie étendue…).
_SUPP_SKIP = [(0x1F650, 0x1F67F), (0x1F3FB, 0x1F3FF), (0x1F1E6, 0x1F1FF), (0x1F10D, 0x1F16F),
              (0x1F1AE, 0x1F1E5), (0x1F203, 0x1F20F), (0x1F23C, 0x1F23F), (0x1F249, 0x1F24F)]

_SYMBOL_RANGES = [
    (0x2318, 0x2318), (0x2325, 0x2325), (0x21E7, 0x21E7), (0x2303, 0x2303), (0x238B, 0x238B),
    (0x23CE, 0x23CE), (0x232B, 0x232B), (0x2326, 0x2326), (0x21E5, 0x21E5), (0x2190, 0x21FF),
    (0x27F0, 0x27FF), (0x2900, 0x297F), (0x2B00, 0x2BFF), (0x2200, 0x22FF), (0x2980, 0x2AFF),
    (0x2010, 0x205E), (0x20A0, 0x20C0), (0x00A1, 0x00BF), (0x00C0, 0x00FF), (0x0152, 0x0153),
    (0x0178, 0x0178), (0x2100, 0x214F), (0x2150, 0x218B), (0x2070, 0x209C), (0x0391, 0x03C9),
    (0x2460, 0x24FF), (0x25A0, 0x25FF), (0x2600, 0x26FF), (0x2700, 0x27BF), (0x2300, 0x23FF),
    (0x2500, 0x259F),
]

_SEQUENCES = [
    ("❤️‍🔥", "heart on fire"), ("❤️‍🩹", "mending heart"), ("😮‍💨", "face exhaling"),
    ("😵‍💫", "face with spiral eyes"), ("😶‍🌫️", "face in clouds"), ("🧑‍💻", "technologist"),
    ("👨‍💻", "man technologist"), ("👩‍💻", "woman technologist"), ("🧑‍🚀", "astronaut"),
    ("🧑‍🍳", "cook"), ("🧑‍🎨", "artist"), ("🧑‍🔬", "scientist"), ("🧑‍🎓", "student"),
    ("🐈‍⬛", "black cat"), ("🐻‍❄️", "polar bear"), ("🐦‍🔥", "phoenix"), ("🍋‍🟩", "lime"),
    ("🏳️‍🌈", "rainbow flag"), ("🏳️‍⚧️", "transgender flag"), ("🏴‍☠️", "pirate flag"),
    ("👁️‍🗨️", "eye in speech bubble"), ("🧑‍🤝‍🧑", "people holding hands"), ("👨‍👩‍👧", "family"),
    ("#️⃣", "keycap number sign"), ("*️⃣", "keycap asterisk"),
] + [(f"{d}️⃣", f"keycap {d}") for d in range(10)]

# Les noms Unicode sont en anglais : ces alias permettent de chercher en français.
ALIASES = {
    "coeur": ["heart"], "amour": ["heart", "love", "kiss"], "rire": ["joy", "laugh", "grinning", "rolling"],
    "sourire": ["smil", "grin"], "triste": ["sad", "cry", "disappointed", "pensive"], "pleur": ["cry", "sob", "tear"],
    "larme": ["tear", "cry"], "colere": ["angry", "rage", "pouting"], "peur": ["fear", "scream"],
    "clin": ["wink"], "bisou": ["kiss"], "fatigue": ["tired", "sleep", "yawn"], "dormir": ["sleep", "zzz"],
    "reflechir": ["thinking"], "chaud": ["hot"], "froid": ["cold", "freezing"], "malade": ["sick", "mask", "nause"],
    "fou": ["zany", "crazy"], "choque": ["astonished", "shock", "open mouth"], "cool": ["sunglasses", "cool"],
    "feu": ["fire"], "pouce": ["thumbs"], "main": ["hand"], "merci": ["folded hands"], "prier": ["folded hands"],
    "applaudir": ["clapping"], "muscle": ["biceps"], "yeux": ["eyes"], "oeil": ["eye"], "cerveau": ["brain"],
    "crane": ["skull"], "fantome": ["ghost"], "caca": ["pile of poo"], "fete": ["party", "confetti", "balloon"],
    "cadeau": ["gift"], "gateau": ["cake"], "biere": ["beer"], "vin": ["wine"], "cafe": ["coffee", "hot beverage"],
    "the": ["teacup", "tea"], "pomme": ["apple"], "fraise": ["strawberry"], "banane": ["banana"],
    "chat": ["cat"], "chien": ["dog"], "cheval": ["horse"], "lapin": ["rabbit"], "ours": ["bear"],
    "singe": ["monkey"], "oiseau": ["bird"], "poisson": ["fish"], "cochon": ["pig"], "vache": ["cow"],
    "licorne": ["unicorn"], "serpent": ["snake"], "tortue": ["turtle"], "papillon": ["butterfly"],
    "soleil": ["sun"], "lune": ["moon"], "etoile": ["star"], "nuage": ["cloud"], "pluie": ["rain"],
    "neige": ["snow"], "eclair": ["lightning", "high voltage"], "arc-en-ciel": ["rainbow"], "arbre": ["tree"],
    "fleur": ["flower", "blossom", "rose", "tulip"], "plante": ["plant", "seedling"], "terre": ["earth", "globe"],
    "voiture": ["car", "automobile"], "avion": ["airplane"], "fusee": ["rocket"], "velo": ["bicycle"],
    "train": ["train"], "bateau": ["boat", "ship"], "maison": ["house"], "argent": ["money", "dollar"],
    "ordinateur": ["computer", "laptop"], "telephone": ["phone", "telephone"], "livre": ["book", "pound"],
    "crayon": ["pencil"], "stylo": ["pen"], "cle": ["key"], "cadenas": ["lock"], "coche": ["check mark"],
    "valider": ["check mark"], "croix": ["cross mark", "multiplication"], "attention": ["warning"],
    "interdit": ["prohibited", "no entry"], "musique": ["music", "musical"], "horloge": ["clock"],
    "trophee": ["trophy"], "medaille": ["medal"], "ballon": ["ball", "balloon"], "cible": ["direct hit", "target"],
    "idee": ["light bulb"], "ampoule": ["light bulb"], "bombe": ["bomb"], "poubelle": ["wastebasket"],
    "dossier": ["folder"], "calendrier": ["calendar"], "epingle": ["pushpin", "pin"], "loupe": ["magnifying"],
    "cloche": ["bell"], "drapeau": ["flag"], "fleche": ["arrow"], "haut": ["up"], "bas": ["down"],
    "gauche": ["left"], "droite": ["right"], "cent": ["hundred"], "degre": ["degree"], "infini": ["infinity"],
    "somme": ["summation"], "different": ["not equal"], "environ": ["almost equal"], "racine": ["square root"],
    "plus": ["plus"], "moins": ["minus"], "fois": ["multiplication"], "divise": ["division"],
    "puce": ["bullet"], "tiret": ["dash"], "guillemet": ["quotation"], "copyright": ["copyright"],
    "marque": ["trade mark", "registered"], "paragraphe": ["pilcrow", "section sign"], "points": ["ellipsis"],
    "commande": ["place of interest"], "super": ["place of interest"], "option": ["option key"],
    "shift": ["upwards white arrow"], "majuscule": ["capital", "upwards white arrow"], "minuscule": ["small"],
    "controle": ["up arrowhead"], "ctrl": ["up arrowhead"], "echap": ["broken circle with northwest arrow"],
    "escape": ["broken circle with northwest arrow"], "entree": ["return symbol"], "retour": ["return symbol"],
    "effacer": ["erase"], "tab": ["rightwards arrow to bar"], "accent": ["acute", "grave", "circumflex"],
    "aigu": ["acute"], "circonflexe": ["circumflex"], "trema": ["diaeresis"], "cedille": ["cedilla"],
    "ligature": ["ligature"], "euro": ["euro"], "carre": ["square"], "cercle": ["circle"], "triangle": ["triangle"],
    "etoiles": ["star"], "rouge": ["red"], "vert": ["green"], "bleu": ["blue"], "jaune": ["yellow"],
    "noir": ["black"], "blanc": ["white"], "violet": ["purple"], "orange": ["orange"],
}


def expand_alias(token):
    if len(token) < 2:
        return []
    out = []
    for key, values in ALIASES.items():
        if key == token or (len(token) >= 3 and key.startswith(token)):
            out += values
    return out


class Glyph:
    __slots__ = ("id", "char", "name", "key", "is_emoji")

    def __init__(self, gid, char, name, key, is_emoji):
        self.id, self.char, self.name, self.key, self.is_emoji = gid, char, name, key, is_emoji

    @property
    def code(self):
        return " ".join(f"U+{ord(c):04X}" for c in self.char if ord(c) != 0xFE0F)


def _display(name):
    lower = name.lower()
    return lower[:1].upper() + lower[1:]


def _skip(v):
    return any(a <= v <= b for a, b in _SUPP_SKIP)


def _build_emoji():
    seen = set()
    out = []

    def add(v, presentation):
        if v in seen:
            return
        seen.add(v)
        name = unicodedata.name(chr(v), None)
        if not name:
            return
        char = chr(v) if presentation else chr(v) + "️"
        out.append(Glyph(f"e{v}", char, _display(name), f"{name.lower()} u+{v:04x}", True))

    for a, b in _SUPP_EMOJI:
        for v in range(a, b + 1):
            if not _skip(v) and unicodedata.category(chr(v)) == "So":
                add(v, v not in _SUPP_TEXT)
    for a, b in _BMP_EMOJI:
        for v in range(a, b + 1):
            add(v, v in _BMP_PRESENTATION)
    for i, (char, name) in enumerate(_SEQUENCES):
        out.append(Glyph(f"s{i}", char, _display(name), name, True))

    # Drapeaux : noms des pays en français via iso-codes (paquet présent sur presque toutes les distributions).
    countries = load_json("/usr/share/iso-codes/json/iso_3166-1.json", {}).get("3166-1", [])
    fr = gettext.translation("iso_3166-1", languages=["fr"], fallback=True)
    for c in countries:
        code = c.get("alpha_2", "")
        if len(code) != 2:
            continue
        en = c.get("common_name") or c.get("name", "")
        name = fr.gettext(c.get("name", en))
        flag = "".join(chr(0x1F1E6 + ord(ch) - 65) for ch in code)
        out.append(Glyph("f" + code, flag, "Drapeau : " + name, fold(f"flag drapeau {name} {en} {code}"), True))
    return out


def _build_symbols():
    seen = set()
    out = []
    for a, b in _SYMBOL_RANGES:
        for v in range(a, b + 1):
            if v in seen:
                continue
            seen.add(v)
            ch = chr(v)
            name = unicodedata.name(ch, None)
            if not name or v in _BMP_PRESENTATION:
                continue
            if unicodedata.category(ch) in ("Cc", "Cf", "Mn", "Me", "Mc", "Cn", "Co", "Cs", "Zl", "Zp", "Zs"):
                continue
            out.append(Glyph(f"u{v}", ch, _display(name), f"{name.lower()} u+{v:04x}", False))
    return out


class GlyphIndex:
    _emoji = None
    _symbols = None
    _by_char = None

    @classmethod
    def warm(cls):
        if cls._emoji is None:
            cls._emoji = _build_emoji()
            cls._symbols = _build_symbols()
            cls._by_char = {}
            for g in cls._emoji + cls._symbols:
                cls._by_char.setdefault(g.char, g)

    @classmethod
    def search(cls, query, flt):
        cls.warm()
        pool = {"all": cls._emoji + cls._symbols, "emoji": cls._emoji, "symbols": cls._symbols}[flt]
        q = fold(query).strip()
        if not q:
            recents = []
            for ch in Recents.chars:
                g = cls._by_char.get(ch)
                if g and (flt == "all" or g.is_emoji == (flt == "emoji")):
                    recents.append(Glyph("recent-" + g.id, g.char, g.name, g.key, g.is_emoji))
            return recents + pool

        tokens = [[t] + expand_alias(t) for t in q.split(" ") if t]
        hits = []
        for i, g in enumerate(pool):
            if all(any(alt in g.key for alt in alternatives) for alternatives in tokens):
                rank = 0 if g.key.startswith(q) else (1 if " " + q in g.key else 2)
                hits.append((rank, i, g))
        hits.sort(key=lambda h: (h[0], h[1]))
        result = [h[2] for h in hits]
        # On a tapé / collé le caractère lui-même : on l'affiche en premier.
        raw = query.strip()
        exact = cls._by_char.get(raw) or cls._by_char.get(raw + "️")
        if exact and all(g.id != exact.id for g in result):
            result.insert(0, exact)
        return result


FILTERS = [("all", "Tout"), ("emoji", "Emoji"), ("symbols", "Symboles")]


def next_filter(flt):
    keys = [k for k, _ in FILTERS]
    return keys[(keys.index(flt) + 1) % len(keys)]


def filter_title(flt):
    return dict(FILTERS)[flt]


class Recents:
    _path = os.path.join(DATA_DIR, "recent_glyphs.json")
    chars = load_json(_path, [])

    @classmethod
    def add(cls, char):
        cls.chars = ([char] + [c for c in cls.chars if c != char])[:22]
        save_json(cls._path, cls.chars)

    @classmethod
    def clear(cls):
        cls.chars = []
        save_json(cls._path, cls.chars)

