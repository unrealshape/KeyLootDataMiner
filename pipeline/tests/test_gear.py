import json
import sys
import tempfile
import unittest
import urllib.error
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import build  # noqa: E402
import fetch_blizzard  # noqa: E402
from klm import gear, lua  # noqa: E402
from klm.merge import gear_groups, merge  # noqa: E402
from klm.model import DatasetError, validate  # noqa: E402
from klm.sources import blizzard, blizzard_gear, blizzard_stats, blizzard_talents  # noqa: E402


def piece(slot, item, enchants=(), sockets=(), limit=None, spells=(), level=330):
    entry = {"slot": {"type": slot}, "item": {"id": item}, "level": {"value": level}}
    if enchants:
        entry["enchantments"] = [{"enchantment_id": i, "display_string": t} for i, t in enchants]
    if sockets:
        entry["sockets"] = [{"socket_type": {"type": "PRISMATIC"}, "item": {"id": i, "name": n}} for i, n in sockets]
    if limit:
        entry["limit_category"] = limit
    if spells:
        entry["spells"] = [{"spell": {"id": i, "name": n}, "description": d} for i, n, d in spells]
    return entry


EQUIPMENT = {
    "character": {"name": "Tank", "realm": {"name": "Silvermoon", "slug": "silvermoon"}},
    "equipped_items": [
        piece("HEAD", 100, enchants=[(8017, "Enchanted: Empowered Rune of Avoidance |A:Professions-ChatIcon-Quality-12-Tier2:20:20|a")],
              spells=[(5, "Set bonus", "Set: x")]),
        piece("NECK", 101, sockets=[(240983, "Indecipherable Eversong Diamond"), (240898, "Flawless Deadly Amethyst")]),
        piece("FINGER_1", 102, sockets=[(240898, "Flawless Deadly Amethyst")]),
        piece("FINGER_2", 103, sockets=[(240900, "Quick Peridot"), (240901, "Masterful Garnet"), (240902, "Weird Opal")]),
        piece("WRIST", 104, limit="Unique-Equipped: Embellished (2)",
              spells=[(9, "Other", "On use: x"), (1283697, "Arcanoweave Lining", "Equip: Your spells")]),
        piece("TRINKET_1", 105, spells=[(7, "Trinket proc", "Equip: proc")]),
        piece("MAIN_HAND", 106, level=340),
    ],
}


class ParseGearTest(unittest.TestCase):
    def setUp(self):
        self.worn, self.extras = blizzard_gear.parse_gear(EQUIPMENT)

    def test_an_enchant_keeps_the_item_that_applies_it(self):
        data = {"equipped_items": [{"slot": {"type": "FINGER_1"}, "item": {"id": 102}, "enchantments": [
            {"enchantment_id": 7001, "display_string": "Enchanted: Cursed Devotion",
             "source_item": {"id": 223456, "name": "Enchant Ring - Cursed Devotion"}}]}]}
        _, extras = blizzard_gear.parse_gear(data)
        self.assertEqual(extras["enchants"]["finger"], [{"id": 7001, "name": "Cursed Devotion", "item": 223456}])
        summary = gear.summarize([{"enchants": extras["enchants"]}])
        self.assertEqual(summary["enchants"]["finger"][0]["item"], 223456)
        self.assertIn("item=223456", lua._cells(summary["enchants"]["finger"],
                                              [("id", "n"), ("name", "s"), ("item", "n"), ("n", "n")]))

    def test_items_are_unchanged(self):
        self.assertEqual(self.worn["finger"], {102, 103})
        self.assertEqual(self.worn["head"], {100})

    def test_enchant_text_loses_markup_and_prefix(self):
        self.assertEqual(self.extras["enchants"], {"head": [{"id": 8017, "name": "Empowered Rune of Avoidance"}]})
        self.assertEqual(blizzard_gear.clean_enchant("Thalassian Phoenix Oil |A:x:20:20|a"), "Thalassian Phoenix Oil")
        self.assertEqual(blizzard_gear.clean_enchant("Enchanted: +41 Agility"), "+41 Agility")

    def test_gem_colours_from_names(self):
        colors = {g["name"]: g["color"] for g in self.extras["gems"]}
        self.assertEqual(colors["Indecipherable Eversong Diamond"], "meta")
        self.assertEqual(colors["Flawless Deadly Amethyst"], "purple")
        self.assertEqual(colors["Quick Peridot"], "green")
        self.assertEqual(colors["Masterful Garnet"], "red")
        self.assertEqual(colors["Weird Opal"], "other")
        self.assertEqual(blizzard_gear.gem_color("Lapis Thing"), "blue")
        self.assertEqual(len(self.extras["gems"]), 6)

    def test_gem_signature_counts_colours(self):
        self.assertEqual(gear.gem_signature(self.extras["gems"]),
                         {"meta": 1, "purple": 2, "green": 1, "red": 1, "other": 1})

    def test_embellishment_is_the_equip_spell_of_a_limit_category_item(self):
        self.assertEqual(self.extras["embellishments"], [{"id": 1283697, "name": "Arcanoweave Lining", "item": 104}])

    def test_item_level_is_the_mean_of_sixteen_slots_two_hander_twice(self):
        # 6 pieces at 330 + a two-hander at 340 counted twice
        self.assertEqual(self.extras["ilvl"], (6 * 330 + 2 * 340) // 16)

    def test_name_and_realm_come_from_the_answer(self):
        self.assertEqual((self.extras["name"], self.extras["realm"]), ("Tank", "Silvermoon"))


def loadout(code, hero, active=True, shift=0):
    def pick(ident, name, spell):
        return {"id": ident, "rank": 1, "tooltip": {"talent": {"id": ident + 1000, "name": name},
                                                    "spell_tooltip": {"spell": {"id": spell, "name": name}}}}
    return {"is_active": active, "talent_loadout_code": code,
            "selected_class_talents": [pick(1, "Class A", 11), {"id": 99, "rank": 1}],
            "selected_spec_talents": [pick(2 + shift, "Spec B", 12)],
            "selected_hero_talents": [pick(3, "Hero C", 13)],
            "selected_hero_talent_tree": {"name": hero, "id": 7}}


SPECIALIZATIONS = {"specializations": [
    {"specialization": {"id": 66}, "loadouts": [loadout("OLD", "Templar", active=False), loadout("NEW", "Lightsmith")]},
    {"specialization": {"id": 70}, "loadouts": [loadout("RET", "Templar")]}]}


class TalentsTest(unittest.TestCase):
    def test_active_loadout_of_the_players_own_specialization(self):
        parsed = blizzard_talents.parse_specializations(SPECIALIZATIONS, 66)
        self.assertEqual(parsed["code"], "NEW")
        self.assertEqual(parsed["hero"], "Lightsmith")
        self.assertEqual([(t["tree"], t["id"], t["name"], t["spell"]) for t in parsed["selected"]],
                         [("class", 1001, "Class A", 11), ("spec", 1002, "Spec B", 12), ("hero", 1003, "Hero C", 13)])

    def test_unnamed_picks_are_left_out_and_unknown_specs_give_nothing(self):
        parsed = blizzard_talents.parse_specializations(SPECIALIZATIONS, 66)
        self.assertNotIn(99, [t["id"] for t in parsed["selected"]])
        self.assertIsNone(blizzard_talents.parse_specializations(SPECIALIZATIONS, 71))

    def test_cache_is_fresh_for_a_week_per_region_and_spec(self):
        calls = []

        def opener(request):
            if request.full_url == blizzard.TOKEN_URL:
                return {"access_token": "t"}
            calls.append(request.full_url)
            return SPECIALIZATIONS
        client = blizzard.Client("i", "s", opener=opener, sleep=lambda s: None)
        cache = {}
        who = {"realm": "r", "name": "Tank", "spec": 66, "region": "us"}
        first = blizzard_talents.cached_talents(client, who, cache, today=date(2026, 10, 1))
        blizzard_talents.cached_talents(client, who, cache, today=date(2026, 10, 5))
        self.assertEqual(len(calls), 1)
        self.assertEqual(sorted(cache), ["us/r/tank"])
        self.assertEqual(first["code"], "NEW")
        blizzard_talents.cached_talents(client, who, cache, today=date(2026, 10, 20))
        self.assertEqual(len(calls), 2)
        blizzard_talents.cached_talents(client, {**who, "spec": 70}, cache, today=date(2026, 10, 20))
        self.assertEqual(len(calls), 3)

    def test_an_unreadable_character_is_skipped_and_not_cached(self):
        def opener(request):
            if request.full_url == blizzard.TOKEN_URL:
                return {"access_token": "t"}
            raise urllib.error.HTTPError(request.full_url, 404, "gone", {}, None)
        client = blizzard.Client("i", "s", opener=opener, sleep=lambda s: None)
        cache = {}
        self.assertIsNone(blizzard_talents.cached_talents(client, {"realm": "r", "name": "Gone", "spec": 66}, cache))
        self.assertEqual(cache, {})

    def test_stats_cache_key_has_the_region_and_old_european_keys_still_serve(self):
        self.assertEqual(blizzard_stats.cache_key({"realm": "r", "name": "Tank", "region": "us"}), "us/r/tank")
        self.assertEqual(blizzard_stats.cache_key({"realm": "r", "name": "Tank"}), "r/tank")
        old = {"r/tank": {"day": "2026-10-01", "stats": {"c": [1, 1.0]}}}
        eu = {"realm": "r", "name": "Tank", "region": "eu"}
        self.assertIsNotNone(blizzard_stats.lookup_cached(old, eu))
        self.assertIsNone(blizzard_stats.lookup_cached(old, {**eu, "region": "us"}))


def member(name, spec=66, slug="r"):
    return {"profile": {"name": name, "realm": {"slug": slug}}, "specialization": {"id": spec}}


def region_opener(layout, calls, failing=()):
    """layout: region -> {character name: key level}. The same names in two regions are different characters."""
    def opener(request):
        url = request.full_url
        if url == blizzard.TOKEN_URL:
            return {"access_token": "t"}
        region = url.split("https://", 1)[1].split(".api", 1)[0]
        path = url.split(".blizzard.com", 1)[1].split("?", 1)[0]
        calls.append((region, path))
        if region in failing and "/mythic-keystone/season/index" in path:
            raise urllib.error.HTTPError(url, 500, "down", {}, None)
        if path == "/data/wow/mythic-keystone/season/index":
            return {"current_season": {"id": 1}}
        if path == "/data/wow/mythic-keystone/season/1":
            return {"periods": [{"id": 7}]}
        if path == "/data/wow/connected-realm/index":
            return {"connected_realms": [{"href": "https://x/data/wow/connected-realm/1?n=d"}]}
        if path.endswith("/mythic-leaderboard/index"):
            return {"current_leaderboards": [{"id": 249}]}
        if "/mythic-leaderboard/" in path:
            return {"leading_groups": [{"keystone_level": level, "completed_timestamp": 1, "members": [member(name)]}
                                       for name, level in layout.get(region, {}).items()]}
        if path == "/data/wow/playable-specialization/66":
            return {"name": "Protection", "playable_class": {"name": "Paladin"}}
        name = path.rsplit("/", 2)[1]
        if path.endswith("/equipment"):
            return {"character": {"name": name.capitalize(), "realm": {"name": "Realm"}},
                    "equipped_items": [piece("HEAD", 100 + len(name), enchants=[(8017, "Enchanted: Rune")],
                                             sockets=[(1, "Peridot")], level=330)]}
        if path.endswith("/specializations"):
            return {"specializations": [{"specialization": {"id": 66}, "loadouts": [loadout("CODE-" + region, "Lightsmith")]}]}
        raise AssertionError(path)
    return opener


def clients_for(regions, layout, calls, failing=()):
    opener = region_opener(layout, calls, failing)
    return {r: blizzard.Client("i", "s", region=r, opener=opener, sleep=lambda s: None) for r in regions}


class RegionsTest(unittest.TestCase):
    def fetch(self, regions, layout, failing=(), **kw):
        calls, players, problems, messages = [], [], [], []
        clients = clients_for(regions, layout, calls, failing)
        entries = blizzard_gear.fetch_entries(clients[regions[0]], top_per_spec=2, pool=4, players_out=players,
                                              clients=clients, problems=problems, progress=messages.append, **kw)
        return entries, players, problems, messages, calls

    def test_players_of_all_regions_are_ranked_together_with_region_in_the_record(self):
        layout = {"eu": {"Aa": 20, "Bb": 18}, "us": {"Cc": 19, "Dd": 17}}
        _, players, problems, messages, calls = self.fetch(["eu", "us"], layout)
        self.assertEqual([(p["region"], p["name"], p["rank"], p["key"]) for p in players],
                         [("eu", "Aa", 1, 20), ("us", "Cc", 2, 19), ("eu", "Bb", 3, 18), ("us", "Dd", 4, 17)])
        self.assertEqual(problems, [])
        self.assertTrue(any("pool 4 (eu 2, us 2)" in m for m in messages))
        self.assertEqual({r for r, _ in calls if "/equipment" in _}, {"eu", "us"})

    def test_same_name_in_two_regions_stays_two_players_with_their_own_cache_entries(self):
        layout = {"eu": {"Aa": 20}, "us": {"Aa": 19}}
        calls, stats_cache, talents_cache = [], {}, {}
        clients = clients_for(["eu", "us"], layout, calls)
        players = []
        blizzard_gear.fetch_entries(clients["eu"], top_per_spec=2, pool=4, players_out=players, clients=clients,
                                    talents_cache=talents_cache, progress=lambda m: None)
        self.assertEqual([(p["region"], p["talents"]["code"]) for p in players],
                         [("eu", "CODE-eu"), ("us", "CODE-us")])
        self.assertEqual(sorted(talents_cache), ["eu/r/aa", "us/r/aa"])

    def test_a_failing_or_empty_region_is_reported_and_skipped(self):
        layout = {"eu": {"Aa": 20}, "us": {"Cc": 19}, "kr": {}}
        _, players, problems, messages, _ = self.fetch(["eu", "us", "kr"], layout, failing=("us",))
        self.assertEqual([p["region"] for p in players], ["eu"])
        self.assertEqual(len(problems), 2)
        self.assertTrue(problems[0].startswith("us:") and problems[1].startswith("kr:"))
        self.assertTrue(any("region us: skipped" in m for m in messages))

    def test_no_region_left_is_an_error(self):
        with self.assertRaises(blizzard.BlizzardError):
            self.fetch(["eu"], {"eu": {}})

    def test_regions_option(self):
        self.assertEqual(fetch_blizzard.region_list("EU, us,kr,us", "eu"), ["eu", "us", "kr"])
        self.assertEqual(fetch_blizzard.region_list("", "kr"), ["kr"])
        self.assertEqual(fetch_blizzard.DEFAULT_REGIONS, "eu,us,kr,tw")


def player(rank, name, region="eu", code="A", hero="Lightsmith", gems=None, enchant=8017, emb=1283697,
           race=None, talents=("T1", "T2")):
    record = {"class": "paladin", "spec": "protection", "rank": rank, "items": [100 + rank], "gear": {"head": [100 + rank]},
              "name": name, "realm": 'Sil"ver\\moon', "region": region, "ilvl": 330 + rank, "key": 20,
              "enchants": {"head": [{"id": enchant, "name": "Rune"}], "finger": [{"id": 1, "name": "Eyes"}, {"id": 1, "name": "Eyes"}]},
              "gems": gems if gems is not None else [{"id": 5, "name": "Peridot", "color": "green"},
                                                       {"id": 6, "name": "Garnet", "color": "red"},
                                                       {"id": 5, "name": "Peridot", "color": "green"}],
              "embellishments": [{"id": emb, "name": "Arcanoweave Lining", "item": 104}],
              "talents": {"code": code, "hero": hero,
                          "selected": [{"id": 1, "name": talents[0], "spell": 11, "rank": 1, "tree": "class"},
                                       {"id": 2, "name": talents[1], "spell": 12, "rank": 1, "tree": "spec"}]}}
    if race:
        record["race"] = race
    return record


def dataset(players):
    return {"source": "s", "generated": "2026-10-13T00:00:00Z", "players": players, "drops": [], "entries": []}


class SummaryTest(unittest.TestCase):
    def test_counts_players_not_pieces_and_orders_by_count(self):
        group = [player(1, "A", code="X"), player(2, "B", code="X"), player(3, "C", code="Y", enchant=8018, hero="Templar")]
        summary = gear.summarize(group)
        self.assertEqual(summary["n"], 3)
        self.assertEqual(summary["enchants"]["head"], [{"id": 8017, "name": "Rune", "n": 2}, {"id": 8018, "name": "Rune", "n": 1}])
        self.assertEqual(summary["enchants"]["finger"], [{"id": 1, "name": "Eyes", "n": 3}])
        self.assertEqual([(g["id"], g["color"], g["n"]) for g in summary["gems"]], [(5, "green", 3), (6, "red", 3)])
        self.assertEqual(summary["gemSets"], [{"sig": {"red": 1, "green": 2}, "n": 3}])
        self.assertEqual(summary["builds"], [{"code": "X", "n": 2, "hero": "Lightsmith"}, {"code": "Y", "n": 1, "hero": "Templar"}])
        self.assertEqual(summary["heroes"], [{"name": "Lightsmith", "n": 2}, {"name": "Templar", "n": 1}])
        self.assertEqual(summary["embellishments"], [{"id": 1283697, "name": "Arcanoweave Lining", "n": 3}])
        self.assertEqual(summary["races"], [])
        self.assertEqual([(t["tree"], t["n"]) for t in summary["talents"]], [("class", 3), ("spec", 3)])

    def test_limits(self):
        group = [player(i, f"P{i}", enchant=9000 + i, emb=2000 + i,
                        gems=[{"id": 50 + i, "name": "Peridot", "color": "green"}], race=f"Race{i % 7}") for i in range(1, 16)]
        summary = gear.summarize(group)
        self.assertEqual(len(summary["enchants"]["head"]), 5)
        self.assertEqual(len(summary["gems"]), 10)
        self.assertEqual(len(summary["embellishments"]), 5)
        self.assertEqual(len(summary["races"]), 5)
        self.assertEqual(len(summary["players"]), 10)
        self.assertEqual([p["name"] for p in summary["players"]][:3], ["P1", "P2", "P3"])

    def test_ties_do_not_depend_on_player_order(self):
        group = [player(i, f"P{i}", enchant=9000 + i % 3, code="C%d" % (i % 4)) for i in range(1, 9)]
        self.assertEqual(gear.summarize(group), gear.summarize(list(reversed(group))))

    def test_old_players_without_details_give_empty_figures(self):
        summary = gear.summarize([{"class": "paladin", "spec": "protection", "rank": 1, "items": [1]}])
        self.assertEqual((summary["enchants"], summary["gems"], summary["builds"], summary["players"]), ({}, [], [], []))


class OutputTest(unittest.TestCase):
    def merged(self, count=4):
        players = [player(i, f"P{i}", race="Dwarf" if i % 2 else None) for i in range(1, count + 1)]
        return merge([dataset(players)])

    def test_groups_exist_only_with_gear_details(self):
        old = merge([dataset([{"class": "paladin", "spec": "protection", "rank": 1, "items": [1], "gear": {"head": [1]}}])])
        self.assertEqual(gear_groups(old, 50, 1), {})
        self.assertEqual(lua.gear_file(old), "")
        groups = gear_groups(self.merged(), 3, 1)
        (found,) = groups.values()
        self.assertEqual([len(found["mplus"]), len(found["mplus_all"])], [3, 3])

    def test_file_follows_the_contract(self):
        text = lua.gear_file(self.merged())
        self.assertTrue(text.startswith(lua.HEADER + "KeyLootMasterGear = {\n"))
        self.assertIn('  ["paladin"] = {\n    ["protection"] = {\n      mplus = {\n        n = 4,\n', text)
        self.assertIn("      mplus_all = {\n", text)
        self.assertIn('enchants = { finger = { {id=1, name="Eyes", n=4} }, head = { {id=8017, name="Rune", n=4} } },', text)
        self.assertIn('gems = { {id=5, name="Peridot", color="green", n=4}, {id=6, name="Garnet", color="red", n=4} },', text)
        self.assertIn("gemSets = { { sig = {red=1, green=2}, n = 4 } },", text)
        self.assertIn('embellishments = { {id=1283697, name="Arcanoweave Lining", n=4} },', text)
        self.assertIn("races = {  },", text)   # two known races are too few for a distribution
        self.assertIn('builds = { {code="A", n=4, hero="Lightsmith"} },', text)
        self.assertIn('{id=1, name="T1", n=4, tree="class"},', text)
        self.assertIn('heroes = { {name="Lightsmith", n=4} },', text)
        self.assertIn('{name="P1", realm="Sil\\"ver\\\\moon", region="eu", race="Dwarf", ilvl=331, key=20}', text)

    def test_output_is_deterministic(self):
        self.assertEqual(lua.gear_file(self.merged()), lua.gear_file(merge([dataset(list(reversed(self.merged()["players"])))])))

    def test_manifest_loads_gear_after_stats(self):
        manifest = lua.manifest(["paladin.lua", "Gear.lua", "Stats.lua", "Items.lua", "Meta.lua", "Bonus.lua"])
        order = [manifest.index(n) for n in ("Items.lua", "Stats.lua", "Gear.lua", "Bonus.lua", "paladin.lua")]
        self.assertEqual(order, sorted(order))

    def test_build_writes_gear_only_with_player_details(self):
        with_gear = build.render(self.merged(), 8)
        self.assertIn("Gear.lua", with_gear)
        self.assertIn("Gear.lua", with_gear["Data.xml"])
        plain = build.render(merge([dataset([{"class": "paladin", "spec": "protection", "rank": 1, "items": [1], "gear": {"head": [1]}}])]), 8)
        self.assertNotIn("Gear.lua", plain)

    def test_build_cli_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder, out = Path(tmp) / "ds", Path(tmp) / "out"
            folder.mkdir()
            (folder / "s.json").write_text(json.dumps(dataset([player(1, "A"), player(2, "B")])), encoding="utf-8")
            self.assertEqual(build.main(["--datasets", str(folder), "--out", str(out)]), 0)
            self.assertIn("KeyLootMasterGear", (out / "Gear.lua").read_text(encoding="utf-8"))


class ModelTest(unittest.TestCase):
    def test_details_are_validated(self):
        validate(dataset([player(1, "A")]))
        for change in ({"enchants": {"head": [{"name": "x"}]}}, {"gems": [{"id": 1, "color": "pink"}]},
                       {"talents": {"code": "x", "selected": [{"id": 1, "tree": "oak"}]}}, {"name": ""}):
            with self.assertRaises(DatasetError):
                validate(dataset([{**player(1, "A"), **change}]))


if __name__ == "__main__":
    unittest.main()
