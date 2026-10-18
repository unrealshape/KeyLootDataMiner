"""Where the Catalyst's raw pieces drop, and the text of each class's tier set.

The Catalyst turns a piece of a tier slot (head, shoulders, chest, hands, legs) into the
tier piece of the player's armor type. So a tier piece comes from any dungeon drop of the
same slot and armor type: `catalyst_records` lists those drops from the item facts
(klm/sources/blizzard_items.py keeps the slot and the armor type of every item it reads).

`tierset_records` gives every class the set of its highest item level among the items
its players wear, with the set bonuses in English and, when the item API answers in
German, in German too.
"""

from __future__ import annotations

import sys
from datetime import date

from .blizzard import BlizzardError
from .blizzard_items import ARMOR_TYPES, MAX_AGE_DAYS, TIER_SLOTS, read_item

GERMAN = "de_DE"
SLOTS = set(TIER_SLOTS.values())


def log(message):
    print(message, file=sys.stderr, flush=True)


def catalyst_records(drops, cache):
    """The dungeon drops of a tier slot with a known armor type, one record per item and boss:
    [{slot, armor, item, instance, instance_name, encounter, encounter_name}], by item."""
    records, seen = [], set()
    for drop in sorted(drops, key=lambda d: (d["item"], d["instance"], d["encounter"])):
        if drop["kind"] != "dungeon":
            continue
        facts = cache.get(str(drop["item"])) or {}
        slot, armor = facts.get("slot"), facts.get("armor")
        if slot not in SLOTS or armor not in ARMOR_TYPES:
            continue
        key = (drop["item"], drop["instance"], drop["encounter"])
        if key in seen:
            continue
        seen.add(key)
        records.append({"slot": slot, "armor": armor, "item": drop["item"], "instance": drop["instance"],
                        "instance_name": drop["instance_name"], "encounter": drop["encounter"],
                        "encounter_name": drop["encounter_name"]})
    return records


def chosen_sets(entries, cache):
    """class -> (set name, an item id of the set): of the sets of the items a class's players wear, the one with
    the highest item level (the season's, not an older one)."""
    best: dict = {}
    for entry in entries:
        facts = cache.get(str(entry["item"])) or {}
        name = facts.get("set")
        if not name or not facts.get("effects"):
            continue
        rank = (facts.get("ilvl", 0), name, -entry["item"])
        held = best.get(entry["class"])
        if held is None or rank > held[0]:
            best[entry["class"]] = (rank, name, entry["item"])
    return {cls: (name, item) for cls, (_, name, item) in sorted(best.items())}


def german_text(client, item_id, cache, today):
    """The set name and bonuses of an item read in German, from the cache or the item API; None when unavailable."""
    key = f"de:{item_id}"
    held = cache.get(key)
    if held and (today - date.fromisoformat(held["day"])).days <= MAX_AGE_DAYS:
        return held if held.get("set") else None
    try:
        facts = read_item(client, item_id, today, GERMAN)
    except BlizzardError:
        return None
    cache[key] = {"set": facts["set"], "effects": facts["effects"], "day": today.isoformat()}
    return cache[key] if facts["set"] else None


def tierset_records(client, entries, cache, today=None, progress=log):
    """[{class, name, name_de?, bonuses: {"2": {en, de?}, ...}}] for the classes that have a tier set."""
    today = today or date.today()
    records = []
    for cls, (name, item) in chosen_sets(entries, cache).items():
        english = cache[str(item)]["effects"]
        german = german_text(client, item, cache, today)
        record = {"class": cls, "name": name, "bonuses": {}}
        if german:
            record["name_de"] = german["set"]
        for count, text in sorted(english.items(), key=lambda kv: int(kv[0])):
            bonus = {"en": text}
            if german and german["effects"].get(count):
                bonus["de"] = german["effects"][count]
            record["bonuses"][count] = bonus
        records.append(record)
    progress(f"{len(records)} tier set(s)")
    return records
