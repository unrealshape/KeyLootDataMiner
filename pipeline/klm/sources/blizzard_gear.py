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

import re
import sys
import urllib.parse
from collections import Counter, defaultdict

from . import blizzard_stats, blizzard_talents
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
    return {spec: sorted(rows, key=lambda c: (-c["level"], -c["completed"], c.get("region") or "", c["realm"],
                                              c["name"].lower()))[:top_per_spec]
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


GEM_COLORS = (("garnet", "red"), ("peridot", "green"), ("amethyst", "purple"), ("lapis", "blue"), ("diamond", "meta"))
MARKUP = re.compile(r"\|A:[^|]*\|a")
EMBELLISHED = "embellish"


def gem_color(name):
    """The colour of a gem from its name (Garnet red, Peridot green, Amethyst purple, Lapis blue,
    Diamond meta); anything else is "other"."""
    lowered = str(name).lower()
    for word, color in GEM_COLORS:
        if word in lowered:
            return color
    return "other"


def clean_enchant(text):
    """An enchantment's display string without the `|A:...|a` icon markup and the "Enchanted: " prefix."""
    text = MARKUP.sub("", str(text)).strip()
    if text.startswith("Enchanted:"):
        text = text[len("Enchanted:"):]
    return text.strip()


def _embellishment(entry):
    """{id (the effect's spell), name, item} when the item is embellished, else None. The
    Equipment answer marks one with `limit_category` "Unique-Equipped: Embellished (2)"; its effect
    is the spell whose description starts with "Equip:" (else the first spell)."""
    if EMBELLISHED not in str(entry.get("limit_category", "")).lower():
        return None
    spells = [s for s in entry.get("spells", []) if isinstance(s.get("spell", {}).get("id"), int)]
    if not spells:
        return None
    chosen = next((s for s in spells if str(s.get("description", "")).startswith("Equip:")), spells[0])
    return {"id": chosen["spell"]["id"], "name": chosen["spell"].get("name", ""), "item": entry.get("item", {}).get("id")}


def parse_gear(data):
    """(worn, extras) from an /equipment answer. `worn` is slot -> set of item ids; `extras`:

        enchants       {slot: [{id, name}]}
        gems           [{id, name, color}]            one per filled socket
        embellishments [{id, name, item}]
        ilvl           average item level, or None
        name, realm    the character's name and realm as the answer spells them (optional)
    """
    worn = defaultdict(set)
    enchants: dict = {}
    gems, embellishments, levels = [], [], {}
    for entry in data.get("equipped_items", []):
        slot_type = entry.get("slot", {}).get("type")
        slot = SLOTS.get(slot_type)
        item = entry.get("item", {}).get("id")
        if not (slot and isinstance(item, int)):
            continue
        worn[slot].add(item)
        level = entry.get("level", {}).get("value")
        if isinstance(level, (int, float)):
            levels[slot_type] = level
        for enchant in entry.get("enchantments", []):
            if isinstance(enchant.get("enchantment_id"), int):
                enchants.setdefault(slot, []).append(
                    {"id": enchant["enchantment_id"], "name": clean_enchant(enchant.get("display_string", ""))})
        for socket in entry.get("sockets", []):
            gem = socket.get("item", {})
            if isinstance(gem.get("id"), int):
                name = gem.get("name", "")
                gems.append({"id": gem["id"], "name": name, "color": gem_color(name)})
        embellished = _embellishment(entry)
        if embellished:
            embellishments.append(embellished)
    ilvl = None
    if levels:
        total = sum(levels.values()) + (levels.get("MAIN_HAND", 0) if "OFF_HAND" not in levels else 0)
        ilvl = int(total / 16)
    extras = {"enchants": enchants, "gems": gems, "embellishments": embellishments, "ilvl": ilvl}
    character = data.get("character", {})
    if character.get("name"):
        extras["name"] = character["name"]
    if character.get("realm", {}).get("name"):
        extras["realm"] = character["realm"]["name"]
    return worn, extras


def read_gear(client, character):
    """(worn, extras) of a character (see parse_gear), or None when it cannot be read."""
    path = ("/profile/wow/character/" + urllib.parse.quote(character["realm"]) + "/"
            + urllib.parse.quote(character["name"].lower()) + "/equipment")
    try:
        data = client.get(path, "profile")
    except BlizzardError as error:
        if error.status in (403, 404):
            return None
        raise
    return parse_gear(data)


def read_equipment(client, character):
    """slot -> set of item ids the character wears, or None when it cannot be read."""
    read = read_gear(client, character)
    return None if read is None else read[0]


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


def player_record(spec_key, rank, worn, stats=None, character=None, extras=None, talents=None):
    """One `players` record (klm/model.py) of a character read."""
    record = {"class": spec_key[0], "spec": spec_key[1], "rank": rank,
              "items": sorted({i for ids in worn.values() for i in ids}),
              "gear": {slot: sorted(ids) for slot, ids in sorted(worn.items())}}
    if stats:
        record["stats"] = stats
    if extras is not None:
        character = character or {}
        record["name"] = extras.get("name") or character.get("name", "")
        record["realm"] = extras.get("realm") or character.get("realm", "")
        if character.get("region"):
            record["region"] = character["region"]
        if character.get("realm"):
            record["slug"] = character["realm"]
        if character.get("level") is not None:
            record["key"] = character["level"]
        if extras.get("ilvl"):
            record["ilvl"] = extras["ilvl"]
        if extras.get("race"):
            record["race"] = extras["race"]
        record["enchants"] = extras["enchants"]
        record["gems"] = extras["gems"]
        record["embellishments"] = extras["embellishments"]
    if talents:
        record["talents"] = talents
    return record


def scan_region(client, realm_limit, periods, progress):
    """(season, characters) of one region's leaderboards; characters are tagged with the region."""
    season, period_ids = season_periods(client, count=periods)
    realms = connected_realms(client)
    if realm_limit:
        realms = realms[:realm_limit]
    dungeons = season_dungeons(client, realms[0])
    progress(f"{client.region}: season {season}, periods {period_ids}, {len(realms)} realm groups, {len(dungeons)} dungeons")
    found = scan_leaderboards(client, realms, dungeons, period_ids, progress)
    for character in found.values():
        character["region"] = client.region
    return season, found


def fetch_entries(client, top_per_spec=50, periods=2, realm_limit=None, progress=log, specs_out=None,
                  stats_out=None, stats_cache=None, pool=None, players_out=None, only_specs=None,
                  clients=None, talents_cache=None, problems=None):
    """The entries; `specs_out`, when given, receives {"66": ["paladin", "protection"], ...}.

    The entries and `stats_out` describe the best `top_per_spec` characters of each
    specialization (the mixed group). `pool` (default: `top_per_spec`) is how many of
    the leaderboard are read; `players_out`, when given, receives a record per character
    read, in ranking order, so the build can pick the pure Mythic+ players among them.
    `only_specs` is a collection of "class/spec" names that limits the run.

    `clients` ({region: Client}) reads several regions: every region is scanned with its
    own client, the characters of a specialization are ranked together (key level, then
    recency) and the cache keys carry the region. A region that fails or delivers no
    characters is reported (to `progress` and to the list `problems`) and skipped; the run
    fails only when no region is left. Without `clients` the one `client` is used.

    `stats_out`, when given, receives the `stats` records of the same characters
    (see blizzard_stats); `stats_cache` is the cache dict they are read through.
    `talents_cache`, when given, turns on reading the talent builds (blizzard_talents)
    through that cache dict."""
    multi = clients is not None
    clients = dict(clients) if multi else {None: client}
    problems = problems if problems is not None else []
    characters, region_sizes = {}, {}
    for region, regional in clients.items():
        try:
            if multi:
                season, found = scan_region(regional, realm_limit, periods, progress)
            else:
                season, period_ids = season_periods(regional, count=periods)
                realms = connected_realms(regional)
                if realm_limit:
                    realms = realms[:realm_limit]
                dungeons = season_dungeons(regional, realms[0])
                progress(f"season {season}, periods {period_ids}, {len(realms)} realm groups, {len(dungeons)} dungeons")
                found = scan_leaderboards(regional, realms, dungeons, period_ids, progress)
        except (BlizzardError, KeyError, IndexError) as error:
            problems.append(f"{region}: {error}")
            progress(f"region {region}: skipped, {error}")
            continue
        if not found:
            problems.append(f"{region}: no characters on the leaderboards")
            progress(f"region {region}: skipped, the leaderboards are empty")
            continue
        region_sizes[region] = len(found)
        for (slug, name), character in found.items():
            characters[(region, slug, name)] = character
        if multi:
            progress(f"region {region}: {len(found)} characters")
    if not characters:
        raise BlizzardError("no region delivered leaderboard characters: " + "; ".join(problems))
    live = {r: c for r, c in clients.items() if r in region_sizes}
    pool = max(pool or top_per_spec, top_per_spec)
    chosen = pick_best(characters, pool)
    names = spec_names(next(iter(live.values())), chosen)
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
            regional = live[character.get("region")]
            read = read_gear(regional, character)
            worn, extras = read if read else (None, None)
            stats = None
            if stats_out is not None:
                stats = blizzard_stats.cached_statistics(regional, character,
                                                         stats_cache if stats_cache is not None else {})
            talents = None
            if talents_cache is not None and worn:
                talents = blizzard_talents.cached_talents(regional, character, talents_cache)
            if worn and in_top:
                players.append(worn)
            if stats and in_top:
                player_stats.append(stats)
            if worn and players_out is not None:
                players_out.append(player_record(names[spec_id], rank, worn, stats,
                                                 character if multi else None, extras if multi else None, talents))
        if stats_out is not None:
            record = blizzard_stats.stats_for(names[spec_id], player_stats)
            if record:
                stats_out.append(record)
        by_region = Counter(c.get("region") for c in chosen[spec_id])
        split = ", ".join(f"{r} {n}" for r, n in sorted(by_region.items())) if multi else ""
        progress(f"{names[spec_id][0]} {names[spec_id][1]}: {len(players)}/{min(len(chosen[spec_id]), top_per_spec)} characters read"
                 + (f", pool {len(chosen[spec_id])}" if pool > top_per_spec else "") + (f" ({split})" if split else ""))
        entries.extend(entries_for(names[spec_id], players))
    return entries
