"""Several sources into one dataset.

Entries with the same (class, spec, content, slot, item) are one figure: the
share is the average of the sources' shares weighted by their samples, the
sample is the sum, and `sources` names who contributed. Drops are the union
per item, one location once. The result does not depend on the order the
sources arrive in.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from .model import STAT_KEYS, validate


def merge(datasets: list) -> dict:
    entries: dict = {}
    drops: dict = {}
    items: dict = {}
    catalyst: dict = {}
    tiersets: dict = {}
    specs: dict = {}
    stats: dict = {}
    players: list = []
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
        for record in dataset.get("catalyst", []):
            catalyst.setdefault((record["slot"], record["armor"], record["item"], record["instance"],
                                 record["encounter"]), record)
        for record in dataset.get("tierset", []):
            tiersets.setdefault(record["class"], record)
        for spec_id, names in dataset.get("specs", {}).items():
            specs.setdefault(spec_id, names)
        seen: dict = {}
        for player in dataset.get("players", []):
            where = (player["class"], player["spec"])
            seen[where] = seen.get(where, 0) + 1
            players.append({**player, "rank": player.get("rank", seen[where]), "items": sorted(set(player["items"]))})
        for record in dataset.get("stats", []):
            held = stats.setdefault((record["class"], record["spec"]),
                                    {"n": 0, "sum": {k: [0.0, 0.0] for k in STAT_KEYS}})
            held["n"] += record["n"]
            for stat in STAT_KEYS:
                held["sum"][stat][0] += record[stat][0] * record["n"]
                held["sum"][stat][1] += record[stat][1] * record["n"]
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
    merged_stats = []
    for (cls, spec), held in sorted(stats.items()):
        record = {"class": cls, "spec": spec, "n": held["n"]}
        for stat in STAT_KEYS:
            record[stat] = [int(held["sum"][stat][0] / held["n"] + 0.5), round(held["sum"][stat][1] / held["n"], 1)]
        merged_stats.append(record)
    return {"source": "merged", "generated": generated, "sources": sorted(set(sources)),
            "entries": merged_entries, "drops": merged_drops,
            "items": [items[i] for i in sorted(items)], "specs": dict(sorted(specs.items(), key=lambda kv: int(kv[0]))),
            "catalyst": [catalyst[k] for k in sorted(catalyst)], "tierset": [tiersets[c] for c in sorted(tiersets)],
            "stats": merged_stats,
            "players": sorted(players, key=lambda p: (p["class"], p["spec"], p["rank"], p["items"]))}


MIN_PLAYERS = 2


def top_per_slot(entries: list, limit: int, min_players: int = MIN_PLAYERS) -> dict:
    """(class, spec, content, slot) -> the `limit` items most worn, best first.

    An item worn by fewer than `min_players` players is noise (one odd character);
    it is left out unless it is the most worn of its slot.
    """
    grouped: dict = defaultdict(list)
    for entry in entries:
        grouped[(entry["class"], entry["spec"], entry["content"], entry["slot"])].append(entry)
    result = {}
    for key, rows in grouped.items():
        ordered = sorted(rows, key=lambda r: (-r["share"], -r["sample"], r["item"]))
        kept = [r for index, r in enumerate(ordered) if index == 0 or round(r["share"] * r["sample"]) >= min_players]
        result[key] = kept[:limit]
    return result


def raid_items(drops: list) -> set:
    """Items that drop in a raid and in no dungeon: wearing one means the player raids."""
    kinds: dict = defaultdict(set)
    for drop in drops:
        kinds[drop["item"]].add(drop["kind"])
    return {item for item, found in kinds.items() if "raid" in found and "dungeon" not in found}


def mplus_groups(merged: dict, group_size: int, max_raid_items: int) -> dict:
    """(class, spec) -> {"pool": all players, "eligible": those with at most `max_raid_items`
    raid items, "group": the first `group_size` of them by rank}. Specializations without players
    do not appear."""
    raids = raid_items(merged.get("drops", []))
    pools: dict = defaultdict(list)
    for player in merged.get("players", []):
        pools[(player["class"], player["spec"])].append(player)
    result = {}
    for key, pool in pools.items():
        pool = sorted(pool, key=lambda p: p["rank"])
        eligible = [p for p in pool if len(raids.intersection(p["items"])) <= max_raid_items]
        result[key] = {"pool": pool, "eligible": eligible, "group": eligible[:group_size]}
    return result


def _group_entries(key: tuple, group: list) -> list:
    counts: dict = defaultdict(Counter)
    for player in group:
        for slot, ids in player.get("gear", {}).items():
            for item in set(ids):
                counts[slot][item] += 1
    return [{"class": key[0], "spec": key[1], "content": "mplus", "slot": slot, "item": item,
             "share": round(count / len(group), 4), "sample": len(group), "sources": ["players"]}
            for slot in sorted(counts) for item, count in sorted(counts[slot].items())]


def _group_stats(group: list):
    rows = [p["stats"] for p in group if "stats" in p]
    if not rows:
        return None
    record = {"n": len(rows)}
    for stat in STAT_KEYS:
        record[stat] = [int(sum(r[stat][0] for r in rows) / len(rows) + 0.5),
                        round(sum(r[stat][1] for r in rows) / len(rows), 1)]
    return record


def derive_mplus(merged: dict, group_size: int, max_raid_items: int) -> dict:
    """The merged dataset with the Mythic+ figures split in two groups.

    For every specialization that has players and a non-empty group of "pure"
    Mythic+ players the entries of content "mplus" become "mplus_all" (the mixed
    top group, as before) and the group's entries take the name "mplus"; the stats
    record gets a `mplus` sub-record with the group's means. Without players (an
    old dataset) or without any eligible player the specialization stays as it was."""
    groups = {key: g["group"] for key, g in mplus_groups(merged, group_size, max_raid_items).items()
              if g["group"] and any(p.get("gear") for p in g["group"])}
    if not groups:
        return merged
    entries = []
    for entry in merged["entries"]:
        if entry["content"] == "mplus" and (entry["class"], entry["spec"]) in groups:
            entry = {**entry, "content": "mplus_all"}
        entries.append(entry)
    for key in sorted(groups):
        entries.extend(_group_entries(key, groups[key]))
    stats = []
    for record in merged.get("stats", []):
        group = groups.get((record["class"], record["spec"]))
        extra = _group_stats(group) if group else None
        stats.append({**record, "mplus": extra} if extra else record)
    return {**merged, "entries": entries, "stats": stats}


def gear_groups(merged: dict, group_size: int, max_raid_items: int) -> dict:
    """(class, spec) -> {"mplus": players, "mplus_all": players} for the gear file, only for the
    specializations whose players carry gear details (`enchants`).

    With a group of pure Mythic+ players "mplus" is that group and "mplus_all" the mixed top group
    (the first `group_size` of the pool), as derive_mplus names the item lists; without such a group
    "mplus" is the mixed top group and there is no "mplus_all"."""
    result = {}
    for key, found in mplus_groups(merged, group_size, max_raid_items).items():
        if not any("enchants" in p for p in found["pool"]):
            continue
        mixed = found["pool"][:group_size]
        if found["group"] and any(p.get("gear") for p in found["group"]):
            result[key] = {"mplus": found["group"], "mplus_all": mixed}
        else:
            result[key] = {"mplus": mixed}
    return result
