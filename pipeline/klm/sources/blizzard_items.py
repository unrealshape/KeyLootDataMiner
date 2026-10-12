"""Item facts and the sources the Adventure Journal does not list.

For the items the addon shows (the most worn per slot) this reads Blizzard's item
API once and keeps the answer in a cache file, then names a source for each
item the journal has no drop for:

  catalyst  an item of the season's tier set, or a piece of the same theme the
            set does not list (a cloak, bracers ...): made at the Catalyst or
            dropped as a tier token
  crafted   an item whose name is that of a Midnight profession recipe
  other     everything else: vendors, PvP, world drops, older seasons

and the secondary stats each item carries (for filtering), as letters:
c critical strike, h haste, m mastery, v versatility.
"""

from __future__ import annotations

import re
import sys
from datetime import date

from .blizzard import BlizzardError

# Professions that craft gear and trinkets. Tiers whose name starts with the
# expansion's name are read ("Midnight Blacksmithing").
CRAFT_PROFESSIONS = (164, 165, 197, 755, 202, 773, 171)
EXPANSION = "Midnight"
MAX_AGE_DAYS = 30
STAT_LETTERS = (("CRIT", "c"), ("HASTE", "h"), ("MASTERY", "m"), ("VERSATILITY", "v"))


def log(message):
    print(message, file=sys.stderr, flush=True)


def recipe_names(client, progress=log):
    """Lower-case names of every recipe in the current expansion's craft tiers."""
    names = set()
    for profession in CRAFT_PROFESSIONS:
        info = client.get(f"/data/wow/profession/{profession}", "static")
        for tier in info.get("skill_tiers", []):
            if not tier["name"].startswith(EXPANSION):
                continue
            detail = client.get(f"/data/wow/profession/{profession}/skill-tier/{tier['id']}", "static")
            for category in detail.get("categories", []):
                for recipe in category.get("recipes", []):
                    names.add(recipe["name"].strip().lower())
    progress(f"{len(names)} recipe names")
    return names


def stat_letters(preview):
    found = set()
    for stat in preview.get("stats", []):
        if stat.get("is_negated"):
            continue
        kind = stat.get("type", {}).get("type", "")
        for needle, letter in STAT_LETTERS:
            if needle in kind:
                found.add(letter)
    return "".join(letter for _, letter in STAT_LETTERS if letter in found)


def read_item(client, item_id, today=None):
    """The facts the addon needs about one item, from the item API."""
    data = client.get(f"/data/wow/item/{item_id}", "static")
    preview = data.get("preview_item") or {}
    return {"name": data.get("name", ""), "ilvl": data.get("level", 0),
            "set": (preview.get("set") or {}).get("item_set", {}).get("name"),
            "stats": stat_letters(preview), "day": (today or date.today()).isoformat()}


def refresh(client, item_ids, cache, today=None, progress=log):
    """Reads every item not in `cache` (or older than MAX_AGE_DAYS) into it.

    An item the API does not know (404) is recorded as unknown and not asked again
    until it goes stale. Returns how many were read.
    """
    today = today or date.today()
    read = 0
    for item_id in sorted(item_ids):
        held = cache.get(str(item_id))
        if held and (today - date.fromisoformat(held["day"])).days <= MAX_AGE_DAYS:
            continue
        try:
            cache[str(item_id)] = read_item(client, item_id, today)
        except BlizzardError as error:
            if error.status != 404:
                raise
            cache[str(item_id)] = {"name": "", "ilvl": 0, "set": None, "stats": "", "day": today.isoformat()}
        read += 1
        if read % 200 == 0:
            progress(f"items: {read} read")
    return read


def themes(cache):
    """The tier sets' themes, as lower-case fragments an item of the theme carries:

    "Radiance of the Consecrated Flame" -> "consecrated flame"
    "Ophidian Oracle's Prophecy" -> "ophidian oracle" (its pieces read "... of the Ophidian
    Oracle" or "Ophidian Oracle's ...", so the possessive is dropped)
    """
    found = set()
    for facts in cache.values():
        name = facts.get("set")
        if not name:
            continue
        match = re.search(r"\bof (?:the )?(.+)$", name)
        if match:
            found.add(match.group(1).strip().lower())
        possessive = re.match(r"(.+?'s)\b", name)
        if possessive:
            found.add(possessive.group(1)[:-2].strip().lower())
        if not match and not possessive:
            found.add(name.strip().lower())
    return found


def source_of(facts, recipes, tier_themes):
    """"catalyst", "crafted" or "other" for an item the journal does not list."""
    if facts.get("set"):
        return "catalyst"
    name = facts.get("name", "").strip().lower()
    if name and any(theme in name for theme in tier_themes):
        return "catalyst"
    if name and name in recipes:
        return "crafted"
    return "other"


def other_drops(item_ids, journal_items, cache, recipes):
    """Drop records (no instance) for the items the journal does not list."""
    tier_themes = themes(cache)
    labels = {"catalyst": "Catalyst / tier", "crafted": "Crafted", "other": "Other source"}
    drops = []
    for item_id in sorted(item_ids):
        if item_id in journal_items:
            continue
        facts = cache.get(str(item_id))
        if facts is None:
            continue
        kind = source_of(facts, recipes, tier_themes)
        drops.append({"item": item_id, "kind": kind, "instance": 0, "instance_name": labels[kind],
                      "encounter": 0, "encounter_name": ""})
    return drops


def item_records(item_ids, cache, tier_themes):
    """The `items` section of a dataset: stats letters and whether it is tier."""
    records = []
    for item_id in sorted(item_ids):
        facts = cache.get(str(item_id))
        if facts is None:
            continue
        tier = bool(facts.get("set")) or any(t in facts.get("name", "").strip().lower() for t in tier_themes)
        records.append({"item": item_id, "stats": facts.get("stats", ""), "ilvl": facts.get("ilvl", 0), "tier": tier})
    return records
