"""The normalized records every source delivers.

A source hands over one dataset (a plain dict, stored as JSON):

    {
      "source": "blizzard-journal",
      "generated": "2026-10-12T00:00:00Z",
      "entries": [ {class, spec, content, slot, item, share, sample}, ... ],
      "drops":   [ {item, kind, instance, instance_name, encounter, encounter_name}, ... ],
      "items":   [ {item, stats, ilvl, tier}, ... ],           (optional)
      "specs":   { "66": ["paladin", "protection"], ... }      (optional)
    }

`entries` say how often the best players of a class and specialization wear
an item (`share`, 0-1, out of `sample` players) in one content; `drops` say
where an item comes from (a drop without an instance, such as the Catalyst or
a craft, has instance 0); `items` carry what filters need (secondary stats as
letters of "chmv", item level, tier piece); `specs` map the game's specialization
ids to our class and specialization names. A source may deliver any of them.
"""

from __future__ import annotations

CONTENTS = ("mplus", "raid")
DROP_KINDS = ("dungeon", "raid", "catalyst", "crafted", "vendor", "other")
STAT_LETTERS = "chmv"
ENTRY_FIELDS = ("class", "spec", "content", "slot", "item", "share", "sample")
DROP_FIELDS = ("item", "kind", "instance", "instance_name", "encounter", "encounter_name")


class DatasetError(ValueError):
    pass


def _check_keys(record: dict, fields: tuple, where: str) -> None:
    missing = [f for f in fields if f not in record]
    if missing:
        raise DatasetError(f"{where}: missing {', '.join(missing)}")


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
    for spec_id, names in dataset.get("specs", {}).items():
        if not spec_id.isdigit() or not (isinstance(names, list) and len(names) == 2
                                         and all(isinstance(n, str) and n for n in names)):
            raise DatasetError(f"specs[{spec_id!r}]: expected an id and [class, spec]")
    return dataset
