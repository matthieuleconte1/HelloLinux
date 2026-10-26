"""Mémoire d'utilisation « frécence » (fréquence × récence, à la Firefox) + apprentissage
de ce que tu tapes : si tu choisis Firefox après avoir tapé « f », « f » finira par donner Firefox."""
import datetime as dt
import math
import os
import time

from .fuzzy import fold
from .settings import DATA_DIR, Debounced, load_json, save_json, settings

_PATH = os.path.join(DATA_DIR, "usage.json")
records = load_json(_PATH, {})
_save = Debounced(2, lambda: save_json(_PATH, dict(records)))


def record(item_id, query=""):
    r = records.setdefault(item_id, {"count": 0, "first": time.time(), "last": 0, "recent": [], "queries": {}})
    now = time.time()
    r["count"] += 1
    r["last"] = now
    r["recent"] = (r["recent"] + [now])[-60:]
    q = fold(query.strip())
    if q and settings.learnQueries:
        # On apprend chaque préfixe tapé : « fir » apprend aussi « f » et « fi ».
        for length in range(1, min(len(q), 8) + 1):
            prefix = q[:length]
            r["queries"][prefix] = r["queries"].get(prefix, 0) + 1
    _save()


def _weight(days):
    if days < 1:
        return 100
    if days < 4:
        return 80
    if days < 14:
        return 60
    if days < 31:
        return 40
    if days < 90:
        return 20
    return 10


def frecency(item_id, now=None):
    r = records.get(item_id)
    if not r or r["count"] <= 0:
        return 0.0
    if not r["recent"]:
        return r["count"] * 10.0
    now = now or time.time()
    weights = [_weight((now - t) / 86400) for t in r["recent"]]
    return r["count"] * sum(weights) / len(weights)


def boost(item_id, folded):
    """Bonus ajouté au score de correspondance (qui va de ~1 à 1000)."""
    f = frecency(item_id) if settings.frecencyRanking else 0
    bonus = min(250, int(60 * math.log2(1 + f / 40))) if f > 0 else 0
    if settings.learnQueries:
        learned = records.get(item_id, {}).get("queries", {}).get(folded, 0)
        if learned > 0:
            bonus += min(450, 150 + learned * 60)
    return bonus


def top(n):
    now = time.time()
    scored = sorted(((frecency(k, now), k) for k in records), reverse=True)
    return [k for _, k in scored[:n]]


def launches(item_id, days):
    limit = time.time() - days * 86400
    return sum(1 for t in records.get(item_id, {}).get("recent", []) if t > limit)


def daily(item_id, days):
    """Ouvertures par jour sur les `days` derniers jours (le plus ancien d'abord)."""
    today = dt.date.today()
    buckets = [0] * days
    for t in records.get(item_id, {}).get("recent", []):
        diff = (today - dt.date.fromtimestamp(t)).days
        if 0 <= diff < days:
            buckets[days - 1 - diff] += 1
    return buckets


def shortcuts(item_id, limit=3):
    """Les requêtes courtes les plus utilisées pour un élément (ex. « f », « fi »)."""
    queries = records.get(item_id, {}).get("queries", {})
    short = [(k, v) for k, v in queries.items() if len(k) <= 4]
    short.sort(key=lambda kv: (-kv[1], len(kv[0])))
    return [k for k, _ in short[:limit]]


def forget(item_id):
    records.pop(item_id, None)
    _save()


def reset():
    records.clear()
    _save()
