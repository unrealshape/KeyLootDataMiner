"""The normalized records every source delivers.

A source hands over one dataset (a plain dict, stored as JSON):

    {
      "source": "blizzard-journal",
      "generated": "2026-10-12T00:00:00Z",
      "entries": [ {class, spec, content, slot, item, share, sample}, ... ],
      "drops":   [ {item, kind, instance, instance_name, encounter, encounter_name}, ... ],
      "items":   [ {item, stats, ilvl, tier}, ... ],           (optional)
      "specs":   { "66": ["paladin", "protection"], ... },     (optional)
      "stats":   [ {class, spec, n, c: [rating, percent], h, m, v, leech, avoidance, speed}, ... ]  (optional)
      "players": [ {class, spec, rank, items: [ids], gear: {slot: [ids]}, stats: {c: [..], ...},
                    name, realm, slug?, region, key, ilvl, race?, rating?, enchants: {slot: [{id, name}]},
                    gems: [{id, name, color}], embellishments: [{id, name, item}],
                    talents: {code, hero, selected: [{id, name, spell, rank, tree}]}}, ... ]  (optional)
    }

`entries` say how often the best players of a class and specialization wear
an item (`share`, 0-1, out of `sample` players) in one content; `drops` say
where an item comes from (a drop without an instance, such as the Catalyst or
a craft, has instance 0); `items` carry what filters need (secondary stats as
letters of "chmv", item level, tier piece); `specs` map the game's specialization
ids to our class and specialization names; `players` are the individual Mythic+
players of the pool in ranking order (`rank` 1 is the best; `gear` and `stats`
are optional): the merge step uses them to tell the players who raid from the
players who only run Mythic+. A source may deliver any of them.
"""

from __future__ import annotations

CONTENTS = ("mplus", "raid")
DROP_KINDS = ("dungeon", "raid", "catalyst", "crafted", "vendor", "other")
STAT_LETTERS = "chmv"
ENTRY_FIELDS = ("class", "spec", "content", "slot", "item", "share", "sample")
STAT_KEYS = ("c", "h", "m", "v", "leech", "avoidance", "speed")
DROP_FIELDS = ("item", "kind", "instance", "instance_name", "encounter", "encounter_name")


GEM_COLORS = ("red", "green", "purple", "blue", "meta", "other")
TALENT_TREES = ("class", "spec", "hero")


class DatasetError(ValueError):
    pass


def _check_keys(record: dict, fields: tuple, where: str) -> None:
    missing = [f for f in fields if f not in record]
    if missing:
        raise DatasetError(f"{where}: missing {', '.join(missing)}")


def _is_id(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _check_player_gear(player: dict, where: str) -> None:
    """The optional gear and talent details of a player (all fields optional)."""
    for field in ("name", "realm", "slug", "region", "race"):
        if field in player and not (isinstance(player[field], str) and player[field]):
            raise DatasetError(f"{where}: {field} must be a text")
    if "rating" in player and (not isinstance(player["rating"], int) or isinstance(player["rating"], bool)
                               or player["rating"] < 0):
        raise DatasetError(f"{where}: rating must be a non-negative integer")
    enchants = player.get("enchants", {})
    if not isinstance(enchants, dict):
        raise DatasetError(f"{where}: enchants must map slots to lists")
    for slot, rows in enchants.items():
        if not (isinstance(rows, list) and all(isinstance(r, dict) and _is_id(r.get("id")) for r in rows)):
            raise DatasetError(f"{where}: enchants[{slot!r}] must be a list of {{id, name}}")
    for field in ("gems", "embellishments"):
        rows = player.get(field, [])
        if not (isinstance(rows, list) and all(isinstance(r, dict) and _is_id(r.get("id")) for r in rows)):
            raise DatasetError(f"{where}: {field} must be a list of records with an id")
    if any(g.get("color") not in GEM_COLORS for g in player.get("gems", [])):
        raise DatasetError(f"{where}: a gem colour is not one of {GEM_COLORS}")
    if "talents" in player:
        talents = player["talents"]
        if not (isinstance(talents, dict) and isinstance(talents.get("code"), str) and talents["code"]
                and isinstance(talents.get("selected"), list)
                and all(isinstance(t, dict) and _is_id(t.get("id")) and t.get("tree") in TALENT_TREES
                        for t in talents["selected"])):
            raise DatasetError(f"{where}: talents need a code and picks {{id, name, tree}}")


def validate(dataset: dict) -> dict:
    """Returns the dataset when it is well formed, else raises DatasetError."""
    if not isinstance(dataset, dict):
        raise DatasetError("a dataset is an object")
    for name in ("source", "generated"):
        if not isinstance(dataset.get(name), str) or not dataset[name]:
            raise DatasetError(f"dataset needs a text '{name}'")
    for index, entry in enumerate(dataset.get("entries", [])):
        where = f"entries[{index}]"
        _check_keys(entry, ENTRY_FIELDS, where)
        if entry["content"] not in CONTENTS:
            raise DatasetError(f"{where}: content {entry['content']!r} is not one of {CONTENTS}")
        if not isinstance(entry["item"], int) or entry["item"] <= 0:
            raise DatasetError(f"{where}: item must be a positive integer")
        if not 0 <= entry["share"] <= 1:
            raise DatasetError(f"{where}: share must be between 0 and 1")
        if not isinstance(entry["sample"], int) or entry["sample"] <= 0:
            raise DatasetError(f"{where}: sample must be a positive integer")
    for index, drop in enumerate(dataset.get("drops", [])):
        where = f"drops[{index}]"
        _check_keys(drop, DROP_FIELDS, where)
        if drop["kind"] not in DROP_KINDS:
            raise DatasetError(f"{where}: kind {drop['kind']!r} is not one of {DROP_KINDS}")
        if not isinstance(drop["item"], int) or drop["item"] <= 0:
            raise DatasetError(f"{where}: item must be a positive integer")
    for index, item in enumerate(dataset.get("items", [])):
        where = f"items[{index}]"
        _check_keys(item, ("item", "stats", "ilvl", "tier"), where)
        if not isinstance(item["item"], int) or item["item"] <= 0:
            raise DatasetError(f"{where}: item must be a positive integer")
        if not isinstance(item["stats"], str) or any(c not in STAT_LETTERS for c in item["stats"]):
            raise DatasetError(f"{where}: stats are letters of {STAT_LETTERS!r}")
        if not isinstance(item["ilvl"], int) or not isinstance(item["tier"], bool):
            raise DatasetError(f"{where}: ilvl is an integer and tier a boolean")
    for index, record in enumerate(dataset.get("stats", [])):
        where = f"stats[{index}]"
        _check_keys(record, ("class", "spec", "n") + STAT_KEYS, where)
        if not isinstance(record["n"], int) or isinstance(record["n"], bool) or record["n"] <= 0:
            raise DatasetError(f"{where}: n must be a positive integer")
        for stat in STAT_KEYS:
            pair = record[stat]
            if not (isinstance(pair, list) and len(pair) == 2
                    and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in pair)):
                raise DatasetError(f"{where}: {stat} must be [rating, percent]")
    for index, player in enumerate(dataset.get("players", [])):
        where = f"players[{index}]"
        _check_keys(player, ("class", "spec", "items"), where)
        if not (isinstance(player["items"], list)
                and all(isinstance(i, int) and not isinstance(i, bool) and i > 0 for i in player["items"])):
            raise DatasetError(f"{where}: items must be a list of positive integers")
        if "rank" in player and (not isinstance(player["rank"], int) or player["rank"] <= 0):
            raise DatasetError(f"{where}: rank must be a positive integer")
        for slot, ids in player.get("gear", {}).items():
            if not (isinstance(ids, list) and all(isinstance(i, int) and i > 0 for i in ids)):
                raise DatasetError(f"{where}: gear[{slot!r}] must be a list of item ids")
        if "stats" in player:
            for stat in STAT_KEYS:
                pair = player["stats"].get(stat)
                if not (isinstance(pair, list) and len(pair) == 2
                        and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in pair)):
                    raise DatasetError(f"{where}: stats.{stat} must be [rating, percent]")
        _check_player_gear(player, where)
    for spec_id, names in dataset.get("specs", {}).items():
        if not spec_id.isdigit() or not (isinstance(names, list) and len(names) == 2
                                         and all(isinstance(n, str) and n for n in names)):
            raise DatasetError(f"specs[{spec_id!r}]: expected an id and [class, spec]")
    return dataset
