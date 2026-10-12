"""Several sources into one dataset.

Entries with the same (class, spec, content, slot, item) are one figure: the
share is the average of the sources' shares weighted by their samples, the
sample is the sum, and `sources` names who contributed. Drops are the union
per item, one location once. The result does not depend on the order the
sources arrive in.
"""

from __future__ import annotations

from collections import defaultdict

from .model import validate


def merge(datasets: list) -> dict:
    entries: dict = {}
    drops: dict = {}
    items: dict = {}
    specs: dict = {}
    sources: list = []
    generated = ""
    for dataset in datasets:
        validate(dataset)
        sources.append(dataset["source"])
        generated = max(generated, dataset["generated"])
        for entry in dataset.get("entries", []):
            key = (entry["class"], entry["spec"], entry["content"], entry["slot"], entry["item"])
            held = entries.get(key)
            if held is None:
                entries[key] = {**entry, "_weighted": entry["share"] * entry["sample"],
                                "sources": {dataset["source"]}}
            else:
                held["_weighted"] += entry["share"] * entry["sample"]
                held["sample"] += entry["sample"]
                held["sources"].add(dataset["source"])
        for drop in dataset.get("drops", []):
            key = (drop["item"], drop["kind"], str(drop["instance"]), str(drop["encounter"]))
            drops.setdefault(key, {**drop, "sources": set()})["sources"].add(dataset["source"])
        for item in dataset.get("items", []):
            items.setdefault(item["item"], item)
        for spec_id, names in dataset.get("specs", {}).items():
            specs.setdefault(spec_id, names)
    merged_entries = []
    for key in sorted(entries):
        held = entries[key]
        weighted = held.pop("_weighted")
        held["share"] = round(weighted / held["sample"], 4)
        held["sources"] = sorted(held["sources"])
        merged_entries.append(held)
    merged_drops = []
    for key in sorted(drops):
        held = drops[key]
        held["sources"] = sorted(held["sources"])
        merged_drops.append(held)
    return {"source": "merged", "generated": generated, "sources": sorted(set(sources)),
            "entries": merged_entries, "drops": merged_drops,
            "items": [items[i] for i in sorted(items)], "specs": dict(sorted(specs.items(), key=lambda kv: int(kv[0])))}


def top_per_slot(entries: list, limit: int) -> dict:
    """(class, spec, content, slot) -> the `limit` items most worn, best first."""
    grouped: dict = defaultdict(list)
    for entry in entries:
        grouped[(entry["class"], entry["spec"], entry["content"], entry["slot"])].append(entry)
    return {key: sorted(rows, key=lambda r: (-r["share"], -r["sample"], r["item"]))[:limit]
            for key, rows in grouped.items()}
