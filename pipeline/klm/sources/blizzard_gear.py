"""What the best Mythic+ players wear, from Blizzard's Game Data and Profile APIs.

    season periods x connected realms x season dungeons  -> leaderboard groups
      -> every member: realm, name, specialization, key level
      -> per specialization the best `top_per_spec` characters
      -> their equipment -> per slot the share of players wearing each item

delivers `entries` records (klm/model.py), content "mplus". Where an item drops
comes from klm.sources.blizzard.

A character that cannot be read (404: renamed, hidden or inactive) is skipped;
the sample of a specialization is the number of characters actually read.
"""

from __future__ import annotations

import sys
import urllib.parse
from collections import Counter, defaultdict

from . import blizzard_stats
from .blizzard import BlizzardError

# The API's slot names, folded to the addon's: a ring or trinket counts for
# whoever wears the item in either of the two places.
SLOTS = {
    "HEAD": "head", "NECK": "neck", "SHOULDER": "shoulder", "BACK": "back", "CHEST": "chest",
    "WRIST": "wrist", "HANDS": "hands", "WAIST": "waist", "LEGS": "legs", "FEET": "feet",
    "FINGER_1": "finger", "FINGER_2": "finger", "TRINKET_1": "trinket", "TRINKET_2": "trinket",
    "MAIN_HAND": "main_hand", "OFF_HAND": "off_hand",
}


def log(message):
    print(message, file=sys.stderr, flush=True)


def season_periods(client, season=None, count=2):
    """(season id, the last `count` period ids of it)."""
    if season is None:
        season = client.get("/data/wow/mythic-keystone/season/index", "dynamic")["current_season"]["id"]
    periods = client.get(f"/data/wow/mythic-keystone/season/{season}", "dynamic")["periods"]
    return season, [p["id"] for p in periods][-count:]


def connected_realms(client):
    index = client.get("/data/wow/connected-realm/index", "dynamic")
    return sorted(int(r["href"].split("connected-realm/")[1].split("?")[0]) for r in index["connected_realms"])


def season_dungeons(client, realm):
    """The dungeons of the current season, from one realm's leaderboard index."""
    index = client.get(f"/data/wow/connected-realm/{realm}/mythic-leaderboard/index", "dynamic")
    return [d["id"] for d in index["current_leaderboards"]]


def scan_leaderboards(client, realms, dungeons, periods, progress=log):
    """(realm slug, lower-case name) -> {name, realm, spec, level, completed}: each
    character's best group."""
    found = {}
    for number, realm in enumerate(realms, 1):
        for dungeon in dungeons:
            for period in periods:
                try:
                    board = client.get(f"/data/wow/connected-realm/{realm}/mythic-leaderboard/{dungeon}/period/{period}",
                                       "dynamic")
                except BlizzardError as error:
                    if error.status == 404:
                        continue
                    raise
                for group in board.get("leading_groups", []):
                    level, completed = group.get("keystone_level", 0), group.get("completed_timestamp", 0)
                    for member in group.get("members", []):
                        profile, spec = member.get("profile", {}), member.get("specialization", {})
                        slug = profile.get("realm", {}).get("slug")
                        if not (slug and profile.get("name") and isinstance(spec.get("id"), int)):
                            continue
                        key = (slug, profile["name"].lower())
                        held = found.get(key)
                        if held is None or (level, completed) > (held["level"], held["completed"]):
                            found[key] = {"name": profile["name"], "realm": slug, "spec": spec["id"],
                                          "level": level, "completed": completed}
        if number % 10 == 0:
            progress(f"leaderboards: {number}/{len(realms)} realm groups, {len(found)} characters")
    return found


def pick_best(characters, top_per_spec):
    """spec id -> its `top_per_spec` characters by key level, then recency."""
    by_spec = defaultdict(list)
    for character in characters.values():
        by_spec[character["spec"]].append(character)
    return {spec: sorted(rows, key=lambda c: (-c["level"], -c["completed"], c["realm"], c["name"].lower()))[:top_per_spec]
            for spec, rows in by_spec.items()}


def spec_names(client, spec_ids):
    """spec id -> (class slug, spec slug), e.g. 66 -> ("paladin", "protection")."""
    def slug(text):
        return text.strip().lower().replace(" ", "-")
    names = {}
    for spec_id in sorted(spec_ids):
        spec = client.get(f"/data/wow/playable-specialization/{spec_id}", "static")
        names[spec_id] = (slug(spec["playable_class"]["name"]), slug(spec["name"]))
    return names


def all_specs(client):
    """{"66": ["paladin", "protection"], ...} for every playable specialization."""
    index = client.get("/data/wow/playable-specialization/index", "static")
    ids = [s["id"] for s in index["character_specializations"] if not s["name"].startswith("Initial")]
    return {str(spec_id): list(key) for spec_id, key in spec_names(client, ids).items()}


def read_equipment(client, character):
    """slot -> set of item ids the character wears, or None when it cannot be read."""
    path = ("/profile/wow/character/" + urllib.parse.quote(character["realm"]) + "/"
            + urllib.parse.quote(character["name"].lower()) + "/equipment")
    try:
        data = client.get(path, "profile")
    except BlizzardError as error:
        if error.status == 404:
            return None
        raise
    worn = defaultdict(set)
    for entry in data.get("equipped_items", []):
        slot = SLOTS.get(entry.get("slot", {}).get("type"))
        item = entry.get("item", {}).get("id")
        if slot and isinstance(item, int):
            worn[slot].add(item)
    return worn


def entries_for(spec_key, players):
    """Entries of one specialization from the equipment of the players read."""
    class_slug, spec_slug = spec_key
    sample = len(players)
    if sample == 0:
        return []
    counts = defaultdict(Counter)
    for worn in players:
        for slot, items in worn.items():
            for item in items:
                counts[slot][item] += 1
    return [{"class": class_slug, "spec": spec_slug, "content": "mplus", "slot": slot, "item": item,
             "share": round(count / sample, 4), "sample": sample}
            for slot in sorted(counts) for item, count in sorted(counts[slot].items())]


def player_record(spec_key, rank, worn, stats=None):
    """One `players` record (klm/model.py) of a character read."""
    record = {"class": spec_key[0], "spec": spec_key[1], "rank": rank,
              "items": sorted({i for ids in worn.values() for i in ids}),
              "gear": {slot: sorted(ids) for slot, ids in sorted(worn.items())}}
    if stats:
        record["stats"] = stats
    return record


def fetch_entries(client, top_per_spec=50, periods=2, realm_limit=None, progress=log, specs_out=None,
                  stats_out=None, stats_cache=None, pool=None, players_out=None, only_specs=None):
    """The entries; `specs_out`, when given, receives {"66": ["paladin", "protection"], ...}.

    The entries and `stats_out` describe the best `top_per_spec` characters of each
    specialization (the mixed group). `pool` (default: `top_per_spec`) is how many of
    the leaderboard are read; `players_out`, when given, receives a record per character
    read, in ranking order, so the build can pick the pure Mythic+ players among them.
    `only_specs` is a collection of "class/spec" names that limits the run.

    `stats_out`, when given, receives the `stats` records of the same characters
    (see blizzard_stats); `stats_cache` is the cache dict they are read through."""
    season, period_ids = season_periods(client, count=periods)
    realms = connected_realms(client)
    if realm_limit:
        realms = realms[:realm_limit]
    dungeons = season_dungeons(client, realms[0])
    progress(f"season {season}, periods {period_ids}, {len(realms)} realm groups, {len(dungeons)} dungeons")
    characters = scan_leaderboards(client, realms, dungeons, period_ids, progress)
    pool = max(pool or top_per_spec, top_per_spec)
    chosen = pick_best(characters, pool)
    names = spec_names(client, chosen)
    if only_specs:
        wanted = {w.lower() for w in only_specs}
        names = {i: k for i, k in names.items() if "/".join(k) in wanted}
        chosen = {i: rows for i, rows in chosen.items() if i in names}
    if specs_out is not None:
        specs_out.update({str(spec_id): list(key) for spec_id, key in names.items()})
    entries = []
    for spec_id in sorted(chosen):
        players, player_stats = [], []
        for rank, character in enumerate(chosen[spec_id], 1):
            in_top = rank <= top_per_spec
            if not in_top and players_out is None:
                break
            worn = read_equipment(client, character)
            stats = None
            if stats_out is not None:
                stats = blizzard_stats.cached_statistics(client, character,
                                                         stats_cache if stats_cache is not None else {})
            if worn and in_top:
                players.append(worn)
            if stats and in_top:
                player_stats.append(stats)
            if worn and players_out is not None:
                players_out.append(player_record(names[spec_id], rank, worn, stats))
        if stats_out is not None:
            record = blizzard_stats.stats_for(names[spec_id], player_stats)
            if record:
                stats_out.append(record)
        progress(f"{names[spec_id][0]} {names[spec_id][1]}: {len(players)}/{min(len(chosen[spec_id]), top_per_spec)} characters read"
            + (f", pool {len(chosen[spec_id])}" if pool > top_per_spec else ""))
        entries.extend(entries_for(names[spec_id], players))
    return entries
