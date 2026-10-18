import sys
import unittest
import urllib.error
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from klm import lua  # noqa: E402
from klm.merge import merge  # noqa: E402
from klm.model import DatasetError, validate  # noqa: E402
from klm.sources import blizzard, blizzard_items as bi  # noqa: E402


def api(items, tiers, recipes):
    calls = []

    def opener(request):
        url = request.full_url
        if url == blizzard.TOKEN_URL:
            return {"access_token": "t"}
        path = url.split(".blizzard.com", 1)[1].split("?", 1)[0]
        calls.append(path)
        if path.startswith("/data/wow/item/"):
            item_id = int(path.rsplit("/", 1)[1])
            if item_id not in items:
                raise urllib.error.HTTPError(url, 404, "none", {}, None)
            return items[item_id]
        if path.startswith("/data/wow/profession/") and "skill-tier" not in path:
            return {"skill_tiers": tiers}
        if "skill-tier" in path:
            return {"categories": [{"recipes": [{"name": n} for n in recipes]}]}
        raise AssertionError(path)

    return blizzard.Client("i", "s", opener=opener, sleep=lambda s: None), calls


def item(name, level=219, set_name=None, stats=()):
    preview = {"stats": [{"type": {"type": s}} for s in stats]}
    if set_name:
        preview["set"] = {"item_set": {"name": set_name}}
    return {"name": name, "level": level, "preview_item": preview}


ITEMS = {
    1: item("Warhelm of the Consecrated Flame", set_name="Radiance of the Consecrated Flame",
            stats=("CRIT_RATING", "HASTE_RATING", "STAMINA")),
    2: item("Cloak of the Consecrated Flame", stats=("MASTERY_RATING",)),
    3: item("Blood-Tempered Gauntlets", stats=("VERSATILITY",)),
    4: item("Some Vendor Ring", level=197),
}


class FactsTest(unittest.TestCase):
    def test_stat_letters_skip_negated_and_primary(self):
        preview = {"stats": [{"type": {"type": "CRIT_RATING"}}, {"type": {"type": "HASTE_RATING"}, "is_negated": True},
                             {"type": {"type": "VERSATILITY"}}, {"type": {"type": "STAMINA"}}]}
        self.assertEqual(bi.stat_letters(preview), "cv")

    def test_read_item(self):
        client, _ = api(ITEMS, [], [])
        facts = bi.read_item(client, 1, date(2026, 10, 13))
        self.assertEqual(facts["set"], "Radiance of the Consecrated Flame")
        self.assertEqual(facts["stats"], "ch")
        self.assertEqual(facts["ilvl"], 219)
        self.assertEqual(facts["day"], "2026-10-13")


class RefreshTest(unittest.TestCase):
    def test_reads_only_new_or_stale_items_and_records_unknown_ones(self):
        client, calls = api(ITEMS, [], [])
        cache = {"1": {"name": "x", "ilvl": 1, "set": None, "stats": "", "slot": "", "day": "2026-10-10"},
                 "2": {"name": "old", "ilvl": 1, "set": None, "stats": "", "slot": "", "day": "2026-08-01"}}
        read = bi.refresh(client, {1, 2, 3, 99}, cache, today=date(2026, 10, 13), progress=lambda m: None)
        self.assertEqual(read, 3)  # 2 is stale, 3 and 99 are new
        self.assertNotIn("/data/wow/item/1", calls)
        self.assertEqual(cache["2"]["name"], "Cloak of the Consecrated Flame")
        self.assertEqual(cache["99"]["name"], "")  # unknown to the API, not asked again
        self.assertEqual(bi.refresh(client, {99}, cache, today=date(2026, 10, 14), progress=lambda m: None), 0)


class ClassifyTest(unittest.TestCase):
    def setUp(self):
        client, _ = api(ITEMS, [], [])
        self.cache = {}
        bi.refresh(client, set(ITEMS), self.cache, today=date(2026, 10, 13), progress=lambda m: None)
        self.recipes = {"blood-tempered gauntlets"}

    def test_themes(self):
        self.assertEqual(bi.themes(self.cache), {"consecrated flame"})
        both = {"1": {"set": "Baleful Grave-Knight's Battlegear"}, "2": {"set": "Regalia of the Ophidian Oracle"},
                "3": {"set": "Plain Set"}, "4": {"set": None}}
        self.assertEqual(bi.themes(both), {"baleful grave-knight", "ophidian oracle", "plain set"})
        pieces = {"1": {"set": "Ophidian Oracle's Prophecy"}}
        self.assertEqual(bi.source_of({"name": "Ritual Drape of the Ophidian Oracle"}, set(), bi.themes(pieces)), "catalyst")
        self.assertEqual(bi.source_of({"name": "Baleful Grave-Knight's Girdle"}, set(), {"baleful grave-knight"}), "catalyst")

    def test_sources(self):
        drops = bi.other_drops({1, 2, 3, 4, 5}, journal_items={5}, cache=self.cache, recipes=self.recipes)
        kinds = {d["item"]: d["kind"] for d in drops}
        self.assertEqual(kinds, {1: "catalyst", 2: "catalyst", 3: "crafted", 4: "other"})
        self.assertTrue(all(d["instance"] == 0 for d in drops))

    def test_item_records(self):
        records = {r["item"]: r for r in bi.item_records({1, 2, 3, 4}, self.cache, bi.themes(self.cache))}
        self.assertTrue(records[1]["tier"] and records[2]["tier"])
        self.assertFalse(records[3]["tier"])
        self.assertEqual(records[3]["stats"], "v")
        self.assertIsInstance(records[1]["ilvl"], int)


class RecipesTest(unittest.TestCase):
    def test_only_the_current_expansion_tiers_are_read(self):
        tiers = [{"id": 1, "name": "Khaz Algar Blacksmithing"}, {"id": 2, "name": "Midnight Blacksmithing"}]
        client, calls = api({}, tiers, ["Blood-Tempered Gauntlets", " Primalforged Axe "])
        names = bi.recipe_names(client, progress=lambda m: None)
        self.assertEqual(names, {"blood-tempered gauntlets", "primalforged axe"})
        self.assertFalse(any(p.endswith("/skill-tier/1") for p in calls))


class DatasetTest(unittest.TestCase):
    def test_items_and_specs_validate_and_merge(self):
        base = {"source": "a", "generated": "2026-10-13T00:00:00Z", "entries": [], "drops": [],
                "items": [{"item": 7, "stats": "ch", "ilvl": 219, "tier": True}], "specs": {"66": ["paladin", "protection"]}}
        other = {"source": "b", "generated": "2026-10-13T00:00:00Z", "specs": {"65": ["paladin", "holy"]},
                 "items": [{"item": 7, "stats": "m", "ilvl": 1, "tier": False}]}
        merged = merge([base, other])
        self.assertEqual(merged["items"], [base["items"][0]])  # the first source's facts stay
        self.assertEqual(list(merged["specs"]), ["65", "66"])
        for bad in ({"items": [{"item": 7, "stats": "x", "ilvl": 1, "tier": False}]},
                    {"items": [{"item": 7, "stats": "c", "ilvl": 1, "tier": 1}]},
                    {"specs": {"abc": ["a", "b"]}}):
            with self.assertRaises(DatasetError):
                validate({"source": "a", "generated": "x", **bad})

    def test_lua_files(self):
        data = {"source": "a", "generated": "2026-10-13T00:00:00Z",
                "entries": [{"class": "paladin", "spec": "protection", "content": "mplus", "slot": "head",
                             "item": 7, "share": 0.9, "sample": 50}],
                "drops": [], "items": [{"item": 7, "stats": "ch", "ilvl": 219, "tier": True},
                                       {"item": 8, "stats": "m", "ilvl": 1, "tier": False}],
                "specs": {"66": ["paladin", "protection"]}}
        merged = merge([data])
        items = lua.items_file(merged, 8)
        self.assertIn('[7] = { s = "ch", l = 219, t = true },', items)
        self.assertNotIn("[8]", items)  # not shown in any class file
        self.assertIn('[66] = { "paladin", "protection" },', lua.specs_file(merged))
        manifest = lua.manifest(["paladin.lua", "Items.lua", "Drops.lua", "Specs.lua", "Meta.lua"])
        order = [manifest.index(n) for n in ("Meta.lua", "Specs.lua", "Drops.lua", "Items.lua", "paladin.lua")]
        self.assertEqual(order, sorted(order))


if __name__ == "__main__":
    unittest.main()
