"""The talent builds of the best Mythic+ players, from the Profile API.

For every character read for the equipment this reads
`/profile/wow/character/{realm}/{name}/specializations` once and keeps, of the
character's own specialization, the ACTIVE loadout (`is_active`):

    {"code": "CYQA...",                      the import string (`talent_loadout_code`)
     "hero": "Lightsmith",                   the hero talent tree
     "selected": [ {id, name, spell, rank, tree: "class"|"spec"|"hero"}, ... ]}

`id` is the talent's id (the tooltip's `talent.id`, else the entry's own id), `spell`
the spell behind it. Picks without a tooltip (free or choice nodes the API gives no
name for) are left out. The answer is cached in a file for 7 days like the stats
(key region/realm/name, see blizzard_stats.cache_key); a character that cannot be
read is skipped.
"""

from __future__ import annotations

import urllib.parse
from datetime import date

from .blizzard import BlizzardError
from .blizzard_stats import MAX_AGE_DAYS, cache_key, lookup_cached

TREES = (("selected_class_talents", "class"), ("selected_spec_talents", "spec"), ("selected_hero_talents", "hero"))


def parse_specializations(data, spec_id):
    """The active loadout of the specialization `spec_id` as described above, or None."""
    for specialization in data.get("specializations", []):
        if specialization.get("specialization", {}).get("id") != spec_id:
            continue
        for loadout in specialization.get("loadouts", []):
            if not loadout.get("is_active"):
                continue
            selected = []
            for field, tree in TREES:
                for pick in loadout.get(field, []):
                    tooltip = pick.get("tooltip", {})
                    talent = tooltip.get("talent", {})
                    spell = tooltip.get("spell_tooltip", {}).get("spell", {})
                    name = talent.get("name") or spell.get("name")
                    ident = talent.get("id", pick.get("id"))
                    if not name or not isinstance(ident, int):
                        continue
                    selected.append({"id": ident, "name": name, "spell": spell.get("id"),
                                     "rank": pick.get("rank", 1), "tree": tree})
            code = loadout.get("talent_loadout_code")
            if not code or not selected:
                return None
            return {"code": code, "hero": loadout.get("selected_hero_talent_tree", {}).get("name"),
                    "selected": selected}
    return None


def read_talents(client, character):
    """The character's talents (parse_specializations), or None when they cannot be read."""
    path = ("/profile/wow/character/" + urllib.parse.quote(character["realm"]) + "/"
            + urllib.parse.quote(character["name"].lower()) + "/specializations")
    try:
        return parse_specializations(client.get(path, "profile"), character["spec"])
    except BlizzardError:
        return None


def cached_talents(client, character, cache, today=None):
    """Talents from the cache while fresh (and for the same specialization), else read and cached."""
    today = today or date.today()
    held = lookup_cached(cache, character)
    if held and held.get("spec") == character["spec"] and (today - date.fromisoformat(held["day"])).days <= MAX_AGE_DAYS:
        return held["talents"]
    talents = read_talents(client, character)
    if talents is None:
        return None
    cache[cache_key(character)] = {"day": today.isoformat(), "spec": character["spec"], "talents": talents}
    return talents
