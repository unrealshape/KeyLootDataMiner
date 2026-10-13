"""Race and Mythic+ rating of the players the addon lists, from the Profile API.

For a character this reads two endpoints (namespace "profile"):

    /profile/wow/character/{realm}/{name}                          race.name              "Night Elf"
    /profile/wow/character/{realm}/{name}/mythic-keystone-profile  current_mythic_rating.rating   3950.65

(`current_mythic_rating` is the rating of the running season; the per-season
endpoint of an old season is not needed.) The result is `{"race": text, "rating": int}`, the
rating rounded half up. The answer is cached for 3 days in a file (key region/realm/name, see
blizzard_stats.cache_key); a character that cannot be read (any API error, 403, 404, a missing
field) is skipped: no result, no cache entry, no abort.

Which characters are read: group formation happens later, in the build (merge.mplus_groups), so
`select_players` repeats it here from the dataset the fetch just made (same drops, same group
size) and takes the first `limit` players of each specialization's "mplus" group and of its mixed
top group (they are mostly the same). With the default limit of 10 that is at most 20 characters,
40 calls, per specialization; fewer when the cache is fresh. The rating ranks only the players
that were read, so the list the addon shows is the best 10 by rating among the first `limit`
players by key level of each group.
"""

from __future__ import annotations

import urllib.parse
from datetime import date

from ..merge import mplus_groups
from .blizzard import BlizzardError
from .blizzard_stats import cache_key, round_half_up

MAX_AGE_DAYS = 3
DEFAULT_LIMIT = 50


def parse_profile(profile, keystone):
    """{"race", "rating"} from the two answers, or None when either field is missing."""
    race = profile.get("race", {}).get("name") if isinstance(profile, dict) else None
    current = keystone.get("current_mythic_rating") if isinstance(keystone, dict) else None
    rating = current.get("rating") if isinstance(current, dict) else None
    if not (isinstance(race, str) and race) or isinstance(rating, bool) or not isinstance(rating, (int, float)):
        return None
    return {"race": race, "rating": round_half_up(rating)}


def read_profile(client, character):
    """The character's race and rating, or None when they cannot be read (any API error)."""
    path = ("/profile/wow/character/" + urllib.parse.quote(character["realm"]) + "/"
            + urllib.parse.quote(character["name"].lower()))
    try:
        profile = client.get(path, "profile")
        keystone = client.get(path + "/mythic-keystone-profile", "profile")
    except BlizzardError:
        return None
    return parse_profile(profile, keystone)


def cached_profile(client, character, cache, today=None):
    """The profile from the cache while fresh, else read (and cached); None when unreadable."""
    today = today or date.today()
    held = cache.get(cache_key(character))
    if held and (today - date.fromisoformat(held["day"])).days <= MAX_AGE_DAYS:
        return {"race": held["race"], "rating": held["rating"]}
    found = read_profile(client, character)
    if found is None:
        return None
    cache[cache_key(character)] = {"day": today.isoformat(), **found}
    return found


def select_players(players, drops, group_size, max_raid_items, limit=DEFAULT_LIMIT):
    """The player records to read: per specialization the first `limit` of the Mythic+ group and
    of the mixed top group, once each, in ranking order. Only records with a name and a realm slug
    (`slug`, written by blizzard_gear.player_record; the `realm` text is the display name)."""
    chosen, seen = [], set()
    for found in mplus_groups({"drops": drops, "players": players}, group_size, max_raid_items).values():
        for group in (found["group"], found["pool"][:group_size]):
            for player in group[:limit]:
                if id(player) in seen or not (player.get("name") and player.get("slug")):
                    continue
                seen.add(id(player))
                chosen.append(player)
    return chosen


def enrich_players(clients, players, drops, group_size, max_raid_items, cache, limit=DEFAULT_LIMIT,
                   today=None, progress=None):
    """Adds `rating` and `race` to the selected player records (in place); returns how many were read."""
    chosen = select_players(players, drops, group_size, max_raid_items, limit)
    done = 0
    for player in chosen:
        client = clients.get(player.get("region")) or next(iter(clients.values()))
        found = cached_profile(client, {"region": player.get("region"), "realm": player["slug"],
                                        "name": player["name"]}, cache, today)
        if found is None:
            continue
        player["rating"], player["race"] = found["rating"], found["race"]
        done += 1
    if progress:
        progress(f"profiles: {done}/{len(chosen)} players")
    return done
