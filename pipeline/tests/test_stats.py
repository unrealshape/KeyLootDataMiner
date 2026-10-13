import sys
import unittest
import urllib.error
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from klm import lua  # noqa: E402
from klm.merge import merge  # noqa: E402
from klm.model import DatasetError, validate  # noqa: E402
from klm.sources import blizzard, blizzard_gear, blizzard_stats  # noqa: E402


def block(rating, value=None, bonus=0.0):
    out = {"rating_bonus": bonus, "rating_normalized": rating}
    if value is not None:
        out["value"] = value
    return out


def api_stats(crit=900, haste=800, mastery=1000, vers=100, leech=80, avoid=160, speed=0):
    return {
        "melee_crit": block(crit - 50, 20.0), "ranged_crit": block(crit, 25.0), "spell_crit": block(crit - 10, 24.0),
        "melee_haste": block(haste, 20.0), "ranged_haste": block(haste - 5, 19.0), "spell_haste": block(haste - 5, 19.0),
        "mastery": block(mastery, 40.0), "versatility": float(vers), "versatility_damage_done_bonus": 2.0,
        "lifesteal": block(leech, 1.5), "avoidance": block(avoid, bonus=4.5), "speed": block(speed, bonus=2.0),
    }


def stat_set(c=(1000, 30.0), h=(900, 20.0), m=(500, 20.0), v=(300, 6.0), leech=(280, 4.0), avoidance=(40, 1.0),
             speed=(0, 2.0)):
    return {"c": list(c), "h": list(h), "m": list(m), "v": list(v), "leech": list(leech),
            "avoidance": list(avoidance), "speed": list(speed)}


class ParseTest(unittest.TestCase):
    def test_takes_the_highest_variant_and_its_percent(self):
        parsed = blizzard_stats.parse_statistics(api_stats())
        self.assertEqual(parsed["c"], [900.0, 25.0])
        self.assertEqual(parsed["h"], [800.0, 20.0])
        self.assertEqual(parsed["m"], [1000.0, 40.0])
        self.assertEqual(parsed["v"], [100.0, 2.0])
        self.assertEqual(parsed["leech"], [80.0, 1.5])

    def test_avoidance_and_speed_use_the_rating_bonus(self):
        parsed = blizzard_stats.parse_statistics(api_stats())
        self.assertEqual(parsed["avoidance"], [160.0, 4.5])
        self.assertEqual(parsed["speed"], [0.0, 2.0])

    def test_an_incomplete_answer_is_not_used(self):
        data = api_stats()
        del data["lifesteal"]
        self.assertIsNone(blizzard_stats.parse_statistics(data))


class AggregationTest(unittest.TestCase):
    def test_means_rounding_and_n(self):
        a = stat_set(c=(1000, 30.04), leech=(281, 4.0))
        b = stat_set(c=(1001, 30.12), leech=(282, 4.0))
        record = blizzard_stats.stats_for(("paladin", "protection"), [a, b])
        self.assertEqual(record["n"], 2)
        self.assertEqual(record["c"], [1001, 30.1])     # 1000.5 rounds up, 30.08 to 30.1
        self.assertEqual(record["leech"], [282, 4.0])   # 281.5 rounds up
        self.assertEqual((record["class"], record["spec"]), ("paladin", "protection"))

    def test_no_players_no_record(self):
        self.assertIsNone(blizzard_stats.stats_for(("paladin", "protection"), []))


def client_with(stats_by_name, calls):
    def opener(request):
        url = request.full_url
        if url == blizzard.TOKEN_URL:
            return {"access_token": "t"}
        path = url.split(".blizzard.com", 1)[1].split("?", 1)[0]
        calls.append(path)
        name = path.rsplit("/", 2)[1]
        if name not in stats_by_name:
            raise urllib.error.HTTPError(url, 404, "gone", {}, None)
        return stats_by_name[name]
    return blizzard.Client("i", "s", opener=opener, sleep=lambda s: None)


class ReadTest(unittest.TestCase):
    def test_a_failing_player_is_skipped(self):
        calls = []
        client = client_with({"tank": api_stats()}, calls)
        self.assertIsNone(blizzard_stats.read_statistics(client, {"realm": "r", "name": "Gone"}))
        self.assertIsNotNone(blizzard_stats.read_statistics(client, {"realm": "r", "name": "Tank"}))

    def test_cache_spares_fresh_players_and_rereads_stale_ones(self):
        calls = []
        client = client_with({"tank": api_stats()}, calls)
        cache = {}
        who = {"realm": "r", "name": "Tank"}
        blizzard_stats.cached_statistics(client, who, cache, today=date(2026, 10, 1))
        blizzard_stats.cached_statistics(client, who, cache, today=date(2026, 10, 3))
        self.assertEqual(len(calls), 1)
        blizzard_stats.cached_statistics(client, who, cache, today=date(2026, 10, 20))
        self.assertEqual(len(calls), 2)
        self.assertEqual(cache["r/tank"]["day"], "2026-10-20")

    def test_unreadable_players_are_not_cached(self):
        client = client_with({}, [])
        cache = {}
        self.assertIsNone(blizzard_stats.cached_statistics(client, {"realm": "r", "name": "Gone"}, cache))
        self.assertEqual(cache, {})


class FetchTest(unittest.TestCase):
    def test_fetch_entries_collects_stats_and_skips_the_unreadable(self):
        def member(name):
            return {"profile": {"name": name, "realm": {"slug": "r"}}, "specialization": {"id": 66}}
        stats = {"tank": api_stats(), "other": api_stats(crit=1100)}

        def opener(request):
            url = request.full_url
            if url == blizzard.TOKEN_URL:
                return {"access_token": "t"}
            path = url.split(".blizzard.com", 1)[1].split("?", 1)[0]
            if path == "/data/wow/mythic-keystone/season/index":
                return {"current_season": {"id": 18}}
            if path == "/data/wow/mythic-keystone/season/18":
                return {"periods": [{"id": 7}]}
            if path == "/data/wow/connected-realm/index":
                return {"connected_realms": [{"href": "https://x/data/wow/connected-realm/1?namespace=d"}]}
            if path == "/data/wow/connected-realm/1/mythic-leaderboard/index":
                return {"current_leaderboards": [{"id": 249}]}
            if path.startswith("/data/wow/connected-realm/1/mythic-leaderboard/"):
                return {"leading_groups": [{"keystone_level": 20, "completed_timestamp": 1,
                                            "members": [member("Tank"), member("Other"), member("Gone")]}]}
            if path == "/data/wow/playable-specialization/66":
                return {"name": "Protection", "playable_class": {"name": "Paladin"}}
            name = path.rsplit("/", 2)[1]
            if name == "gone":
                raise urllib.error.HTTPError(url, 404, "gone", {}, None)
            if path.endswith("/equipment"):
                return {"equipped_items": [{"slot": {"type": "HEAD"}, "item": {"id": 100}}]}
            if path.endswith("/statistics"):
                return stats[name]
            raise AssertionError(path)

        client = blizzard.Client("i", "s", opener=opener, sleep=lambda s: None)
        out, cache = [], {}
        blizzard_gear.fetch_entries(client, progress=lambda m: None, stats_out=out, stats_cache=cache)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["n"], 2)
        self.assertEqual(out[0]["c"], [1000, 25.0])
        self.assertEqual(sorted(cache), ["r/other", "r/tank"])


def stats_dataset(source="blizzard-mplus", **records):
    return {"source": source, "generated": "2026-10-13T00:00:00Z", "entries": [], "drops": [],
            "stats": [dict({"class": "paladin", "spec": "protection", "n": 50}, **stat_set(), **records)]}


class OutputTest(unittest.TestCase):
    def test_lua_file_matches_the_contract(self):
        text = lua.stats_file(merge([stats_dataset()]))
        self.assertTrue(text.startswith(lua.HEADER + "KeyLootMasterStats = {\n"))
        self.assertIn('  ["paladin"] = {\n', text)
        self.assertIn('    ["protection"] = { n = 50, c = {1000, 30.0}, h = {900, 20.0}, m = {500, 20.0}, '
                      'v = {300, 6.0}, leech = {280, 4.0}, avoidance = {40, 1.0}, speed = {0, 2.0} },\n', text)
        self.assertEqual(text, lua.stats_file(merge([stats_dataset()])))

    def test_merge_weights_by_n(self):
        a = stats_dataset("a")
        b = stats_dataset("b")
        b["stats"][0].update(n=50, c=[1100, 31.0])
        merged = merge([a, b])
        self.assertEqual(merged["stats"][0]["n"], 100)
        self.assertEqual(merged["stats"][0]["c"], [1050, 30.5])

    def test_manifest_loads_stats_after_items(self):
        manifest = lua.manifest(["paladin.lua", "Stats.lua", "Items.lua", "Drops.lua", "Specs.lua", "Meta.lua"])
        order = [manifest.index(n) for n in ("Meta.lua", "Specs.lua", "Drops.lua", "Items.lua", "Stats.lua", "paladin.lua")]
        self.assertEqual(order, sorted(order))

    def test_build_writes_stats_only_with_stats(self):
        import build
        with_stats = build.render(merge([stats_dataset()]), 8)
        self.assertIn("Stats.lua", with_stats)
        self.assertIn("Stats.lua", with_stats["Data.xml"])
        old = {"source": "x", "generated": "2026-10-13T00:00:00Z", "entries": [], "drops": []}
        self.assertNotIn("Stats.lua", build.render(merge([old]), 8))

    def test_old_datasets_without_stats_still_validate_and_merge(self):
        old = {"source": "x", "generated": "2026-10-13T00:00:00Z"}
        self.assertEqual(merge([validate(old)])["stats"], [])

    def test_a_malformed_stats_record_is_rejected(self):
        bad = stats_dataset()
        bad["stats"][0]["c"] = [1000]
        with self.assertRaises(DatasetError):
            validate(bad)
        bad = stats_dataset()
        bad["stats"][0]["n"] = 0
        with self.assertRaises(DatasetError):
            validate(bad)


if __name__ == "__main__":
    unittest.main()
