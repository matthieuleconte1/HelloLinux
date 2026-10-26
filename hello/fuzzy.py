"""Recherche floue (AppIndex.swift › Fuzzy) : mêmes scores que la version macOS."""
import re
import unicodedata

_SPLIT = re.compile(r"[ \-_.]+")


def fold(s):
    """Minuscules, sans accents : « Éditeur » → « editeur »."""
    decomposed = unicodedata.normalize("NFD", s.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def score(query, target):
    """Score de correspondance (plus haut = meilleur), None si pas de correspondance.
    `query` et `target` doivent déjà être normalisés avec `fold`."""
    if not query:
        return 0
    if target == query:
        return 1000
    if target.startswith(query):
        return 900 - min(len(target) - len(query), 50)

    words = [w for w in _SPLIT.split(target) if w]
    if any(w.startswith(query) for w in words):
        return 800 - min(len(target), 50)
    if len(query) >= 2 and "".join(w[0] for w in words).startswith(query):
        return 750
    if query in target:
        return 600 - min(len(target), 50)
    if len(query) < 3:
        return None

    # Sous-séquence : « vsc » → « visual studio code »
    result = 300
    index = 0
    adjacent = False
    for ch in query:
        found = target.find(ch, index)
        if found < 0:
            return None
        if found == index and adjacent:
            result += 12
        else:
            result -= min(found - index, 10)
        adjacent = True
        index = found + 1
    return max(result, 1)


def words_match(query, text):
    """Tous les mots de la requête sont des préfixes de mots du texte."""
    words = text.split(" ")
    return all(any(w.startswith(q) for w in words) for q in query.split(" ") if q)
