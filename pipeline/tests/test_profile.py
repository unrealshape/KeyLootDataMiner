import json
import sys
import tempfile
import unittest
import urllib.error
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fetch_blizzard  # noqa: E402
from klm import gear, lua  # noqa: E402
from klm.merge import merge  # noqa: E402
from klm.model import DatasetError, validate  # noqa: E402
from klm.sources import blizzard, blizzard_gear, blizzard_profile  # noqa: E402

RAID, DUNGEON = 900, 100
DROPS = [{"item": RAID, "kind": "raid", "instance": 1, "instance_name": "X", "encounter": 2, "encounter_name": "Y"},
         {"item": DUNGEON, "kind": "dungeon", "instance": 1, "instance_name": "X", "encounter": 2, "encounter_name": "Y"}]
TODAY = date(2026, 10, 13)


def opener_for(ratings, calls, failing=()):
    """A stub opener: ratings maps lower-case names to (race, rating); `failing` names answer HTTP 404."""
    def opener(request):
        url = request.full_url.split("?")[0]
        if "oauth" in url:
            return {"access_token": "t"}
        calls.append(url)
        name = url.split("/character/")[1].split("/")[1]
        if name in failing:
            raise urllib.error.HTTPError(url, 404, "nf", {}, None)
        race, rating = ratings[name]
        if url.endswith("/mythic-keystone-profile"):
            return {"current_mythic_rating": {"rating": rating}} if rating is not None else {}
        return {"race": {"name": race, "id": 1}}
    return opener


def client_for(ratings, calls, failing=()):
    return blizzard.Client("i", "s", region="eu", opener=opener_for(ratings, calls, failing), sleep=lambda s: None)


def record(rank, name, items=(DUNGEON,), **extra):
    return {"class": "paladin", "spec": "protection", "rank": rank, "items": list(items), "gear": {"head": list(items)},
            "name": name, "realm": "Sil ver", "slug": "sil-ver", "region": "eu", "key": 20 - rank, **extra}


class ProfileReadTest(unittest.TestCase):
    def test_parse_rounds_the_current_rating_and_needs_both_fields(self):
        keystone = {"current_mythic_rating": {"rating": 4041.5}}
        self.assertEqual(blizzard_profile.parse_profile({"race": {"name": "Night Elf"}}, keystone),
                         {"race": "Night Elf", "rating": 4042})
        self.assertIsNone(blizzard_profile.parse_profile({"race": {"name": "Night Elf"}}, {}))
        self.assertIsNone(blizzard_profile.parse_profile({}, keystone))

    def test_two_calls_then_cache_for_three_days(self):
        calls, cache = [], {}
        client = client_for({"aa": ("Dwarf", 3755.54)}, calls)
        character = {"region": "eu", "realm": "sil-ver", "name": "Aa"}
        found = blizzard_profile.cached_profile(client, character, cache, TODAY)
        self.assertEqual(found, {"race": "Dwarf", "rating": 3756})
        self.assertEqual(calls, ["https://eu.api.blizzard.com/profile/wow/character/sil-ver/aa",
                                 "https://eu.api.blizzard.com/profile/wow/character/sil-ver/aa/mythic-keystone-profile"])
        self.assertEqual(list(cache), ["eu/sil-ver/aa"])
        blizzard_profile.cached_profile(client, character, cache, date(2026, 10, 16))
        self.assertEqual(len(calls), 2)                                    # 3 days old: still fresh
        blizzard_profile.cached_profile(client, character, cache, date(2026, 10, 17))
        self.assertEqual(len(calls), 4)                                    # 4 days: read again

    def test_unreadable_character_is_skipped_without_cache_entry(self):
        calls, cache = [], {}
        client = client_for({"aa": ("Dwarf", 1.0), "bb": ("Dwarf", None)}, calls, failing={"aa"})
        for name in ("Aa", "Bb"):
            self.assertIsNone(blizzard_profile.cached_profile(
                client, {"region": "eu", "realm": "sil-ver", "name": name}, cache, TODAY))
        self.assertEqual(cache, {})


class SelectionTest(unittest.TestCase):
    def test_only_the_first_players_of_each_group_are_read_once(self):
        raiders = [record(i, f"R{i}", items=(RAID,)) for i in range(1, 4)]
        pure = [record(i, f"P{i}") for i in range(4, 40)]
        chosen = blizzard_profile.select_players(raiders + pure, DROPS, 30, 0, limit=10)
        names = [p["name"] for p in chosen]
        self.assertEqual(len(names), len(set(names)))
        self.assertLessEqual(len(names), 20)
        self.assertTrue({"R1", "R2", "R3"} <= set(names))   # the mixed top group
        self.assertIn("P4", names)                          # first of the pure group
        self.assertNotIn("P39", names)

    def test_players_without_slug_are_left_out(self):
        loose = record(1, "A")
        del loose["slug"]
        self.assertEqual(blizzard_profile.select_players([loose], DROPS, 50, 1), [])

    def test_enrich_sets_rating_and_race_and_skips_failures(self):
        calls, cache = [], {}
        ratings = {"a": ("Dwarf", 4041.6), "b": ("Orc", 3000.0), "c": ("Orc", 1.0)}
        client = client_for(ratings, calls, failing={"c"})
        players = [record(1, "A"), record(2, "B"), record(3, "C")]
        done = blizzard_profile.enrich_players({"eu": client}, players, DROPS, 50, 1, cache, today=TODAY)
        self.assertEqual(done, 2)
        self.assertEqual([(p.get("rating"), p.get("race")) for p in players],
                         [(4042, "Dwarf"), (3000, "Orc"), (None, None)])
        self.assertEqual(len(calls), 5)             # 2 calls for A and B, 1 failing call for C; mixed and pure group are one set


def dataset(players):
    return {"source": "s", "generated": "2026-10-13T00:00:00Z", "drops": DROPS, "entries": [], "players": players}


def detail(rank, name, **extra):
    return {**record(rank, name), "enchants": {}, "gems": [], "embellishments": [], **extra}


class OutputTest(unittest.TestCase):
    def test_players_are_sorted_by_rating_then_key_then_name(self):
        players = [detail(1, "Zed", rating=3000, key=20), detail(2, "Bob", rating=4042), detail(3, "Ann", rating=3000, key=20),
                   detail(4, "Cy", rating=3000, key=30), detail(5, "Unrated")]
        listed = gear.summarize(players)["players"]
        self.assertEqual([p["name"] for p in listed], ["Bob", "Cy", "Ann", "Zed", "Unrated"])
        self.assertEqual(listed[0]["rating"], 4042)
        self.assertEqual(listed[0]["key"], 18)       # key stays as an extra field

    def test_without_ratings_the_rank_order_stays(self):
        listed = gear.summarize([detail(2, "B"), detail(1, "A")])["players"]
        self.assertEqual([p["name"] for p in listed], ["A", "B"])
        self.assertNotIn("rating", listed[0])

    def test_races_need_ten_known_races(self):
        few = [detail(i, f"P{i}", race="Dwarf") for i in range(1, 10)]
        self.assertEqual(gear.summarize(few)["races"], [])
        enough = few + [detail(10, "P10", race="Orc")]
        self.assertEqual(gear.summarize(enough)["races"], [{"name": "Dwarf", "n": 9}, {"name": "Orc", "n": 1}])

    def test_gear_lua_carries_rating_and_race(self):
        players = [detail(i, f"P{i}", race="Dwarf", rating=4000 + i) for i in range(1, 11)]
        text = lua.gear_file(merge([dataset(players)]))
        self.assertIn('races = { {name="Dwarf", n=10} },', text)
        self.assertIn('{name="P10", realm="Sil ver", region="eu", race="Dwarf", rating=4010, key=10}', text)
        self.assertLess(text.index('name="P10"'), text.index('name="P9"'))

    def test_model_validates_the_optional_rating(self):
        validate(dataset([detail(1, "A", rating=4042, race="Dwarf")]))
        validate(dataset([detail(1, "A")]))
        for bad in (4042.5, "4042", -1, True):
            with self.assertRaises(DatasetError):
                validate(dataset([detail(1, "A", rating=bad)]))

    def test_player_record_keeps_the_realm_slug(self):
        made = blizzard_gear.player_record(
            ("paladin", "protection"), 1, {"head": {DUNGEON}}, None,
            {"name": "A", "realm": "sil-ver", "region": "eu", "level": 20},
            {"enchants": {}, "gems": [], "embellishments": [], "name": "A", "realm": "Sil ver"})
        self.assertEqual((made["realm"], made["slug"]), ("Sil ver", "sil-ver"))

    def test_fetch_uses_drops_of_an_earlier_journal_file(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            self.assertEqual(fetch_blizzard.journal_drops(out, []), [])
            (out / "blizzard-journal.json").write_text(json.dumps({"drops": DROPS}), encoding="utf-8")
            self.assertEqual(fetch_blizzard.journal_drops(out, []), DROPS)
            self.assertEqual(fetch_blizzard.journal_drops(out, [1]), [1])


if __name__ == "__main__":
    unittest.main()
