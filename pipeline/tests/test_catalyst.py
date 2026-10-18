import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from klm import lua  # noqa: E402
from klm.merge import merge  # noqa: E402
from klm.model import DatasetError, validate  # noqa: E402
from klm.sources import blizzard, blizzard_catalyst as bc, blizzard_items as bi  # noqa: E402
from test_items import api  # noqa: E402

TODAY = date(2026, 10, 18)


def piece(name, inventory, subclass, set_name=None, effects=(), level=240, klass=4):
    """An item answer of the item API: a piece of armor (class 4) or something else."""
    preview = {"stats": []}
    if set_name:
        preview["set"] = {"item_set": {"name": set_name},
                          "effects": [{"display_string": text, "required_count": count} for count, text in effects]}
    return {"name": name, "level": level, "inventory_type": {"type": inventory},
            "item_class": {"id": klass}, "item_subclass": {"name": subclass}, "preview_item": preview}


def dungeon(item, instance, name, encounter, boss):
    return {"item": item, "kind": "dungeon", "instance": instance, "instance_name": name,
            "encounter": encounter, "encounter_name": boss}


FLAME = "Radiance of the Consecrated Flame"
EFFECTS = ((2, "(2) Set: Consecration is 30% larger."), (4, "(4) Set: Enemies take 20% more damage."))


class FactsTest(unittest.TestCase):
    def test_an_item_read_keeps_its_tier_slot_armor_type_and_set_bonuses(self):
        client, _ = api({1: piece("Warhelm of the Consecrated Flame", "HEAD", "Plate", FLAME, EFFECTS),
                         2: piece("Robe of Flame", "ROBE", "Cloth"),
                         3: piece("Ring of Haste", "FINGER", "Miscellaneous"),
                         4: piece("Sword", "WEAPON", "One-Handed Swords", klass=2)}, [], [])
        helm = bi.read_item(client, 1, TODAY)
        self.assertEqual((helm["slot"], helm["armor"]), ("head", "plate"))
        self.assertEqual(helm["effects"], {"2": "Consecration is 30% larger.", "4": "Enemies take 20% more damage."})
        self.assertEqual(bi.read_item(client, 2, TODAY)["slot"], "chest")
        ring = bi.read_item(client, 3, TODAY)
        self.assertEqual((ring["slot"], ring["armor"], ring["effects"]), ("", "", {}))
        self.assertEqual(bi.read_item(client, 4, TODAY)["armor"], "")

    def test_an_item_read_before_the_new_facts_existed_is_read_again(self):
        client, calls = api({1: piece("Helm", "HEAD", "Plate")}, [], [])
        cache = {"1": {"name": "Helm", "ilvl": 240, "set": None, "stats": "", "day": TODAY.isoformat()}}
        self.assertEqual(bi.refresh(client, {1}, cache, TODAY, progress=lambda m: None), 1)
        self.assertEqual(cache["1"]["slot"], "head")
        # and an item the API does not know is not asked again until it is stale
        cache = {}
        bi.refresh(client, {99}, cache, TODAY, progress=lambda m: None)
        self.assertEqual(bi.refresh(client, {99}, cache, TODAY, progress=lambda m: None), 0)

    def test_the_locale_of_a_request_can_be_chosen(self):
        seen = []

        def opener(request):
            if request.full_url == blizzard.TOKEN_URL:
                return {"access_token": "t"}
            seen.append(request.full_url)
            return {}

        client = blizzard.Client("i", "s", opener=opener, sleep=lambda s: None)
        client.get("/data/wow/item/1")
        client.get("/data/wow/item/1", locale="de_DE")
        self.assertIn("locale=en_US", seen[0])
        self.assertIn("locale=de_DE", seen[1])


class ProfessionTest(unittest.TestCase):
    def test_a_crafted_piece_names_its_profession(self):
        tiers = [{"id": 2, "name": "Midnight Blacksmithing"}]

        def opener(request):
            url = request.full_url
            if url == blizzard.TOKEN_URL:
                return {"access_token": "t"}
            path = url.split(".blizzard.com", 1)[1].split("?", 1)[0]
            if "skill-tier" in path:
                return {"categories": [{"recipes": [{"name": "Spellbreaker's Bracers"}]}]}
            if path.startswith("/data/wow/profession/"):
                return {"name": "Blacksmithing", "skill_tiers": tiers}
            raise AssertionError(path)

        client = blizzard.Client("i", "s", opener=opener, sleep=lambda s: None)
        recipes = bi.recipe_professions(client, progress=lambda m: None)
        self.assertEqual(recipes, {"spellbreaker's bracers": "Blacksmithing"})
        cache = {"5": {"name": "Spellbreaker's Bracers", "ilvl": 240, "set": None, "stats": "", "day": "x"}}
        drops = bi.other_drops({5}, set(), cache, recipes)
        self.assertEqual((drops[0]["kind"], drops[0]["encounter_name"]), ("crafted", "Blacksmithing"))
        # a plain set of names (the old shape) still works and names no profession
        drops = bi.other_drops({5}, set(), cache, set(recipes))
        self.assertEqual((drops[0]["kind"], drops[0]["encounter_name"]), ("crafted", ""))


class CatalystTest(unittest.TestCase):
    CACHE = {
        "10": {"slot": "head", "armor": "plate"},
        "11": {"slot": "head", "armor": "cloth"},
        "12": {"slot": "", "armor": "plate"},          # a ring: not a tier slot
        "13": {"slot": "legs", "armor": "plate"},      # drops in a raid, not a dungeon
        "14": {"slot": "legs", "armor": ""},           # armor type unknown
    }

    def test_the_raw_pieces_are_the_dungeon_drops_of_a_tier_slot_with_an_armor_type(self):
        drops = [dungeon(11, 1041, "Kings' Rest", 2172, "Dazar"), dungeon(10, 1041, "Kings' Rest", 2172, "Dazar"),
                 dungeon(10, 1041, "Kings' Rest", 2172, "Dazar"), dungeon(12, 1, "Keep", 2, "Boss"),
                 {**dungeon(13, 1320, "Abyss", 9, "Eel"), "kind": "raid"}, dungeon(14, 1, "Keep", 2, "Boss"),
                 dungeon(99, 1, "Keep", 2, "Boss")]
        records = bc.catalyst_records(drops, self.CACHE)
        self.assertEqual([(r["item"], r["slot"], r["armor"]) for r in records], [(10, "head", "plate"), (11, "head", "cloth")])
        self.assertEqual((records[0]["instance"], records[0]["instance_name"], records[0]["encounter_name"]),
                         (1041, "Kings' Rest", "Dazar"))


class TierSetTest(unittest.TestCase):
    def setUp(self):
        self.cache = {
            "1": {"name": "Warhelm of the Consecrated Flame", "ilvl": 250, "set": FLAME, "day": "x",
                  "effects": {"2": "Consecration is 30% larger.", "4": "Enemies take 20% more damage."}},
            "2": {"name": "Old Helm", "ilvl": 200, "set": "Old Set", "day": "x", "effects": {"2": "Old."}},
            "3": {"name": "Plain", "ilvl": 250, "set": None, "day": "x", "effects": {}},
        }
        self.entries = [{"class": "paladin", "item": 1}, {"class": "paladin", "item": 2}, {"class": "paladin", "item": 3}]

    def test_a_class_gets_the_set_of_its_highest_item_level_with_english_and_german_text(self):
        german = piece("Kriegshelm", "HEAD", "Plate", "Strahlung der Geweihten Flamme",
                       ((2, "(2) Set: Weihe ist 30% größer."), (4, "(4) Set: Gegner erleiden 20% mehr Schaden.")))
        client, calls = api({1: german}, [], [])
        records = bc.tierset_records(client, self.entries, self.cache, TODAY, progress=lambda m: None)
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual((record["class"], record["name"], record["name_de"]),
                         ("paladin", FLAME, "Strahlung der Geweihten Flamme"))
        self.assertEqual(record["bonuses"]["2"], {"en": "Consecration is 30% larger.", "de": "Weihe ist 30% größer."})
        self.assertEqual(record["bonuses"]["4"]["en"], "Enemies take 20% more damage.")
        # the German text is cached: a second run asks nothing
        before = len(calls)
        bc.tierset_records(client, self.entries, self.cache, TODAY, progress=lambda m: None)
        self.assertEqual(len(calls), before)

    def test_without_the_german_text_the_english_one_stands_alone(self):
        client, _ = api({}, [], [])  # the item API answers 404
        records = bc.tierset_records(client, self.entries, self.cache, TODAY, progress=lambda m: None)
        self.assertEqual(records[0]["bonuses"]["2"], {"en": "Consecration is 30% larger."})
        self.assertNotIn("name_de", records[0])

    def test_classes_without_a_set_give_nothing(self):
        client, _ = api({}, [], [])
        self.assertEqual(bc.tierset_records(client, [{"class": "mage", "item": 3}], self.cache, TODAY,
                                            progress=lambda m: None), [])


class SectionsTest(unittest.TestCase):
    def test_the_sections_come_from_the_dungeon_drops_and_the_entries(self):
        import fetch_items

        client, _ = api({10: piece("Helm of Kings", "HEAD", "Plate")}, [], [])
        merged = {"drops": [dungeon(10, 1041, "Kings' Rest", 2172, "Dazar")], "entries": []}
        sections = fetch_items.new_sections(client, merged, set(), {})
        self.assertEqual([r["item"] for r in sections["catalyst"]], [10])
        self.assertEqual(sections["tierset"], [])

    def test_a_failing_api_leaves_the_sections_out_instead_of_stopping_the_run(self):
        import urllib.error

        import fetch_items

        def opener(request):
            if request.full_url == blizzard.TOKEN_URL:
                return {"access_token": "t"}
            raise urllib.error.HTTPError(request.full_url, 400, "bad", {}, None)

        client = blizzard.Client("i", "s", opener=opener, sleep=lambda s: None)
        merged = {"drops": [dungeon(10, 1, "Keep", 2, "Boss")], "entries": []}
        self.assertEqual(fetch_items.new_sections(client, merged, set(), {}), {})


class DatasetTest(unittest.TestCase):
    BASE ={"source": "a", "generated": "2026-10-18T00:00:00Z"}
    CATALYST = [{"slot": "head", "armor": "plate", "item": 10, "instance": 1041, "instance_name": "Kings' Rest",
                 "encounter": 2172, "encounter_name": "Dazar"}]
    TIERSET = [{"class": "paladin", "name": FLAME, "name_de": "Strahlung",
                "bonuses": {"2": {"en": "Big.", "de": "Groß."}, "4": {"en": "Bigger."}}}]

    def test_the_new_sections_validate_and_merge(self):
        data = {**self.BASE, "catalyst": self.CATALYST, "tierset": self.TIERSET}
        validate(data)
        merged = merge([data, {**self.BASE, "source": "b", "catalyst": self.CATALYST,
                               "tierset": [{**self.TIERSET[0], "name": "Other"}]}])
        self.assertEqual(merged["catalyst"], self.CATALYST)       # one location once
        self.assertEqual(merged["tierset"][0]["name"], FLAME)      # the first source's text stays
        for bad in ({"catalyst": [{**self.CATALYST[0], "slot": "finger"}]},
                    {"catalyst": [{**self.CATALYST[0], "armor": "scale"}]},
                    {"catalyst": [{**self.CATALYST[0], "item": 0}]},
                    {"tierset": [{**self.TIERSET[0], "bonuses": {"2": {"de": "x"}}}]},
                    {"tierset": [{"class": "paladin", "name": ""}]}):
            with self.assertRaises(DatasetError):
                validate({**self.BASE, **bad})

    def test_the_lua_files_and_their_load_order(self):
        merged = merge([{**self.BASE, "catalyst": self.CATALYST, "tierset": self.TIERSET}])
        catalyst = lua.catalyst_file(merged)
        self.assertIn('KeyLootMasterCatalyst = {', catalyst)
        self.assertIn('["head"] = { ["plate"] = { {10, 1041, "Kings\' Rest", 2172, "Dazar"} } },', catalyst)
        tierset = lua.tierset_file(merged)
        self.assertIn('["paladin"] = { name = {"Radiance of the Consecrated Flame", "Strahlung"}, bonus = { [2] = {"Big.", "Groß."}, [4] = {"Bigger.", ""} } },', tierset)
        manifest = lua.manifest(["TierSet.lua", "Catalyst.lua", "Items.lua", "paladin.lua", "Meta.lua"])
        order = [manifest.index(n) for n in ("Meta.lua", "Items.lua", "Catalyst.lua", "TierSet.lua", "paladin.lua")]
        self.assertEqual(order, sorted(order))
        self.assertEqual(lua.catalyst_file({}), "")
        self.assertEqual(lua.tierset_file({}), "")


if __name__ == "__main__":
    unittest.main()
