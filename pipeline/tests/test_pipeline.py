import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import build  # noqa: E402
from klm import lua  # noqa: E402
from klm.merge import merge, top_per_slot  # noqa: E402
from klm.model import DatasetError, validate  # noqa: E402


def entry(item, share, sample, **over):
    base = {"class": "paladin", "spec": "protection", "content": "mplus", "slot": "head",
            "item": item, "share": share, "sample": sample}
    base.update(over)
    return base


def drop(item, instance=1, encounter=2, kind="dungeon"):
    return {"item": item, "kind": kind, "instance": instance, "instance_name": "Example Keep",
            "encounter": encounter, "encounter_name": "The \"Boss\""}


def dataset(source, entries=(), drops=(), generated="2026-10-12T00:00:00Z"):
    return {"source": source, "generated": generated, "entries": list(entries), "drops": list(drops)}


class ValidateTest(unittest.TestCase):
    def test_accepts_a_good_dataset(self):
        validate(dataset("a", [entry(1, 0.5, 10)], [drop(1)]))

    def test_rejects_what_would_corrupt_the_output(self):
        bad = [
            dataset("a", [entry(1, 1.5, 10)]),
            dataset("a", [entry(1, 0.5, 0)]),
            dataset("a", [entry(0, 0.5, 10)]),
            dataset("a", [entry(1, 0.5, 10, content="pvp")]),
            dataset("a", [], [drop(1, kind="loot-goblin")]),
            {"source": "", "generated": "x"},
        ]
        for case in bad:
            with self.assertRaises(DatasetError, msg=case):
                validate(case)


class MergeTest(unittest.TestCase):
    def test_shares_are_weighted_by_their_samples(self):
        merged = merge([dataset("a", [entry(7, 0.5, 10)]), dataset("b", [entry(7, 0.2, 30)])])
        (only,) = merged["entries"]
        self.assertEqual(only["sample"], 40)
        self.assertAlmostEqual(only["share"], 0.275)
        self.assertEqual(only["sources"], ["a", "b"])

    def test_order_of_the_sources_does_not_matter(self):
        a = dataset("a", [entry(7, 0.5, 10), entry(8, 0.1, 5)], [drop(7)])
        b = dataset("b", [entry(7, 0.2, 30)], [drop(7), drop(8, kind="raid")])
        self.assertEqual(merge([a, b]), merge([b, a]))

    def test_a_drop_both_sources_know_is_one_location(self):
        merged = merge([dataset("a", drops=[drop(7)]), dataset("b", drops=[drop(7)])])
        self.assertEqual(len(merged["drops"]), 1)
        self.assertEqual(merged["drops"][0]["sources"], ["a", "b"])

    def test_top_per_slot_keeps_the_most_worn(self):
        rows = [entry(1, 0.1, 10), entry(2, 0.6, 10), entry(3, 0.3, 10)]
        (kept,) = top_per_slot(rows, 2).values()
        self.assertEqual([r["item"] for r in kept], [2, 3])


class LuaTest(unittest.TestCase):
    def test_text_is_escaped(self):
        self.assertEqual(lua.quote('a"b\\c\nd'), '"a\\"b\\\\c\\nd"')

    def test_class_file_shape(self):
        merged = merge([dataset("a", [entry(7, 0.5, 10), entry(9, 0.25, 4, slot="neck")])])
        text = lua.class_files(merged, 8)["paladin.lua"]
        self.assertIn('KeyLootMasterData["paladin"] = {', text)
        self.assertIn('["head"] = { {7, 0.5, 10} },', text)
        self.assertIn('["neck"] = { {9, 0.25, 4} },', text)

    def test_drops_file_shape(self):
        text = lua.drops_file(merge([dataset("a", drops=[drop(7)])]))
        self.assertIn('[7] = { {kind = "dungeon", instance = 1, instanceName = "Example Keep", '
                      'encounter = 2, encounterName = "The \\"Boss\\""} },', text)


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "in").mkdir()
        self.out = self.root / "out"

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, name, data):
        (self.root / "in" / name).write_text(json.dumps(data), encoding="utf-8")

    def run_build(self):
        return build.main(["--datasets", str(self.root / "in"), "--out", str(self.out)])

    def test_builds_and_a_second_run_changes_nothing(self):
        self.put("a.json", dataset("a", [entry(7, 0.5, 10)], [drop(7)]))
        self.assertEqual(self.run_build(), 0)
        self.assertEqual({p.name for p in self.out.glob("*.lua")},
                         {"paladin.lua", "Drops.lua", "Items.lua", "Specs.lua", "Meta.lua"})
        manifest = (self.out / "Data.xml").read_text(encoding="utf-8")
        self.assertLess(manifest.index("Meta.lua"), manifest.index("Drops.lua"))
        self.assertLess(manifest.index("Drops.lua"), manifest.index("paladin.lua"))
        before = {p.name: p.read_bytes() for p in self.out.glob("*.lua")}
        stamps = {p.name: p.stat().st_mtime_ns for p in self.out.glob("*.lua")}
        self.assertEqual(self.run_build(), 0)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.out.glob("*.lua")})
        self.assertEqual(stamps, {p.name: p.stat().st_mtime_ns for p in self.out.glob("*.lua")})

    def test_a_malformed_dataset_writes_nothing(self):
        self.put("a.json", dataset("a", [entry(7, 0.5, 10)]))
        self.put("b.json", dataset("b", [entry(8, 2, 10)]))
        self.assertEqual(self.run_build(), 1)
        self.assertFalse(self.out.exists())

    def test_no_dataset_is_an_error(self):
        self.assertEqual(self.run_build(), 1)

    def test_a_class_that_is_gone_is_removed(self):
        self.put("a.json", dataset("a", [entry(7, 0.5, 10), entry(8, 0.5, 10, **{"class": "mage"})]))
        self.assertEqual(self.run_build(), 0)
        self.assertTrue((self.out / "mage.lua").exists())
        self.put("a.json", dataset("a", [entry(7, 0.5, 10)]))
        self.assertEqual(self.run_build(), 0)
        self.assertFalse((self.out / "mage.lua").exists())


if __name__ == "__main__":
    unittest.main()
