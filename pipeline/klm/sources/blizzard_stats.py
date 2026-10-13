"""Secondary and side stats of the best Mythic+ players, from the Profile API.

For every character read for the equipment this reads `/statistics` once, keeps
the answer in a cache file (a daily run reads only new or stale characters) and
averages per specialization:

    "stats": [ {class, spec, n, c: [rating, percent], h, m, v, leech, avoidance, speed}, ... ]

c crit, h haste, m mastery, v versatility; `n` is the number of characters whose
values went in. A character that cannot be read is skipped.

The API's fields: melee_/ranged_/spell_crit and _haste, mastery, lifesteal, avoidance
and speed are blocks {rating_normalized, rating_bonus, value?}: the rating is
`rating_normalized`, the percent is `value` (avoidance and speed have only
`rating_bonus`); versatility is the rating (a number) and
`versatility_damage_done_bonus` its percent.
"""

from __future__ import annotations

import urllib.parse
from datetime import date

from .blizzard import BlizzardError

STAT_KEYS = ("c", "h", "m", "v", "leech", "avoidance", "speed")
MAX_AGE_DAYS = 7


def round_half_up(value):
    return int(value + 0.5) if value >= 0 else -int(-value + 0.5)


def _pair(block):
    """(rating, percent) of an API stat block, or None."""
    if not isinstance(block, dict):
        return None
    rating = block.get("rating_normalized")
    percent = block["value"] if "value" in block else block.get("rating_bonus")
    if not isinstance(rating, (int, float)) or not isinstance(percent, (int, float)):
        return None
    return float(rating), float(percent)


def _highest(data, names):
    """The variant (melee / ranged / spell) with the highest rating."""
    pairs = [p for p in (_pair(data.get(name)) for name in names) if p]
    return max(pairs, key=lambda p: p[0]) if pairs else None


def parse_statistics(data):
    """{key: [rating, percent]} from a /statistics answer, or None when a stat is missing."""
    versatility = data.get("versatility")
    bonus = data.get("versatility_damage_done_bonus")
    if not isinstance(versatility, (int, float)) or not isinstance(bonus, (int, float)):
        return None
    found = {
        "c": _highest(data, ("melee_crit", "ranged_crit", "spell_crit")),
        "h": _highest(data, ("melee_haste", "ranged_haste", "spell_haste")),
        "m": _pair(data.get("mastery")),
        "v": (float(versatility), float(bonus)),
        "leech": _pair(data.get("lifesteal")),
        "avoidance": _pair(data.get("avoidance")),
        "speed": _pair(data.get("speed")),
    }
    if any(found[k] is None for k in STAT_KEYS):
        return None
    return {k: list(found[k]) for k in STAT_KEYS}


def read_statistics(client, character):
    """The character's stats, or None when they cannot be read (any API error)."""
    path = ("/profile/wow/character/" + urllib.parse.quote(character["realm"]) + "/"
            + urllib.parse.quote(character["name"].lower()) + "/statistics")
    try:
        return parse_statistics(client.get(path, "profile"))
    except BlizzardError:
        return None


def cache_key(character):
    """region/realm/name for a character that knows its region, else realm/name (one-region runs)."""
    key = character["realm"] + "/" + character["name"].lower()
    return character["region"] + "/" + key if character.get("region") else key


def lookup_cached(cache, character):
    """The cache entry of a character. Entries written before the region was part of the key
    (realm/name) were all European: they still serve a European character."""
    held = cache.get(cache_key(character))
    if held is None and character.get("region") == "eu":
        held = cache.get(character["realm"] + "/" + character["name"].lower())
    return held


def cached_statistics(client, character, cache, today=None):
    """Stats from the cache while fresh, else read (and cached); None when unreadable."""
    today = today or date.today()
    key = cache_key(character)
    held = lookup_cached(cache, character)
    if held and (today - date.fromisoformat(held["day"])).days <= MAX_AGE_DAYS:
        return held["stats"]
    stats = read_statistics(client, character)
    if stats is None:
        return None
    cache[key] = {"day": today.isoformat(), "stats": stats}
    return stats


def stats_for(spec_key, players):
    """One `stats` record of a specialization from the players' stats; None without players."""
    if not players:
        return None
    n = len(players)
    record = {"class": spec_key[0], "spec": spec_key[1], "n": n}
    for key in STAT_KEYS:
        record[key] = [round_half_up(sum(p[key][0] for p in players) / n),
                       round(sum(p[key][1] for p in players) / n, 1)]
    return record
