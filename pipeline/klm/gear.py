"""What the best players of a group wear besides items, and how they are specced.

`summarize(players)` condenses a group of `players` records (klm/model.py) to the
figures the addon's gear page shows (see lua.gear_file for the Lua form): enchants
per slot, gems, gem signatures, embellishments, races, talent builds and the
heatmap of chosen talents, the hero trees and the best players. Every figure counts
players, not pieces: a player with two identical rings enchanted alike counts once.
Ties are broken by id or name so the same players give the same bytes.
"""

from __future__ import annotations

from collections import Counter

LIMITS = {"enchants": 5, "gems": 10, "gemSets": 3, "embellishments": 5, "races": 5, "builds": 3, "players": 10}
MIN_RACES = 10   # fewer players with a known race make no meaningful distribution
COLOR_ORDER = ("meta", "red", "green", "blue", "purple", "other")


def gem_signature(gems: list) -> dict:
    """{color: count} of a player's gems, e.g. {"meta": 1, "green": 2, "red": 1}."""
    return dict(Counter(g["color"] for g in gems))


def _ranked(counter: Counter, limit=None) -> list:
    rows = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    return rows[:limit] if limit else rows


def best_players(players: list, limit: int) -> list:
    """The listed players: the rated ones first by rating (a tie: higher key level, then name), then the
    rest by rank. Without any rating this is the ranking order."""
    named = [p for p in players if p.get("name")]
    rated = sorted((p for p in named if isinstance(p.get("rating"), int)),
                   key=lambda p: (-p["rating"], -(p.get("key") or 0), p["name"], p.get("rank", 0)))
    rest = sorted((p for p in named if not isinstance(p.get("rating"), int)), key=lambda p: p.get("rank", 0))
    return (rated + rest)[:limit]


def summarize(players: list) -> dict:
    enchants: dict = {}
    gems, embellishments, races = Counter(), Counter(), Counter()
    gem_info, emb_info = {}, {}
    sets, builds, talents, heroes = Counter(), Counter(), Counter(), Counter()
    build_hero: dict = {}
    talent_info: dict = {}
    for player in players:
        for slot, rows in player.get("enchants", {}).items():
            counter, info = enchants.setdefault(slot, (Counter(), {}))
            for row in rows:
                info.setdefault(row["id"], (row.get("name", ""), row.get("item")))
            counter.update({row["id"] for row in rows})
        for gem in player.get("gems", []):
            gem_info.setdefault(gem["id"], gem)
        gems.update({g["id"] for g in player.get("gems", [])})
        for emb in player.get("embellishments", []):
            emb_info.setdefault(emb["id"], emb)
        embellishments.update({e["id"] for e in player.get("embellishments", [])})
        if player.get("gems"):
            signature = gem_signature(player["gems"])
            sets[tuple((color, signature[color]) for color in COLOR_ORDER if color in signature)] += 1
        if player.get("race"):
            races[player["race"]] += 1
        build = player.get("talents")
        if build:
            builds[build["code"]] += 1
            if build.get("hero"):
                build_hero.setdefault(build["code"], build["hero"])
                heroes[build["hero"]] += 1
            seen = set()
            for talent in build["selected"]:
                key = (talent["tree"], talent["id"])
                if key in seen:
                    continue
                seen.add(key)
                talents[key] += 1
                talent_info.setdefault(key, talent)
    return {
        "n": len(players),
        "enchants": {slot: [dict({"id": i, "name": info[i][0], "n": n}, **({"item": info[i][1]} if info[i][1] else {}))
                            for i, n in _ranked(counter, LIMITS["enchants"])]
                     for slot, (counter, info) in sorted(enchants.items())},
        "gems": [{"id": i, "name": gem_info[i].get("name", ""), "color": gem_info[i]["color"], "n": n}
                 for i, n in _ranked(gems, LIMITS["gems"])],
        "gemSets": [{"sig": dict(sig), "n": n} for sig, n in _ranked(sets, LIMITS["gemSets"])],
        "embellishments": [{"id": i, "name": emb_info[i].get("name", ""), "n": n}
                           for i, n in _ranked(embellishments, LIMITS["embellishments"])],
        "races": ([{"name": r, "n": n} for r, n in _ranked(races, LIMITS["races"])]
                  if sum(races.values()) >= MIN_RACES else []),
        "builds": [{"code": c, "n": n, "hero": build_hero.get(c)} for c, n in _ranked(builds, LIMITS["builds"])],
        "talents": [{"id": talent_info[k]["id"], "name": talent_info[k]["name"], "n": n, "tree": k[0]}
                    for k, n in sorted(talents.items(), key=lambda kv: (-kv[1], kv[0][1], kv[0][0]))],
        "heroes": [{"name": h, "n": n} for h, n in _ranked(heroes)],
        "players": [{k: p[k] for k in ("name", "realm", "region", "race", "rating", "ilvl", "key") if k in p}
                    for p in best_players(players, LIMITS["players"])],
    }
