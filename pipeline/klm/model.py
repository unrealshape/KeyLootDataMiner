"""The normalized records every source delivers.

A source hands over one dataset (a plain dict, stored as JSON):

    {
      "source": "blizzard-journal",
      "generated": "2026-10-12T00:00:00Z",
      "entries": [ {class, spec, content, slot, item, share, sample}, ... ],
      "drops":   [ {item, kind, instance, instance_name, encounter, encounter_name}, ... ]
    }

`entries` say how often the best players of a class and specialization wear
an item (`share`, 0-1, out of `sample` players) in one content; `drops` say
where an item comes from. A source may deliver either list or both.
"""

from __future__ import annotations

CONTENTS = ("mplus", "raid")
DROP_KINDS = ("dungeon", "raid", "crafted", "vendor", "other")
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
    return dataset
