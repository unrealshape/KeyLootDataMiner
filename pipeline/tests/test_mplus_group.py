import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import build  # noqa: E402
from klm import lua  # noqa: E402
from klm.merge import derive_mplus, merge, mplus_groups, raid_items  # noqa: E402
from klm.model import DatasetError, validate  # noqa: E402
from klm.sources import blizzard, blizzard_gear  # noqa: E402

RAID_A, RAID_B, DUNGEON, BOTH = 900, 901, 100, 902


def drop(item, kind):
    return {"item": item, "kind": kind, "instance": 1, "instance_name": "X", "encounter": 2, "encounter_name": "Y"}


DROPS = [drop(RAID_A, "raid"), drop(RAID_B, "raid"), drop(DUNGEON, "dungeon"),
         drop(BOTH, "raid"), drop(BOTH, "dungeon")]


def stats(crit):
    pair = [crit, 20.0]
    return {k: list(pair) for k in ("c", "h", "m", "v", "leech", "avoidance", "speed")}


def player(rank, head, extra=(), crit=None):
    gear = {"head": [head]}
    if extra:
        gear["trinket"] = list(extra)
    record = {"class": "paladin", "spec": "protection", "rank": rank,
              "items": sorted({head, *extra}), "gear": gear}
    if crit is not None:
        record["stats"] = stats(crit)
    return record


def mixed_entry(item, share=0.5, sample=4):
    return {"class": "paladin", "spec": "protection", "content": "mplus", "slot": "head",
            "item": item, "share": share, "sample": sample}


def dataset(players, drops=DROPS, entries=None, with_stats=False):
    out = {"source": "s", "generated": "2026-10-13T00:00:00Z", "drops": list(drops),
           "entries": [mixed_entry(DUNGEON)] if entries is None else entries, "players": players}
    if with_stats:
        out["stats"] = [dict({"class": "paladin", "spec": "protection", "n": 9}, **stats(1000))]
    return out


class ClassifyTest(unittest.TestCase):
    def test_raid_item_is_raid_without_a_dungeon_source(self):
        self.assertEqual(raid_items(DROPS), {RAID_A, RAID_B})

    def test_zero_one_two_raid_items(self):
        players = [player(1, DUNGEON), player(2, DUNGEON, [RAID_A]), player(3, DUNGEON, [RAID_A, RAID_B])]
        groups = mplus_groups(merge([dataset(players)]), 10, 1)
        (group,) = groups.values()
        self.assertEqual([p["rank"] for p in group["eligible"]], [1, 2])
        self.assertEqual(len(group["pool"]), 3)
        strict = mplus_groups(merge([dataset(players)]), 10, 0)
        self.assertEqual([p["rank"] for p in next(iter(strict.values()))["eligible"]], [1])

    def test_an_item_from_raid_and_dungeon_does_not_count(self):
        players = [player(1, DUNGEON, [BOTH, RAID_A])]
        (group,) = mplus_groups(merge([dataset(players)]), 10, 1).values()
        self.assertEqual(len(group["eligible"]), 1)


class SelectionTest(unittest.TestCase):
    def test_best_n_by_rank_among_the_eligible(self):
        players = [player(1, DUNGEON, [RAID_A, RAID_B]), player(2, DUNGEON), player(3, DUNGEON, [RAID_A]),
                   player(4, DUNGEON), player(5, DUNGEON)]
        (group,) = mplus_groups(merge([dataset(players)]), 2, 1).values()
        self.assertEqual([p["rank"] for p in group["group"]], [2, 3])

    def test_fewer_eligible_than_n_takes_all_and_sample_is_their_number(self):
        players = [player(1, DUNGEON), player(2, DUNGEON, [RAID_A, RAID_B]), player(3, 101)]
        merged = derive_mplus(merge([dataset(players)]), 50, 1)
        mplus = [e for e in merged["entries"] if e["content"] == "mplus"]
        self.assertTrue(mplus)
        self.assertTrue(all(e["sample"] == 2 for e in mplus))
        shares = {e["item"]: e["share"] for e in mplus}
        self.assertEqual(shares, {DUNGEON: 0.5, 101: 0.5})

    def test_merge_does_not_depend_on_player_order(self):
        players = [player(1, DUNGEON), player(2, 101)]
        self.assertEqual(merge([dataset(players)]), merge([dataset(list(reversed(players)))]))


class OutputTest(unittest.TestCase):
    def merged_with_players(self, **kw):
        players = [player(1, DUNGEON, crit=1000), player(2, DUNGEON, [RAID_A], crit=1200),
                   player(3, 101, [RAID_A, RAID_B], crit=2000)]
        return merge([dataset(players, **kw)])

    def test_both_keys_in_the_class_file(self):
        merged = derive_mplus(self.merged_with_players(), 50, 1)
        text = lua.class_files(merged, 8)["paladin.lua"]
        self.assertIn('["mplus"] = {', text)
        self.assertIn('["mplus_all"] = {', text)
        self.assertIn('["head"] = { {100, 1.0, 2} }', text.split('["mplus"]')[1].split('["mplus_all"]')[0])
        self.assertIn("{100, 0.5, 4}", text.split('["mplus_all"]')[1])

    def test_old_dataset_without_players_stays_as_before(self):
        old = {"source": "s", "generated": "2026-10-13T00:00:00Z", "drops": DROPS, "entries": [mixed_entry(DUNGEON)]}
        validate(old)
        merged = merge([old])
        self.assertEqual(derive_mplus(merged, 50, 1), merged)
        text = lua.class_files(derive_mplus(merged, 50, 1), 8)["paladin.lua"]
        self.assertIn('["mplus"]', text)
        self.assertNotIn("mplus_all", text)

    def test_stats_get_a_mplus_subfield(self):
        merged = derive_mplus(self.merged_with_players(with_stats=True), 50, 1)
        (record,) = merged["stats"]
        self.assertEqual(record["n"], 9)
        self.assertEqual(record["c"], [1000, 20.0])
        self.assertEqual(record["mplus"]["n"], 2)
        self.assertEqual(record["mplus"]["c"], [1100, 20.0])
        text = lua.stats_file(merged)
        self.assertIn("n = 9, c = {1000, 20.0}", text)
        self.assertIn("mplus = { n = 2, c = {1100, 20.0}", text)

    def test_stats_without_group_keep_the_old_format(self):
        old = merge([{"source": "s", "generated": "2026-10-13T00:00:00Z",
                      "stats": [dict({"class": "paladin", "spec": "protection", "n": 5}, **stats(1000))]}])
        self.assertNotIn("mplus", lua.stats_file(derive_mplus(old, 50, 1)))

    def test_build_writes_the_split(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder, out = Path(tmp) / "ds", Path(tmp) / "out"
            folder.mkdir()
            (folder / "s.json").write_text(json.dumps(dataset([player(1, DUNGEON), player(2, 101)])), encoding="utf-8")
            self.assertEqual(build.main(["--datasets", str(folder), "--out", str(out), "--group-size", "1",
                                         "--max-raid-items", "0"]), 0)
            text = (out / "paladin.lua").read_text(encoding="utf-8")
            self.assertIn("mplus_all", text)
            self.assertIn("{100, 1.0, 1}", text.split('["mplus_all"]')[0])


class ModelTest(unittest.TestCase):
    def test_players_are_validated(self):
        validate(dataset([player(1, DUNGEON)]))
        for bad in ({"class": "p", "spec": "s"}, {"class": "p", "spec": "s", "items": [0]},
                    {"class": "p", "spec": "s", "items": [1], "rank": 0}):
            with self.assertRaises(DatasetError):
                validate(dataset([bad]))


class FetchTest(unittest.TestCase):
    def test_pool_is_read_but_the_mixed_group_stays_top_n(self):
        def member(name):
            return {"profile": {"name": name, "realm": {"slug": "r"}}, "specialization": {"id": 66}}
        names = ["a", "b", "c"]

        def opener(request):
            url = request.full_url
            if url == blizzard.TOKEN_URL:
                return {"access_token": "t"}
            path = url.split(".blizzard.com", 1)[1].split("?", 1)[0]
            if path == "/data/wow/mythic-keystone/season/index":
                return {"current_season": {"id": 1}}
            if path == "/data/wow/mythic-keystone/season/1":
                return {"periods": [{"id": 7}]}
            if path == "/data/wow/connected-realm/index":
                return {"connected_realms": [{"href": "https://x/data/wow/connected-realm/1?n=d"}]}
            if path.endswith("/mythic-leaderboard/index"):
                return {"current_leaderboards": [{"id": 249}]}
            if "/mythic-leaderboard/" in path:
                return {"leading_groups": [{"keystone_level": 30 - i, "completed_timestamp": 1,
                                            "members": [member(n.capitalize())]} for i, n in enumerate(names)]}
            if path == "/data/wow/playable-specialization/66":
                return {"name": "Protection", "playable_class": {"name": "Paladin"}}
            if path.endswith("/equipment"):
                return {"equipped_items": [{"slot": {"type": "HEAD"}, "item": {"id": 100 + names.index(path.rsplit("/", 2)[1])}}]}
            raise AssertionError(path)

        client = blizzard.Client("i", "s", opener=opener, sleep=lambda s: None)
        players = []
        entries = blizzard_gear.fetch_entries(client, top_per_spec=2, pool=3, players_out=players, progress=lambda m: None)
        self.assertEqual({e["sample"] for e in entries}, {2})
        self.assertEqual([(p["rank"], p["items"]) for p in players], [(1, [100]), (2, [101]), (3, [102])])
        validate(blizzard.make_dataset("blizzard-mplus", entries=entries, players=players))
        only = blizzard_gear.fetch_entries(client, top_per_spec=2, only_specs=["druid/guardian"], progress=lambda m: None)
        self.assertEqual(only, [])


if __name__ == "__main__":
    unittest.main()
